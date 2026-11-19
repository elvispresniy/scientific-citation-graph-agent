from collections import Counter
from dataclasses import replace
import json
from threading import Barrier, Event, Lock

import httpx
import pytest

pytest.importorskip('openai')

from graph_pilot.factory_step1_5 import build_plan, execute
from graph_pilot.probe_modules import ProbeError
from graph_pilot.llm import Config as LLMConfig, LLMClient
from graph_pilot.tests.test_factory_step1_5 import Graph, Guard, assessment, inputs


def response(value=None):
    return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1,
        'model': 'qwen38_27b', 'choices': [{'index': 0, 'message': {
            'role': 'assistant', 'content': json.dumps(assessment()) if value is None else value},
            'finish_reason': 'stop'}]})


def client_for(handle, budget=100):
    return LLMClient(LLMConfig('http://llm.test/v1', model='qwen38_27b', max_requests=budget),
                     'mock-key', http_client=httpx.Client(transport=httpx.MockTransport(handle)))


def test_three_seeds_concurrent_but_one_pair_per_seed_and_no_extra_neighbors(tmp_path, inputs):
    db, seeds, config = inputs
    config = replace(config, seed_count=3, max_concurrent_seeds=3)
    barrier, lock = Barrier(3), Lock()
    in_flight, calls = Counter(), Counter()
    total_active, peak = 0, 0

    def handle(request):
        nonlocal total_active, peak
        pid = json.loads(json.loads(request.content)['messages'][1]['content'])[0]['paper_id']
        with lock:
            calls[pid] += 1
            in_flight[pid] += 1
            assert in_flight[pid] == 1
            total_active += 1
            peak = max(peak, total_active)
            first = calls[pid] == 1
        if first:
            barrier.wait(timeout=5)
        with lock:
            total_active -= 1
            in_flight[pid] -= 1
        return response()

    client, graph = client_for(handle), Graph()
    try:
        report = execute(build_plan(db, seeds, config), config, graph=graph, llm=client,
                         guard=Guard(), output=tmp_path / 'run')
    finally:
        client.close()
    assert report['status'] == 'complete'
    assert peak == 3 and len(calls) == 3
    assert list(calls.values()) == [3, 3, 3]
    assert client.requests == report['llm_requests'] == 9
    assert len(graph.reads) == len(set(graph.reads)) == 12
    assert all(s['accepted'] is True and len(s['pairs']) == 3 for s in report['seeds'])


@pytest.mark.parametrize('budget_kind', ['pair_budget', 'request_budget'])
@pytest.mark.parametrize('limit', [1, 2, 4])
def test_global_budget_exact_under_parallel_dispatch(tmp_path, inputs, budget_kind, limit):
    db, seeds, config = inputs
    config = replace(config, seed_count=3, max_concurrent_seeds=3)
    sent, lock = [], Lock()
    def handle(request):
        with lock:
            sent.append(request)
        return response()
    client = client_for(handle, budget=limit if budget_kind == 'request_budget' else 100)
    try:
        report = execute(build_plan(db, seeds, config), config, graph=Graph(), llm=client,
                         guard=Guard(), output=tmp_path / 'run',
                         max_pairs=limit if budget_kind == 'pair_budget' else None)
    finally:
        client.close()
    assert len(sent) == client.requests == limit
    assert report['status'] == budget_kind
    assert report['attempted_pairs'] == limit
    assert sum(s['positives'] for s in report['seeds']) == limit
    assert all(s['accepted'] is None for s in report['seeds'])


@pytest.mark.parametrize('failure', ['429', 'invalid_json'])
def test_error_blocks_admissions_retains_already_sent_responses(tmp_path, inputs, failure):
    db, seeds, config = inputs
    config = replace(config, seed_count=3, max_concurrent_seeds=3)
    barrier, stopped, lock = Barrier(3), Event(), Lock()
    sent = []
    def handle(request):
        pid = json.loads(json.loads(request.content)['messages'][1]['content'])[0]['paper_id']
        with lock:
            sent.append(pid)
        barrier.wait(timeout=5)
        if pid == 'arxiv:1901.00001':
            return (httpx.Response(429, json={'error': {'message': 'private-error-body'}})
                    if failure == '429' else response('{invalid-json}'))
        assert stopped.wait(timeout=5)
        return response()
    client = client_for(handle)
    original_stop = client.stop
    def stop():
        original_stop()
        stopped.set()
    client.stop = stop
    try:
        report = execute(build_plan(db, seeds, config), config, graph=Graph(), llm=client,
                         guard=Guard(), output=tmp_path / 'run')
    finally:
        client.close()
    assert len(sent) == client.requests == 3
    assert client.stopped and report['status'] == 'stopped_on_error'
    assert len(set(sent)) == 3
    assert all(s['accepted'] is None and s['negatives'] == 0 for s in report['seeds'])
    assert sum(s['positives'] for s in report['seeds']) == 2
    assert len(list((tmp_path / 'run/pairs').glob('*/completion.json'))) == (2 if failure == '429' else 3)
    raw = (tmp_path / 'run/report.json').read_text()
    assert 'mock-key' not in raw and 'private-error-body' not in raw
    if failure == '429':
        assert '429' in raw


def test_invalid_concurrency_values_rejected(inputs):
    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match='max_concurrent_seeds'):
            replace(inputs[2], max_concurrent_seeds=value)


def test_preparation_error_stops_and_drains_an_existing_request(tmp_path, inputs):
    db, seeds, config = inputs
    config = replace(config, seed_count=3, max_concurrent_seeds=3)
    started, stopped = Event(), Event()
    def handle(request):
        started.set()
        assert stopped.wait(timeout=5)
        return response()
    client = client_for(handle)
    original_stop = client.stop
    def stop():
        original_stop()
        stopped.set()
    client.stop = stop
    class FailSecond(Guard):
        checks = 0
        def check(self, messages, output_tokens):
            self.checks += 1
            if self.checks == 2:
                assert started.wait(timeout=5)
                raise ProbeError('Input preparation failed')
            return super().check(messages, output_tokens)
    try:
        report = execute(build_plan(db, seeds, config), config, graph=Graph(), llm=client,
                         guard=FailSecond(), output=tmp_path / 'run')
    finally:
        client.close()
    assert client.requests == 1 and report['status'] == 'stopped_on_error'
    assert report['seeds'][0]['positives'] == 1
    assert report['seeds'][1]['pairs'][0]['status'] == 'error'
    assert report['seeds'][2]['status'] == 'not_started'
    assert all(s['accepted'] is None for s in report['seeds'])
