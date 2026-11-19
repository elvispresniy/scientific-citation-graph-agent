import json

import pytest

from graph_pilot.factory_step2 import ContextBudgetExceeded
from graph_pilot.factory_step3 import (Config, Step3Error, card_order, dry_run, execute, membership_class,
                                       membership_messages, numbered_cards, shared_aspects_messages,
                                       validate_membership, validate_shared_aspects)
from graph_pilot.llm import Config as LLMConfig, LLMError


def card(*problems):
    return {'aspects': [{'problem': p, 'mechanism_or_approach': p, 'author_terms': [], 'conventional_terms': [],
                         'findings': [], 'conditions_and_limits': []} for p in problems],
            'missing_or_unclear': []}


CARDS = [{'paper_id': 'arxiv:2101.00001', 'card': card('a', 'b')},
         {'paper_id': 'arxiv:2101.00002', 'card': card('c')},
         {'paper_id': 'arxiv:2101.00003', 'card': card('d')}]
TEXTS = {'arxiv:2101.00001': 'text one', 'arxiv:2101.00002': 'text two', 'arxiv:2101.00003': 'text three'}


def aspect(support=('arxiv:2101.00001#1', 'arxiv:2101.00002#0')):
    return {'rationale': 'Both add one unit.', 'problem': 'p', 'mechanism_or_object': 'm',
            'conditions': ['c'], 'context': 'x', 'support': list(support)}


def check(criteria=(True,) * 5, terms=('t',)):
    crit = dict(zip(('problem', 'mechanism', 'conditions', 'substantive', 'context'), criteria))
    return {'reason': 'Compared part.', 'criteria': crit, 'own_terms': list(terms) if all(criteria[:4]) else [],
            'sections': ['Method'], 'class': membership_class(crit)}


class Guard:
    def __init__(self, overflow=()):
        self.overflow = overflow

    def check(self, messages, output_tokens):
        if any(marker in messages[1]['content'] for marker in self.overflow):
            raise ContextBudgetExceeded('too long')
        return {'content_tokens': len(messages[1]['content'])}


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []
        self.requests = 0
        self.stopped = False
        self.config = LLMConfig('http://test.invalid/v1', model='test-model', max_requests=100)

    def complete(self, model, messages):
        self.requests += 1
        self.messages.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return {'text': json.dumps(response), 'finish_reason': 'stop', 'message': {}}

    def stop(self):
        self.stopped = True


def test_cards_are_numbered_and_order_is_reproducible():
    rendered = numbered_cards(CARDS, ['arxiv:2101.00002', 'arxiv:2101.00001'])
    assert [r['paper_id'] for r in rendered] == ['arxiv:2101.00002', 'arxiv:2101.00001']
    assert [a['index'] for a in rendered[1]['card']['aspects']] == [0, 1]
    assert 'index' not in CARDS[0]['card']['aspects'][0]
    config = Config()
    assert card_order(CARDS, config, 1) == card_order(CARDS, config, 1)
    assert sorted(card_order(CARDS, config, 2)) == ['arxiv:2101.00001', 'arxiv:2101.00002', 'arxiv:2101.00003']


def test_stage1_prompt_receives_cards_only():
    messages = shared_aspects_messages('Cards: {{paper_cards}}', CARDS, ['arxiv:2101.00001', 'arxiv:2101.00002', 'arxiv:2101.00003'])
    assert '"index": 1' in messages[1]['content']


def test_membership_prompt_hides_rationale_and_support():
    messages = membership_messages('{{shared_aspect}} / {{full_text}}', aspect(), 'paper body')
    content = messages[1]['content']
    assert 'paper body' in content and 'Both add one unit' not in content and 'arxiv:2101.00001#1' not in content


@pytest.mark.parametrize('support', [('arxiv:2101.00001#0', 'arxiv:2101.00001#1'), ('arxiv:2101.00001#2', 'arxiv:2101.00002#0'),
                                     ('arxiv:2101.00009#0', 'arxiv:2101.00002#0'), ('arxiv:2101.00001#0', 'arxiv:2101.00001#0', 'arxiv:2101.00002#0')])
def test_shared_aspect_support_needs_two_papers_and_real_aspects(support):
    with pytest.raises(Step3Error):
        validate_shared_aspects({'shared_aspects': [aspect(support)]}, CARDS)


def test_shared_aspects_may_be_empty_but_keys_are_strict():
    assert validate_shared_aspects({'shared_aspects': []}, CARDS)
    bad = aspect()
    bad['near_misses'] = []
    with pytest.raises(Step3Error):
        validate_shared_aspects({'shared_aspects': [bad]}, CARDS)


@pytest.mark.parametrize('criteria,expected', [((True,) * 5, 'core'), ((True,) * 4 + (False,), 'adjacent'),
                                               ((True, False, True, True, True), 'none'),
                                               ((True, True, True, False, False), 'none')])
