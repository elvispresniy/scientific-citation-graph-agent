from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_pilot.factory_step2 import card_model_call, parse_completion
from graph_pilot.step2_card_format import normalize_card_format
from graph_pilot.step2_features import Step2Error, digest, encoded, validate_card


def fixture_card():
    return {'aspects': [{'problem': 'A problem.', 'mechanism_or_approach': 'An approach.',
                        'author_terms': [{'term': 'Term', 'meaning': 'Its meaning.'}],
                        'conventional_terms': [], 'findings': [],
                        'conditions_and_limits': ['An already canonical condition.']}],
            'missing_or_unclear': []}


def test_only_two_allowed_arrays_are_serialized_without_changing_values():
    original = fixture_card()
    condition = {'statement': '  A condition\nwith notation α. ', 'concern': ' Its scope [x]. '}
    missing = {'statement': 'An unavailable quantity.', 'concern': 'What cannot be established.'}
    original['aspects'][0]['conditions_and_limits'].append(condition)
    original['missing_or_unclear'] = [missing]
    before = deepcopy(original)
    normalized, report = normalize_card_format(original)
    assert original == before
    expected = deepcopy(before)
    expected['aspects'][0]['conditions_and_limits'][1] = (
        '  A condition\nwith notation α.  [Concern:  Its scope [x]. ]')
    expected['missing_or_unclear'][0] = 'An unavailable quantity. [Concern: What cannot be established.]'
    assert normalized == expected
    assert validate_card(normalized) == expected
    assert report['source_json_sha256'] == digest(encoded(before))
    assert report['paths'] == ['/missing_or_unclear/0', '/aspects/0/conditions_and_limits/1']
    second, unchanged = normalize_card_format(normalized)
    assert second == normalized and not unchanged['applied'] and unchanged['paths'] == []


@pytest.mark.parametrize('item', [
    {'statement': 'A.', 'concern': 'B.', 'extra': 'Unsupported.'},
    {'statement': 'A.'}, {'statement': None, 'concern': 'B.'},
    {'statement': 'A.', 'concern': ['B.']}, {'statement': '', 'concern': 'B.'},
    {'statement': 'A.', 'concern': '   '}, 42,
])
@pytest.mark.parametrize('field', ['missing_or_unclear', 'conditions_and_limits'])
def test_unknown_keys_and_wrong_types_are_not_repaired(item, field):
    original = fixture_card()
    owner = original if field == 'missing_or_unclear' else original['aspects'][0]
    owner[field] = [item]
    normalized, report = normalize_card_format(original)
    assert normalized == original and not report['applied']
    with pytest.raises(Step2Error):
        validate_card(normalized)


def test_matching_object_outside_two_fields_is_not_repaired():
    original = fixture_card()
    original['aspects'][0]['author_terms'][0]['meaning'] = {'statement': 'A.', 'concern': 'B.'}
    normalized, report = normalize_card_format(original)
    assert normalized == original and not report['applied']
    with pytest.raises(Step2Error, match='Terms'):
        validate_card(normalized)


@pytest.mark.parametrize('field', ['author_terms', 'conventional_terms'])
def test_single_term_object_wrapped_in_list_is_unwrapped_without_changes(field):
    original = fixture_card()
    term = {'term': ' Wrapped term ', 'meaning': 'Meaning with α.'}
    original['aspects'][0][field] = [[term]]
    normalized, report = normalize_card_format(original)
    assert normalized['aspects'][0][field] == [term]
    assert validate_card(normalized) == normalized
    path = f'/aspects/0/{field}/0'
    assert report['paths'] == [path] and report['rules'] == {path: 'unwrap-single-term-list'}


