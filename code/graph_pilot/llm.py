"""Bounded access to the supplied OpenAI-compatible server; no selection policy."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import getpass
import json
import math
import os
from pathlib import Path
import time
from threading import Lock
from urllib.parse import urlsplit


class LLMError(RuntimeError):
    """Safe to display: never includes response bodies or authentication headers."""

    def __init__(self, message, *, retryable=False, status_code=None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class Config:
    base_url: str
    timeout_seconds: float = 20
    max_requests: int = 2
    max_output_tokens: int = 128
    max_input_characters: int = 20000
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    reasoning_effort: str | None = None

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError('base_url must be an HTTP(S) URL without credentials')
        if url.query or url.fragment:
            raise ValueError('base_url must not contain a query or fragment')
        if self.model is not None and (not isinstance(self.model, str) or not self.model.strip()):
            raise ValueError('model must be a nonempty string or null')
        if self.temperature is not None and (type(self.temperature) not in (int, float)
                or not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2):
            raise ValueError('temperature must be a finite number between 0 and 2 or null')
        if self.top_p is not None and (type(self.top_p) not in (int, float)
                or not math.isfinite(self.top_p) or not 0 < self.top_p <= 1):
            raise ValueError('top_p must be a finite number > 0 and <= 1 or null')
        if self.reasoning_effort is not None and self.reasoning_effort not in ('low', 'medium', 'xhigh'):
            raise ValueError('reasoning_effort must be low, medium, xhigh or null')
        if (type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds)
                or not 0 < self.timeout_seconds <= 3600):
            raise ValueError('timeout_seconds must be > 0 and <= 3600')
        for field in ('max_requests', 'max_output_tokens', 'max_input_characters'):
            if type(getattr(self, field)) is not int or getattr(self, field) < 1:
                raise ValueError(f'{field} must be a positive integer')

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text()))


class LLMClient:
    def __init__(self, config, api_key, *, http_client=None):
        from openai import OpenAI
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError('Set GRAPH_LLM_API_KEY or use --ask-key')
        self.config = config
        self.requests = 0
        self.stopped = False
        self._request_lock = Lock()
        self.client = OpenAI(api_key=api_key, base_url=config.base_url,
                             timeout=config.timeout_seconds, max_retries=0, http_client=http_client)

    def close(self):
        self.client.close()

    def stop(self):
        """Block new admissions; already admitted HTTP operations may still finish."""
        with self._request_lock:
            self.stopped = True

    def _request(self, operation):
        from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAIError
        with self._request_lock:
            if self.stopped:
                raise LLMError('Client stopped after a previous error; no request sent')
            if self.requests >= self.config.max_requests:
                raise LLMError('Request budget exhausted; no request sent')
            self.requests += 1
        try:
            return operation()
        except APIStatusError as exc:
            self.stop()
            raise LLMError(f'LLM HTTP {exc.status_code}; stopped without retry',
                           retryable=exc.status_code in (408, 429, 500, 502, 503, 504),
                           status_code=exc.status_code) from None
        except (APITimeoutError, APIConnectionError) as exc:
            self.stop()
            raise LLMError(f'LLM {type(exc).__name__}; stopped without retry', retryable=True) from None
        except OpenAIError as exc:
            self.stop()
            raise LLMError(f'LLM {type(exc).__name__}; stopped without retry') from None

    def models(self):
        # Do not auto-paginate or choose a scientific model by name/order.
        result = self._request(self.client.models.list)
        return sorted(m.id for m in result.data)

    def complete(self, model, messages):
        if not isinstance(model, str) or not model.strip():
            raise ValueError('An explicit model ID is required')
        if not isinstance(messages, list) or not messages:
            raise ValueError('messages must be a nonempty list')
        for message in messages:
            if not isinstance(message, dict) or set(message) != {'role', 'content'}:
                raise ValueError('Only role/content text messages are supported')
            if message['role'] not in ('system', 'user', 'assistant') or not isinstance(message['content'], str):
                raise ValueError('Unsupported message role or content')
        if sum(len(m['content']) for m in messages) > self.config.max_input_characters:
            raise ValueError('Input character budget exceeded; no request sent')
        options = {key: getattr(self.config, key) for key in ('temperature', 'top_p', 'reasoning_effort')
                   if getattr(self.config, key) is not None}
        started = time.monotonic()
        response = self._request(lambda: self.client.chat.completions.create(
            model=model, messages=messages, max_tokens=self.config.max_output_tokens, **options))
        if not response.choices:
            raise LLMError('Server returned no completion choices')
        choice = response.choices[0]
        return {'requested_model': model, 'response_model': response.model,
                'text': choice.message.content or '', 'finish_reason': choice.finish_reason,
                'message': choice.message.model_dump(exclude_none=True),
                'elapsed_seconds': round(time.monotonic() - started, 3),
                'usage': response.usage.model_dump() if response.usage else None}


def main():
    parser = argparse.ArgumentParser(description='Model list or one bounded connectivity completion')
    parser.add_argument('command', choices=['models', 'smoke'])
    parser.add_argument('--config', type=Path, default=Path(__file__).parent / 'configs/llm-server.json')
    parser.add_argument('--model', help='Override the model ID explicitly selected in the configuration')
    parser.add_argument('--ask-key', action='store_true', help='Read credential with hidden terminal input')
    parser.add_argument('--output', type=Path, help='Write a new credential-free JSON report')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('Use a new output file')
    client = None
    started = time.monotonic()
    try:
        config = Config.load(args.config)
        model = args.model or config.model
        if args.command == 'smoke' and not model:
            parser.error('Select a model in the configuration or pass --model')
        key = getpass.getpass('API credential (hidden): ') if args.ask_key else os.environ.get('GRAPH_LLM_API_KEY')
        client = LLMClient(config, key)
        report = {'purpose': 'connectivity only; not factory step 1.5 selection', 'config': asdict(config),
                  'automatic_retries': 0}
        if args.command == 'models':
            report['model_ids'] = client.models()
            report['ok'] = True
        else:
            completion = client.complete(model, [
                {'role': 'user', 'content': 'Return exactly {"ok":true}. Do not add other text.'}])
            report['completion'] = completion
            report['http_completion_received'] = True
            try:
                report['ok'] = completion['finish_reason'] == 'stop' and json.loads(completion['text']) == {'ok': True}
            except ValueError:
                report['ok'] = False
        report['requests'] = client.requests
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x') as stream:
                stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['ok'] else 1
    except (LLMError, ValueError, TypeError, OSError) as exc:
        # Deliberately omit SDK exception bodies, URLs and headers from errors.
        parser.exit(1, str(exc) + '\n')
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    raise SystemExit(main())
