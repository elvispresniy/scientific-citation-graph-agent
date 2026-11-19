from dataclasses import asdict, replace
import importlib
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from graph_pilot.factory_step2 import (CardUnavailable, Config, ContextBudgetExceeded, Step2ContextGuard,
                                      admission_messages, bootstrap, dry_run, execute, model_call,
                                      parse_completion, render_messages, selected_comparison_focus,
                                      validate_admission)
from graph_pilot.llm import Config as LLMConfig, LLMError
from graph_pilot.step2_features import (IndexConfig, Lexicon, LocalGraph, Step2Error, TopicIndex,
                                       build_index, digest, encoded, frontier, rank_candidates, validate_card, validate_cards)
from graph_pilot.step2_index_compat import create_index_compatibility
from graph_pilot.store import Store


def card(problem='graph message passing node classification', terms=None):
    return {'aspects': [{'problem': problem, 'mechanism_or_approach': problem,
                        'author_terms': terms if terms is not None else [{'term': 'message passing', 'meaning': 'aggregate graph neighbors'}],
                        'conventional_terms': [{'term': 'graph learning', 'meaning': problem}],
                        'findings': [], 'conditions_and_limits': []}], 'missing_or_unclear': []}


def admission(ids, accepted=True, gap=False):
    return {'reason': 'Concrete relation established.' if accepted else 'No substantive relation established.',
            'related_paper_ids': ids if accepted else [],
            'criteria': {'specific_scientific_relation': accepted, 'substantive_role': accepted},
            'terminology_gap': gap, 'limitations': [], 'accept': accepted}


class Guard:
    def check(self, messages, output_tokens):
        return {'checked': True}


class Model:
    def __init__(self, responses, selected_dir=None, max_requests=100):
        self.responses = iter(responses)
        self.messages = []
        self.requests = 0
        self.stopped = False
        self.selected_dir = selected_dir
        self.config = LLMConfig('http://test.invalid/v1', model='test-model', max_requests=max_requests)

    def complete(self, model, messages):
        # Selection must already exist before the first admission request.
        if self.selected_dir:
            pending = json.loads((self.selected_dir / 'state.json').read_text())['pending']
            assert pending and pending['paper_id']
            ranking = json.loads((self.selected_dir / 'iterations' / f"{pending['iteration']:06d}" / 'ranking.json').read_text())
            assert ranking['selected_id'] == pending['paper_id']
        self.requests += 1
        self.messages.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return {'finish_reason': 'stop', 'text': json.dumps(response),
                'message': {'reasoning_content': 'Saved provider diagnostic.'}}

    def stop(self):
        self.stopped = True


@pytest.fixture(scope='module')
def lexicon():
    return Lexicon()


@pytest.fixture
def inputs(tmp_path, lexicon):
    ids = [f'arxiv:2001.{i:05d}' for i in range(1, 8)]
    texts = [
        'Graph message passing node classification network learning. Graph neighbors aggregate information.',
        'Graph node classification network learning aggregation. Graph neighbors propagate signals.',
        'Graph message passing network learning. Graph classification and prediction.',
        'Quantum particle scattering field interactions physics measurements. Quantum particle physics.',
        'Quantum field scattering measurements particles. Physics energy measurements.',
        'Graph network learning propagation classification. Graph nodes share information.',
        'Quantum particle field interactions and scattering. Physics quantum energy.'
    ]
    store = Store(tmp_path / 'graph.sqlite')
    store.setting('snapshot_id', 'step2-test')
    for pid, text in zip(ids, texts):
        source = tmp_path / (pid[6:] + '.txt')
        source.write_text(text)
        store.upsert(pid, {'title': pid})
        store.add_node(pid, 0)
        store.source(pid, 'plain_text', source, {}, 'available')
    for a, b in ((0, 1), (2, 0), (0, 3), (1, 4), (2, 5), (6, 0)):
        store.db.execute('INSERT INTO edges VALUES (?,?,0,?)', (ids[a], ids[b], json.dumps({'contexts': [{'text': 'fixture context'}]})))
    store.close()
    graph = LocalGraph(tmp_path / 'graph.sqlite')
    directory = tmp_path / 'index'
    build_index(graph, directory, IndexConfig(n_components=3, min_df=1), lexicon)
    index = TopicIndex(directory, lexicon)
    cards = [{'paper_id': ids[0], 'card': card()}]
    yield graph, index, cards, ids
    graph.close()


