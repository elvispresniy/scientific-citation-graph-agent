import gzip
import json
from pathlib import Path

import pytest

from graph_pilot.step2_features import digest, frontier
from graph_pilot.step2_sources import source_availability
from graph_pilot.unarxive import render_text


PID = 'arxiv:2001.00002'


def structured_index(tmp_path, paragraphs):
    document = {'paper_id': PID.removeprefix('arxiv:'), '_source_hash': 'opaque-upstream-hash',
                'metadata': {'abstract': 'An available abstract is not a main body.'},
                'body_text': paragraphs, 'ref_entries': {}}
    source = tmp_path / 'document.json.gz'
    source.write_bytes(gzip.compress(json.dumps(document).encode()))
    paper = {'text_format': 'unarxive_structured_text',
             'source_text_sha256': digest(render_text(document).encode()),
             'provenance': {'source_path': str(source), 'locator': {'source_hash': document['_source_hash']}}}

    class Index:
        rows = {PID: (0, {})}
        calls = 0

        def item(self, pid):
            self.calls += 1
            assert pid == PID
            return {'paper': paper}

    return Index(), source, document


@pytest.mark.parametrize('paragraphs', [
    [{'section': '', 'text': 'noitemsep,topsep=0pt,parsep=0pt,partopsep=0pt, leftmargin=12pt\n'},
     {'section': '', 'text': '\n'}, {'section': '', 'text': '['}],
    [{'section': 'Abstract', 'text': 'The abstract reports a result.'}],
    [{'section': '# Abstract:', 'text': 'The abstract reports a result.'},
     {'section': '', 'text': '[noitemsep,leftmargin=2em]'}],
    [{'section': '', 'text': 'draft,twocolumn'}, {'section': '', 'text': '... [] ()'}],
    [],
])
def test_formatting_or_explicit_abstract_only_is_unavailable(tmp_path, paragraphs):
    index, source, document = structured_index(tmp_path, paragraphs)
    status = source_availability(index, PID)
    assert status['status'] == 'unavailable' and status['reason'] == 'no_substantive_main_body'
    assert status['paragraphs']['main_body'] == 0


@pytest.mark.parametrize('paragraph', [
    {'section': 'Results', 'text': 'We prove this.'},  # No minimum word/text length.
    {'section': '', 'text': 'The final model uses two columns.'},  # Headings are optional.
    {'section': None, 'text': 'alpha=0.2,beta=0.3'},  # Scientific parameters are not layout keys.
    {'section': '', 'text': 'x=2pt,y=3pt'},
    {'section': '', 'text': 'E=mc^2'},
    {'section': 'Abstract methods', 'text': 'A method description.'},
])
def test_normal_short_or_unheaded_body_is_available(tmp_path, paragraph):
    index, source, document = structured_index(tmp_path, [paragraph])
    status = source_availability(index, PID)
    assert status['status'] == 'available' and status['paragraphs']['main_body'] == 1


def test_abstract_heading_does_not_invent_missing_headings_for_unheaded_body(tmp_path):
    index, source, document = structured_index(tmp_path, [
        {'section': 'Abstract', 'text': 'An abstract paragraph.'},
        {'section': '', 'text': 'A main body paragraph without a heading.'}])
    assert source_availability(index, PID)['status'] == 'available'


@pytest.mark.parametrize('mutation,reason', [
    ('identity', 'source_identity_mismatch'), ('hash', 'source_hash_mismatch'),
    ('body', 'source_text_mismatch'), ('missing', 'source_missing')])
def test_source_identity_locator_hash_and_frozen_content_are_verified(tmp_path, mutation, reason):
    index, source, document = structured_index(tmp_path, [{'section': '', 'text': 'A main body paragraph.'}])
    if mutation == 'identity':
        document['paper_id'] = '2001.00003'
    elif mutation == 'hash':
        document['_source_hash'] = 'another-upstream-hash'
    elif mutation == 'body':
        document['body_text'][0]['text'] = 'Changed after index creation.'
    if mutation == 'missing':
        source.unlink()
    else:
        source.write_bytes(gzip.compress(json.dumps(document).encode()))
    assert source_availability(index, PID) == {'status': 'unavailable', 'reason': reason}


def test_status_cache_is_scoped_to_index_instance(tmp_path):
    index, source, document = structured_index(tmp_path, [{'section': '', 'text': 'A main body paragraph.'}])
    first = source_availability(index, PID)
    assert source_availability(index, PID) is first and index.calls == 1
    assert set(index._source_availability) == {PID}


def test_frontier_excludes_unavailable_without_scientific_rejection(tmp_path):
    index, source, document = structured_index(tmp_path, [{'section': '', 'text': 'topsep=0pt,leftmargin=12pt'}])
    accepted = 'arxiv:2001.00001'

    class Graph:
        def connections(self, pid):
            return [{'src': accepted, 'dst': PID, 'evidence': '{}'}]

    rejected, unavailable = {}, {}
    assert frontier(Graph(), [{'paper_id': accepted}], rejected, unavailable, index) == {}
    assert unavailable == {PID: 'no_substantive_main_body'} and rejected == {}


def test_other_source_formats_are_unverified_and_allowed():
    class Index:
        rows = {PID: (0, {})}

        def item(self, pid):
            return {'paper': {'text_format': 'plain_text', 'text': 'A short text.'}}

    index = Index()
    assert source_availability(index, PID)['status'] == 'unverified'
