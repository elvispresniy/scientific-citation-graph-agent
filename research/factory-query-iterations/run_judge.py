"""Prepare and run full-text question verification."""
import argparse
import gzip
import json
import os
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

from graph_pilot.factory_step2 import Step2ContextGuard, render_messages
from graph_pilot.factory_step3 import Config as GuardConfig
from graph_pilot.llm import Config, LLMClient, LLMError
from graph_pilot.step2_features import LocalGraph, digest, read_json, write_json
from run_queries import BASE, ROOT, now


SOURCE = BASE / 'pilot-v1'


def parse_verdict(completion):
    if completion['finish_reason'] != 'stop':
        raise ValueError('Incomplete response')
    literal = completion['text'].strip()
    if literal not in ('true', 'false'):
        raise ValueError('Expected a bare boolean literal')
    return literal == 'true'


def vision_top_pool(source, question, index_manifest):
    direct = read_json(BASE / 'direct-search-v1/results.json')
    group = source['vision-01']
    previous = read_json(BASE / 'judge-subgraph-v1/summary.json')['results']
    prior = {r['paper_id']: r['verdict'] for r in previous
             if r['group'] == 'vision-01' and r['question_number'] == 1 and r['status'] == 'completed'}
    entry = next(q for q in direct['questions'] if q['group'] == 'vision-01' and q['question_number'] == 1)
    if entry['question'] != question or direct['index_manifest_sha256'] != digest(index_manifest.read_bytes()):
        raise ValueError('Direct-search inputs differ')
    ranks = defaultdict(dict)
    for method, result in entry['methods'].items():
        for rank, row in enumerate(result['top_20'][:10], 1):
            ranks[row['paper_id']][method] = rank
    seeds = sorted(c['paper_id'] for c in read_json(ROOT / group['source'] / 'cards.json'))
    graph = LocalGraph(ROOT / 'research/unarxive-pilot/graph.sqlite')
    try:
        identity = graph.identity()
        if identity != read_json(index_manifest)['graph']:
            raise ValueError('Graph snapshot differs from the search index')
        neighbors = defaultdict(set)
        for src, dst in graph.db.execute('SELECT src,dst FROM edges'):
            neighbors[src].add(dst)
            neighbors[dst].add(src)
    finally:
        graph.close()
    parent = dict.fromkeys(seeds)
    frontier = deque(seeds)
    while frontier:
        pid = frontier.popleft()
        for neighbor in sorted(neighbors[pid]):
            if neighbor not in parent:
                parent[neighbor] = pid
                frontier.append(neighbor)
    candidates = []
    for pid, hits in sorted(ranks.items()):
        path = []
        node = pid if pid in parent else None
        while node is not None:
            path.append(node)
            node = parent[node]
        candidates.append({'paper_id': pid, 'ranks': hits,
                           'distance': len(path) - 1 if path else None,
                           'path_to_subgraph': path, 'prior_verdict': prior.get(pid)})
    return {'graph': identity, 'source_subgraph': seeds, 'candidates': candidates}