def test_normalization_matches_frozen_benchmark(lexicon, monkeypatch):
    legacy = Path(__file__).resolve().parents[3] / 'research' / 'terminology-pilot'
    monkeypatch.syspath_prepend(str(legacy))
    old = importlib.import_module('measure_terms')
    text = "Models’ graph-based propa-\ngation and particles' scattering 3.5 studies"
    assert lexicon.words(text) == old.tokens(text)
    assert lexicon.words(text, query=True) == old.tokens(text, query=True)
    for word in ('models', 'studies', 'axes', 'physics', 'networks', '3.5', 'unknownmethod'):
        assert lexicon.lemma(word) == old.lemma_word(word)
    # Distinct original forms, even when they collapse to one lemma.
    result = lexicon.gap([{'term': 'model models', 'meaning': 'unused'}], {'model'})
    assert result['denominator'] == 2 and result['numerator'] == 2 and result['G'] == 0
    assert lexicon.gap([], set())['G'] is None


def test_index_readonly_integrity_and_both_directions(inputs):
    graph, index, cards, ids = inputs
    before = graph.path.read_bytes()
    candidates = frontier(graph, cards, {}, {}, index)
    assert set(candidates) == {ids[1], ids[2], ids[3], ids[6]}
    assert candidates[ids[2]][0]['src'] == ids[2]  # Incoming citation keeps its original direction.
    assert graph.path.read_bytes() == before
    with pytest.raises(Exception):
        graph.db.execute('DELETE FROM edges')
    path = index.directory / index.rows[ids[1]][1]['artifact']
    path.write_bytes(b'corrupted cache')
    with pytest.raises(Step2Error, match='hash'):
        index.item(ids[1])


