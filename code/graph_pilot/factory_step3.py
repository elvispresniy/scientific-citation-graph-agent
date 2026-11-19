"""Step 3: shared aspects over one region's cards, then paper-by-aspect fulltext checks."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import random

from .factory_step2 import ContextBudgetExceeded, model_call, render_messages
from .llm import LLMError
from .probe_modules import ProbeError
from .step2_features import Step2Error, digest, read_json, validate_cards, write_json

VERSION = 'factory-step3-v1'
FIELDS = ('problem', 'mechanism_or_object', 'conditions', 'context')
CRITERIA = ('problem', 'mechanism', 'conditions', 'substantive', 'context')


class Step3Error(Step2Error):
    """Invalid input or model response for step 3."""


@dataclass(frozen=True)
class Config:
    shared_aspects_prompt: str = str(Path(__file__).with_name('prompts') / 'step3-shared-aspects-v2-draft.md')
    membership_prompt: str = str(Path(__file__).with_name('prompts') / 'step3-aspect-membership-v2-draft.md')
    stage1_repeats: int = 1  # Repeats beyond the first only measure stability; stage 2 uses repeat 1.
    # wave1-v1: 16384 output tokens were exhausted by reasoning before stage 1 answered.
    stage1_max_output_tokens: int = 32768
    rng_seed: int = 42
    tokenizer_path: str = str(Path(__file__).resolve().parents[2] / 'research/factory-step1_5-llm/data/qwen38-tokenizer.json')
    tokenizer_sha256: str = '0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3'
    max_context_tokens: int = 200000
    chat_template_reserve_tokens: int = 2048

    def __post_init__(self):
        for name in ('stage1_repeats', 'stage1_max_output_tokens', 'max_context_tokens', 'chat_template_reserve_tokens'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise Step3Error(f'{name} must be a positive integer')
        if type(self.rng_seed) is not int or self.rng_seed < 0:
            raise Step3Error('rng_seed must be a nonnegative integer')

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        value = read_json(path)
        for key in ('shared_aspects_prompt', 'membership_prompt', 'tokenizer_path'):
            if key in value:
                value[key] = str((path.parent / value[key]).resolve())
        return cls(**value)


def prompts(config):
    return {'shared-aspects': Path(config.shared_aspects_prompt).read_text(),
            'membership': Path(config.membership_prompt).read_text()}


def numbered_cards(cards, order):
    """Cards in the given order, each aspect prefixed by its zero-based index."""
    by_id = {r['paper_id']: r for r in cards}
    return [{'paper_id': pid,
             'card': {'aspects': [{'index': i, **a} for i, a in enumerate(by_id[pid]['card']['aspects'])],
                      'missing_or_unclear': by_id[pid]['card'].get('missing_or_unclear', [])}}
            for pid in order]


def card_order(cards, config, repeat):
    order = sorted(r['paper_id'] for r in cards)
    random.Random(f'{config.rng_seed}:{repeat}').shuffle(order)
    return order


def shared_aspects_messages(prompt, cards, order):
    return render_messages(prompt, {'paper_cards': json.dumps(numbered_cards(cards, order),
                                                              ensure_ascii=False, allow_nan=False)})


def aspect_description(aspect):
    # Rationale and support name papers and their terms; the check sees only the fields.
    return {key: aspect[key] for key in FIELDS}


def membership_messages(prompt, aspect, text):
    return render_messages(prompt, {'shared_aspect': json.dumps(aspect_description(aspect), ensure_ascii=False,
                                                                allow_nan=False),
                                    'full_text': text})


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_shared_aspects(value, cards):
    if list(value) != ['shared_aspects'] or not isinstance(value['shared_aspects'], list):
        raise Step3Error('Shared-aspects response must contain only a shared_aspects list')
    sizes = {r['paper_id']: len(r['card']['aspects']) for r in cards}
    keys = ['rationale', *FIELDS, 'support']
    for item in value['shared_aspects']:
        if not isinstance(item, dict) or list(item) != keys:
            raise Step3Error('Invalid shared-aspect keys or order')
        if not all(nonempty(item[k]) for k in ('rationale', 'problem', 'mechanism_or_object', 'context')):
            raise Step3Error('Shared-aspect text fields must be nonempty strings')
        if not isinstance(item['conditions'], list) or not all(nonempty(c) for c in item['conditions']):
            raise Step3Error('Shared-aspect conditions must be a list of nonempty strings')
        support = item['support']
        if not isinstance(support, list) or len(support) != len(set(support)):
            raise Step3Error('Shared-aspect support must be a list of distinct references')
        papers = set()
        for ref in support:
            pid, sep, number = ref.rpartition('#') if isinstance(ref, str) else ('', '', '')
            if not sep or pid not in sizes or not number.isdigit() or int(number) >= sizes[pid]:
                raise Step3Error('Shared-aspect support references an unknown card aspect')
            papers.add(pid)
        if len(papers) < 2:
            raise Step3Error('Shared-aspect support must cover at least two papers')
    return value


def membership_class(criteria):
    if all(criteria[k] for k in CRITERIA):
        return 'core'
    if all(criteria[k] for k in CRITERIA[:4]):
        return 'adjacent'
    return 'none'


def normalize_membership(value):
    """Clear own_terms of a paper outside the first four criteria; the class is unaffected (agreed 2026-11-02)."""
    info = {'applied': False}
    criteria = value.get('criteria') if isinstance(value, dict) else None
    if (isinstance(criteria, dict) and set(CRITERIA) <= set(criteria)
            and all(type(criteria[k]) is bool for k in CRITERIA)
            and not all(criteria[k] for k in CRITERIA[:4])
            and isinstance(value.get('own_terms'), list) and value['own_terms']):
        info = {'applied': True, 'rule': 'clear-own-terms-outside-membership', 'removed_own_terms': value['own_terms']}
        value = {**value, 'own_terms': []}
    return value, info


def validate_membership(value):
    if list(value) != ['reason', 'criteria', 'own_terms', 'sections', 'class']:
        raise Step3Error('Invalid membership keys or order')
    if not nonempty(value['reason']):
        raise Step3Error('Missing membership explanation')
    criteria = value['criteria']
    if (not isinstance(criteria, dict) or list(criteria) != list(CRITERIA)
            or not all(type(v) is bool for v in criteria.values())):
        raise Step3Error('Membership criteria must be the five JSON booleans in order')
    for key in ('own_terms', 'sections'):
        if not isinstance(value[key], list) or not all(nonempty(x) for x in value[key]):
            raise Step3Error(f'{key} must be a list of nonempty strings')
    if value['own_terms'] and not all(criteria[k] for k in CRITERIA[:4]):
        raise Step3Error('own_terms must be empty unless the first four criteria hold')
    if value['class'] != membership_class(criteria):
        raise Step3Error('Membership class differs from the class implied by the criteria')
    return value


def provenance(config, cards):
    names = ('factory_step3.py', 'factory_step2.py', 'llm.py')
    return {'version': VERSION, 'config': asdict(config),
            'implementation_sha256': {n: digest(Path(__file__).with_name(n).read_bytes()) for n in names},
            'prompt_sha256': {n: digest(t.encode()) for n, t in prompts(config).items()},
            'cards_sha256': digest(json.dumps(cards, ensure_ascii=False, sort_keys=True).encode())}


def mapping(state):
    """Shared aspect -> papers classed core/adjacent; the step 3 result."""
    result = []
    for number, aspect in enumerate(state['shared_aspects'], 1):
        members = [{'paper_id': pid, **{k: r[k] for k in ('class', 'own_terms', 'sections')}}
                   for pid, r in state['checks'].get(f'{number:02d}', {}).items()
                   if r.get('class') in ('core', 'adjacent')]
        result.append({'aspect': f'{number:02d}', **aspect_description(aspect), 'members': members})
    return result


def dry_run(cards, texts, config, guard, output):
    """No LLM: render every request and count tokens; one stand-in aspect for stage 2."""
    validate_cards(cards)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    prompt = prompts(config)

    def tokens(messages):
        try:
            return guard.check(messages, 0)['content_tokens']
        except ContextBudgetExceeded:
            return 'overflow'

    stage1 = [tokens(shared_aspects_messages(prompt['shared-aspects'], cards, card_order(cards, config, repeat)))
              for repeat in range(1, config.stage1_repeats + 1)]
    stand_in = {k: 'x' for k in FIELDS} | {'conditions': ['x']}
    papers = {}
    for pid in sorted(r['paper_id'] for r in cards):
        text = texts(pid)
        papers[pid] = None if text is None else tokens(membership_messages(prompt['membership'], stand_in, text))
    report = {'stage1_content_tokens': stage1, 'stage2_content_tokens_per_paper': papers,
              'unavailable_texts': [p for p, t in papers.items() if t is None]}
    write_json(output / 'manifest.json', provenance(config, cards))
    write_json(output / 'dry-run.json', report)
    return report


def saved_membership(directory):
    """Re-validate a response already on disk; no request is sent."""
    from .factory_step2 import parse_completion
    value, info = normalize_membership(parse_completion(read_json(directory / 'completion.json')))
    write_json(directory / 'membership-normalization.json', info)
    return validate_membership(value)


def resume_state(output, config, cards, llm):
    """Continue a stopped region from its saved artifacts with the same prompts, cards and model settings."""
    old = read_json(output / 'manifest.json')
    new = provenance(config, cards)
    new['llm_config'] = asdict(llm.config)
    for key in ('prompt_sha256', 'cards_sha256', 'config', 'llm_config'):
        a, b = old[key], new[key]
        if key == 'llm_config':
            a, b = {k: v for k, v in a.items() if k != 'max_requests'}, {k: v for k, v in b.items() if k != 'max_requests'}
        if a != b:
            raise Step3Error(f'Resume {key} differs from the stopped run')
    state = read_json(output / 'state.json')
    if state['status'] not in ('stopped_on_error', 'interrupted') or not state['shared_aspects']:
        raise Step3Error('Only a region stopped after stage 1 can be resumed')
    write_json(output / f"resume-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json",
               {'previous_status': state['status'], 'previous_error': state.get('error'),
                'previous_llm_requests': state['llm_requests'],
                'implementation_sha256': {'before': old['implementation_sha256'], 'now': new['implementation_sha256']}})
    state.pop('error', None)
    state['status'] = 'running'
    return state


def execute(cards, texts, config, *, llm, guard, output, progress=None, resume=False):
    """Stage 1 (repeats) then stage 2 on repeat 1. Nothing is retried; any error but a failed later repeat stops the region.

    On resume, stage 1 and checked pairs are kept and a pending pair is re-validated from its saved response.
    """
    if not llm.config.model:
        raise Step3Error('Select an explicit model')
    validate_cards(cards)
    output = Path(output)
    prompt = prompts(config)
    if resume:
        state = resume_state(output, config, cards, llm)
    else:
        output.mkdir(parents=True, exist_ok=False)
        info = provenance(config, cards)
        info['llm_config'] = asdict(llm.config)
        write_json(output / 'manifest.json', info)
        write_json(output / 'cards.json', cards)
        for name, text in prompt.items():
            (output / f'{name}-prompt.md').write_text(text)
        state = {'status': 'running', 'stage1': [], 'shared_aspects': [], 'checks': {},
                 'started_at': datetime.now(timezone.utc).isoformat()}
    previous_requests = state.get('llm_requests', 0)
    initial_requests = llm.requests

    def checkpoint():
        state['llm_requests'] = previous_requests + llm.requests - initial_requests
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'state.json', state)

    checkpoint()
    try:
        stage2_config = llm.config
        if not resume:
            (output / 'stage1').mkdir()
        llm.config = replace(stage2_config, max_output_tokens=config.stage1_max_output_tokens)
        for repeat in range(1, config.stage1_repeats + 1 if not resume else 1):
            order = card_order(cards, config, repeat)
            directory = output / 'stage1' / f'repeat-{repeat:03d}'
            write_json(output / 'stage1' / f'order-{repeat:03d}.json', order)
            try:
                value = validate_shared_aspects(model_call(llm, guard, shared_aspects_messages(
                    prompt['shared-aspects'], cards, order), directory), cards)
            except (Step2Error, ProbeError) as exc:
                if repeat == 1:
                    raise
                # Repeats after the first only measure stability; a bad response is recorded, not fatal.
                state['stage1'].append({'repeat': repeat, 'error': {'type': type(exc).__name__, 'message': str(exc)}})
                checkpoint()
                continue
            write_json(directory / 'shared-aspects.json', value)
            state['stage1'].append({'repeat': repeat, 'shared_aspects': len(value['shared_aspects'])})
            if repeat == 1:
                state['shared_aspects'] = value['shared_aspects']
            checkpoint()
            if progress:
                progress({'stage': 1, 'repeat': repeat, 'shared_aspects': len(value['shared_aspects'])})
        llm.config = stage2_config
        (output / 'stage2').mkdir(exist_ok=resume)
        for number, aspect in enumerate(state['shared_aspects'], 1):
            key = f'{number:02d}'
            checks = state['checks'].setdefault(key, {})
            for pid in sorted(r['paper_id'] for r in cards):
                if checks.get(pid, {}).get('status') in ('checked', 'source_unavailable', 'context_overflow'):
                    continue
                directory = output / 'stage2' / key / pid.replace(':', '_').replace('/', '_')
                if checks.get(pid, {}).get('status') == 'pending' and (directory / 'completion.json').exists():
                    value = saved_membership(directory)
                    write_json(directory / 'assessment.json', value)
                    checks[pid] = {'status': 'checked', 'from_saved_response': True,
                                   **{k: value[k] for k in ('class', 'own_terms', 'sections')}}
                    checkpoint()
                    continue
                if checks.get(pid, {}).get('status') == 'pending':
                    raise Step3Error('A pending pair has no saved response; inspect it before resuming')
                text = texts(pid)
                if text is None:
                    checks[pid] = {'status': 'source_unavailable'}
                    checkpoint()
                    continue
                messages = membership_messages(prompt['membership'], aspect, text)
                try:
                    guard.check(messages, llm.config.max_output_tokens)
                except ContextBudgetExceeded:
                    # The pair is skipped without a request; the region continues.
                    checks[pid] = {'status': 'context_overflow'}
                    checkpoint()
                    continue
                checks[pid] = {'status': 'pending'}
                checkpoint()
                value, normalization = normalize_membership(model_call(llm, guard, messages, directory))
                write_json(directory / 'membership-normalization.json', normalization)
                value = validate_membership(value)
                write_json(directory / 'assessment.json', value)
                checks[pid] = {'status': 'checked', **{k: value[k] for k in ('class', 'own_terms', 'sections')}}
                checkpoint()
                if progress:
                    progress({'stage': 2, 'aspect': key, 'paper_id': pid, 'class': value['class']})
        state['status'] = 'completed'
        write_json(output / 'result.json', mapping(state))
    except (Exception, KeyboardInterrupt) as exc:
        if hasattr(llm, 'stop'):
            llm.stop()
        state['status'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'stopped_on_error'
        state['error'] = {'type': type(exc).__name__,
                          'message': str(exc) if isinstance(exc, (Step2Error, LLMError, ProbeError)) else type(exc).__name__}
    checkpoint()
    return state
