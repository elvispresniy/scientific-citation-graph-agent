from dataclasses import replace
import gzip
import json

import httpx
import pytest

from graph_pilot.durable_llm import DurableClient, Journal, RunLimit, exclusive_run
from graph_pilot.llm import Config, LLMClient, LLMError


RETRY = {'max_attempts': 3, 'max_invalid_responses': 2,
         'initial_delay_seconds': 0, 'max_delay_seconds': 0}
CONFIG = Config('http://test.invalid/v1', model='test', max_requests=20)
MESSAGES = [{'role': 'user', 'content': 'synthetic input'}]


def make(tmp_path, outcomes, *, budget=20, retry=None, validator=None):
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, int):
            return httpx.Response(outcome, json={'error': {'message': 'secret-server-body'}})
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': 'test',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': outcome}, 'finish_reason': 'stop'}]})
    def factory(config, key):
        return LLMClient(config, key, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    journal = Journal(tmp_path, max_requests=budget, max_hours=1)
    return DurableClient(CONFIG, 'test-secret', journal, retry or RETRY, factory=factory, validator=validator), sent


@pytest.mark.parametrize('status', [408, 429, 500, 502, 503, 504])
def test_transient_failure_retries_and_reuses_success_across_restart(tmp_path, status):
    client, sent = make(tmp_path, [status, 'true'])
    assert client.complete('test', MESSAGES)['text'] == 'true'
    assert client.requests == 1
    assert len(sent) == client.journal.budget['http_attempts'] == 2
    again, other = make(tmp_path, [])
    assert again.complete('test', MESSAGES)['text'] == 'true'
    assert other == []
    assert again.journal.budget['http_attempts'] == 2
    assert 'test-secret' not in (tmp_path / 'events.jsonl').read_text()
    assert 'secret-server-body' not in (tmp_path / 'events.jsonl').read_text()


@pytest.mark.parametrize('status', [400, 401, 403, 404])
def test_permanent_error_halts_without_retry_and_survives_restart(tmp_path, status):
    client, sent = make(tmp_path, [status])
    with pytest.raises(LLMError):
        client.complete('test', MESSAGES)
    assert len(sent) == 1 and client.journal.halted.is_set()
    again, sent = make(tmp_path, [])
    with pytest.raises(LLMError, match='Permanent error'):
        again.complete('test', MESSAGES)
    assert not sent


def test_timeout_retried(tmp_path):
    client, sent = make(tmp_path, [httpx.ReadTimeout('private detail'), 'true'])
    assert client.complete('test', MESSAGES)['text'] == 'true'
    assert len(sent) == 2


def test_invalid_boolean_response_retries_but_false_is_success(tmp_path):
    from graph_pilot.factory_e2e import parse_verdict
    client, sent = make(tmp_path, ['`true`', 'false'], validator=parse_verdict)
    assert parse_verdict(client.complete('test', MESSAGES)) is False
    assert len(sent) == 2
    records = list((tmp_path / 'responses').glob('*/completion-001.json.gz'))
    with gzip.open(records[0], 'rt') as stream:
        assert json.load(stream)['text'] == '`true`'


def test_validation_limit_and_attempt_limit_not_reset_on_resume(tmp_path):
    client, sent = make(tmp_path, ['bad', 'bad'], validator=json.loads)
    # Validator sees a completion object, so explicitly validate its text.
    client.validator = lambda r: json.loads(r['text'])
    with pytest.raises(LLMError, match='validation retry limit'):
        client.complete('test', MESSAGES)
    again, resent = make(tmp_path, [], validator=lambda r: json.loads(r['text']))
    with pytest.raises(LLMError, match='validation retry limit'):
        again.complete('test', MESSAGES)
    assert len(sent) == 2 and not resent


def test_global_budget_counts_failed_attempts_and_never_resets(tmp_path):
    client, sent = make(tmp_path, [503, 503], budget=2)
    with pytest.raises(RunLimit, match='budget exhausted'):
        client.complete('test', MESSAGES)
    assert len(sent) == 2
    again, resent = make(tmp_path, [], budget=2)
    with pytest.raises(RunLimit):
        again.complete('test', MESSAGES)
    assert not resent


def test_unknown_inflight_is_recorded_and_may_be_resent(tmp_path):
    client, sent = make(tmp_path, [KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        client.complete('test', MESSAGES)
    assert len(sent) == 1
    again, resent = make(tmp_path, ['true'])
    assert again.complete('test', MESSAGES)['text'] == 'true'
    assert len(resent) == 1 and again.journal.budget['http_attempts'] == 2


def test_changed_generation_parameters_do_not_reuse_cache(tmp_path):
    client, sent = make(tmp_path, ['true', 'false'])
    client.complete('test', MESSAGES)
    client.config = replace(client.config, temperature=0)
    assert client.complete('test', MESSAGES)['text'] == 'false'
    assert len(sent) == 2


def test_persistent_time_limit(tmp_path):
    journal = Journal(tmp_path, max_requests=4, max_hours=1, clock=lambda: 100)
    assert journal.deadline == 3700
    again = Journal(tmp_path, max_requests=4, max_hours=1, clock=lambda: 3701)
    with pytest.raises(RunLimit, match='wall-time'):
        again.reserve()
    assert again.budget['http_attempts'] == 0


def test_single_writer_lock(tmp_path):
    with exclusive_run(tmp_path):
        with pytest.raises(RuntimeError, match='Another worker'):
            with exclusive_run(tmp_path):
                pytest.fail('must not admit another worker')
    with exclusive_run(tmp_path):
        pass


def test_parallel_identical_calls_share_one_http_attempt(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    first, sent = make(tmp_path, ['true'])
    second = DurableClient(CONFIG, 'test-secret', first.journal, RETRY, factory=first.factory)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda client: client.complete('test', MESSAGES), [first, second]))
    assert [reply['text'] for reply in replies] == ['true', 'true']
    assert len(sent) == first.journal.budget['http_attempts'] == 1
