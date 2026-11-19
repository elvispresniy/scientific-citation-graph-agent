"""Conservative runtime availability checks; no scientific relevance verdicts."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import re

from .step2_features import digest
from .store import canonical_id


_LAYOUT_FLAGS = {
    'noitemsep', 'nosep', 'notopsep', 'compact', 'onecolumn', 'twocolumn',
    'landscape', 'portrait', 'draft', 'final', 'twoside', 'oneside',
    'openany', 'openright', 'fleqn', 'leqno', 'titlepage', 'notitlepage',
    'a4paper', 'letterpaper', 'legalpaper', 'executivepaper', '10pt', '11pt', '12pt',
}
_LAYOUT_KEYS = {
    'topsep', 'parsep', 'partopsep', 'leftmargin', 'rightmargin', 'itemsep',
    'labelsep', 'itemindent', 'listparindent', 'labelwidth', 'labelindent',
    'textwidth', 'textheight', 'columnsep', 'parindent', 'parskip', 'margin',
    'hmargin', 'vmargin', 'headheight', 'headsep', 'footskip', 'linespread',
}
_DIMENSION = re.compile(
    r'(?:[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:pt|pc|in|bp|cm|mm|dd|cc|sp|em|ex)'
    r'|(?:[+-]?(?:\d+(?:\.\d*)?|\.\d+))?\\(?:textwidth|linewidth|columnwidth|baselineskip|parindent))'
    r'(?:\s+(?:plus|minus)\s+[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:pt|em|ex))?$', re.I)


def _layout_options(text):
    """Recognize complete formatting option lists, never matching prose fragments."""
    value = text.strip()
    bracketed = value.startswith('[') and value.endswith(']')
    if bracketed:
        value = value[1:-1].strip()
    parts = [part.strip() for part in value.split(',')]
    if not parts or any(not part for part in parts):
        return False
    if len(parts) == 1 and not bracketed and '=' not in value:
        return False  # A bare word such as "final" is not an option list.
    for part in parts:
        if part.casefold() in _LAYOUT_FLAGS:
            continue
        if '=' not in part:
            return False
        key, val = [x.strip() for x in part.split('=', 1)]
        if key.casefold() not in _LAYOUT_KEYS:
            return False
        val = val.strip('{}').strip()
        if val != '*' and not _DIMENSION.fullmatch(val):
            return False
    return True


def _abstract_section(section):
    return (isinstance(section, str)
            and ''.join(c for c in section.casefold() if c.isalpha()) == 'abstract')


def _check(paper, pid):
    formats = {paper.get('text_format'), paper.get('source_format')}
    if ('unarxive_structured_text' not in formats
            and paper.get('index_text_view') != 'structured_body_without_bibliography'):
        return {'status': 'unverified', 'reason': 'source_format_not_structurally_verified'}
    provenance = paper.get('provenance') or {}
    source = provenance.get('source_path')
    if not isinstance(source, str) or not Path(source).is_file():
        return {'status': 'unavailable', 'reason': 'source_missing'}
    try:
        with gzip.open(source, 'rt') as stream:
            document = json.load(stream)
    except (OSError, ValueError, EOFError):
        return {'status': 'unavailable', 'reason': 'source_unreadable'}
    if not isinstance(document, dict):
        return {'status': 'unavailable', 'reason': 'source_unreadable'}
    try:
        if canonical_id(document.get('paper_id', '')) != pid:
            return {'status': 'unavailable', 'reason': 'source_identity_mismatch'}
    except (ValueError, TypeError):
        return {'status': 'unavailable', 'reason': 'source_identity_mismatch'}
    locator = provenance.get('locator') or {}
    expected_hash = locator.get('source_hash')
    if expected_hash and document.get('_source_hash') != expected_hash:
        return {'status': 'unavailable', 'reason': 'source_hash_mismatch'}
    # The upstream locator hash is an opaque archive identifier. Independently
    # check the rendered body against the content frozen in the index cache.
    from .unarxive import render_text
    try:
        if digest(render_text(document).encode()) != paper['source_text_sha256']:
            return {'status': 'unavailable', 'reason': 'source_text_mismatch'}
    except (KeyError, TypeError, AttributeError):
        return {'status': 'unavailable', 'reason': 'source_unreadable'}
    counts = {'blank_or_punctuation': 0, 'abstract': 0, 'layout_options': 0, 'main_body': 0}
    paragraphs = document.get('body_text')
    if not isinstance(paragraphs, list):
        return {'status': 'unavailable', 'reason': 'no_substantive_main_body', 'paragraphs': counts}
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            continue
        text = paragraph.get('text')
        if not isinstance(text, str) or not any(c.isalnum() for c in text):
            counts['blank_or_punctuation'] += 1
        elif _abstract_section(paragraph.get('section')):
            counts['abstract'] += 1
        elif _layout_options(text):
            counts['layout_options'] += 1
        else:
            counts['main_body'] += 1
    available = counts['main_body'] > 0
    return {'status': 'available' if available else 'unavailable',
            'reason': 'substantive_main_body_present' if available else 'no_substantive_main_body',
            'paragraphs': counts, 'locator_hash_checked': bool(expected_hash)}


def source_availability(index, pid):
    """Cache only status, rather than full documents, for this index/run instance."""
    if not hasattr(index, '_source_availability'):
        index._source_availability = {}
    if pid not in index._source_availability:
        index._source_availability[pid] = _check(index.item(pid)['paper'], pid)
    return index._source_availability[pid]
