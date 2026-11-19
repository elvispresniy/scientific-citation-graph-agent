"""Synthetic full-chain checks: no scientific papers and no external server."""
from collections import Counter
from dataclasses import asdict, replace
import json
from pathlib import Path
import re

import httpx
import pytest

from graph_pilot import factory_e2e as e2e
from graph_pilot.durable_llm import DurableClient
from graph_pilot.llm import LLMClient
from graph_pilot.step2_features import (IndexConfig, Lexicon, LocalGraph, TopicIndex, build_index,
                                       digest, encoded, read_json, write_json)
from graph_pilot.store import Store


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    plan = read_json(e2e.ROOT / 'research/factory-e2e/night-20-plan.json')
    tokenizers = pytest.importorskip('tokenizers')
    tokenizer = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    tokenizer_path = tmp_path / 'tiny-tokenizer.json'
    tokenizer.save(str(tokenizer_path))
    tokenizer_config = {'tokenizer_path': str(tokenizer_path),
                        'tokenizer_sha256': e2e.digest(tokenizer_path.read_bytes())}
    ids = [f'arxiv:2001.{i:05d}' for i in range(1, 8)]
    store = Store(tmp_path / 'graph.sqlite')
    store.setting('snapshot_id', 'unarxive-open-cs-local-2026-10-18')
    for i, pid in enumerate(ids):
        source = tmp_path / f'{i}.txt'
        source.write_text(f'Graph message passing node classification. Synthetic text {i} aggregation learning.')
        store.upsert(pid, {'title': f'Synthetic {i}'})
        store.add_node(pid, 0)
        store.source(pid, 'plain_text', source, {}, 'available')
    for pid in ids[1:]:
        store.db.execute('INSERT INTO edges VALUES (?,?,0,?)', (ids[0], pid, '{}'))
    store.close()
    graph = LocalGraph(store.path)
    build_index(graph, tmp_path / 'index', IndexConfig(n_components=2, min_df=1), Lexicon())
    graph.close()
    # Fixture is a newly built compatible index, not the historical index-001 adapter.
    monkeypatch.setattr(e2e, 'TopicIndex', lambda directory, lexicon, compatibility=None: TopicIndex(directory, lexicon))
    compat = tmp_path / 'compat.json'
    write_json(compat, {'synthetic_fixture': True})
    cfg2 = replace(e2e.step2.Config.load(e2e.path(plan['step2_config'])), max_accepted=1,
                   **tokenizer_config)
    write_json(tmp_path / 'step2.json', asdict(cfg2))
    cfg_probe = replace(e2e.ProbeConfig.load(e2e.path(plan['probe_config'])), **tokenizer_config)
    cfg3 = replace(e2e.step3.Config.load(e2e.path(plan['step3_config'])), **tokenizer_config)
    write_json(tmp_path / 'probe.json', asdict(cfg_probe))
    write_json(tmp_path / 'step3.json', asdict(cfg3))
    plan.update(graph=str(store.path), index=str(tmp_path / 'index'), index_compatibility=str(compat),
                step2_config=str(tmp_path / 'step2.json'), exclude_seed_reports=[], exclude_question_runs=[],
                probe_config=str(tmp_path / 'probe.json'), step3_config=str(tmp_path / 'step3.json'),
                llm_config='code/graph_pilot/configs/examples/step2-llm.example.json',
                probe_llm_config='code/graph_pilot/configs/examples/step1_5-llm-run.json',
                seed_draw_count=1, max_seeds=1, workers=1, target_questions=1, min_target_papers=1, max_http_requests=100,
                retry={'max_attempts': 3, 'max_invalid_responses': 2,
                       'initial_delay_seconds': 0, 'max_delay_seconds': 0})
    write_json(tmp_path / 'plan.json', plan)
    output = tmp_path / 'run'
    result = e2e.prepare(tmp_path / 'plan.json', output)
    assert result['seeds'] == 1
    manifest = e2e.verify(output)
    return output, manifest, ids


