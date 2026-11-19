from dataclasses import replace
import gzip
import io
import itertools
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from graph_pilot.factory_step1_5 import build_plan, execute, reaggregate
from graph_pilot.llm import Config as LLMConfig, LLMClient
from graph_pilot.probe_modules import (LocalContextGuard, ProbeConfig, ProbeError,
                                       fulltext_preserve, messages_for_pair,
                                       sha256, validate_response)
from graph_pilot.store import Store


def assessment(positive=True):
    return {'reason': 'Supported comparison.',
            'criteria': {'problem': positive, 'objects_conditions': False,
                         'method_mechanism': False, 'results_properties': False},
            'differences': [], 'verdict': positive}


def completion(value, finish='stop'):
    return {'text': json.dumps(value), 'finish_reason': finish}


class Graph:
    base_url = 'http://graph.test'

    def __init__(self):
        self.reads = []
        self.snapshot = 'probe-test'

    def health(self):
        return {'ok': True, 'snapshot_id': self.snapshot}

    def paper(self, pid):
        self.reads.append(pid)
        return {'arxiv_id': pid[6:], 'title': 'Article ' + pid,
                'text': 'Shared mechanism. An independently studied problem.',
                'text_format': 'unarxive_structured_text', 'merged_latex': None}


class Guard:
    def check(self, messages, output_tokens):
        return {'test_guard': True}


class Model:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.requests = 0
        self.messages = []
        self.config = LLMConfig('http://llm.test/v1', model='qwen38_27b', max_requests=100)

    def complete(self, model, messages):
        self.requests += 1
        self.messages.append(messages)
        value = next(self.outcomes)
        return value if isinstance(value, dict) else completion(assessment(value))


@pytest.fixture
def inputs(tmp_path):
    store = Store(tmp_path / 'graph.sqlite')
    store.setting('snapshot_id', 'probe-test')
    ids = [f'arxiv:1901.{i:05d}' for i in range(1, 19)]
    for pid in ids:
        store.upsert(pid, {'title': 'Article ' + pid})
        store.add_node(pid, 0)
        store.source(pid, 'fixture', tmp_path / pid[6:], {}, 'available')
    for start in (0, 6, 12):
        for i in range(start + 1, start + 6):
            store.db.execute('INSERT INTO edges VALUES (?,?,0,?)', (ids[start], ids[i], '{}'))
    store.close()
    seed_report = tmp_path / 'seeds.json'
    seed_report.write_text(json.dumps({'snapshot_id': 'probe-test',
                                      'selected': [{'paper_id': ids[i]} for i in (0, 6, 12)]}))
    prompt = tmp_path / 'prompt.md'
    prompt.write_text('Evaluate A and B with binary criteria.')
    config = ProbeConfig(seed_count=1, max_neighbors=5, min_positive_neighbors=3, rng_seed=42,
                         prompt_path=str(prompt), tokenizer_path=str(tmp_path / 'unused.json'),
                         tokenizer_sha256='0' * 64, max_context_tokens=200000,
                         chat_template_reserve_tokens=2048)
    return store.path, seed_report, config


def run_case(tmp_path, inputs, outcomes, *, config=None, graph=None, guard=None, cap=None):
    db, seeds, default_config = inputs
    config = config or default_config
    model = Model(outcomes)
    graph = graph or Graph()
    report = execute(build_plan(db, seeds, config), config, graph=graph,
                     llm=model, guard=guard or Guard(), output=tmp_path / 'run', max_pairs=cap)
    return report, model, graph


@pytest.mark.parametrize('outcomes', list(itertools.product((False, True), repeat=5)))
def test_threshold_and_exact_early_stop_for_all_five_pair_patterns(tmp_path, inputs, outcomes):
    report, model, graph = run_case(tmp_path, inputs, outcomes)
    assert report['status'] == 'complete'
    seed = report['seeds'][0]
    assert seed['accepted'] is (sum(outcomes) >= 3)
    stopping_index = next(i for i in range(3, 6)
                          if sum(outcomes[:i]) >= 3 or outcomes[:i].count(False) >= 3)
    assert report['attempted_pairs'] == model.requests == stopping_index
    assert len(graph.reads) == stopping_index + 1  # seed is read once
    assert len(set(graph.reads)) == len(graph.reads)
    saved = json.loads((tmp_path / 'run/report.json').read_text())
    assert saved == report
    assert len(list((tmp_path / 'run/pairs').glob('*/completion.json'))) == stopping_index
    assert len(list((tmp_path / 'run/papers').glob('*.json.gz'))) == stopping_index + 1
    # The model sees only neutral articles, no neighbor/graph/seed metadata.
    records = json.loads(model.messages[0][1]['content'])
    assert [r['role'] for r in records] == ['A', 'B']
    assert set(records[0]) == {'role', 'paper_id', 'title', 'text_format', 'text'}
    with gzip.open(tmp_path / 'run/pairs/000001/input.json.gz', 'rt') as stream:
        assert json.load(stream) == model.messages[0]


