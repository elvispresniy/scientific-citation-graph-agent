"""Reproducible step-1.5 plan, bounded execution and offline reaggregation."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import datetime, timezone
import getpass
import gzip
import json
import os
from pathlib import Path
import time
from threading import Event
from urllib.parse import urlsplit

from .client import GraphClient
from .llm import Config as LLMConfig, LLMClient, LLMError
from .probe_modules import (LocalContextGuard, NEIGHBOR_SELECTORS, PAIR_POLICIES,
                            SEED_POLICIES, TEXT_PREPARERS, ProbeConfig, ProbeError,
                            RESPONSE_SCHEMA, json_bytes, messages_for_pair,
                            reasoning_record, sha256, validate_response)


VERSION = 'factory-step1.5-v3'


def save_json(path, value):
    """Atomic checkpoint; only used inside this invocation's new output directory."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save_gzip(path, value):
    with Path(path).open('xb') as stream:
        stream.write(gzip.compress(json_bytes(value), mtime=0))
        stream.flush()
        os.fsync(stream.fileno())


def build_plan(database, seed_report, config):
    prompt = Path(config.prompt_path).read_bytes()
    if not prompt.decode().strip():
        raise ProbeError('Empty prompt')
    plan = NEIGHBOR_SELECTORS[config.neighbor_selector](database, seed_report, config)
    return {'version': VERSION, 'response_schema': RESPONSE_SCHEMA, 'config': config.manifest(),
            'prompt_sha256': sha256(prompt), 'prompt_text': prompt.decode(),
            'implementation_sha256': {name: sha256(Path(__file__).with_name(name).read_bytes())
                                      for name in ('factory_step1_5.py', 'probe_modules.py',
                                                   'llm.py', 'client.py', 'latex_to_text.py')},
            'neighbors': plan}


def _update_decision(seed, config):
    seed['positives'] = sum(p.get('positive') is True for p in seed['pairs'])
    seed['negatives'] = sum(p.get('positive') is False for p in seed['pairs'])
    seed['unresolved'] = len(seed['selected_neighbors']) - seed['positives'] - seed['negatives']
    seed['accepted'] = SEED_POLICIES[config.seed_policy](
        seed['positives'], seed['unresolved'], config.min_positive_neighbors)
    if seed['accepted'] is not None:
        seed['status'] = 'accepted' if seed['accepted'] else 'not_accepted'
        seed['stop_reason'] = 'positive_threshold' if seed['accepted'] else 'threshold_unreachable'


