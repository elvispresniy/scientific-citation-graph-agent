"""Opt-in durable HTTP retries for new e2e runs; legacy runners keep fail-fast behavior."""
from contextlib import contextmanager
from dataclasses import asdict, replace
import fcntl
import gzip
import json
from pathlib import Path
import random
from threading import RLock, Event
import time

from .llm import LLMClient, LLMError
from .step2_features import digest, encoded, read_json, write_json


class RunLimit(LLMError):
    pass


@contextmanager
def exclusive_run(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another worker owns this run') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Journal:
    def __init__(self, directory, *, max_requests, max_hours, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / 'responses').mkdir(exist_ok=True)
        self.lock, self.halted, self.clock = RLock(), Event(), clock
        self.path = self.directory / 'budget.json'
        limits = {'max_requests': max_requests, 'max_hours': max_hours}
        if self.path.exists():
            self.budget = read_json(self.path)
            if self.budget['limits'] != limits:
                raise ValueError('Resume budget differs from frozen run')
        else:
            self.budget = {'limits': limits, 'started_at': clock(), 'http_attempts': 0}
            write_json(self.path, self.budget)
        self.deadline = self.budget['started_at'] + max_hours * 3600
        self.key_locks = {}

    def event(self, **value):
        with self.lock:
            with (self.directory / 'events.jsonl').open('a') as stream:
                stream.write(json.dumps({'time': self.clock(), **value}, ensure_ascii=False) + '\n')
                stream.flush()

    def check(self):
        if self.halted.is_set():
            raise RunLimit('Run halted after a permanent server error')
        if self.clock() >= self.deadline:
            raise RunLimit('Run wall-time limit reached')

    def reserve(self):
        with self.lock:
            self.check()
            if self.budget['http_attempts'] >= self.budget['limits']['max_requests']:
                raise RunLimit('Global HTTP request budget exhausted')
            self.budget['http_attempts'] += 1
            # Reserve before sending: an interrupted/unknown request still consumes budget.
            write_json(self.path, self.budget)

    def key_lock(self, key):
        with self.lock:
            return self.key_locks.setdefault(key, RLock())


class DurableClient:
    """Logical-call interface expected by engines, plus a separate persistent HTTP budget.

    Replay reconstructs deterministic stage state in a new attempt directory. Exact
    successful requests are read from disk; unknown in-flight calls may be resent.
    The server has no idempotency contract, so exactly-once billing is not claimed.
    """
    def __init__(self, config, api_key, journal, retry, *, factory=LLMClient,
                 sleep=time.sleep, validator=None):
        self.config, self.api_key, self.journal = config, api_key, journal
        self.retry, self.factory, self.sleep, self.validator = retry, factory, sleep, validator
        self.requests, self.stopped = 0, False

    def stop(self):
        self.stopped = True

    def close(self):
        pass

    def complete(self, model, messages):
        if self.stopped:
            raise LLMError('Stage client stopped; no request sent')
        if self.requests >= self.config.max_requests:
            raise LLMError('Stage logical request budget exhausted')
        self.requests += 1
        identity = {'model': model, 'messages': messages,
                    'config': {k: v for k, v in asdict(self.config).items() if k != 'max_requests'}}
        key = digest(encoded(identity))
        with self.journal.key_lock(key):
            return self._complete(key, identity, model, messages)

    def _complete(self, key, identity, model, messages):
        directory = self.journal.directory / 'responses' / key
        directory.mkdir(exist_ok=True)
        success = directory / 'success.json.gz'
        if success.exists():
            with gzip.open(success, 'rt') as stream:
                record = json.load(stream)
            if record['identity'] != identity:
                raise ValueError('Response cache identity mismatch')
            if self.validator:
                self.validator(record['completion'])
            self.journal.event(kind='cache_hit', key=key)
            return record['completion']
        attempts = sorted(directory.glob('attempt-*.json'))
        invalid = sum(read_json(p).get('status') == 'invalid_response' for p in attempts)
        if invalid >= self.retry['max_invalid_responses']:
            raise LLMError('Response validation retry limit reached')
        if any(read_json(p).get('status') == 'transport_error'
               and read_json(p).get('retryable') is False for p in attempts):
            self.journal.halted.set()
            raise LLMError('Permanent error recorded for this request; no retry')
        for number in range(len(attempts) + 1, self.retry['max_attempts'] + 1):
            self.journal.reserve()
            path = directory / f'attempt-{number:03d}.json'
            write_json(path, {'status': 'in_flight', 'number': number})
            self.journal.event(kind='http_start', key=key, attempt=number)
            remaining = max(0.001, self.journal.deadline - self.journal.clock())
            client = self.factory(replace(self.config, timeout_seconds=min(self.config.timeout_seconds, remaining)), self.api_key)
            try:
                completion = client.complete(model, messages)
            except LLMError as exc:
                write_json(path, {'status': 'transport_error', 'number': number,
                                  'retryable': exc.retryable, 'status_code': exc.status_code})
                self.journal.event(kind='http_error', key=key, attempt=number,
                                   retryable=exc.retryable, status_code=exc.status_code)
                if not exc.retryable:
                    self.journal.halted.set()
                    raise
            else:
                # Keep every response, including truncated/malformed replies, before validation.
                raw = directory / f'completion-{number:03d}.json.gz'
                with gzip.open(raw, 'wt') as stream:
                    json.dump(completion, stream, ensure_ascii=False)
                try:
                    if self.validator:
                        self.validator(completion)
                except (ValueError, TypeError, KeyError):
                    invalid += 1
                    write_json(path, {'status': 'invalid_response', 'number': number})
                    self.journal.event(kind='invalid_response', key=key, attempt=number)
                    if invalid >= self.retry['max_invalid_responses']:
                        raise LLMError('Response validation retry limit reached') from None
                else:
                    temporary = directory / 'success.tmp.gz'
                    with gzip.open(temporary, 'wt') as stream:
                        json.dump({'identity': identity, 'completion': completion}, stream, ensure_ascii=False)
                    temporary.replace(success)
                    write_json(path, {'status': 'completed', 'number': number})
                    self.journal.event(kind='http_complete', key=key, attempt=number)
                    return completion
            finally:
                client.close()
            if number < self.retry['max_attempts']:
                delay = min(self.retry['max_delay_seconds'],
                            self.retry['initial_delay_seconds'] * 2 ** (number - 1))
                delay *= random.uniform(0.8, 1.2)
                self.journal.event(kind='retry_wait', key=key, seconds=delay)
                # Short waits allow deadline checks and shutdown between retries.
                end = self.journal.clock() + delay
                while self.journal.clock() < end:
                    self.journal.check()
                    self.sleep(min(1, end - self.journal.clock()))
        raise LLMError('Persistent request retry limit reached', retryable=True)
