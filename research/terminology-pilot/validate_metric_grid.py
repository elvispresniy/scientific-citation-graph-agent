"""Check completeness, input integrity and cross-view invariants of the final grid.

This checks computation/data integrity, not scientific relevance or human agreement.
"""
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def rows(name):
    return [json.loads(line) for line in (ROOT / name).read_text().splitlines() if line]

def stable(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

questions = {q['question_id']: q for q in rows('questions.jsonl')}
papers = {p['paper_id']: p for p in rows('papers.jsonl')}
full = {p['paper_id']: p for p in rows('fulltexts.jsonl')}
run = json.loads((ROOT / 'metric-run.json').read_text())
assert not run['development_partial_run'], 'Final validation requires a complete fetch inventory.'
assert full.keys() == papers.keys()
assert all(f['status'] in ('ready', 'unavailable') for f in full.values())

ready = 0
for f in full.values():
    if f['status'] != 'ready':
        assert f.get('reason'), f
        continue
    ready += 1
    text = (ROOT / f['text_path']).read_bytes()
    assert hashlib.sha256(text).hexdigest() == f['text_sha256'], f['paper_id']
    assert len(text) > 500, f['paper_id']
    if f.get('format') == 'html':
        raw = (ROOT / f['html_path']).read_bytes()
        assert b'</html>' in raw[-8192:].lower() and b'</article>' in raw.lower(), f['paper_id']
        assert hashlib.sha256(raw).hexdigest() == f['html_sha256']
        if f['has_references_element']:
            assert (ROOT / f['body_path']).exists() and (ROOT / f['references_path']).exists()
    else:
        raw = (ROOT / f['pdf_path']).read_bytes()
        assert raw.startswith(b'%PDF-') and b'%%EOF' in raw[-4096:], f['paper_id']
        assert hashlib.sha256(raw).hexdigest() == f['pdf_sha256']

terms = json.loads((ROOT / 'query-terms.v2.json').read_text())
assert {q['question_id'] for q in terms['questions']} == questions.keys()
spans = 0
for q in terms['questions']:
    for term in q['terms']:
        assert questions[q['question_id']]['text'][term['start']:term['end']] == term['text']
        assert term['role'] in ('mentioned', 'excluded')
        spans += 1

expected_pairs = {(qid, pid) for qid, q in questions.items() for pid in q['gold_paper_ids']}
pairs = rows('term-pairs.jsonl')
assert len(pairs) == len(expected_pairs)
assert {(p['question_id'], p['paper_id']) for p in pairs} == expected_pairs
methods = set(run['methods'])
views = set(run['views'])
word_methods = {'words_exact', 'words_lemma', 'words_stem', 'words_idf', 'words_alias'}
expected_cells = {('terms__' + view, method) for view in views for method in methods}
expected_cells |= {('question__' + view, method) for view in views for method in word_methods}
seen = set()
per_pair = Counter()
status_counts = Counter()
config = json.loads((ROOT / 'metric-config.v1.json').read_text())
for m in rows('metrics.jsonl'):
    pair = (m['question_id'], m['paper_id'])
    cell = (m['input_view'], m['metric_name'])
    key = (*pair, *cell)
    assert pair in expected_pairs and cell in expected_cells
    assert key not in seen, key
    seen.add(key)
    per_pair[pair] += 1
    status_counts[m['status']] += 1
    assert m['run_id'] == run['run_id']
    assert m['preprocessing']['config_sha256'] == stable(config)
    value = m['score']
    if m['status'] == 'ok':
        assert isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1 + 1e-12
    else:
        assert value is None and m['details']['missing_reason']
assert set(per_pair) == expected_pairs
assert all(n == len(expected_cells) for n in per_pair.values())
assert len(seen) == run['metric_records'] == len(expected_pairs) * len(expected_cells)

for p in pairs:
    for view in views:
        d = p['views'][view]
        if d['scores']['words_lemma'] is None:
            continue
        words = set(d['query_words'])
        assert words == set(d['found_lemma_words']) | set(d['missing_lemma_words'])
        assert not set(d['found_lemma_words']) & set(d['missing_lemma_words'])
        assert math.isclose(d['scores']['words_lemma'], len(d['found_lemma_words']) / len(words))
        assert d['scores']['words_lemma'] + 1e-12 >= d['scores']['words_exact']
    for method in word_methods:
        values = [p['views'][v]['scores'][method] for v in ('title_abstract', 'body_no_references_no_related_work', 'body_no_references', 'full_text')]
        if all(v is not None for v in values):
            assert all(a<=b+1e-12 for a,b in zip(values,values[1:])), (p['paper_id'], method)
    for view in views:
        values = [p['views'][view]['scores'][m] for m in ('local_terms_10', 'local_terms', 'local_terms_100')]
        if all(v is not None for v in values):
            assert values[0] <= values[1] + 1e-12 <= values[2] + 2e-12

related=rows('related-work-splits.jsonl')
assert {x['paper_id'] for x in related}==papers.keys()
for x in related:
    if x['status'] in ('removed','no_explicit_section'):
        assert hashlib.sha256((ROOT/x['text_path']).read_bytes()).hexdigest()==x['text_sha256']
        assert x['kept_characters']<=x['body_characters']
    else:
        assert all(p['views']['body_no_references_no_related_work']['scores']['words_lemma'] is None for p in pairs if p['paper_id']==x['paper_id'])
summary = {
    'status': 'passed', 'pairs': len(expected_pairs), 'metric_records': len(seen),
    'cells_per_pair': len(expected_cells), 'scientific_term_spans': spans,
    'unique_articles': len(papers), 'fulltexts_ready': ready,
    'metric_status_counts': dict(status_counts),
    'related_work_split_counts':dict(Counter(x['status'] for x in related)),
    'checks': ['all target pairs represented', 'complete metric/view grid without duplicate cells',
               'finite scores in range; missing text is null', 'fixed term offsets in original questions',
               'raw PDF/HTML completeness and text hashes', 'fixed config hashes and run ID',
               'found/missing word partitions', 'coverage grows across nested text views'],
    'limitation': 'No independent validation of scientific equivalence or target relevance.'
}
(ROOT / 'metric-validation-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