def test_partial_budget_does_not_become_false_and_reaggregation_needs_no_llm(tmp_path, inputs):
    report, model, _ = run_case(tmp_path, inputs, [True], cap=1)
    assert report['status'] == 'pair_budget'
    assert report['seeds'][0]['accepted'] is None
    assert report['seeds'][0]['unresolved'] == 4
    before = (tmp_path / 'run/report.json').read_bytes()
    assert reaggregate(tmp_path / 'run', threshold=1)['seeds'][0]['accepted'] is True
    assert reaggregate(tmp_path / 'run', threshold=3)['seeds'][0]['accepted'] is None
    assert (tmp_path / 'run/report.json').read_bytes() == before
    assert model.requests == 1


def test_larger_threshold_after_early_stop_is_incomplete_not_false(tmp_path, inputs):
    run_case(tmp_path, inputs, [True, True, True])
    result = reaggregate(tmp_path / 'run', threshold=4)
    assert result['llm_requests'] == 0
    assert result['seeds'][0]['accepted'] is None


@pytest.mark.parametrize('response', [
    {'text': '```json\n{}\n```', 'finish_reason': 'stop'},
    completion(assessment(), 'length'),
    {'text': '', 'finish_reason': 'stop'},
])
def test_invalid_response_saved_and_stops_without_negative_or_replacement(tmp_path, inputs, response):
    config = replace(inputs[2], seed_count=2)
    report, model, graph = run_case(tmp_path, inputs, [response], config=config)
    assert report['status'] == 'stopped_on_error'
    assert model.requests == 1 and len(graph.reads) == 2
    seed = report['seeds'][0]
    assert seed['accepted'] is None and seed['negatives'] == 0 and seed['unresolved'] == 5
    assert seed['pairs'][0]['status'] == 'error'
    assert report['seeds'][1]['status'] == 'not_started'
    saved = json.loads((tmp_path / 'run/pairs/000001/completion.json').read_text())
    assert saved == response


def test_missing_text_stops_before_llm_without_substitution(tmp_path, inputs):
    class Missing(Graph):
        def paper(self, pid):
            if self.reads:
                raise LookupError('private graph response')
            return super().paper(pid)
    report, model, _ = run_case(tmp_path, inputs, [], graph=Missing())
    assert report['status'] == 'stopped_on_error'
    assert model.requests == 0 and report['seeds'][0]['accepted'] is None
    assert 'private graph response' not in json.dumps(report)


def test_context_failure_stops_before_generation(tmp_path, inputs):
    class TooLong:
        def check(self, messages, output_tokens):
            raise ProbeError('Context budget exceeded')
    report, model, _ = run_case(tmp_path, inputs, [], guard=TooLong())
    assert report['status'] == 'stopped_on_error' and model.requests == 0
    assert report['seeds'][0]['accepted'] is None
    assert (tmp_path / 'run/pairs/000001/input.json.gz').is_file()


def test_graph_snapshot_mismatch_stops_before_texts(tmp_path, inputs):
    graph = Graph()
    graph.snapshot = 'other-snapshot'
    report, model, _ = run_case(tmp_path, inputs, [], graph=graph)
    assert report['status'] == 'stopped_on_error'
    assert model.requests == 0 and not graph.reads
    assert report['seeds'][0]['status'] == 'not_started'


def test_request_budget_stops_before_more_texts(tmp_path, inputs):
    db, seeds, config = inputs
    model = Model([True])
    model.config = replace(model.config, max_requests=1)
    graph = Graph()
    report = execute(build_plan(db, seeds, config), config, graph=graph, llm=model,
                     guard=Guard(), output=tmp_path / 'run')
    assert report['status'] == 'request_budget'
    assert report['seeds'][0]['accepted'] is None and len(graph.reads) == 2


