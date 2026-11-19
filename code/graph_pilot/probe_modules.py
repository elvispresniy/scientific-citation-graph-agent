"""Replaceable components of factory step 1.5; no network calls at import time."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from .latex_to_text import latex_to_index_text
from .sample_neighbors import sample
from .store import canonical_id


CRITERIA = ('problem', 'objects_conditions', 'method_mechanism', 'results_properties')
CORE_CRITERIA = ('problem', 'method_mechanism', 'results_properties')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


class ProbeError(ValueError):
    """Fixed diagnostic text safe to store; never include an HTTP response body."""


@dataclass(frozen=True)
class ProbeConfig:
    seed_count: int
    max_neighbors: int
    min_positive_neighbors: int
    rng_seed: int
    prompt_path: str
    tokenizer_path: str
    tokenizer_sha256: str
    max_context_tokens: int
    chat_template_reserve_tokens: int
    neighbor_selector: str = 'uniform_index_v1'
    text_preparer: str = 'fulltext_preserve_v1'
    pair_policy: str = 'model_verdict_v1'
    seed_policy: str = 'min_positive_v1'
    max_concurrent_seeds: int = 1

    def __post_init__(self):
        for name in ('seed_count', 'max_neighbors', 'min_positive_neighbors',
                     'max_context_tokens', 'chat_template_reserve_tokens', 'max_concurrent_seeds'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.min_positive_neighbors > self.max_neighbors:
            raise ValueError('min_positive_neighbors must be <= max_neighbors')
        if type(self.rng_seed) is not int:
            raise ValueError('rng_seed must be an integer')
        for field in ('prompt_path', 'tokenizer_path'):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f'{field} must be a nonempty path')
        if (not isinstance(self.tokenizer_sha256, str) or len(self.tokenizer_sha256) != 64
                or any(c not in '0123456789abcdef' for c in self.tokenizer_sha256)):
            raise ValueError('tokenizer_sha256 must be a lowercase SHA-256')
        for field, registry in [('neighbor_selector', NEIGHBOR_SELECTORS),
                                ('text_preparer', TEXT_PREPARERS), ('pair_policy', PAIR_POLICIES),
                                ('seed_policy', SEED_POLICIES)]:
            if not isinstance(getattr(self, field), str) or getattr(self, field) not in registry:
                raise ValueError(f'Unknown {field}')

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        data = json.loads(path.read_text())
        for field in ('prompt_path', 'tokenizer_path'):
            if field in data and isinstance(data[field], str):
                data[field] = str((path.parent / data[field]).resolve())
        return cls(**data)

    def manifest(self):
        return asdict(self)


def uniform_index(database, seed_report, config):
    plan = sample(database, seed_report, budget=config.max_neighbors,
                  rng_seed=config.rng_seed, seed_count=config.seed_count)
    plan['purpose'] = 'Factory step 1.5 frozen neighbor order; no text reads or LLM calls'
    return plan


def fulltext_preserve(payload, paper_id):
    """Use the same /paper response for local and original APIs; clean only LaTeX."""
    if canonical_id(payload.get('arxiv_id', '')) != paper_id:
        raise ProbeError('Graph returned a different paper ID')
    latex = payload.get('merged_latex')
    if isinstance(latex, str) and latex.strip():
        source_text, source_format = latex, 'merged_latex'
        clean = latex_to_index_text(latex)
        text, text_format = clean['text'], 'latex_preserved_text'
        processing = {'name': 'latex_to_index_text',
                      'implementation_sha256': sha256(Path(__file__).with_name('latex_to_text.py').read_bytes()),
                      'preservation_fallback': clean['preservation_fallback']}
    else:
        source_text, source_format = payload.get('text'), payload.get('text_format')
        if not isinstance(source_text, str) or not source_text.strip():
            raise ProbeError('No readable text in graph response')
        if not isinstance(source_format, str) or not source_format.strip():
            raise ProbeError('Missing text format in graph response')
        text, text_format = source_text, source_format
        processing = {'name': 'identity'}
    if not text.strip():
        raise ProbeError('Text preparation returned empty text')
    title = payload.get('title')
    if title is not None and not isinstance(title, str):
        raise ProbeError('Invalid paper title')
    return {'paper_id': paper_id, 'title': title, 'text_format': text_format, 'text': text,
            'source_text': source_text, 'source_format': source_format,
            'source_text_sha256': sha256(source_text.encode()),
            'text_sha256': sha256(text.encode()), 'processing': processing,
            'provenance': payload.get('provenance')}


def messages_for_pair(prompt, article_a, article_b):
    articles = []
    for role, article in [('A', article_a), ('B', article_b)]:
        articles.append({'role': role, **{k: article[k] for k in
                        ('paper_id', 'title', 'text_format', 'text')}})
    return [{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': json.dumps(articles, ensure_ascii=False, allow_nan=False)}]


class LocalContextGuard:
    """Local tokenizer + explicit framing reserve; remote chat template is unverified."""

    def __init__(self, config):
        from tokenizers import Tokenizer
        source = Path(config.tokenizer_path).read_bytes()
        if sha256(source) != config.tokenizer_sha256:
            raise ProbeError('Tokenizer SHA-256 mismatch')
        self.tokenizer = Tokenizer.from_str(source.decode())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.config = config

    def check(self, messages, output_tokens):
        count = sum(len(self.tokenizer.encode(m['content'], add_special_tokens=False).ids)
                    for m in messages)
        reserved = count + self.config.chat_template_reserve_tokens + output_tokens
        if reserved > self.config.max_context_tokens:
            raise ProbeError('Context budget exceeded; no truncation or LLM request')
        return {'content_tokens': count,
                'chat_template_reserve_tokens': self.config.chat_template_reserve_tokens,
                'max_output_tokens': output_tokens, 'max_context_tokens': self.config.max_context_tokens,
                'remote_tokenizer_and_chat_template_verified': False}


def _unique_object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ProbeError('Duplicate JSON key in model response')
        result[k] = v
    return result


def _invalid_constant(value):
    raise ProbeError('Nonfinite JSON value in model response')


RESPONSE_SCHEMA = 'binary-comparison-v1-no-quote-check'


def reasoning_record(completion):
    """Keep provider-returned reasoning as optional internal diagnostics."""
    message = completion.get('message') or {}
    fields = {key: message[key] for key in ('reasoning', 'reasoning_content')
              if message.get(key) is not None and message[key] != ''}
    return {'available': bool(fields), 'provider_fields': fields}


def validate_response(completion):
    if completion.get('finish_reason') != 'stop':
        raise ProbeError('Completion did not finish normally')
    try:
        result = json.loads(completion['text'], object_pairs_hook=_unique_object,
                            parse_constant=_invalid_constant)
    except (json.JSONDecodeError, TypeError, KeyError):
        raise ProbeError('Model response is not a JSON object') from None
    required = {'criteria', 'verdict', 'reason'}
    optional = {'differences', 'evidence'}
    if (not isinstance(result, dict) or not required <= set(result)
            or set(result) - required - optional):
        raise ProbeError('Unexpected response schema')
    criteria = result['criteria']
    if (not isinstance(criteria, dict) or set(criteria) != set(CRITERIA)
            or any(type(v) is not bool for v in criteria.values())
            or type(result['verdict']) is not bool):
        raise ProbeError('All criteria and verdict must be JSON booleans')
    if not isinstance(result['reason'], str) or not result['reason'].strip():
        raise ProbeError('Missing explanation')
    if ('differences' in result and (not isinstance(result['differences'], list)
            or any(not isinstance(x, str) or not x.strip() for x in result['differences']))):
        raise ProbeError('Invalid differences')
    if result['verdict'] and not any(criteria[k] for k in CORE_CRITERIA):
        raise ProbeError('Positive verdict requires a core criterion')
    # Legacy evidence is retained as opaque diagnostics. Neither its shape nor
    # textual matches affect a preliminary pair decision. Source texts are not read.
    return result


def model_verdict(assessment):
    return assessment['verdict']


def min_positive(positives, unresolved, threshold):
    if positives >= threshold:
        return True
    if positives + unresolved < threshold:
        return False
    return None


NEIGHBOR_SELECTORS = {'uniform_index_v1': uniform_index}
TEXT_PREPARERS = {'fulltext_preserve_v1': fulltext_preserve}
PAIR_POLICIES = {'model_verdict_v1': model_verdict}
SEED_POLICIES = {'min_positive_v1': min_positive}