def test_class_follows_criteria(criteria, expected):
    assert validate_membership(check(criteria))['class'] == expected


def test_class_inconsistent_with_criteria_is_rejected():
    value = check((True, False, True, True, False))
    value['class'] = 'adjacent'
    with pytest.raises(Step3Error):
        validate_membership(value)


def test_terms_require_first_four_criteria():
    value = check((True, False, True, True, True))
    value['own_terms'] = ['t']
    with pytest.raises(Step3Error):
        validate_membership(value)


def test_execute_checks_every_paper_against_every_aspect(tmp_path):
    first = aspect()
    second = aspect(('arxiv:2101.00002#0', 'arxiv:2101.00003#0'))
    responses = [{'shared_aspects': [first, second]},
                 check(), check((True,) * 4 + (False,)), check((False,) * 5),
                 check((False,) * 5), check(), check()]
    model = Model(responses)
    state = execute(CARDS, TEXTS.get, Config(), llm=model, guard=Guard(), output=tmp_path / 'r')
    assert state['status'] == 'completed' and model.requests == 7
    result = json.loads((tmp_path / 'r' / 'result.json').read_text())
    assert [[(m['paper_id'], m['class']) for m in r['members']] for r in result] == [
        [('arxiv:2101.00001', 'core'), ('arxiv:2101.00002', 'adjacent')], [('arxiv:2101.00002', 'core'), ('arxiv:2101.00003', 'core')]]
    assert 'rationale' not in result[0]


def test_repeats_run_but_stage2_uses_repeat_one(tmp_path):
    responses = [{'shared_aspects': [aspect()]}, {'shared_aspects': []}, {'shared_aspects': []},
                 check(), check(), check()]
    model = Model(responses)
    state = execute(CARDS, TEXTS.get, Config(stage1_repeats=3), llm=model, guard=Guard(), output=tmp_path / 'r')
    assert state['status'] == 'completed' and [r['shared_aspects'] for r in state['stage1']] == [1, 0, 0]
    assert len(state['checks']['01']) == 3
    orders = [json.loads((tmp_path / 'r' / 'stage1' / f'order-00{i}.json').read_text()) for i in (1, 2, 3)]
    assert all(sorted(o) == sorted(TEXTS) for o in orders)


def test_unavailable_text_and_overflow_skip_the_pair_without_request(tmp_path):
    texts = {'arxiv:2101.00001': 'text one', 'arxiv:2101.00002': None, 'arxiv:2101.00003': 'HUGE'}
    model = Model([{'shared_aspects': [aspect()]}, check()])
    state = execute(CARDS, texts.get, Config(), llm=model, guard=Guard(overflow=('HUGE',)), output=tmp_path / 'r')
    assert state['status'] == 'completed' and model.requests == 2
    assert state['checks']['01']['arxiv:2101.00002'] == {'status': 'source_unavailable'}
    assert state['checks']['01']['arxiv:2101.00003'] == {'status': 'context_overflow'}


def test_invalid_response_stops_region_and_keeps_pending(tmp_path):
    bad = check()
    bad['class'] = 'none'
    model = Model([{'shared_aspects': [aspect()]}, bad])
    state = execute(CARDS, TEXTS.get, Config(), llm=model, guard=Guard(), output=tmp_path / 'r')
    assert state['status'] == 'stopped_on_error' and model.stopped
    assert state['checks']['01']['arxiv:2101.00001'] == {'status': 'pending'}
    assert not (tmp_path / 'r' / 'result.json').exists()


def test_llm_error_is_not_retried(tmp_path):
    model = Model([LLMError('LLM APITimeoutError; stopped without retry')])
    state = execute(CARDS, TEXTS.get, Config(), llm=model, guard=Guard(), output=tmp_path / 'r')
    assert state['status'] == 'stopped_on_error' and state['error']['type'] == 'LLMError'
    assert model.requests == 1


def test_dry_run_sends_nothing_and_reports_tokens(tmp_path):
    report = dry_run(CARDS, {'arxiv:2101.00001': 'a', 'arxiv:2101.00002': None, 'arxiv:2101.00003': 'HUGE'}.get, Config(stage1_repeats=2),
                     Guard(overflow=('HUGE',)), tmp_path / 'd')
    assert len(report['stage1_content_tokens']) == 2
    assert report['unavailable_texts'] == ['arxiv:2101.00002']
    assert report['stage2_content_tokens_per_paper']['arxiv:2101.00003'] == 'overflow'


def test_shipped_prompts_have_expected_placeholders():
    config = Config.load(__import__('pathlib').Path(__file__).parents[1] / 'configs/factory-step3-local.json')
    from graph_pilot.factory_step3 import prompts
    p = prompts(config)
    assert shared_aspects_messages(p['shared-aspects'], CARDS, ['arxiv:2101.00001', 'arxiv:2101.00002', 'arxiv:2101.00003'])
    assert membership_messages(p['membership'], aspect(), 'text')