class Server:
    def __init__(self, plan, interrupt_judge=False):
        self.plan, self.interrupt_judge = plan, interrupt_judge
        self.sent = Counter()
        self.responses = Counter()
        self.judge_calls = 0
        self.did_interrupt = False
        self.prefixes = {}
        cfg2 = e2e.step2.Config.load(e2e.path(plan['step2_config']))
        cfg3 = e2e.step3.Config.load(e2e.path(plan['step3_config']))
        for kind, filename in {'card': cfg2.card_prompt, 'admission': cfg2.admission_prompt,
                               'aspect': cfg3.shared_aspects_prompt, 'membership': cfg3.membership_prompt,
                               'composer': plan['composer_prompt'], 'judge': plan['judge_prompt']}.items():
            self.prefixes[kind] = e2e.path(filename).read_text().split('{{')[0]

    def handle(self, request):
        payload = json.loads(request.content)
        self.sent[digest(encoded(payload))] += 1
        messages = payload['messages']
        text = messages[1]['content']
        if messages[0]['content'].startswith('#') or messages[0]['content'] == e2e.path(
                e2e.ProbeConfig.load(e2e.path(self.plan['probe_config'])).prompt_path).read_text():
            kind = 'probe'
        else:
            kind = next(kind for kind, prefix in self.prefixes.items() if text.startswith(prefix))
        paper_ids = list(dict.fromkeys(re.findall(r'"paper_id": "(arxiv:[^"]+)"', text)))
        if kind == 'probe':
            value = {'reason': 'Synthetic shared problem.', 'criteria': {'problem': True,
                     'objects_conditions': False, 'method_mechanism': False, 'results_properties': False},
                     'differences': [], 'verdict': True}
        elif kind == 'card':
            value = {'aspects': [{'problem': 'graph learning', 'mechanism_or_approach': 'message passing',
                     'author_terms': [{'term': 'message passing', 'meaning': 'aggregate neighbors'}],
                     'conventional_terms': [], 'findings': [], 'conditions_and_limits': []}], 'missing_or_unclear': []}
        elif kind == 'admission':
            value = {'reason': 'Synthetic relation.', 'related_paper_ids': [paper_ids[0]],
                     'criteria': {'specific_scientific_relation': True, 'substantive_role': True},
                     'terminology_gap': False, 'limitations': [], 'accept': True}
        elif kind == 'aspect':
            value = {'shared_aspects': [{'rationale': 'Synthetic common mechanism.', 'problem': 'graph learning',
                     'mechanism_or_object': 'message passing', 'conditions': [], 'context': 'synthetic',
                     'support': [pid + '#0' for pid in paper_ids[:2]]}]}
        elif kind == 'membership':
            value = {'reason': 'Synthetic membership.', 'criteria': {key: True for key in e2e.step3.CRITERIA},
                     'own_terms': ['message passing'], 'sections': ['Method'], 'class': 'core'}
        elif kind == 'composer':
            value = {'questions': [{'question': 'How can neighbors share signals for node prediction?',
                                    'answer_paper_ids': paper_ids[:2]}]}
        else:
            assert payload['temperature'] == 0
            self.judge_calls += 1
            if self.interrupt_judge and self.judge_calls == 2 and not self.did_interrupt:
                self.did_interrupt = True
                raise KeyboardInterrupt()
            value = True
        self.responses[kind] += 1
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': 'qwen38_27b',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': json.dumps(value),
                         'reasoning_content': 'Synthetic internal reasoning.'}, 'finish_reason': 'stop'}]})

    def client(self, config, key, journal, retry, **kwargs):
        def factory(cfg, credential):
            return LLMClient(cfg, credential, http_client=httpx.Client(transport=httpx.MockTransport(self.handle)))
        return DurableClient(config, key, journal, retry, factory=factory, **kwargs)


def test_full_chain_uses_real_engines_and_does_not_repeat_completed_work(prepared):
    output, manifest, ids = prepared
    server = Server(manifest['plan'])
    pipeline = e2e.Pipeline(output, manifest, 'synthetic-key', client_factory=server.client)
    summary = pipeline.execute()
    assert summary['stop_reason'] == 'target_reached'
    assert summary['completed_questions'] == 1
    assert set(server.responses) == {'probe', 'card', 'admission', 'aspect', 'membership', 'composer', 'judge'}
    q = summary['questions'][0]
    assert len(q['verdicts']) == 7  # Five subgraph cards + two search-only papers.
    assert len(q['targets']) == 7
    assert all(type(v['verdict']) is bool for v in q['verdicts'])
    outside = [v for v in q['verdicts'] if not v['in_subgraph']]
    assert len(outside) == 2 and all(v['distance_to_subgraph'] == 1 for v in outside)
    assert set(q['methods']['bm25']['target_ranks']) == set(ids)
    assert (output / 'questions.md').is_file()
    before = server.sent.copy()
    again = e2e.Pipeline(output, manifest, 'synthetic-key', client_factory=server.client).execute()
    assert again['completed_questions'] == 1 and server.sent == before


