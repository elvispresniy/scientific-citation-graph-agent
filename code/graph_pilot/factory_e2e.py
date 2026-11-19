"""Autonomous diagnostic factory, step 1 through full-text judging and direct search.

Commands: prepare (offline), run/resume (foreground), launch (detached), status.
Scientific prompts/policies are reused unchanged. Results are diagnostic tasks,
not automatically certified benchmark items.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import argparse
import shutil
import time
import uuid

from . import factory_step1 as step1, factory_step1_5 as probe
from . import factory_step2 as step2, factory_step3 as step3
from .durable_llm import DurableClient, Journal, RunLimit, exclusive_run
from .llm import Config as LLMConfig, LLMError
from .probe_modules import ProbeConfig, LocalContextGuard, validate_response, ProbeError
from .step2_features import (ROOT, Lexicon, LocalGraph, TopicIndex, digest, encoded,
                             read_json, write_json, Step2Error)
from .direct_retrieval import ranked_search, target_ranks, distances


def now():
    return datetime.now(timezone.utc).isoformat()


def path(value):
    return (ROOT / value).resolve()


def validate_questions(value, paper_ids):
    if not isinstance(value, dict) or set(value) != {'questions'} or not isinstance(value['questions'], list):
        raise Step2Error('Expected only a questions list')
    for item in value['questions']:
        if not isinstance(item, dict) or set(item) != {'question', 'answer_paper_ids'}:
            raise Step2Error('Expected question and answer_paper_ids')
        ids = item['answer_paper_ids']
        if not isinstance(item['question'], str) or not item['question'].strip():
            raise Step2Error('Empty question')
        if (not isinstance(ids, list) or not ids or not all(isinstance(pid, str) for pid in ids)
                or len(set(ids)) != len(ids) or not set(ids) <= set(paper_ids)):
            raise Step2Error('Answer IDs must be distinct members of the input pool')
    return value


def parse_verdict(completion):
    if completion.get('finish_reason') != 'stop' or completion.get('text', '').strip() not in ('true', 'false'):
        raise ValueError('Expected a complete bare JSON boolean')
    return completion['text'].strip() == 'true'


def json_completion(completion):
    return step2.parse_completion(completion)


def prepare(plan_file, output):
    """Freeze a new seed plan and implementation/config/input identities, without LLM."""
    plan = read_json(plan_file)
    validate_plan(plan)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    graph = LocalGraph(path(plan['graph']))
    try:
        identity = graph.identity()
    finally:
        graph.close()
    lexicon = Lexicon(ROOT / 'research/terminology-pilot')
    index = TopicIndex(path(plan['index']), lexicon, compatibility=path(plan['index_compatibility']))
    if identity != index.manifest['graph']:
        raise ValueError('Graph differs from the frozen search index')
    cfg1 = replace(step1.Config.load(path(plan['step1_config'])),
                   K=plan['seed_draw_count'], rng_seed=plan['seed_rng'])
    report = step1.run(path(plan['graph']), cfg1, output / 'step1')
    excluded = set()
    for filename in plan['exclude_seed_reports']:
        old = read_json(path(filename))
        excluded.update(item['paper_id'] for item in old.get('selected', old.get('seeds', [])))
    selected = [item for item in report['selected']
                if item['paper_id'] not in excluded and item['paper_id'] in index.rows][:plan['max_seeds']]
    filtered = {**report, 'selected': selected, 'selected_count': len(selected),
                'excluded_prior_seeds': sorted(excluded), 'purpose': 'New e2e seed queue'}
    write_json(output / 'seed-queue.json', filtered)
    cfg_probe = replace(ProbeConfig.load(path(plan['probe_config'])), seed_count=plan['max_seeds'],
                        max_concurrent_seeds=1)
    neighbor_plan = probe.build_plan(path(plan['graph']), output / 'seed-queue.json', cfg_probe)
    write_json(output / 'neighbor-plan.json', neighbor_plan)
    if not selected:
        raise ValueError('No fresh indexed seeds available')
    # Freeze complete local source index as well as modules, prompts and configuration.
    files = set(Path(__file__).parent.glob('*.py'))
    files.update(Path(__file__).parent.glob('prompts/*.md'))
    files.update(path(plan[key]) for key in ('step1_config', 'probe_config', 'step2_config',
                 'step3_config', 'llm_config', 'probe_llm_config', 'composer_prompt', 'judge_prompt',
                 'index_compatibility'))
    files.update(path(filename) for filename in plan['exclude_seed_reports'])
    prior_questions = set()
    for run in plan.get('exclude_question_runs', []):
        for filename in path(run).glob('*/questions.json'):
            files.add(filename)
            for item in read_json(filename)['questions']:
                prior_questions.add(question_key(item['question']))
    files.add(path(plan['index']) / 'manifest.json')
    for config in (cfg_probe, step2.Config.load(path(plan['step2_config'])),
                   step3.Config.load(path(plan['step3_config']))):
        files.add(Path(config.tokenizer_path))
    fingerprints = {str(p.resolve()): digest(p.read_bytes()) for p in sorted(files)}
    write_json(output / 'plan.json', plan)
    write_json(output / 'manifest.json', {'version': 1, 'prepared_at': now(), 'plan': plan,
               'files': fingerprints, 'graph': identity, 'index_manifest_sha256': index.manifest_hash,
               'seed_count': len(selected), 'neighbor_plan_sha256': digest((output / 'neighbor-plan.json').read_bytes()),
               'excluded_question_keys': sorted(prior_questions),
               'seed_queue_sha256': digest((output / 'seed-queue.json').read_bytes()),
               'scope': 'diagnostic generation, subgraph + search-pool judging, BM25/LSA; no release certification'})
    return {'output': str(output), 'seeds': len(selected), 'target_questions': plan['target_questions']}


def validate_plan(plan):
    if type(plan.get('min_target_papers', 0)) is not int or plan.get('min_target_papers', 0) < 0:
        raise ValueError('min_target_papers must be a nonnegative integer')
    for key in ('seed_draw_count', 'seed_rng', 'max_seeds', 'target_questions', 'workers',
                'max_http_requests', 'top_k_per_method'):
        if type(plan[key]) is not int or plan[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    for key in ('max_hours', 'timeout_seconds'):
        if type(plan[key]) not in (int, float) or not 0 < plan[key] <= (3600 if key == 'timeout_seconds' else 168):
            raise ValueError(f'Invalid {key}')
    if not 1 <= plan['top_k_per_method'] <= 20:
        raise ValueError('top_k_per_method must be <= 20')
    retry = plan['retry']
    for key in ('max_attempts', 'max_invalid_responses'):
        if type(retry[key]) is not int or retry[key] < 1:
            raise ValueError(f'Invalid retry {key}')
    for key in ('initial_delay_seconds', 'max_delay_seconds'):
        if type(retry[key]) not in (int, float) or retry[key] < 0:
            raise ValueError(f'Invalid retry {key}')
    # Load all configs before any external calls, including URL and parameter validation.
    for key in ('llm_config', 'probe_llm_config'):
        LLMConfig.load(path(plan[key]))


def verify(output):
    manifest = read_json(output / 'manifest.json')
    if read_json(output / 'plan.json') != manifest['plan']:
        raise ValueError('Prepared plan changed; prepare a separate run')
    for filename, expected in manifest['files'].items():
        if digest(Path(filename).read_bytes()) != expected:
            raise ValueError(f'Frozen source/config/input changed: {filename}')
    for filename, key in (('neighbor-plan.json', 'neighbor_plan_sha256'), ('seed-queue.json', 'seed_queue_sha256')):
        if digest((output / filename).read_bytes()) != manifest[key]:
            raise ValueError('Frozen seed input changed')
    graph = LocalGraph(path(manifest['plan']['graph']))
    try:
        if graph.identity() != manifest['graph']:
            raise ValueError('Graph snapshot changed')
    finally:
        graph.close()
    return manifest


class Pipeline:
    def __init__(self, output, manifest, api_key, *, client_factory=DurableClient):
        self.output, self.manifest, self.key = Path(output), manifest, api_key
        self.plan, self.client_factory = manifest['plan'], client_factory
        p = self.plan
        self.journal = Journal(self.output / 'journal', max_requests=p['max_http_requests'], max_hours=p['max_hours'])
        self.lexicon = Lexicon(ROOT / 'research/terminology-pilot')
        self.index = TopicIndex(path(p['index']), self.lexicon, compatibility=path(p['index_compatibility']))
        self.cfg2 = step2.Config.load(path(p['step2_config']))
        self.cfg3 = step3.Config.load(path(p['step3_config']))
        self.cfg_probe = replace(ProbeConfig.load(path(p['probe_config'])), seed_count=p['max_seeds'],
                                 max_concurrent_seeds=1)
        self.probe_plan = read_json(self.output / 'neighbor-plan.json')

    def client(self, kind='json', *, validator=None):
        config = LLMConfig.load(path(self.plan['probe_llm_config'] if kind == 'probe' else self.plan['llm_config']))
        config = replace(config, timeout_seconds=self.plan['timeout_seconds'], max_requests=10000)
        if kind == 'judge':
            config = replace(config, temperature=0)
        elif kind == 'composer':
            config = replace(config, max_output_tokens=32768)
        validators = {'probe': validate_response, 'judge': parse_verdict}
        return self.client_factory(config, self.key, self.journal, self.plan['retry'],
                                   validator=validator or validators.get(kind, json_completion))

    def stage(self, directory, function):
        """Successful stage is immutable; interrupted attempts remain as audit artifacts."""
        directory.mkdir(parents=True, exist_ok=True)
        success = directory / 'completed.json'
        if success.exists():
            return read_json(success)['value']
        number = 1
        while ((directory / f'attempt-{number:03d}').exists()
               or (directory / f'attempt-{number:03d}.claim.json').exists()):
            number += 1
        attempt = directory / f'attempt-{number:03d}'
        write_json(directory / f'attempt-{number:03d}.claim.json', {'started_at': now()})
        self.journal.event(kind='stage_start', stage=str(directory.relative_to(self.output)), attempt=number)
        try:
            value = function(attempt)
        except Exception as exc:
            write_json(directory / 'status.json', {'status': 'error', 'time': now(),
                       'attempt': number, 'error_type': type(exc).__name__})
            self.journal.event(kind='stage_error', stage=str(directory.relative_to(self.output)),
                               error_type=type(exc).__name__)
            raise
        write_json(success, {'time': now(), 'value': value})
        write_json(directory / 'status.json', {'status': 'completed', 'time': now(), 'attempt': number})
        self.journal.event(kind='stage_complete', stage=str(directory.relative_to(self.output)))
        # write_json canonicalizes object-key order. Feed the persisted representation
        # downstream on BOTH first execution and resume, so rendered messages remain
        # byte-for-byte identical and successful HTTP calls are actually reusable.
        return read_json(success)['value']

    def checked_state(self, value):
        if value['status'] in ('stopped_on_error', 'interrupted', 'card_unavailable', 'request_budget', 'context_overflow'):
            if value.get('error', {}).get('type') == 'RunLimit':
                raise RunLimit('Global run limit interrupted a stage')
            raise Step2Error('Stage incomplete; inspect saved state and response journal')
        return value

    def run_seed(self, seed):
        pid = seed['paper_id']
        directory = self.output / 'seeds' / pid.replace(':', '_').replace('/', '_')
        directory.mkdir(parents=True, exist_ok=True)
        done = directory / 'completed.json'
        if done.exists():
            return read_json(done)
        graph = LocalGraph(path(self.plan['graph']))
        try:
            single = {**self.probe_plan, 'neighbors': {**self.probe_plan['neighbors'], 'seeds': [seed]}}
            # LocalGraph already returns prepared, hash-checked fulltexts. Reconstruct the
            # public paper payload so the existing step-1.5 text preparer remains active.
            class ProbeGraph:
                def health(inner):
                    return {'ok': True, 'snapshot_id': self.manifest['graph']['snapshot_id']}

                def paper(inner, paper_id):
                    paper = self.index.item(paper_id)['paper']
                    return {'arxiv_id': paper_id.removeprefix('arxiv:'), 'title': paper.get('title'),
                            'text': paper['text'], 'text_format': paper['text_format'],
                            'provenance': paper.get('provenance')}

            def do_probe(attempt):
                value = probe.execute(single, self.cfg_probe, graph=ProbeGraph(), llm=self.client('probe'),
                                      guard=LocalContextGuard(self.cfg_probe), output=attempt)
                if value['status'] != 'complete':
                    if value.get('error', {}).get('type') == 'RunLimit':
                        raise RunLimit('Run limit reached during probing')
                    raise Step2Error('Seed probe incomplete')
                return value
            probed = self.stage(directory / 'probe', do_probe)
            trial = probed['seeds'][0]
            if not trial['accepted']:
                result = {'seed_id': pid, 'status': 'not_accepted', 'questions': []}
            else:
                initial = [pid] + [pair['neighbor_id'] for pair in trial['pairs'] if pair['positive'] is True]
                cards = self.stage(directory / 'bootstrap', lambda out: step2.bootstrap(
                    self.index, initial, self.cfg2, llm=self.client(), guard=step2.Step2ContextGuard(self.cfg2), output=out))
                state = self.stage(directory / 'expansion', lambda out: self.checked_state(step2.execute(
                    graph, self.index, self.lexicon, cards, self.cfg2, llm=self.client(),
                    guard=step2.Step2ContextGuard(self.cfg2), output=out)))
                cards = state['cards']
                aspects = self.stage(directory / 'aspects', lambda out: self.checked_state(step3.execute(
                    cards, lambda paper_id: self.index.item(paper_id)['paper']['text'], self.cfg3,
                    llm=self.client(), guard=step2.Step2ContextGuard(self.cfg3), output=out)))
                questions, errors = [], []
                for number, aspect in enumerate(aspects['shared_aspects'], 1):
                    aspect_id = f'{number:02d}'
                    core = sorted(paper_id for paper_id, check in aspects['checks'].get(aspect_id, {}).items()
                                  if check.get('class') == 'core')
                    if not core:
                        continue
                    try:
                        ready, failed = self.run_group(directory / 'groups' / aspect_id, aspect,
                                                       [c for c in cards if c['paper_id'] in core], cards, graph)
                        questions.extend(ready)
                        errors.extend(failed)
                    except RunLimit:
                        raise
                    except (ValueError, LLMError) as exc:
                        errors.append({'aspect': aspect_id, 'error_type': type(exc).__name__})
                result = {'seed_id': pid, 'status': 'partial' if errors else 'completed',
                          'questions': questions, 'errors': errors}
            # Partial seeds remain resumable; completed question units are preserved.
            write_json(directory / ('partial.json' if result['status'] == 'partial' else 'completed.json'), result)
            return result
        except RunLimit:
            raise
        except Exception as exc:
            result = {'seed_id': pid, 'status': 'error', 'error_type': type(exc).__name__, 'questions': []}
            write_json(directory / 'error.json', result)
            self.journal.event(kind='seed_error', seed=pid, error_type=type(exc).__name__)
            return result
        finally:
            graph.close()

    def run_group(self, directory, aspect, core_cards, all_cards, graph):
        prompt = path(self.plan['composer_prompt']).read_text()
        inputs = {'shared_aspect': step3.aspect_description(aspect), 'paper_cards': core_cards}
        messages = step2.render_messages(prompt, {k: json.dumps(v, ensure_ascii=False) for k, v in inputs.items()})
        core_ids = [c['paper_id'] for c in core_cards]
        def compose(out):
            client = self.client('composer', validator=lambda response: validate_questions(json_completion(response), core_ids))
            value = step2.model_call(client, step2.Step2ContextGuard(self.cfg3), messages, out)
            return validate_questions(value, core_ids)
        composed = self.stage(directory / 'compose', compose)
        questions, errors = [], []
        for number, question in enumerate(composed['questions'], 1):
            qdir = directory / f'question-{number:03d}'
            try:
                result = self.stage(qdir, lambda out, q=question: self.finish_question(out, q, all_cards, graph))
                questions.append({**result, 'artifact': str(qdir.relative_to(self.output))})
            except RunLimit:
                raise
            except (ValueError, LLMError) as exc:
                errors.append({'question': str(qdir.relative_to(self.output)), 'error_type': type(exc).__name__})
        return questions, errors

    def finish_question(self, out, question, cards, graph):
        out.mkdir(parents=True)
        write_json(out / 'question.json', question)
        methods = self.stage(out.parent / 'search', lambda _: ranked_search(self.index, question['question']))
        subgraph = sorted(c['paper_id'] for c in cards)
        ranks = {row['paper_id']: {} for method in methods.values() for row in method['top_20'][:self.plan['top_k_per_method']]}
        for method, result in methods.items():
            for rank, row in enumerate(result['top_20'][:self.plan['top_k_per_method']], 1):
                ranks[row['paper_id']][method] = rank
        pool = sorted(set(subgraph) | set(ranks))
        distance = distances(graph, subgraph)
        prompt = path(self.plan['judge_prompt']).read_text()
        verdicts = []
        errors = []
        guard = step2.Step2ContextGuard(self.cfg3)
        for paper_id in pool:
            pair_dir = out.parent / 'judge' / paper_id.replace(':', '_').replace('/', '_')
            def assess(attempt):
                attempt.mkdir(parents=True)
                text = self.index.item(paper_id)['paper']['text']
                messages = step2.render_messages(prompt, {'question': question['question'], 'full_text': text})
                write_json(attempt / 'messages.json', messages)
                client = self.client('judge')
                write_json(attempt / 'context.json', guard.check(messages, client.config.max_output_tokens))
                response = client.complete(client.config.model, messages)
                write_json(attempt / 'completion.json', response)
                return parse_verdict(response)
            try:
                verdict = self.stage(pair_dir, assess)
                status = 'completed'
            except RunLimit:
                raise
            except (ValueError, LLMError) as exc:
                # No scientific label is invented for an unavailable/failed assessment.
                verdict, status = None, 'error'
                errors.append({'paper_id': paper_id, 'error_type': type(exc).__name__})
            verdicts.append({'paper_id': paper_id, 'status': status, 'verdict': verdict,
                             'composer_selected': paper_id in question['answer_paper_ids'],
                             'in_subgraph': paper_id in subgraph, 'search_ranks': ranks.get(paper_id, {}),
                             'distance_to_subgraph': distance.get(paper_id)})
            write_json(out / 'verdicts-progress.json', verdicts)
        if errors:
            write_json(out / 'partial-verdicts.json', {'verdicts': verdicts, 'errors': errors})
            raise Step2Error('Question has unresolved judge pairs')
        targets = sorted(item['paper_id'] for item in verdicts if item['verdict'] is True)
        # Rank newly discovered targets too; the subgraph is not assumed exhaustive.
        methods = target_ranks(methods, targets)
        result = {**question, 'targets': targets, 'verdicts': verdicts, 'methods': methods,
                  'status': 'completed', 'release_status': 'diagnostic_only',
                  'judged_pool_size': len(pool), 'index_manifest_sha256': self.index.manifest_hash}
        write_json(out / 'result.json', result)
        return result

    def execute(self):
        seeds = iter(self.probe_plan['neighbors']['seeds'])
        results, active = [], {}
        target = self.plan['target_questions']
        stop_reason = 'seed_pool_exhausted'
        def metrics():
            return question_counts(collect_questions(self.output), self.manifest.get('excluded_question_keys', []))
        def reached():
            counts = metrics()
            return (counts['completed_questions'] >= target
                    and counts['confirmed_target_papers'] >= self.plan.get('min_target_papers', 0))
        def snapshot(status):
            value = {'status': status, 'updated_at': now(), 'stop_reason': stop_reason,
                     'target_questions': target, 'min_target_papers': self.plan.get('min_target_papers', 0),
                     **metrics(),
                     'http_attempts': self.journal.budget['http_attempts'], 'results': results,
                     'questions': collect_questions(self.output)}
            write_json(self.output / 'summary.json', value)
            return value
        with ThreadPoolExecutor(max_workers=self.plan['workers']) as pool:
            exhausted = False
            while active or not exhausted:
                while not exhausted and len(active) < self.plan['workers'] and not reached():
                    try:
                        self.journal.check()
                        if self.journal.budget['http_attempts'] >= self.plan['max_http_requests']:
                            raise RunLimit('Request limit reached')
                        seed = next(seeds)
                    except StopIteration:
                        exhausted = True
                        break
                    except RunLimit:
                        stop_reason, exhausted = 'run_limit', True
                        break
                    future = pool.submit(self.run_seed, seed)
                    active[future] = seed['paper_id']
                if reached():
                    stop_reason, exhausted = 'target_reached', True
                if not active:
                    break
                done, _ = wait(active, timeout=30, return_when=FIRST_COMPLETED)
                for future in done:
                    pid = active.pop(future)
                    try:
                        results.append(future.result())
                    except RunLimit:
                        stop_reason, exhausted = 'run_limit', True
                        results.append({'seed_id': pid, 'status': 'run_limit', 'questions': []})
                snapshot('running')
        if reached():
            stop_reason = 'target_reached'
        summary = snapshot('finished')
        export_questions(self.output, summary)
        return summary


def export_questions(output, summary):
    lines = ['# Diagnostic e2e questions', '',
             f"Completed: {summary['completed_questions']}; stop: {summary['stop_reason']}", '']
    for item in summary['questions']:
        lines.extend([f"## {item['seed_id']} — {item['artifact']}", '', item['question'], '',
                      'Judge targets: ' + ', '.join(item['targets']), '',
                      f"[Full results]({item['artifact']}/completed.json)", ''])
    (output / 'questions.md').write_text('\n'.join(lines))


def question_key(question):
    return digest(' '.join(question.split()).casefold().encode())


def question_counts(questions, excluded=()):
    excluded = set(excluded)
    new = [q for q in questions if question_key(q['question']) not in excluded]
    return {'completed_questions': len({question_key(q['question']) for q in new}),
            'confirmed_target_papers': len({pid for q in new for pid in q['targets']})}


def collect_questions(output):
    result = []
    for filename in sorted(output.glob('seeds/*/groups/*/question-*/completed.json')):
        result.append({**read_json(filename)['value'], 'seed_id': filename.parts[-5].replace('arxiv_', 'arxiv:', 1),
                       'artifact': str(filename.parent.relative_to(output))})
    return result


def worker(output):
    with exclusive_run(output):
        write_json(output / 'worker-started.json', {'pid': os.getpid(), 'time': now(),
                   'launch_token': os.environ.get('GRAPH_E2E_LAUNCH_TOKEN')})
        manifest = verify(output)
        key = os.environ.get('GRAPH_LLM_API_KEY')
        if not key:
            key = (ROOT / '.secrets/llm-api-key').read_text().strip()
        return Pipeline(output, manifest, key).execute()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'resume', 'launch', 'status'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    os.chdir(ROOT)
    if args.command == 'prepare':
        if not args.plan:
            parser.error('prepare requires --plan')
        result = prepare(args.plan, output)
    elif args.command == 'status':
        result = read_json(output / 'summary.json') if (output / 'summary.json').exists() else {'status': 'prepared'}
        result = {key: value for key, value in result.items() if key not in ('results', 'questions')}
    elif args.command == 'launch':
        verify(output)
        key = os.environ.get('GRAPH_LLM_API_KEY')
        if not key:
            key = (ROOT / '.secrets/llm-api-key').read_text().strip()
        if not key:
            raise ValueError('Empty LLM credential')
        # Serialize launchers separately: release worker.lock before the child tries it.
        with exclusive_run(output / 'launch-control'):
            with exclusive_run(output):
                pass
            token = uuid.uuid4().hex
            with (output / 'process.log').open('a') as stream:
                command = [sys.executable, '-m', 'graph_pilot.factory_e2e', 'run', '--output', str(output)]
                if sys.platform == 'darwin' and shutil.which('caffeinate'):
                    command = ['caffeinate', '-i', *command]
                child = subprocess.Popen(command,
                    cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'code'),
                                   'GRAPH_E2E_LAUNCH_TOKEN': token}, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            result = {'pid': child.pid, 'started_at': now(), 'output': str(output)}
            write_json(output / 'background.json', result)
            # Keep the launcher lock until the child owns worker.lock, closing the
            # gap in which a second launcher could create another background job.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                boot = output / 'worker-started.json'
                if boot.exists() and read_json(boot).get('launch_token') == token:
                    result['status'] = 'started'
                    break
                if child.poll() is not None:
                    raise RuntimeError('Background worker exited; inspect process.log')
                time.sleep(0.1)
            else:
                child.terminate()
                child.wait(timeout=5)
                raise RuntimeError('Background startup timed out; inspect process.log')
    else:
        result = worker(output)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