def test_stage1_uses_its_own_output_limit_and_restores_it(tmp_path):
    seen = []

    class Recording(Model):
        def complete(self, model, messages):
            seen.append(self.config.max_output_tokens)
            return super().complete(model, messages)

    model = Recording([{'shared_aspects': [aspect()]}, check(), check(), check()])
    state = execute(CARDS, TEXTS.get, Config(stage1_max_output_tokens=32768), llm=model, guard=Guard(),
                    output=tmp_path / 'r')
    assert state['status'] == 'completed'
    assert seen[0] == 32768 and set(seen[1:]) == {model.config.max_output_tokens}
    assert model.config.max_output_tokens != 32768


def test_failed_stability_repeat_is_recorded_and_region_continues(tmp_path):
    truncated = {'text': '{', 'finish_reason': 'length', 'message': {}}

    class Truncating(Model):
        def complete(self, model, messages):
            if self.requests == 1:
                self.requests += 1
                return truncated
            return super().complete(model, messages)

    model = Truncating([{'shared_aspects': [aspect()]}, {'shared_aspects': []}, check(), check(), check()])
    state = execute(CARDS, TEXTS.get, Config(stage1_repeats=3), llm=model, guard=Guard(), output=tmp_path / 'r')
    assert state['status'] == 'completed'
    assert state['stage1'][1]['repeat'] == 2 and state['stage1'][1]['error']['type'] == 'Step2Error'
    assert len(state['checks']['01']) == 3


def test_failed_first_repeat_still_stops_region(tmp_path):
    class Truncating(Model):
        def complete(self, model, messages):
            self.requests += 1
            return {'text': '{', 'finish_reason': 'length', 'message': {}}

    model = Truncating([])
    state = execute(CARDS, TEXTS.get, Config(stage1_repeats=3), llm=model, guard=Guard(), output=tmp_path / 'r')
    assert state['status'] == 'stopped_on_error' and model.requests == 1


def test_terms_of_a_non_member_are_cleared_not_fatal(tmp_path):
    noisy = check((True, True, True, False, True))
    noisy['own_terms'] = ['leftover']
    model = Model([{'shared_aspects': [aspect()]}, noisy, check(), check()])
    state = execute(CARDS, TEXTS.get, Config(), llm=model, guard=Guard(), output=tmp_path / 'r')
    assert state['status'] == 'completed'
    first = state['checks']['01']['arxiv:2101.00001']
    assert first['class'] == 'none' and first['own_terms'] == []
    record = json.loads((tmp_path / 'r' / 'stage2' / '01' / 'arxiv_2101.00001' / 'membership-normalization.json').read_text())
    assert record['applied'] and record['removed_own_terms'] == ['leftover']


def test_resume_refuses_a_pending_pair_without_saved_response(tmp_path):
    config = Config()
    stopping = Model([{'shared_aspects': [aspect()]}, check(), LLMError('LLM HTTP 500; stopped without retry')])
    first = execute(CARDS, TEXTS.get, config, llm=stopping, guard=Guard(), output=tmp_path / 'r')
    assert first['status'] == 'stopped_on_error' and first['checks']['01']['arxiv:2101.00002'] == {'status': 'pending'}
    # The failed pair has no saved completion, so resume refuses instead of silently retrying it.
    model = Model([])
    again = execute(CARDS, TEXTS.get, config, llm=model, guard=Guard(), output=tmp_path / 'r', resume=True)
    assert again['status'] == 'stopped_on_error' and model.requests == 0


def test_resume_reuses_a_saved_response_without_a_request(tmp_path):
    config = Config()
    noisy = check((True, True, True, False, True))
    noisy['own_terms'] = ['leftover']
    # Simulate the old strict validator: stop on the saved noisy response.
    import graph_pilot.factory_step3 as step3
    original = step3.normalize_membership
    step3.normalize_membership = lambda value: (value, {'applied': False})
    try:
        first = execute(CARDS, TEXTS.get, config, llm=Model([{'shared_aspects': [aspect()]}, noisy]), guard=Guard(),
                        output=tmp_path / 'r')
    finally:
        step3.normalize_membership = original
    assert first['status'] == 'stopped_on_error' and first['llm_requests'] == 2
    model = Model([check(), check()])
    state = execute(CARDS, TEXTS.get, config, llm=model, guard=Guard(), output=tmp_path / 'r', resume=True)
    assert state['status'] == 'completed' and model.requests == 2 and state['llm_requests'] == 4
    assert state['checks']['01']['arxiv:2101.00001']['from_saved_response']
    assert json.loads((tmp_path / 'r' / 'result.json').read_text())[0]['members']