def test_429_stops_entire_run_and_never_leaks_transport_details(tmp_path, inputs):
    pytest.importorskip('openai')
    sent = []
    def handle(request):
        sent.append(request)
        return httpx.Response(429, json={'error': {'message': 'private-body'}})
    db, seeds, config = inputs
    config = replace(config, seed_count=2)
    client = LLMClient(LLMConfig('http://llm.test/v1', model='qwen38_27b'), 'private-key',
                       http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        report = execute(build_plan(db, seeds, config), config, graph=Graph(), llm=client,
                         guard=Guard(), output=tmp_path / 'run')
        assert len(sent) == 1 and client.stopped
        assert report['status'] == 'stopped_on_error'
        assert report['seeds'][0]['accepted'] is None
        assert report['seeds'][1]['status'] == 'not_started'
        text = (tmp_path / 'run/report.json').read_text()
        assert '429' in text and 'private-key' not in text and 'private-body' not in text
    finally:
        client.close()


def test_plan_is_repeatable_and_does_not_read_sources_or_write_database(inputs):
    db, seeds, config = inputs
    before = sha256(Path(db).read_bytes())
    plan = build_plan(db, seeds, config)
    assert plan == build_plan(db, seeds, config)
    assert plan['neighbors']['pair_count'] == 5
    assert sha256(Path(db).read_bytes()) == before


def test_small_pool_does_not_lower_threshold_or_call_model(tmp_path, inputs):
    db, seeds, config = inputs
    store = Store(db)
    store.db.execute('DELETE FROM edges WHERE dst NOT IN (SELECT dst FROM edges ORDER BY dst LIMIT 2)')
    store.close()
    report, model, graph = run_case(tmp_path, inputs, [])
    assert report['seeds'][0]['accepted'] is False
    assert model.requests == 0 and not graph.reads


@pytest.mark.parametrize('change', ['strings', 'integer', 'only_objects', 'unknown_field'])
def test_response_contract_rejects_false_boolean_and_unsupported_positive(change):
    value = assessment()
    if change == 'strings':
        value['criteria']['problem'] = 'true'
    elif change == 'integer':
        value['verdict'] = 1
    elif change == 'only_objects':
        value['criteria']['problem'] = False
        value['criteria']['objects_conditions'] = True
    else:
        value['extra'] = True
    with pytest.raises(ProbeError):
        validate_response(completion(value))


def test_duplicate_keys_are_not_silently_overwritten():
    with pytest.raises(ProbeError, match='Duplicate'):
        validate_response({'text': '{"verdict":true,"verdict":false}', 'finish_reason': 'stop'})


def test_negative_verdict_can_retain_core_match_with_explained_condition_difference():
    value = assessment()
    value['verdict'] = False
    value['differences'] = ['The essential assumptions prevent a supported shared claim.']
    assert validate_response(completion(value)) == value


def test_positive_response_needs_no_evidence_or_source_texts():
    value = assessment()
    assert 'evidence' not in value
    assert validate_response(completion(value))['verdict'] is True


@pytest.mark.parametrize('evidence', [None, [], [{'paper': 'A', 'quote': 'Unmatched diagnostic text.'}]])
def test_legacy_evidence_is_opaque_and_never_blocks_decision(evidence):
    value = assessment()
    value['evidence'] = evidence
    assert validate_response(completion(value)) == value


@pytest.mark.parametrize('field', ['reasoning', 'reasoning_content'])
def test_provider_reasoning_saved_separately_without_new_requests(tmp_path, inputs, field):
    value = completion(assessment())
    value['message'] = {field: 'Provider returned diagnostic reasoning.'}
    report, model, _ = run_case(tmp_path, inputs, [value] * 3)
    assert report['seeds'][0]['accepted'] is True and model.requests == 3
    saved = json.loads((tmp_path / 'run/pairs/000001/reasoning.json').read_text())
    assert saved == {'available': True, 'provider_fields': {field: value['message'][field]}}


def test_missing_provider_reasoning_does_not_block_pair(tmp_path, inputs):
    report, model, _ = run_case(tmp_path, inputs, [True] * 3)
    assert report['seeds'][0]['accepted'] is True
    saved = json.loads((tmp_path / 'run/pairs/000001/reasoning.json').read_text())
    assert saved == {'available': False, 'provider_fields': {}}


def test_reasoning_saved_even_when_final_json_is_invalid(tmp_path, inputs):
    value = {'text': 'invalid json', 'finish_reason': 'stop', 'message': {'reasoning': 'Diagnostic text.'}}
    report, model, _ = run_case(tmp_path, inputs, [value])
    assert report['status'] == 'stopped_on_error' and model.requests == 1
    saved = json.loads((tmp_path / 'run/pairs/000001/reasoning.json').read_text())
    assert saved['provider_fields']['reasoning'] == 'Diagnostic text.'


def test_v1_prompt_requests_explanation_before_final_verdict_without_evidence():
    text = (Path(__file__).parents[1] / 'prompts/step1_5-pair-v1.md').read_text()
    example = json.loads(text.split('```json\n', 1)[1].split('```', 1)[0])
    assert list(example) == ['reason', 'criteria', 'differences', 'verdict']
    assert 'evidence' not in example
    assert all(type(v) is bool for v in example['criteria'].values())
    assert type(example['verdict']) is bool
    assert not any(word in text.lower() for word in ('затрав', 'граф', 'перспектив', 'окружен'))


def test_text_preparer_preserves_structured_text_and_scientific_latex():
    pid = 'arxiv:1901.00001'
    payload = Graph().paper(pid)
    assert fulltext_preserve(payload, pid)['text'] == payload['text']
    payload['merged_latex'] = (r'\newcommand{\method}{ScientificMethod}\begin{document}'
                               r'Use \method. $\frac{x}{y}$ '
                               r'\begin{table}Accuracy 0.97\end{table}\end{document}')
    value = fulltext_preserve(payload, pid)
    assert value['text_format'] == 'latex_preserved_text'
    assert r'\frac{x}{y}' in value['text'] and '0.97' in value['text']
    assert r'\newcommand{\method}{ScientificMethod}' in value['text']
    assert value['source_text'] == payload['merged_latex']


def test_real_local_token_guard_without_any_corpus_measurements(tmp_path, inputs):
    tokenizers = pytest.importorskip('tokenizers')
    tokenizer = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0, 'test': 1}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    path = tmp_path / 'tiny-tokenizer.json'
    tokenizer.save(str(path))
    config = replace(inputs[2], tokenizer_path=str(path), tokenizer_sha256=sha256(path.read_bytes()),
                     max_context_tokens=10, chat_template_reserve_tokens=2)
    guard = LocalContextGuard(config)
    messages = [{'role': 'user', 'content': 'test test'}]
    assert guard.check(messages, 6)['content_tokens'] == 2
    with pytest.raises(ProbeError, match='Context budget'):
        guard.check(messages, 7)
    with pytest.raises(ProbeError, match='SHA-256'):
        LocalContextGuard(replace(config, tokenizer_sha256='0' * 64))