def execute(plan, config, *, graph, llm, guard, output, max_pairs=None, progress=None):
    """Dependencies are injected so the complete runner can be checked without a server."""
    if max_pairs is not None and (type(max_pairs) is not int or max_pairs < 1):
        raise ValueError('max_pairs must be a positive integer')
    if plan['config'] != config.manifest():
        raise ProbeError('Plan/config mismatch')
    if sha256(plan['prompt_text'].encode()) != plan['prompt_sha256']:
        raise ProbeError('Prompt hash mismatch')
    if not llm.config.model:
        raise ProbeError('Select an explicit LLM model')
    graph_url = getattr(graph, 'base_url', None)
    if graph_url is not None:
        url = urlsplit(graph_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username
                or url.password or url.query or url.fragment):
            raise ProbeError('Graph URL must be HTTP(S) without credentials, query or fragment')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'papers').mkdir()
    (output / 'pairs').mkdir()
    save_json(output / 'plan.json', plan)
    (output / 'prompt.md').write_text(plan['prompt_text'])
    started = time.monotonic()
    report = {'version': VERSION, 'response_schema': RESPONSE_SCHEMA,
              'started_at': datetime.now(timezone.utc).isoformat(),
              'config': config.manifest(), 'llm_config': asdict(llm.config),
              'graph_base_url': graph_url,
              'snapshot_id': plan['neighbors']['snapshot_id'], 'status': 'running',
              'max_pairs': max_pairs, 'attempted_pairs': 0, 'llm_requests': 0,
              'accepted_seed_ids': [], 'seeds': [
                  {**s, 'pairs': [], 'accepted': None, 'status': 'not_started',
                   'positives': 0, 'negatives': 0, 'unresolved': len(s['selected_neighbors'])}
                  for s in plan['neighbors']['seeds']]}
    initial_requests = llm.requests
    cache = {}
    stop_event = Event()
    pending = {}
    active = {}
    next_seed = 0
    reserved_requests = initial_requests
    workers = min(config.max_concurrent_seeds, max(1, len(report['seeds'])))
    report['max_concurrent_seeds'] = config.max_concurrent_seeds
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='probe-pair')

    def checkpoint():
        report['llm_requests'] = llm.requests - initial_requests
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['accepted_seed_ids'] = [s['paper_id'] for s in report['seeds'] if s['accepted'] is True]
        save_json(output / 'report.json', report)

    def read_paper(pid):
        if pid not in cache:
            prepared = TEXT_PREPARERS[config.text_preparer](graph.paper(pid), pid)
            ref = Path('papers') / (sha256(pid.encode()) + '.json.gz')
            save_gzip(output / ref, prepared)
            cache[pid] = str(ref)
            return prepared, str(ref)
        # Keep only artifact references across pairs, rather than all fulltexts in RAM.
        with gzip.open(output / cache[pid], 'rt') as stream:
            return json.load(stream), cache[pid]

    def stop_admissions():
        stop_event.set()
        if hasattr(llm, 'stop'):
            llm.stop()

    def admissions_stopped():
        if getattr(llm, 'stopped', False):
            stop_event.set()
        return stop_event.is_set()

    def safe_error(exc):
        return {'type': type(exc).__name__,
                'message': str(exc) if isinstance(exc, (ProbeError, LLMError)) else type(exc).__name__}

    def record_error(error, *, interrupted=False, pair=None):
        stop_admissions()
        if 'error' not in report:
            report['error'] = error
            report['status'] = 'interrupted' if interrupted else 'stopped_on_error'
        if pair is not None and pair['status'] == 'running':
            pair.update(status='error', error=error)
            save_json(output / pair['artifact_dir'] / 'result.json', pair)
        checkpoint()

    def assess(messages, directory):
        if admissions_stopped():
            return {'cancelled': True}
        try:
            completion = llm.complete(llm.config.model, messages)
            save_json(output / directory / 'completion.json', completion)
            save_json(output / directory / 'reasoning.json', reasoning_record(completion))
            assessment = validate_response(completion)
            positive = PAIR_POLICIES[config.pair_policy](assessment)
            if type(positive) is not bool:
                raise ProbeError('Pair policy must return a boolean')
            return {'assessment': assessment, 'positive': positive}
        except (Exception, KeyboardInterrupt) as exc:
            # Signal before the coordinator observes this future, so no new
            # request is admitted while it is preparing another pair.
            stop_admissions()
            return {'error': safe_error(exc), 'interrupted': isinstance(exc, KeyboardInterrupt)}

    def budget_reason():
        if max_pairs is not None and report['attempted_pairs'] >= max_pairs:
            return 'pair_budget'
        if reserved_requests >= llm.config.max_requests:
            return 'request_budget'
        return None

    def consume(future):
        index, pair = pending.pop(future)
        seed = report['seeds'][index]
        outcome = {'cancelled': True} if future.cancelled() else future.result()
        if 'error' in outcome:
            record_error(outcome['error'], interrupted=outcome['interrupted'], pair=pair)
        elif outcome.get('cancelled'):
            pair['status'] = 'cancelled'
            save_json(output / pair['artifact_dir'] / 'result.json', pair)
        else:
            pair.update(status='evaluated', **outcome)
            save_json(output / pair['artifact_dir'] / 'result.json', pair)
            _update_decision(seed, config)
            if progress:
                progress({'seed_id': seed['paper_id'], 'neighbor_id': pair['neighbor_id'],
                          'positive': pair['positive'], 'seed_status': seed['status']})
        if seed['accepted'] is not None:
            active.pop(index, None)
        checkpoint()

    checkpoint()
    try:
        health = graph.health()
        report['graph_identity'] = {'snapshot_id': health.get('snapshot_id'),
                                    'verified': health.get('snapshot_id') == report['snapshot_id']}
        if health.get('ok') is False:
            raise ProbeError('Graph API is not ready')
        if health.get('snapshot_id') is not None and not report['graph_identity']['verified']:
            raise ProbeError('Graph API snapshot differs from frozen neighbor plan')
        checkpoint()
        while True:
            while (not admissions_stopped() and len(active) < workers
                   and next_seed < len(report['seeds']) and budget_reason() is None):
                index = next_seed
                next_seed += 1
                seed = report['seeds'][index]
                seed['status'] = 'running'
                _update_decision(seed, config)
                if seed['accepted'] is None:
                    active[index] = seed

            busy_seeds = {index for index, _ in pending.values()}
            for index, seed in list(active.items()):
                if admissions_stopped() or budget_reason() is not None:
                    break
                if index in busy_seeds:
                    continue
                neighbor = seed['selected_neighbors'][len(seed['pairs'])]
                report['attempted_pairs'] += 1
                directory = Path('pairs') / f"{report['attempted_pairs']:06d}"
                (output / directory).mkdir()
                pair = {'seed_id': seed['paper_id'], 'neighbor_id': neighbor['paper_id'],
                        'directions': neighbor['directions'], 'artifact_dir': str(directory),
                        'status': 'running', 'positive': None}
                seed['pairs'].append(pair)
                checkpoint()
                try:
                    a, a_ref = read_paper(seed['paper_id'])
                    b, b_ref = read_paper(neighbor['paper_id'])
                    pair['paper_artifacts'] = {'A': a_ref, 'B': b_ref}
                    messages = messages_for_pair(plan['prompt_text'], a, b)
                    save_gzip(output / directory / 'input.json.gz', messages)
                    pair['input_sha256'] = sha256(json_bytes(messages))
                    pair['context'] = guard.check(messages, llm.config.max_output_tokens)
                    checkpoint()
                    if admissions_stopped():
                        pair['status'] = 'cancelled'
                        save_json(output / directory / 'result.json', pair)
                        break
                    reserved_requests += 1
                    future = pool.submit(assess, messages, directory)
                    pending[future] = (index, pair)
                except (Exception, KeyboardInterrupt) as exc:
                    record_error(safe_error(exc), interrupted=isinstance(exc, KeyboardInterrupt), pair=pair)
                    break
            if stop_event.is_set():
                for future in pending:
                    future.cancel()
            if not pending:
                if stop_event.is_set() or budget_reason() is not None or not active:
                    break
            else:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    consume(future)
        if 'error' not in report:
            report['status'] = ('complete' if all(s['accepted'] is not None for s in report['seeds'])
                                else budget_reason() or 'incomplete')
    except (Exception, KeyboardInterrupt) as exc:
        record_error(safe_error(exc), interrupted=isinstance(exc, KeyboardInterrupt))
    finally:
        # An HTTP request already admitted cannot be unsent. Cancel queued tasks,
        # retain responses of in-flight requests, and never schedule replacements.
        pool.shutdown(wait=True, cancel_futures=stop_event.is_set())
        for future in list(pending):
            consume(future)
        for seed in report['seeds']:
            if seed['status'] == 'running' and seed['accepted'] is None:
                seed.update(status='incomplete' if seed['pairs'] else 'not_started',
                            stop_reason=report['status'])
        checkpoint()
    return report