def prepare(output, full_pool, subgraph=False, vision_top10=False):
    prompt = (ROOT / 'code/graph_pilot/prompts/question-paper-verdict-v1-draft.md').read_text()
    index = ROOT / 'research/factory-step2-pilot/index-001'
    rows = {row['paper_id']: row for row in read_json(index / 'manifest.json')['rows']}
    source = {group['name']: group for group in read_json(SOURCE / 'manifest.json')['groups']}
    llm = Config.load(ROOT / 'code/graph_pilot/configs/step2-llm.example.json')
    guard_config = GuardConfig.load(ROOT / 'code/graph_pilot/configs/factory-step3-local.json')
    guard = Step2ContextGuard(guard_config)
    prepared = []
    reused = []
    previous = {}
    if subgraph:
        prior = BASE / 'judge-full-pool-v1'
        prior_manifest = read_json(prior / 'manifest.json')
        current_config = asdict(replace(llm, temperature=0, timeout_seconds=1500))
        if any(prior_manifest['llm_config'][key] != value
               for key, value in current_config.items() if key != 'max_requests'):
            raise ValueError('Previous judge configuration differs')
        previous = {pair['directory']: pair for pair in prior_manifest['pairs']}
    questions = {group: read_json(SOURCE / group / 'questions.json')['questions'] for group in source}
    scope = [(group, number) for group, entries in questions.items()
             for number in range(1, len(entries) + 1)] if full_pool or subgraph else [
                 ('highdim-02', 2), ('view_synthesis-01', 1)]
    if vision_top10:
        scope = [('vision-01', 1)]
        pool = vision_top_pool(source, questions['vision-01'][0]['question'], index / 'manifest.json')
    for group, number in scope:
        question = questions[group][number - 1]
        ids = source[group]['paper_ids']
        if vision_top10:
            ids = [row['paper_id'] for row in pool['candidates'] if row['prior_verdict'] is None]
        elif subgraph:
            cards = read_json(ROOT / source[group]['source'] / 'cards.json')
            ids = [card['paper_id'] for card in cards]
            if len(ids) != len(set(ids)) or not set(source[group]['paper_ids']) <= set(ids):
                raise ValueError(f'Inconsistent subgraph pool for {group}')
        elif not full_pool and group == 'highdim-02':
            ids = question['answer_paper_ids']
        for pid in sorted(ids):
            row = rows[pid]
            cached = (index / row['artifact']).read_bytes()
            if digest(cached) != row['sha256']:
                raise ValueError(f'Cached article hash mismatch for {pid}')
            paper = json.loads(gzip.decompress(cached))['paper']
            if paper['paper_id'] != pid or not paper['text'].strip():
                raise ValueError(f'Missing or mismatched article for {pid}')
            messages = render_messages(prompt, {'question': question['question'], 'full_text': paper['text']})
            if sum(len(message['content']) for message in messages) > llm.max_input_characters:
                raise ValueError(f'Character budget exceeded for {pid}')
            budget = guard.check(messages, llm.max_output_tokens)
            pair = {'group': group, 'question_number': number, 'paper_id': pid,
                    'composer_selected': pid in question['answer_paper_ids'],
                    'directory': f'{group}-q{number}-{pid.removeprefix("arxiv:")}',
                    'source_sha256': row['sha256'], 'content_tokens': budget['content_tokens']}
            if pair['directory'] in previous:
                old = previous[pair['directory']]
                old_directory = prior / pair['directory']
                old_messages = old_directory / 'messages.json'
                if (digest(old_messages.read_bytes()) != old['messages_sha256']
                        or read_json(old_messages) != messages):
                    raise ValueError(f'Previous input differs for {pair["directory"]}')
                verdict = parse_verdict(read_json(old_directory / 'completion.json'))
                if read_json(old_directory / 'verdict.json') is not verdict:
                    raise ValueError(f'Previous verdict differs for {pair["directory"]}')
                reused.append({**pair, 'status': 'completed', 'verdict': verdict,
                               'reused_from': str(old_directory.relative_to(ROOT))})
            else:
                prepared.append((pair, messages, budget))
    if subgraph and len(reused) != len(previous):
        raise ValueError('The subgraph scope does not include all previous pairs')
    llm = replace(llm, temperature=0, timeout_seconds=1500, max_requests=len(prepared))
    output.mkdir(exist_ok=False)
    if vision_top10:
        write_json(output / 'pool.json', pool)
    (output / 'prompt.md').write_text(prompt)
    pairs = []
    for pair, messages, budget in prepared:
        directory = output / pair['directory']
        directory.mkdir()
        write_json(directory / 'messages.json', messages)
        write_json(directory / 'context.json', budget)
        pairs.append({**pair, 'messages_sha256': digest((directory / 'messages.json').read_bytes())})
    write_json(output / 'manifest.json', {'prepared_at': now(), 'source': str(SOURCE.relative_to(ROOT)),
               'prompt_sha256': digest(prompt.encode()), 'llm_config': asdict(llm),
               'pairs': pairs, 'reused_results': reused})
    print(json.dumps([{k: p[k] for k in ('group', 'paper_id', 'content_tokens')} for p in pairs]))


def run(output, max_workers=3):
    manifest = read_json(output / 'manifest.json')
    pairs = manifest['pairs']
    for pair in pairs:
        if digest((output / pair['directory'] / 'messages.json').read_bytes()) != pair['messages_sha256']:
            raise ValueError('Prepared input has changed')
    key = os.environ.get('GRAPH_LLM_API_KEY') or (ROOT / '.secrets/llm-api-key').read_text().strip()
    config = Config(**manifest['llm_config'])
    with (output / 'started.json').open('x') as stream:
        json.dump({'started_at': now()}, stream)
    client = LLMClient(config, key)

    def judge(pair):
        directory = output / pair['directory']
        result = {k: pair[k] for k in ('group', 'question_number', 'paper_id', 'composer_selected')}
        try:
            completion = client.complete(config.model, read_json(directory / 'messages.json'))
            write_json(directory / 'completion.json', completion)
            verdict = parse_verdict(completion)
            write_json(directory / 'verdict.json', verdict)
            result.update(status='completed', verdict=verdict)
        except (ValueError, LLMError) as exc:
            result.update(status='error', error=str(exc))
        write_json(directory / 'status.json', result)
        print(json.dumps(result), flush=True)
        return result

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(judge, pairs))
        reused = manifest.get('reused_results', [])
        write_json(output / 'summary.json', {'finished_at': now(), 'llm_requests': client.requests,
                                              'reused_count': len(reused), 'results': reused + results})
    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run'])
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--full-pool', action='store_true')
    scope.add_argument('--subgraph', action='store_true')
    scope.add_argument('--vision-top10', action='store_true')
    args = parser.parse_args()
    output = BASE / ('judge-full-pool-v1' if args.full_pool else 'judge-pilot-v1')
    if args.subgraph:
        output = BASE / 'judge-subgraph-v1'
    if args.vision_top10:
        output = BASE / 'judge-vision-top10-v1'
    if args.command == 'prepare':
        prepare(output, args.full_pool, args.subgraph, args.vision_top10)
    else:
        run(output)