def test_config_paths_resolve_against_config_file(tmp_path, inputs):
    data = inputs[2].manifest()
    data['prompt_path'] = 'relative/prompt.md'
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(data))
    config = ProbeConfig.load(config_path)
    assert config.prompt_path == str(tmp_path / 'relative/prompt.md')
    with pytest.raises(ValueError, match='Unknown neighbor_selector'):
        replace(config, neighbor_selector='not_implemented')
    with pytest.raises(ValueError, match='<= max_neighbors'):
        replace(config, min_positive_neighbors=6)


def test_full_api_and_sdk_pipeline_in_process_without_network(tmp_path, inputs, monkeypatch):
    pytest.importorskip('openai')
    from fastapi.testclient import TestClient
    from graph_pilot.api import create_app
    from graph_pilot.client import GraphClient
    db, seeds, config = inputs
    store = Store(db)
    store.db.execute('DELETE FROM sources')
    for row in store.db.execute('SELECT id FROM papers').fetchall():
        path = tmp_path / (row[0][6:] + '.txt')
        path.write_text('Shared mechanism. A scientific statement.')
        store.source(row[0], 'plain_text', path, {}, 'available')
    store.close()
    with TestClient(create_app(db)) as api:
        routes = []
        def get(url, timeout):
            routes.append(urlsplit(url).path)
            result = api.get(urlsplit(url).path)
            assert result.status_code == 200
            return io.BytesIO(result.content)
        monkeypatch.setattr('graph_pilot.client.urlopen', get)
        def handle(request):
            content = json.loads(request.content)
            articles = json.loads(content['messages'][1]['content'])
            assert all('Shared mechanism.' in a['text'] for a in articles)
            return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1,
                'model': 'qwen38_27b', 'choices': [{'index': 0, 'message': {
                    'role': 'assistant', 'content': json.dumps(assessment())}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}})
        client = LLMClient(LLMConfig('http://llm.test/v1', model='qwen38_27b', max_requests=5), 'mock-key',
                           http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        try:
            report = execute(build_plan(db, seeds, config), config, graph=GraphClient('http://graph.test'),
                             llm=client, guard=Guard(), output=tmp_path / 'run')
        finally:
            client.close()
    assert report['status'] == 'complete' and report['seeds'][0]['accepted'] is True
    assert client.requests == 3 and report['graph_identity']['verified']
    assert routes[0] == '/healthz' and len(routes) == 5  # seed + 3 neighbors
    assert all(p['assessment']['verdict'] is True for p in report['seeds'][0]['pairs'])


def test_interruption_preserves_completed_assessments(tmp_path, inputs):
    class Interrupted(Model):
        def complete(self, model, messages):
            if self.requests == 1:
                raise KeyboardInterrupt()
            return super().complete(model, messages)
    db, seeds, config = inputs
    report = execute(build_plan(db, seeds, config), config, graph=Graph(),
                     llm=Interrupted([True]), guard=Guard(), output=tmp_path / 'run')
    assert report['status'] == 'interrupted' and report['llm_requests'] == 1
    seed = report['seeds'][0]
    assert seed['positives'] == 1 and seed['accepted'] is None
    assert seed['pairs'][0]['status'] == 'evaluated' and seed['pairs'][1]['status'] == 'error'