@pytest.mark.parametrize('item', [
    [{'term': 'A', 'meaning': 'B'}, {'term': 'C', 'meaning': 'D'}],
    [{'term': 'A', 'meaning': 'B', 'extra': 'X'}], [{'term': 'A'}], [{'term': '', 'meaning': 'B'}],
    [['nested']], [], [[{'term': 'A', 'meaning': 'B'}]],
])
def test_other_list_wrapped_terms_are_not_repaired(item):
    original = fixture_card()
    original['aspects'][0]['conventional_terms'] = [item]
    normalized, report = normalize_card_format(original)
    assert normalized == original and not report['applied']
    with pytest.raises(Step2Error):
        validate_card(normalized)


def test_list_wrapped_term_outside_term_fields_is_not_repaired():
    original = fixture_card()
    original['aspects'][0]['findings'] = [[{'term': 'A', 'meaning': 'B'}]]
    normalized, report = normalize_card_format(original)
    assert normalized == original and not report['applied']


@pytest.mark.parametrize('invalid', [False, True])
def test_card_call_saves_diagnostic_before_validation_and_preserves_raw(tmp_path, invalid):
    value = fixture_card()
    value['missing_or_unclear'] = [{'statement': 'A gap.', 'concern': 'Its consequence.'}]
    if invalid:
        value['missing_or_unclear'][0]['extra'] = 'An unsupported key.'
    completion = {'finish_reason': 'stop', 'text': json.dumps(value), 'message': {}}

    class Model:
        config = SimpleNamespace(model='fixture', max_output_tokens=128)

        def complete(self, *args):
            return completion

    class Guard:
        def check(self, *args):
            return {}

    directory = tmp_path / 'card'
    if invalid:
        with pytest.raises(Step2Error, match='limitations'):
            card_model_call(Model(), Guard(), [{'role': 'user', 'content': 'Extract.'}], directory)
    else:
        normalized = card_model_call(Model(), Guard(), [{'role': 'user', 'content': 'Extract.'}], directory)
        assert normalized['missing_or_unclear'] == ['A gap. [Concern: Its consequence.]']
    assert json.loads((directory / 'completion.json').read_text()) == completion
    report = json.loads((directory / 'card-format-normalization.json').read_text())
    assert report['applied'] is not invalid
    assert report['source_json_sha256'] == digest(encoded(value))
    assert report['completion_sha256'] == digest((directory / 'completion.json').read_bytes())


def test_saved_real_completion_is_valid_after_only_format_adapter():
    path = Path(__file__).resolve().parents[3] / (
        'research/factory-step2-iterations/initial-v3/software/new-cards/000001/completion.json')
    if not path.is_file():
        pytest.skip('Saved local iteration record is not distributed with this checkout')
    before = path.read_bytes()
    value = parse_completion(json.loads(before))
    original = deepcopy(value)
    with pytest.raises(Step2Error, match='limitations'):
        validate_card(value)
    normalized, report = normalize_card_format(value)
    assert validate_card(normalized) is normalized
    assert report['applied'] and report['paths']
    assert value == original and path.read_bytes() == before
    for aspect, old in zip(normalized['aspects'], original['aspects']):
        assert {k: v for k, v in aspect.items() if k != 'conditions_and_limits'} == {
            k: v for k, v in old.items() if k != 'conditions_and_limits'}
        assert all(item['statement'] in serialized and item['concern'] in serialized
                   for item, serialized in zip(old['conditions_and_limits'], aspect['conditions_and_limits']))


def test_saved_full_stop_v1_completion_needs_only_term_unwrap():
    path = Path(__file__).resolve().parents[3] / (
        'research/factory-step2-iterations/full-stop-v1/highdim/iterations/000001/card/completion.json')
    if not path.is_file():
        pytest.skip('Saved local iteration record is not distributed with this checkout')
    before = path.read_bytes()
    value = parse_completion(json.loads(before))
    with pytest.raises(Step2Error, match='Terms'):
        validate_card(deepcopy(value))
    normalized, report = normalize_card_format(value)
    assert validate_card(normalized) is normalized
    assert set(report['rules'].values()) == {'unwrap-single-term-list'}
    assert path.read_bytes() == before
