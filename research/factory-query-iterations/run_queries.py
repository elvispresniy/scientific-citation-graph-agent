"""Prepare and run saved group cards through the query prompt; no source reading.

Run from the repository root with PYTHONPATH=code. A prepared run is immutable;
run sends each input once, with no retries. The key is read only in run mode.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from graph_pilot.factory_step2 import Step2ContextGuard, model_call, render_messages
from graph_pilot.factory_step3 import Config as GuardConfig, aspect_description
from graph_pilot.llm import Config as LLMConfig, LLMClient, LLMError
from graph_pilot.step2_features import Step2Error, digest, read_json, validate_cards, write_json

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_questions(value, paper_ids):
    if not isinstance(value, dict) or set(value) != {'questions'} or not isinstance(value['questions'], list):
        raise Step2Error('Expected only a questions list')
    for question in value['questions']:
        if not isinstance(question, dict) or set(question) != {'question', 'answer_paper_ids'}:
            raise Step2Error('Expected question and answer_paper_ids only')
        if not isinstance(question['question'], str) or not question['question'].strip():
            raise Step2Error('Question must be nonempty text')
        ids = question['answer_paper_ids']
        if (not isinstance(ids, list) or not ids or not all(isinstance(pid, str) for pid in ids)
                or len(ids) != len(set(ids)) or not set(ids) <= set(paper_ids)):
            raise Step2Error('Answer IDs must be nonempty, distinct and from the input pool')
    return value


def prepare(plan_path):
    plan = read_json(plan_path)
    output = BASE / plan['phase']
    output.mkdir(exist_ok=False)
    prompt = (ROOT / plan['prompt']).read_text()
    llm = replace(LLMConfig.load(ROOT / plan['llm_config']), max_requests=len(plan['groups']),
                  timeout_seconds=plan['timeout_seconds'], max_output_tokens=plan['max_output_tokens'])
    guard_config = GuardConfig.load(ROOT / plan['guard_config'])
    guard = Step2ContextGuard(guard_config)
    manifests = []
    for group in plan['groups']:
        source = ROOT / group['source']
        state = read_json(source / 'state.json')
        if state['status'] != 'completed':
            raise Step2Error('Only completed step 3 sources are supported')
        aspect = aspect_description(state['shared_aspects'][int(group['aspect']) - 1])
        ids = sorted(pid for pid, check in state['checks'][group['aspect']].items()
                     if check.get('class') == 'core')
        by_id = {card['paper_id']: card for card in read_json(source / 'cards.json')}
        cards = [by_id[pid] for pid in ids]
        validate_cards(cards)
        if not cards:
            raise Step2Error('Group has no core cards')
        inputs = {'shared_aspect': aspect, 'paper_cards': cards}
        messages = render_messages(prompt, {key: json.dumps(value, ensure_ascii=False)
                                            for key, value in inputs.items()})
        if sum(len(m['content']) for m in messages) > llm.max_input_characters:
            raise Step2Error('Input character budget exceeded')
        budget = guard.check(messages, llm.max_output_tokens)
        directory = output / group['name']
        directory.mkdir()
        write_json(directory / 'input.json', inputs)
        write_json(directory / 'messages.json', messages)
        write_json(directory / 'context.json', budget)
        manifests.append({**group, 'paper_ids': ids, 'input_cards': len(ids),
                          'source_state_sha256': digest((source / 'state.json').read_bytes()),
                          'source_cards_sha256': digest((source / 'cards.json').read_bytes()),
                          'input_sha256': digest((directory / 'input.json').read_bytes()),
                          'messages_sha256': digest((directory / 'messages.json').read_bytes()),
                          'content_tokens': budget['content_tokens']})
    (output / 'prompt.md').write_text(prompt)
    write_json(output / 'manifest.json', {'prepared_at': now(), 'status': 'prepared',
               'plan': plan, 'plan_sha256': digest(Path(plan_path).read_bytes()),
               'prompt_sha256': digest(prompt.encode()), 'driver_sha256': digest(Path(__file__).read_bytes()),
               'llm_config': asdict(llm), 'guard_config': asdict(guard_config),
               'member_roles': ['core'], 'automatic_retries': 0, 'groups': manifests})
    print(json.dumps({'prepared': str(output), 'groups': [
        {'name': m['name'], 'cards': m['input_cards'], 'content_tokens': m['content_tokens']}
        for m in manifests]}, ensure_ascii=False), flush=True)


def run(output):
    output = Path(output)
    manifest = read_json(output / 'manifest.json')
    # Claim before reading credentials or sending requests: a run cannot be repeated.
    with (output / 'started.json').open('x') as stream:
        json.dump({'started_at': now()}, stream)
    if digest((output / 'prompt.md').read_bytes()) != manifest['prompt_sha256']:
        raise Step2Error('Frozen prompt differs from prepared input')
    if digest(Path(__file__).read_bytes()) != manifest['driver_sha256']:
        raise Step2Error('Driver differs from prepared version')
    for group in manifest['groups']:
        directory = output / group['name']
        for filename, key in [('input.json', 'input_sha256'), ('messages.json', 'messages_sha256')]:
            if digest((directory / filename).read_bytes()) != group[key]:
                raise Step2Error('Frozen input differs from prepared version')
    key = os.environ.get('GRAPH_LLM_API_KEY')
    if not key:
        key = (ROOT / '.secrets/llm-api-key').read_text().strip()
    client = LLMClient(LLMConfig(**manifest['llm_config']), key)
    guard = Step2ContextGuard(GuardConfig(**manifest['guard_config']))

    def compose(group):
        directory = output / group['name']
        result = {'name': group['name'], 'started_at': now(), 'input_cards': group['input_cards']}
        write_json(directory / 'status.json', {**result, 'status': 'running'})
        try:
            value = model_call(client, guard, read_json(directory / 'messages.json'), directory / 'request')
            value = validate_questions(value, group['paper_ids'])
            write_json(directory / 'questions.json', value)
            result.update(status='completed', questions=len(value['questions']),
                          answer_counts=[len(q['answer_paper_ids']) for q in value['questions']])
        except (LLMError, Step2Error) as exc:
            result.update(status='stopped_on_error', error={'type': type(exc).__name__, 'message': str(exc)})
        except Exception as exc:
            client.stop()
            result.update(status='stopped_on_error', error={'type': type(exc).__name__})
        result['finished_at'] = now()
        write_json(directory / 'status.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result

    try:
        with ThreadPoolExecutor(max_workers=manifest['plan']['max_concurrent_groups']) as pool:
            results = [future.result() for future in as_completed(
                [pool.submit(compose, group) for group in manifest['groups']])]
        summary = {'finished_at': now(), 'llm_requests': client.requests, 'results': results}
        write_json(output / 'summary.json', summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.path)
    else:
        run(args.path)