def test_interrupted_judge_resumes_only_missing_pairs(prepared):
    output, manifest, ids = prepared
    server = Server(manifest['plan'], interrupt_judge=True)
    with pytest.raises(KeyboardInterrupt):
        e2e.Pipeline(output, manifest, 'synthetic-key', client_factory=server.client).execute()
    assert len(list(output.glob('seeds/*/groups/*/question-*/judge/*/completed.json'))) == 1
    counts = server.responses.copy()
    result = e2e.Pipeline(output, manifest, 'synthetic-key', client_factory=server.client).execute()
    assert result['completed_questions'] == 1
    for stage in ('probe', 'card', 'admission', 'aspect', 'membership', 'composer'):
        assert server.responses[stage] == counts[stage]
    assert server.responses['judge'] == 7
    assert sum(server.sent.values()) == sum(server.responses.values()) + 1  # Unknown interrupted request.


def test_frozen_config_change_blocks_resume(prepared):
    output, manifest, _ = prepared
    file = e2e.path(manifest['plan']['step2_config'])
    file.write_text(file.read_text() + '\n')
    with pytest.raises(ValueError, match='Frozen source/config/input changed'):
        e2e.verify(output)


def test_missing_judge_is_not_false_and_partial_question_is_not_counted(prepared, monkeypatch):
    output, manifest, ids = prepared
    server = Server(manifest['plan'])
    original = server.handle
    def failed(request):
        payload = json.loads(request.content)
        if payload['messages'][1]['content'].startswith(server.prefixes['judge']):
            return httpx.Response(503, json={'error': {'message': 'synthetic outage'}})
        return original(request)
    server.handle = failed
    summary = e2e.Pipeline(output, manifest, 'synthetic-key', client_factory=server.client).execute()
    assert summary['completed_questions'] == 0
    partial = list(output.glob('seeds/*/groups/*/question-*/attempt-*/partial-verdicts.json'))
    assert partial
    assert all(v['verdict'] is None and v['status'] == 'error' for v in read_json(partial[0])['verdicts'])


def test_interrupted_expansion_replays_admission_without_another_http_call(prepared):
    output, manifest, _ = prepared
    server = Server(manifest['plan'])
    original = server.handle
    interrupted = False
    def stop_before_expansion_card(request):
        nonlocal interrupted
        text = json.loads(request.content)['messages'][1]['content']
        if text.startswith(server.prefixes['card']) and server.responses['card'] == 4 and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()
        return original(request)
    server.handle = stop_before_expansion_card
    first = e2e.Pipeline(output, manifest, 'synthetic-key', client_factory=server.client).execute()
    assert first['completed_questions'] == 0
    assert server.responses['probe'] == 3 and server.responses['card'] == 4
    assert server.responses['admission'] == 1
    result = e2e.Pipeline(output, manifest, 'synthetic-key', client_factory=server.client).execute()
    assert result['completed_questions'] == 1
    assert server.responses['probe'] == 3
    assert server.responses['card'] == 5
    assert server.responses['admission'] == 1
    admissions = [event for event in (output / 'journal/events.jsonl').read_text().splitlines()
                  if json.loads(event)['kind'] == 'cache_hit']
    assert admissions


def test_question_and_target_counts_are_distinct_and_exclude_old_questions():
    old = e2e.question_key('Old question')
    questions = [{'question': 'Old question', 'targets': ['old']},
                 {'question': 'New question', 'targets': ['a', 'b']},
                 {'question': '  NEW  question ', 'targets': ['b', 'c']},
                 {'question': 'Another', 'targets': []}]
    assert e2e.question_counts(questions, [old]) == {'completed_questions': 2, 'confirmed_target_papers': 3}
