"""Two narrow, lossless serialization adapters for card list items."""
from __future__ import annotations

from copy import deepcopy

from .step2_features import digest, encoded


def _exact(item, keys):
    return (isinstance(item, dict) and set(item) == keys
            and all(isinstance(v, str) and v.strip() for v in item.values()))


def normalize_card_format(value):
    """Preserve all values except two exact serialization defects.

    statement/concern objects in conditions_and_limits and missing_or_unclear
    become one string; a term object wrapped in a one-element list inside
    author_terms or conventional_terms is unwrapped. Unsupported shapes are
    deliberately left unchanged for the strict card validator. Original strings
    are not stripped, summarized, or interpreted.
    """
    source_hash = digest(encoded(value))
    normalized = deepcopy(value)
    paths, rules = [], {}

    def convert(items, prefix):
        if not isinstance(items, list):
            return
        for index, item in enumerate(items):
            if _exact(item, {'statement', 'concern'}):
                items[index] = item['statement'] + ' [Concern: ' + item['concern'] + ']'
                paths.append(prefix + '/' + str(index))
                rules[paths[-1]] = 'statement-concern-to-string'

    def unwrap(items, prefix):
        if not isinstance(items, list):
            return
        for index, item in enumerate(items):
            if isinstance(item, list) and len(item) == 1 and _exact(item[0], {'term', 'meaning'}):
                items[index] = item[0]
                paths.append(prefix + '/' + str(index))
                rules[paths[-1]] = 'unwrap-single-term-list'

    if isinstance(normalized, dict):
        convert(normalized.get('missing_or_unclear'), '/missing_or_unclear')
        aspects = normalized.get('aspects')
        if isinstance(aspects, list):
            for index, aspect in enumerate(aspects):
                if isinstance(aspect, dict):
                    prefix = '/aspects/' + str(index)
                    convert(aspect.get('conditions_and_limits'), prefix + '/conditions_and_limits')
                    for field in ('author_terms', 'conventional_terms'):
                        unwrap(aspect.get(field), prefix + '/' + field)
    return normalized, {
        'adapter': 'card-list-serialization-v2',
        'source_encoding': 'canonical-json-sort-keys-utf8',
        'source_json_sha256': source_hash,
        'normalized_json_sha256': digest(encoded(normalized)),
        'applied': bool(paths),
        'paths': paths,
        'rules': rules,
    }