def test_dry_run_covers_entire_frontier_and_has_no_llm(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    output = tmp_path / 'dry'
    state = dry_run(graph, index, lexicon, cards, Config(), output)
    rank = json.loads((output / 'ranking.json').read_text())
    assert rank['frontier_count'] == 4 and len(rank['profiles']) == 4
    assert state['llm_requests'] == 0 and state['status'] == 'dry_run'
    for profile in rank['profiles']:
        if profile['S'] is not None:
            if profile['T'] == 0:
                assert profile['S'] == 0
            else:
                assert profile['S'] == pytest.approx(profile['T'] * (0.5 * profile['G'] + 0.5 * profile['M']))
            assert 0 <= profile['S'] <= 1
    assert rank['selected_id'] in (ids[1], ids[2])


def test_same_aspect_for_topic_and_gap(lexicon):
    class Index:
        rows = {'a': (0, {}), 'b': (1, {})}
        vectors = np.array([[1., 0.], [0.8, 0.6]])
        def aspects(self, cards):
            return [{'paper_id': 'arxiv:2001.00001', 'aspect_index': i, 'aspect': aspect}
                    for i, aspect in enumerate(cards[0]['card']['aspects'])], np.eye(2)
        def item(self, pid):
            return {'vocabulary': ['graph']}
    cards = [{'paper_id': 'arxiv:2001.00001', 'card': card(terms=[{'term': 'graph', 'meaning': 'known'}])}]
    cards[0]['card']['aspects'].append(card(terms=[{'term': 'unrelatedlabel', 'meaning': 'other topic'}])['aspects'][0])
    rank = rank_candidates(Index(), lexicon, cards, {'a': [], 'b': []}, {})
    for profile in rank['profiles']:
        assert profile['matched_aspect']['aspect_index'] == 0
        assert profile['G'] == 0  # Must not select unrelated aspect just because its gap is 1.
        assert profile['M'] == 1  # Zero median is defined.
    assert rank['selected_id'] == 'a'


def test_focus_copies_selected_candidates_actual_argmax_aspect_without_mutation(lexicon):
    cards = [{'paper_id': 'arxiv:2001.00001', 'card': card()}]
    cards[0]['card']['aspects'].append(card('quantum measurements', [{'term': 'quantum', 'meaning': 'An aspect term.'}])['aspects'][0])

    class Index:
        rows = {'a': (0, {}), 'b': (1, {})}
        vectors = np.array([[0.95, np.sqrt(1 - 0.95**2)], [0.1, np.sqrt(0.99)]])

        def aspects(self, records):
            return [{'paper_id': records[0]['paper_id'], 'aspect_index': i, 'aspect': aspect}
                    for i, aspect in enumerate(records[0]['card']['aspects'])], np.eye(2)

        def item(self, pid):
            return {'vocabulary': []}

    before = digest(encoded(cards))
    ranking = rank_candidates(Index(), lexicon, cards, {'a': [], 'b': []}, {})
    assert ranking['selected_id'] == 'b'
    focus = selected_comparison_focus(ranking, cards)
    assert focus == {'paper_id': cards[0]['paper_id'], 'aspect_index': 1,
                     'aspect': cards[0]['card']['aspects'][1]}
    focus['aspect']['problem'] = 'A changed detached copy.'
    assert digest(encoded(cards)) == before


def test_optional_focus_rendering_is_one_pass_and_preserves_complete_inputs():
    cards = [{'paper_id': 'arxiv:2001.00001', 'card': card('{{candidate_full_text}}')}]
    focus = {'paper_id': cards[0]['paper_id'], 'aspect_index': 0,
             'aspect': {'problem': '{{paper_cards}}'}}
    paper = {'text': 'The literal {{comparison_focus}} is part of the source.'}
    prompt = 'F={{comparison_focus}}\nC={{paper_cards}}\nB={{candidate_full_text}}'
    actual = admission_messages(prompt, cards, paper, comparison_focus=focus)[1]['content']
    assert actual == ('F=' + json.dumps(focus, ensure_ascii=False) + '\nC=' +
                      json.dumps(cards, ensure_ascii=False) + '\nB=' + paper['text'])
    legacy = 'C={{paper_cards}}\nB={{candidate_full_text}}'
    assert admission_messages(legacy, cards, paper)[1]['content'] == (
        'C=' + json.dumps(cards, ensure_ascii=False) + '\nB=' + paper['text'])
    assert admission_messages(prompt, cards, paper)[1]['content'].startswith('F=null\nC=')


def test_missing_representative_aspect_produces_null_focus():
    ranking = {'selected_id': 'candidate', 'profiles': [{'paper_id': 'candidate', 'matched_aspect': None}]}
    assert selected_comparison_focus(ranking, []) is None
    with pytest.raises(Step2Error, match='admission_focus'):
        Config(admission_focus='unknown')


def test_focus_mode_requires_prompt_slot_before_any_model_request(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    llm = Model([])
    with pytest.raises(Step2Error, match='comparison_focus prompt placeholder'):
        execute(graph, index, lexicon, cards, Config(admission_focus='matched_aspect_first'),
                llm=llm, guard=Guard(), output=tmp_path / 'bad-focus-prompt')
    assert llm.requests == 0 and not (tmp_path / 'bad-focus-prompt').exists()


def test_execute_focus_uses_saved_selection_and_keeps_whole_accumulator(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    cards[0]['card']['aspects'].append(card('quantum particle measurements')['aspects'][0])
    prompt = '{{comparison_focus}}\nCARDS={{paper_cards}}\nBODY={{candidate_full_text}}'
    prompt_path = tmp_path / 'focused-admission.md'
    prompt_path.write_text(prompt)
    output = tmp_path / 'focus-run'
    before = digest(encoded(cards))
    llm = Model([admission([], False)], output)
    state = execute(graph, index, lexicon, cards,
                    Config(max_reviewed=1, admission_focus='matched_aspect_first', admission_prompt=str(prompt_path)),
                    llm=llm, guard=Guard(), output=output)
    directory = output / 'iterations/000001'
    ranking = json.loads((directory / 'ranking.json').read_text())
    focus = selected_comparison_focus(ranking, cards)
    assert json.loads((directory / 'comparison-focus.json').read_text()) == focus
    assert llm.messages[0] == admission_messages(prompt, cards, index.item(ranking['selected_id'])['paper'],
                                                comparison_focus=focus)
    assert digest(encoded(cards)) == digest(encoded(state['cards'])) == before
    assert ranking['memory_sha256'] == before and llm.requests == 1
    assert json.loads((output / 'manifest.json').read_text())['config']['admission_focus'] == 'matched_aspect_first'


def test_unknown_is_not_zero_and_fallback_is_reproducible(inputs, lexicon):
    graph, index, cards, ids = inputs
    cards[0]['card']['aspects'][0]['author_terms'] = []
    candidates = frontier(graph, cards, {}, {}, index)
    candidates = {pid: candidates[pid] for pid in (ids[1], ids[2])}
    a = rank_candidates(index, lexicon, cards, candidates, graph.degrees())
    b = rank_candidates(index, lexicon, cards, dict(reversed(list(candidates.items()))), graph.degrees())
    assert a['selection_method'] == 'unknown_seeded_fallback' and a['selected_id'] == b['selected_id']
    assert all(p['S'] is None and p['G'] is None for p in a['profiles'])


def test_zero_cosine_is_known_zero_but_oov_is_unknown(lexicon):
    class Index:
        rows = {'orthogonal': (0, {}), 'oov': (1, {})}
        vectors = np.array([[0., 1.], [0., 0.]])
        def aspects(self, cards):
            return [{'paper_id': 'arxiv:2001.00001', 'aspect_index': 0, 'aspect': card()['aspects'][0]}], np.array([[1., 0.]])
    cards = [{'paper_id': 'arxiv:2001.00001', 'card': card()}]
    result = rank_candidates(Index(), lexicon, cards, {'orthogonal': [], 'oov': []}, {})
    rows = {p['paper_id']: p for p in result['profiles']}
    assert rows['orthogonal']['T'] == 0 and rows['orthogonal']['S'] == 0
    assert rows['orthogonal']['G'] is None and rows['orthogonal']['matched_aspect'] is None
    assert rows['oov']['T'] is None and rows['oov']['S'] is None


def test_winner_beyond_first_matrix_chunk_is_not_lost(lexicon):
    ids = [f'p{i:04d}' for i in range(300)]
    class Index:
        rows = {pid: (i, {}) for i, pid in enumerate(ids)}
        vectors = np.array([[0.9, np.sqrt(1 - 0.9**2)] if i == 299
                            else [0.5, np.sqrt(1 - 0.5**2)] for i in range(300)])
        def aspects(self, cards):
            return [{'paper_id': 'arxiv:2001.00001', 'aspect_index': 0, 'aspect': card()['aspects'][0]}], np.array([[1., 0.]])
        def item(self, pid):
            return {'vocabulary': []}
    cards = [{'paper_id': 'arxiv:2001.00001', 'card': card()}]
    result = rank_candidates(Index(), lexicon, cards, {pid: [] for pid in ids}, {})
    assert result['frontier_count'] == 300 and len(result['profiles']) == 300
    assert result['selected_id'] == ids[-1]


def test_rejection_keeps_memory_and_never_selects_twice(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    before = json.dumps(cards)
    output = tmp_path / 'reject'
    llm = Model([admission([], False)] * 4, output)
    state = execute(graph, index, lexicon, cards, Config(max_consecutive_rejections=None),
                    llm=llm, guard=Guard(), output=output)
    assert state['status'] == 'empty_frontier' and len(state['reviewed']) == 4
    assert len(state['rejected']) == 4 and len({r['paper_id'] for r in state['reviewed']}) == 4
    assert json.dumps(state['cards']) == before and llm.requests == 4
    assert (output / 'iterations/000001/admission/reasoning.json').is_file()


def test_accept_adds_card_then_opens_new_neighbors(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    output = tmp_path / 'accept'
    llm = Model([admission([ids[0]], True, gap=False), card()], output)
    state = execute(graph, index, lexicon, cards, Config(max_accepted=1), llm=llm, guard=Guard(), output=output)
    assert state['status'] == 'accept_budget' and len(state['cards']) == 2
    assert len(state['new_accepted']) == 1 and not state['rejected'] and llm.requests == 2
    expanded = frontier(graph, state['cards'], {}, {}, index)
    new_id = state['new_accepted'][0]
    assert new_id not in expanded
    expected = ids[4] if new_id == ids[1] else ids[5]
    assert expected in expanded


def test_card_failure_is_atomic_and_never_automatically_retried(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    output = tmp_path / 'card-failure'
    llm = Model([admission([ids[0]]), {'aspects': [], 'missing_or_unclear': ['Cannot extract.']}], output)
    state = execute(graph, index, lexicon, cards, Config(), llm=llm, guard=Guard(), output=output)
    assert state['status'] == 'card_unavailable' and state['pending']['phase'] == 'card'
    assert len(state['cards']) == 1 and not state['new_accepted'] and not state['rejected']
    assert not state['reviewed']
    assert json.loads((output / 'iterations/000001/card.json').read_text())['aspects'] == []
    assert llm.stopped
    with pytest.raises(Step2Error, match='retry'):
        execute(graph, index, lexicon, cards, Config(), llm=Model([]), guard=Guard(), output=output, resume=True)


@pytest.mark.parametrize('interrupt_at', ['before_swap', 'after_swap'])
def test_interrupt_cannot_partially_commit_admission_ledger(inputs, lexicon, tmp_path, interrupt_at):
    graph, index, cards, ids = inputs
    output = tmp_path / interrupt_at
    llm = Model([admission([ids[0]]), card()], output)
    lines, start = inspect.getsourcelines(execute)
    swap = next(start + i for i, text in enumerate(lines) if text.strip() == 'state = committed')
    armed = False

    def interrupt(frame, event, arg):
        nonlocal armed
        if frame.f_code is execute.__code__ and event == 'line':
            if frame.f_lineno == swap:
                if interrupt_at == 'before_swap':
                    raise KeyboardInterrupt
                armed = True
            elif armed:
                raise KeyboardInterrupt
        return interrupt

    previous_trace = sys.gettrace()
    sys.settrace(interrupt)
    try:
        state = execute(graph, index, lexicon, cards, Config(), llm=llm, guard=Guard(), output=output)
    finally:
        sys.settrace(previous_trace)
    assert state['status'] == 'interrupted' and state['llm_requests'] == 2 and llm.stopped
    assert json.loads((output / 'state.json').read_text()) == state
    if interrupt_at == 'before_swap':
        assert state['cards'] == cards
        assert not state['new_accepted'] and not state['reviewed'] and not state['rejected']
        assert state['pending']['phase'] == 'card'
    else:
        assert len(state['cards']) == 2 and len(state['new_accepted']) == len(state['reviewed']) == 1
        assert state['cards'][-1]['paper_id'] == state['new_accepted'][0] == state['reviewed'][0]['paper_id']
        assert state['reviewed'][0]['accept'] and state['pending'] is None and not state['rejected']


def test_http_429_stops_without_rejecting(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    llm = Model([LLMError('LLM HTTP 429; stopped without retry')])
    state = execute(graph, index, lexicon, cards, Config(), llm=llm, guard=Guard(), output=tmp_path / '429')
    assert llm.requests == 1 and llm.stopped and not state['rejected'] and not state['reviewed']
    assert state['status'] == 'stopped_on_error'


def test_request_budget_reserves_card_before_admission(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    llm = Model([], max_requests=1)
    state = execute(graph, index, lexicon, cards, Config(), llm=llm, guard=Guard(), output=tmp_path / 'budget')
    assert state['status'] == 'request_budget' and llm.requests == 0


def test_unexpected_guard_error_stops_on_error(inputs, lexicon, tmp_path):
    class Broken:
        def check(self, messages, output_tokens):
            raise Step2Error('Guard failed')
    graph, index, cards, ids = inputs
    llm = Model([])
    state = execute(graph, index, lexicon, cards, Config(), llm=llm, guard=Broken(), output=tmp_path / 'broken')
    assert state['status'] == 'stopped_on_error' and llm.requests == 0
    assert not state['reviewed'] and not state['rejected']


@pytest.mark.parametrize('overflow_call', [1, 2])  # admission request, then the possible card request
def test_context_overflow_is_a_clean_stop_before_any_iteration(inputs, lexicon, tmp_path, overflow_call):
    class Overflow:
        calls = 0
        def check(self, messages, output_tokens):
            self.calls += 1
            if self.calls == overflow_call:
                raise ContextBudgetExceeded('Context budget exceeded; no truncation or LLM request')
            return {'checked': True}
    graph, index, cards, ids = inputs
    llm = Model([])
    output = tmp_path / 'overflow'
    state = execute(graph, index, lexicon, cards, Config(), llm=llm, guard=Overflow(), output=output)
    assert state['status'] == 'context_overflow' and llm.requests == 0 and not llm.stopped
    assert state['pending'] is None and not state['reviewed'] and not state['rejected']
    assert not any((output / 'iterations').iterdir())
    record = json.loads((output / 'context-overflow.json').read_text())
    assert record['paper_id'] == state['context_overflow']['paper_id'] == record['ranking']['selected_id']


def test_real_guard_overflow_has_distinct_type(tmp_path):
    tokenizers = pytest.importorskip('tokenizers')
    tokenizer = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    path = tmp_path / 'tiny-tokenizer.json'
    tokenizer.save(str(path))
    guard = Step2ContextGuard(Config(tokenizer_path=str(path), tokenizer_sha256=digest(path.read_bytes()),
                                    max_context_tokens=100, chat_template_reserve_tokens=1))
    assert guard.check([{'role': 'user', 'content': 'short'}], 10)['content_tokens'] > 0
    with pytest.raises(ContextBudgetExceeded):
        guard.check([{'role': 'user', 'content': 'word ' * 200}], 10)


def test_consecutive_rejections_stop_and_accept_resets_count(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    output = tmp_path / 'patience'
    llm = Model([admission([], False), admission([ids[0]]), card(),
                 admission([], False), admission([], False)], output)
    state = execute(graph, index, lexicon, cards, Config(max_consecutive_rejections=2),
                    llm=llm, guard=Guard(), output=output)
    assert state['status'] == 'rejection_patience'
    assert [r['accept'] for r in state['reviewed']] == [False, True, False, False]
    assert llm.requests == 5


def test_none_review_budget_and_patience_validation():
    assert Config(max_reviewed=None).max_reviewed is None
    for bad in (0, -1, 1.5, True):
        with pytest.raises(Step2Error):
            Config(max_consecutive_rejections=bad)
    with pytest.raises(Step2Error):
        Config(max_accepted=None)


def test_resume_clean_budget_preserves_rejections(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    output = tmp_path / 'resume'
    first = execute(graph, index, lexicon, cards, Config(max_reviewed=1, max_consecutive_rejections=None),
                    llm=Model([admission([], False)]), guard=Guard(), output=output)
    assert first['status'] == 'review_budget'
    second = execute(graph, index, lexicon, cards, Config(max_reviewed=4, max_consecutive_rejections=None),
                     llm=Model([admission([], False)] * 3), guard=Guard(), output=output, resume=True)
    assert len(second['rejected']) == 4 and len(second['reviewed']) == 4 and second['llm_requests'] == 4


def test_resume_may_raise_patience_after_patience_stop(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    output = tmp_path / 'resume-patience'
    first = execute(graph, index, lexicon, cards, Config(max_consecutive_rejections=1),
                    llm=Model([admission([], False)]), guard=Guard(), output=output)
    assert first['status'] == 'rejection_patience' and len(first['reviewed']) == 1
    second = execute(graph, index, lexicon, cards, Config(max_consecutive_rejections=3),
                     llm=Model([admission([], False)] * 2), guard=Guard(), output=output, resume=True)
    assert second['status'] == 'rejection_patience' and len(second['reviewed']) == 3


def test_bootstrap_uses_only_explicit_ids_and_card_prompt(inputs, tmp_path):
    graph, index, cards, ids = inputs
    llm = Model([card(), card()])
    result = bootstrap(index, [ids[0], ids[2]], Config(), llm=llm, guard=Guard(), output=tmp_path / 'initial')
    assert [r['paper_id'] for r in result] == [ids[0], ids[2]] and llm.requests == 2
    assert all('reference cards' not in messages[1]['content'] for messages in llm.messages)


def test_bootstrap_saves_reproducible_provenance_without_client_secrets(inputs, tmp_path):
    graph, index, cards, ids = inputs
    config = Config()
    output = tmp_path / 'bootstrap-provenance'
    llm = Model([card()])
    llm.config = replace(llm.config, temperature=0.25, top_p=0.9, reasoning_effort='medium',
                         timeout_seconds=125, max_output_tokens=4096)
    llm.api_key = 'client-secret-not-part-of-config'
    bootstrap(index, [ids[0]], config, llm=llm, guard=Guard(), output=output)
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['llm_config'] == asdict(llm.config)
    assert manifest['config'] == asdict(config)
    assert manifest['index_manifest_sha256'] == index.manifest_hash
    prompt = (output / 'card-prompt.md').read_bytes()
    assert prompt == Path(config.card_prompt).read_bytes()
    assert manifest['prompt_sha256'] == digest(prompt)
    source = Path(__file__).resolve().parents[1]
    assert manifest['implementation_sha256'] == {
        name: digest((source / name).read_bytes())
        for name in ('factory_step2.py', 'step2_features.py', 'step2_sources.py', 'step2_card_format.py', 'llm.py')}
    assert all(llm.api_key not in path.read_text() for path in output.rglob('*') if path.is_file())


def test_bootstrap_unavailable_card_preserves_partial_without_complete_output(inputs, tmp_path):
    graph, index, cards, ids = inputs
    output = tmp_path / 'unavailable-bootstrap'
    empty = {'aspects': [], 'missing_or_unclear': ['The source cannot support extraction.']}
    llm = Model([card(), empty])
    with pytest.raises(CardUnavailable):
        bootstrap(index, ids[:2], Config(), llm=llm, guard=Guard(), output=output)
    assert llm.stopped and llm.requests == 2
    assert not (output / 'cards.json').exists()
    assert len(json.loads((output / 'partial-cards.json').read_text())) == 1
    assert json.loads((output / '000002/card.json').read_text()) == empty
    assert json.loads((output / 'error.json').read_text())['status'] == 'card_unavailable'


def test_bootstrap_preflights_sources_before_any_request_and_records_hashes(inputs, tmp_path):
    graph, index, cards, ids = inputs
    output = tmp_path / 'unavailable-initial-source'
    index._source_availability = {
        ids[1]: {'status': 'unavailable', 'reason': 'no_substantive_main_body'}}
    llm = Model([])
    with pytest.raises(Step2Error, match='no bootstrap LLM request'):
        bootstrap(index, ids[:2], Config(), llm=llm, guard=Guard(), output=output)
    assert llm.requests == 0 and llm.stopped and not (output / 'cards.json').exists()
    assert not (output / '000001').exists()
    manifest = json.loads((output / 'manifest.json').read_text())
    assert set(manifest['initial_sources']) == set(ids[:2])
    for pid in ids[:2]:
        paper = index.item(pid)['paper']
        source = manifest['initial_sources'][pid]
        assert source['source_text_sha256'] == paper['source_text_sha256']
        assert source['text_sha256'] == paper['text_sha256']
    assert manifest['initial_sources'][ids[1]]['availability']['status'] == 'unavailable'
    assert manifest['initial_sources'][ids[0]]['availability']['status'] == 'unverified'
    assert json.loads((output / 'error.json').read_text()) == {
        'type': 'SourceUnavailable', 'status': 'source_unavailable', 'paper_ids': [ids[1]]}


@pytest.mark.parametrize('missing_field', ['problem', 'mechanism_or_approach'])
def test_nullable_card_strings_are_preserved_and_vectorized(inputs, missing_field):
    graph, index, cards, ids = inputs
    value = cards[0]['card']
    value['aspects'][0][missing_field] = None
    value['aspects'][0]['author_terms'][0]['meaning'] = None
    value['aspects'][0]['conventional_terms'][0]['meaning'] = None
    value['missing_or_unclear'] = ['This description is not available in the source.']
    assert validate_card(value) is value
    records, vectors = index.aspects(cards)
    assert len(records) == 1 and np.isfinite(vectors).all()
    assert value['aspects'][0][missing_field] is None


def test_card_nullable_contract_does_not_allow_fabricated_or_empty_placeholders():
    value = card()
    value['aspects'][0]['problem'] = value['aspects'][0]['mechanism_or_approach'] = None
    with pytest.raises(Step2Error, match='description'):
        validate_card(value)
    value = card()
    value['aspects'][0]['author_terms'][0]['term'] = None
    with pytest.raises(Step2Error, match='Terms'):
        validate_card(value)
    value = card()
    value['aspects'][0]['author_terms'][0]['meaning'] = ''
    with pytest.raises(Step2Error, match='Terms'):
        validate_card(value)
    empty = {'aspects': [], 'missing_or_unclear': ['Extraction is unavailable.']}
    assert validate_card(empty, allow_empty=True) == empty
    with pytest.raises(Step2Error):
        validate_card(empty)  # Never an eligible accumulator card.


def test_complete_card_topic_transform_is_unchanged(inputs):
    from sklearn.preprocessing import normalize
    graph, index, cards, ids = inputs
    aspect = cards[0]['card']['aspects'][0]
    old_text = ' '.join([aspect['problem'], aspect['mechanism_or_approach']] +
                        [t[k] for t in aspect['conventional_terms'] for k in ('term', 'meaning')])
    expected = normalize(index.svd.transform(index.vectorizer.transform([old_text]))).astype(np.float32)
    records, actual = index.aspects(cards)
    np.testing.assert_array_equal(actual, expected)


def compatibility_fixture(index, tmp_path, *, protected_change=False):
    source = Path(__file__).resolve().parents[1] / 'step2_features.py'
    baseline = source.read_text()
    if protected_change:
        baseline = baseline.replace('min_df=config.min_df, dtype=np.float32', 'min_df=1, dtype=np.float32')
    else:
        baseline = baseline.replace("raise Step2Error('Empty aspect description')",
                                    "raise Step2Error('Previous card validation')")
    baseline_path = tmp_path / 'baseline-step2_features.py'
    baseline_path.write_text(baseline)
    manifest_path = index.directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['implementation_sha256'] = digest(baseline_path.read_bytes())
    manifest_path.write_text(json.dumps(manifest))
    archived = [{'path': 'code/graph_pilot/step2_features.py', 'sha256': digest(baseline_path.read_bytes())}]
    for name in ('probe_modules.py', 'unarxive.py', 'latex_to_text.py', 'store.py'):
        archived.append({'path': 'code/graph_pilot/' + name, 'sha256': digest(source.with_name(name).read_bytes())})
    snapshot_path = tmp_path / 'snapshot-manifest.json'
    snapshot_path.write_text(json.dumps({'archived_files': archived}))
    return baseline_path, snapshot_path


def test_exact_index_compatibility_allows_runtime_changes_only(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    baseline, snapshot = compatibility_fixture(index, tmp_path)
    report_path = tmp_path / 'compatibility.json'
    original_manifest = (index.directory / 'manifest.json').read_bytes()
    with pytest.raises(Step2Error, match='explicitly verify'):
        TopicIndex(index.directory, lexicon)
    report = create_index_compatibility(index.directory, baseline, snapshot, report_path)
    loaded = TopicIndex(index.directory, lexicon, compatibility=report_path)
    assert loaded.compatibility['evidence'] == report
    np.testing.assert_array_equal(loaded.vectors, index.vectors)
    assert (index.directory / 'manifest.json').read_bytes() == original_manifest
    expected = rank_candidates(index, lexicon, cards, frontier(graph, cards, {}, {}, index), graph.degrees())
    actual = rank_candidates(loaded, lexicon, cards, frontier(graph, cards, {}, {}, loaded), graph.degrees())
    assert actual == expected
    report['current_source_sha256'] = '0' * 64
    report_path.write_text(json.dumps(report))
    with pytest.raises(Step2Error, match='exact current'):
        TopicIndex(index.directory, lexicon, compatibility=report_path)


def test_index_compatibility_rejects_numerical_ast_changes(inputs, tmp_path):
    graph, index, cards, ids = inputs
    baseline, snapshot = compatibility_fixture(index, tmp_path, protected_change=True)
    with pytest.raises(Step2Error, match='Protected index/normalizer AST'):
        create_index_compatibility(index.directory, baseline, snapshot, tmp_path / 'forbidden.json')
    assert not (tmp_path / 'forbidden.json').exists()


def test_index_compatibility_rejects_preparation_drift_and_output_inside_index(inputs, tmp_path):
    graph, index, cards, ids = inputs
    baseline, snapshot = compatibility_fixture(index, tmp_path)
    with pytest.raises(Step2Error, match='outside the frozen index'):
        create_index_compatibility(index.directory, baseline, snapshot, index.directory / 'compatibility.json')
    contents = json.loads(snapshot.read_text())
    contents['archived_files'][-1]['sha256'] = '0' * 64
    snapshot.write_text(json.dumps(contents))
    with pytest.raises(Step2Error, match='dependency differs'):
        create_index_compatibility(index.directory, baseline, snapshot, tmp_path / 'forbidden.json')


def test_placeholders_are_not_recursively_substituted():
    messages = render_messages('{{paper_cards}} / {{candidate_full_text}}',
                               {'paper_cards': '{{candidate_full_text}}', 'candidate_full_text': 'SECRET BODY'})
    assert messages[1]['content'] == '{{candidate_full_text}} / SECRET BODY'


def test_strict_response_and_admission_consistency():
    with pytest.raises(Step2Error):
        parse_completion({'finish_reason': 'length', 'text': '{}'})
    with pytest.raises(Step2Error):
        parse_completion({'finish_reason': 'stop', 'text': '{"a":1,"a":2}'})
    with pytest.raises(Step2Error):
        parse_completion({'finish_reason': 'stop', 'text': '{"a":NaN}'})
    cards = [{'paper_id': 'arxiv:2001.00001', 'card': card()}]
    value = admission([cards[0]['paper_id']])
    value['criteria']['substantive_role'] = False
    with pytest.raises(Step2Error):
        validate_admission(value, cards)
    value = admission(['arxiv:2001.99999'])
    with pytest.raises(Step2Error):
        validate_admission(value, cards)
    assert validate_admission(admission([cards[0]['paper_id']], gap=False), cards)['accept']


def test_literal_newline_normalization_preserves_reason_and_scientific_fields():
    expected = {'reason': 'First line.\nSecond line.', 'accept': True}
    raw = json.dumps(expected).replace('\\n', '\n')
    normalization = {}
    actual = parse_completion({'finish_reason': 'stop', 'text': raw}, normalization=normalization)
    assert actual == expected and set(actual) == {'reason', 'accept'}
    assert normalization == {'attempted': True, 'applied': True,
                             'repair_type': 'literal_control_characters_in_strings'}
    normalization = {}
    assert parse_completion({'finish_reason': 'stop', 'text': json.dumps(expected)},
                            normalization=normalization) == expected
    assert normalization == {'attempted': False, 'applied': False, 'repair_type': None}


@pytest.mark.parametrize('text,attempted', [
    ('{"reason":"A\\q"}', False),
    ('{"reason":"A","accept":true,}', False),
    ('{"reason":"A\nB","accept":true,}', True),
    ('{"reason":"A\nB","accept":true "other":false}', True),
    ('{"reason":"A\nB","accept":true,"accept":false}', True),
    ('{"reason":"A\nB","score":NaN}', True),
    ('{"reason":"A\nB","score":Infinity}', True),
])
def test_control_character_fallback_does_not_repair_other_json_defects(text, attempted):
    normalization = {}
    with pytest.raises(Step2Error):
        parse_completion({'finish_reason': 'stop', 'text': text}, normalization=normalization)
    assert normalization['attempted'] == attempted and not normalization['applied']


@pytest.mark.parametrize('malformed', [False, True])
def test_model_call_logs_format_normalization_and_keeps_raw_completion(tmp_path, malformed):
    raw = '{"reason":"First\nSecond","accept":true' + (',}' if malformed else '}')
    completion = {'finish_reason': 'stop', 'text': raw, 'message': {}}

    class RawModel(Model):
        def complete(self, model, messages):
            self.requests += 1
            return completion

    output = tmp_path / 'response'
    model = RawModel([])
    if malformed:
        with pytest.raises(Step2Error):
            model_call(model, Guard(), [{'role': 'user', 'content': 'Analyze.'}], output)
    else:
        assert model_call(model, Guard(), [{'role': 'user', 'content': 'Analyze.'}], output) == {
            'reason': 'First\nSecond', 'accept': True}
    assert json.loads((output / 'completion.json').read_text()) == completion
    normalization = json.loads((output / 'json-format-normalization.json').read_text())
    assert normalization['attempted'] and normalization['applied'] is not malformed
    assert normalization['repair_type'] == 'literal_control_characters_in_strings'
    assert model.requests == 1


def test_graph_change_is_detected(inputs, lexicon, tmp_path):
    graph, index, cards, ids = inputs
    store = Store(graph.path)
    store.db.execute('DELETE FROM edges WHERE src=?', (ids[0],))
    store.close()
    with pytest.raises(Step2Error, match='snapshot'):
        dry_run(graph, index, lexicon, cards, Config(), tmp_path / 'changed')
