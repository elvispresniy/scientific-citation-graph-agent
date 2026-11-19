import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import httpx
import pytest

pytest.importorskip('openai')

from graph_pilot.llm import Config, LLMClient, LLMError


def test_compatible_routes_auth_and_budgets():
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers['authorization'] == 'Bearer test-credential'
        if request.method == 'GET':
            assert request.url.path == '/v1/models'
            return httpx.Response(200, json={'object': 'list', 'data': [
                {'id': 'model-b', 'object': 'model'}, {'id': 'model-a', 'object': 'model'}]})
        assert request.url.path == '/v1/chat/completions'
        body = json.loads(request.content)
        assert body['max_tokens'] == 128 and body['model'] == 'model-a'
        assert 'test-credential' not in request.content.decode()
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1,
            'model': 'model-a', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '{"ok":true}'},
                                           'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 5, 'total_tokens': 10}})

    client = LLMClient(Config('http://example.test/v1'), 'test-credential',
                       http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        assert client.models() == ['model-a', 'model-b']
        result = client.complete('model-a', [{'role': 'user', 'content': 'Check'}])
        assert json.loads(result['text']) == {'ok': True}
        assert result['usage']['total_tokens'] == 10
        with pytest.raises(LLMError, match='budget exhausted'):
            client.models()
        assert len(requests) == 2
    finally:
        client.close()


@pytest.mark.parametrize('status', [401, 429, 503])
def test_errors_stop_immediately_without_leaking_response_body(status):
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(status, json={'error': {'message': 'private-response-content'}})

    client = LLMClient(Config('http://example.test/v1'), 'test-credential',
                       http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        with pytest.raises(LLMError) as failure:
            client.models()
        assert str(status) in str(failure.value)
        assert 'private-response-content' not in str(failure.value)
        assert 'test-credential' not in str(failure.value)
        with pytest.raises(LLMError, match='stopped after'):
            client.models()
        assert len(sent) == 1
    finally:
        client.close()


def test_input_limit_before_network():
    client = LLMClient(Config('http://example.test/v1', max_input_characters=3), 'test-credential',
                       http_client=httpx.Client(transport=httpx.MockTransport(
                           lambda request: pytest.fail('No network request expected'))))
    try:
        with pytest.raises(ValueError, match='character budget'):
            client.complete('model', [{'role': 'user', 'content': 'long input'}])
        assert client.requests == 0
    finally:
        client.close()


def test_no_implicit_key_or_official_endpoint_fallback():
    with pytest.raises(ValueError, match='GRAPH_LLM_API_KEY'):
        LLMClient(Config('http://example.test/v1'), None)
    with pytest.raises(ValueError, match='without credentials'):
        Config('http://secret@example.test/v1')


def test_timeout_is_not_retried():
    sent = []

    def handle(request):
        sent.append(request)
        raise httpx.ReadTimeout('private-transport-details', request=request)

    client = LLMClient(Config('http://example.test/v1'), 'test-credential',
                       http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        with pytest.raises(LLMError, match='APITimeoutError') as failure:
            client.models()
        assert 'private-transport-details' not in str(failure.value)
        assert len(sent) == 1 and client.stopped
    finally:
        client.close()


def test_explicit_temperature_sent_and_invalid_values_rejected():
    def handle(request):
        assert json.loads(request.content)['temperature'] == 0
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1,
            'model': 'model', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '{}'},
                                         'finish_reason': 'stop'}]})
    client = LLMClient(Config('http://example.test/v1', temperature=0), 'test-credential',
                       http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        client.complete('model', [{'role': 'user', 'content': 'Check'}])
    finally:
        client.close()
    for value in (True, float('nan'), float('inf'), -1, 3, '0'):
        with pytest.raises(ValueError, match='temperature'):
            Config('http://example.test/v1', temperature=value)


def test_shared_client_budget_is_thread_safe():
    barrier, lock = Barrier(7), Lock()
    sent = []
    def handle(request):
        with lock:
            sent.append(request)
        barrier.wait(timeout=5)
        return httpx.Response(200, json={'object': 'list', 'data': []})
    client = LLMClient(Config('http://example.test/v1', max_requests=7), 'test-credential',
                       http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        def attempt(_):
            try:
                client.models()
                return True
            except LLMError as exc:
                assert 'budget exhausted' in str(exc)
                return False
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(attempt, range(20)))
        assert sum(results) == len(sent) == client.requests == 7
    finally:
        client.close()


def test_scientific_budget_fields_and_provider_message_preserved():
    def handle(request):
        body = json.loads(request.content)
        assert body['top_p'] == 0.95 and body['reasoning_effort'] == 'medium'
        assert body['max_tokens'] == 8192 and body['temperature'] == 1.0
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1,
            'model': 'qwen38_27b', 'choices': [{'index': 0, 'message': {'role': 'assistant',
                'content': '{}', 'reasoning': 'Provider returned diagnostic text.'}, 'finish_reason': 'stop'}]})
    config = Config('http://example.test/v1', timeout_seconds=300, max_output_tokens=8192,
                    temperature=1, top_p=0.95, reasoning_effort='medium')
    client = LLMClient(config, 'test-credential',
                       http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        result = client.complete('qwen38_27b', [{'role': 'user', 'content': 'Compare'}])
        assert result['message']['reasoning'] == 'Provider returned diagnostic text.'
        assert result['elapsed_seconds'] >= 0
    finally:
        client.close()
    for value in (0, -1, 1.1, True, float('nan'), '0.95'):
        with pytest.raises(ValueError, match='top_p'):
            Config('http://example.test/v1', top_p=value)
    for value in ('high', '', True):
        with pytest.raises(ValueError, match='reasoning_effort'):
            Config('http://example.test/v1', reasoning_effort=value)
    for value in (0, -1, 3601, True, float('inf'), '300'):
        with pytest.raises(ValueError, match='timeout_seconds'):
            Config('http://example.test/v1', timeout_seconds=value)
