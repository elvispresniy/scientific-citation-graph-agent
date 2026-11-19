"""Recheck original questions with the unchanged night-20 boolean judge."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path

from graph_pilot.durable_llm import DurableClient, Journal, exclusive_run
from graph_pilot.factory_step2 import Step2ContextGuard, render_messages
from graph_pilot.factory_step3 import Config as GuardConfig
from graph_pilot.llm import Config as LLMConfig
from graph_pilot.step2_features import ROOT, Lexicon, TopicIndex, digest, encoded, read_json, write_json

OUT = ROOT / 'research/factory-e2e/same-prompt-top20-20261115'
SOURCE = ROOT / 'research/factory-e2e/night-20'
NUMBERS = [1, 10, 13, 14, 22, 23]


def verdict(response):
    if response['finish_reason'] != 'stop' or response['text'].strip() not in ('true', 'false'):
        raise ValueError('Expected a complete bare JSON boolean')
    return response['text'].strip() == 'true'


def prepare():
    OUT.mkdir(parents=True, exist_ok=False)
    manifest = read_json(SOURCE / 'manifest.json')
    plan = manifest['plan']
    prompt_path = ROOT / plan['judge_prompt']
    prompt = prompt_path.read_text()
    assert digest(prompt_path.read_bytes()) == manifest['files'][str(prompt_path)]
    cfg_path = ROOT / plan['llm_config']
    assert digest(cfg_path.read_bytes()) == manifest['files'][str(cfg_path)]
    cfg = replace(LLMConfig.load(cfg_path), temperature=0, timeout_seconds=plan['timeout_seconds'], max_requests=10000)
    questions = read_json(SOURCE / 'summary.json')['questions']
    index = TopicIndex(ROOT / plan['index'], Lexicon(ROOT / 'research/terminology-pilot'),
                       compatibility=ROOT / plan['index_compatibility'])
    guard_config = GuardConfig.load(ROOT / plan['step3_config'])
    guard = Step2ContextGuard(guard_config)
    # Verify settings and rendered input against an actual successful night judge request.
    q = questions[0]
    messages_file = next((SOURCE / q['artifact'] / 'judge').glob('*/attempt-*/messages.json'))
    messages = read_json(messages_file)
    identity = {'model': cfg.model, 'messages': messages,
                'config': {k: v for k, v in asdict(cfg).items() if k != 'max_requests'}}
    cache = SOURCE / 'journal/responses' / digest(encoded(identity)) / 'success.json.gz'
    with gzip.open(cache, 'rt') as stream:
        saved = json.load(stream)
    assert saved['identity'] == identity
    write_json(OUT / 'night-config-verification.json', {'verified': True, 'night_success_cache':str(cache.relative_to(ROOT)),
               'identity_sha256':digest(encoded(identity)), 'prompt_sha256':digest(prompt.encode())})
    pairs = []; groups = []
    for number in NUMBERS:
        q = questions[number-1]
        old = set(q['targets'])
        ranks = {}
        for method, result in q['methods'].items():
            for rank, row in enumerate(result['top_20'], 1):
                ranks.setdefault(row['paper_id'], {})[method] = rank
        ids = sorted(set(ranks)-old)
        groups.append({'question_number':number, 'question':q['question'], 'old_targets':sorted(old),
                       'top20_union':len(ranks), 'controls':len(ids)})
        for pid in ids:
            paper = index.item(pid)['paper']
            messages = render_messages(prompt, {'question':q['question'], 'full_text':paper['text']})
            directory = OUT / f'q{number:02d}' / pid.replace(':','_').replace('/','_')
            directory.mkdir(parents=True)
            write_json(directory / 'messages.json',messages)
            try:
                context = guard.check(messages, cfg.max_output_tokens)
                status = 'prepared'
            except ValueError as exc:
                context = {'error_type':type(exc).__name__}
                status = 'context_error'
            write_json(directory / 'context.json',context)
            pair = {'question_number':number,'paper_id':pid,'ranks':ranks[pid],
                    'directory':str(directory.relative_to(OUT)), 'messages_sha256':digest(encoded(messages)),
                    'status':status}
            pairs.append(pair)
    (OUT / 'prompt.md').write_text(prompt)
    write_json(OUT / 'manifest.json', {'source':str(SOURCE.relative_to(ROOT)), 'groups':groups, 'pairs':pairs,
               'llm_config':asdict(cfg), 'retry':plan['retry'], 'prompt_sha256':digest(prompt.encode()),
               'max_http_attempts':900, 'max_hours':6, 'workers':3,
               'policy':'Original exact question and original boolean judge, no A/B layers. Fresh calls for all controls.'})
    print(json.dumps({'prepared_pairs':len(pairs),'groups':groups,'llm_config':asdict(cfg)},ensure_ascii=False),flush=True)


def run():
    with exclusive_run(OUT):
        manifest = read_json(OUT / 'manifest.json')
        assert digest((OUT / 'prompt.md').read_bytes()) == manifest['prompt_sha256']
        key = os.environ.get('GRAPH_LLM_API_KEY') or (ROOT / '.secrets/llm-api-key').read_text().strip()
        journal = Journal(OUT / 'journal',max_requests=manifest['max_http_attempts'],max_hours=manifest['max_hours'])
        results = []
        def assess(pair):
            directory = OUT / pair['directory']
            result_file = directory / 'result.json'
            if result_file.exists() and read_json(result_file)['status']=='completed':
                return read_json(result_file)
            result = {k:pair[k] for k in ('question_number','paper_id','ranks')}
            if pair['status']!='prepared':
                result.update(status=pair['status'], verdict=None)
            else:
                client = DurableClient(LLMConfig(**manifest['llm_config']),key,journal,manifest['retry'],validator=verdict)
                try:
                    messages = read_json(directory / 'messages.json')
                    assert digest(encoded(messages)) == pair['messages_sha256']
                    response = client.complete(client.config.model,messages)
                    write_json(directory / 'completion.json',response)
                    result.update(status='completed',verdict=verdict(response))
                except Exception as exc:
                    result.update(status='error',verdict=None,error_type=type(exc).__name__)
                finally:
                    client.close()
            write_json(result_file,result)
            return result
        def snapshot():
            rows = []
            for group in manifest['groups']:
                rs = [r for r in results if r['question_number']==group['question_number']]
                positives = [r for r in rs if r.get('verdict') is True and r['status']=='completed']
                rows.append({**group,'completed':sum(r['status']=='completed' for r in rs),
                             'errors':sum(r['status']!='completed' for r in rs),
                             'new_true_count':len(positives),'new_true_articles':positives})
            value = {'updated_at':datetime.now(timezone.utc).isoformat(),'total':len(manifest['pairs']),
                     'processed':len(results),'http_attempts':journal.budget['http_attempts'],'rows':rows,'results':results,
                     'status':'finished' if len(results)==len(manifest['pairs']) else 'running'}
            write_json(OUT / 'summary.json',value)
            return value
        with ThreadPoolExecutor(max_workers=manifest['workers']) as pool:
            futures = [pool.submit(assess,p) for p in manifest['pairs']]
            for future in as_completed(futures):
                r=future.result();results.append(r);s=snapshot()
                print(json.dumps({'processed':s['processed'],'total':s['total'],'q':r['question_number'],
                                  'paper_id':r['paper_id'],'status':r['status'],'verdict':r['verdict']},ensure_ascii=False),flush=True)
        s=snapshot()
        md=['# Исходный судья: новые true в top-20','',
            '| Вопрос | Прежних целей | Проверено новых статей top-20 | Новых true | Ошибок |',
            '|---:|---:|---:|---:|---:|']
        for r in s['rows']:
            md.append(f"| {r['question_number']} | {len(r['old_targets'])} | {r['completed']} | {r['new_true_count']} | {r['errors']} |")
        (OUT/'results.md').write_text('\n'.join(md)+'\n')
        print(json.dumps({'status':s['status'],'processed':s['processed'],'rows':s['rows']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    import sys
    {'prepare':prepare,'run':run}[sys.argv[1]]()