def reaggregate(run_directory, *, threshold, pair_policy=None):
    """Apply another threshold/pair policy to saved assessments; never call the model."""
    if type(threshold) is not int or threshold < 1:
        raise ValueError('threshold must be a positive integer')
    source = Path(run_directory) / 'report.json'
    raw = source.read_bytes()
    report = json.loads(raw)
    if threshold > report['config']['max_neighbors']:
        raise ValueError('threshold must be <= max_neighbors')
    policy_name = pair_policy or report['config']['pair_policy']
    if policy_name not in PAIR_POLICIES:
        raise ValueError('Unknown pair policy')
    result = {'source_report_sha256': sha256(raw), 'source_run': str(Path(run_directory).resolve()),
              'min_positive_neighbors': threshold, 'pair_policy': policy_name,
              'llm_requests': 0, 'seeds': []}
    for seed in report['seeds']:
        outcomes = [PAIR_POLICIES[policy_name](p['assessment']) for p in seed['pairs']
                    if p['status'] == 'evaluated']
        positives = sum(v is True for v in outcomes)
        unresolved = len(seed['selected_neighbors']) - len(outcomes)
        decision = SEED_POLICIES[report['config']['seed_policy']](positives, unresolved, threshold)
        result['seeds'].append({'paper_id': seed['paper_id'], 'positives': positives,
                                'negatives': sum(v is False for v in outcomes),
                                'unresolved': unresolved, 'accepted': decision,
                                'status': ('accepted' if decision else 'not_accepted')
                                if decision is not None else 'incomplete'})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    for command in ('plan', 'run'):
        p = subparsers.add_parser(command)
        p.add_argument('--config', type=Path, required=True)
        p.add_argument('--db', type=Path, required=True)
        p.add_argument('--seed-report', type=Path, required=True)
        p.add_argument('--output', type=Path, required=True)
        if command == 'run':
            p.add_argument('--llm-config', type=Path, required=True)
            p.add_argument('--graph-url', required=True)
            p.add_argument('--ask-key', action='store_true')
            p.add_argument('--max-pairs', type=int)
    p = subparsers.add_parser('reaggregate')
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--threshold', type=int, required=True)
    p.add_argument('--pair-policy')
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output path')
    client = None
    try:
        if args.command == 'reaggregate':
            result = reaggregate(args.run, threshold=args.threshold, pair_policy=args.pair_policy)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('xb') as stream:
                stream.write(json_bytes(result))
        else:
            config = ProbeConfig.load(args.config)
            plan = build_plan(args.db, args.seed_report, config)
            if args.command == 'plan':
                args.output.mkdir(parents=True, exist_ok=False)
                save_json(args.output / 'plan.json', plan)
                result = {'status': 'planned', 'seeds': len(plan['neighbors']['seeds']),
                          'pairs': plan['neighbors']['pair_count'], 'llm_requests': 0,
                          'fulltext_reads': 0}
            else:
                llm_config = LLMConfig.load(args.llm_config)
                if not llm_config.model:
                    raise ProbeError('Select an explicit LLM model')
                guard = LocalContextGuard(config)
                key = getpass.getpass('API credential (hidden): ') if args.ask_key else os.environ.get('GRAPH_LLM_API_KEY')
                client = LLMClient(llm_config, key)
                report = execute(plan, config, graph=GraphClient(args.graph_url), llm=client,
                                 guard=guard, output=args.output, max_pairs=args.max_pairs,
                                 progress=lambda value: print(json.dumps(value), flush=True))
                result = {k: report[k] for k in ('status', 'attempted_pairs', 'llm_requests', 'accepted_seed_ids')}
        print(json.dumps({'output': str(args.output), **result}, ensure_ascii=False, indent=2))
        return 0 if result.get('status') in (None, 'planned', 'complete', 'pair_budget') else 1
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')
    finally:
        if client is not None:
            client.close()


if __name__ == '__main__':
    raise SystemExit(main())
