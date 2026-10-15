"""Validate the schema subset used here plus offsets, joins, hashes and sampling.

Standard library only. This is not a general implementation of JSON Schema.
"""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'records.schema.json').read_text())

def fail(message):
    raise ValueError(message)

def check(value, rule, path='$'):
    if '$ref' in rule:
        target = SCHEMA
        for part in rule['$ref'].split('/')[1:]:
            target = target[part]
        return check(value, target, path)
    if 'oneOf' in rule:
        successes = 0
        for candidate in rule['oneOf']:
            try:
                check(value, candidate, path)
                successes += 1
            except ValueError:
                pass
        if successes != 1:
            fail(f'{path}: oneOf matched {successes} branches')
    if 'type' in rule:
        types = rule['type'] if isinstance(rule['type'], list) else [rule['type']]
        matches = {'object':isinstance(value,dict),'array':isinstance(value,list),
                   'string':isinstance(value,str),'integer':type(value) is int,
                   'number':type(value) in (int,float),'boolean':type(value) is bool,
                   'null':value is None}
        if not any(matches[t] for t in types):
            fail(f'{path}: invalid type')
    if 'const' in rule and value != rule['const']:
        fail(f'{path}: const')
    if 'enum' in rule and value not in rule['enum']:
        fail(f'{path}: enum')
    if isinstance(value, dict):
        for key in rule.get('required',[]):
            if key not in value:
                fail(f'{path}: missing {key}')
        props = rule.get('properties',{})
        for key, item in value.items():
            if key in props:
                check(item,props[key],path+'.'+key)
            elif rule.get('additionalProperties') is False:
                fail(f'{path}: unexpected {key}')
            elif isinstance(rule.get('additionalProperties'),dict):
                check(item,rule['additionalProperties'],path+'.'+key)
    if isinstance(value,list):
        if len(value)<rule.get('minItems',0) or len(value)>rule.get('maxItems',float('inf')):
            fail(f'{path}: array size')
        if rule.get('uniqueItems') and len({json.dumps(x,sort_keys=True) for x in value})!=len(value):
            fail(f'{path}: duplicate item')
        for i, item in enumerate(value):
            check(item,rule.get('items',{}),f'{path}[{i}]')
    if isinstance(value,str):
        if len(value)<rule.get('minLength',0):
            fail(f'{path}: string length')
        if 'pattern' in rule and re.search(rule['pattern'],value) is None:
            fail(f'{path}: pattern')
    if type(value) in (int,float) and value<rule.get('minimum',-float('inf')):
        fail(f'{path}: minimum')
    for clause in rule.get('allOf',[]):
        check(value,clause,path)
    if 'if' in rule:
        try:
            check(value,rule['if'],path)
        except ValueError:
            if 'else' in rule:
                check(value,rule['else'],path)
        else:
            if 'then' in rule:
                check(value,rule['then'],path)

records={}
for name in ['questions','papers','annotations','metrics']:
    rows=[]
    for i,line in enumerate((ROOT/(name+'.jsonl')).read_text().splitlines(),1):
        row=json.loads(line)
        check(row,SCHEMA,f'{name}:{i}')
        rows.append(row)
    records[name]=rows
q={x['question_id']:x for x in records['questions']}
p={x['paper_id']:x for x in records['papers']}
assert len(q)==len(records['questions'])
assert len(p)==len(records['papers'])
all_pairs={(x['question_id'],pid) for x in q.values() for pid in x['gold_paper_ids']}
assert all(pid in p for _,pid in all_pairs)
seen=set();fixed={};spans=0
concepts=json.loads((ROOT/'query-concepts.v1.json').read_text())
for a in records['annotations']:
    key=(a['question_id'],a['paper_id'])
    assert key in all_pairs
    assert a['annotation_id'] not in seen
    seen.add(a['annotation_id'])
    source_q,source_p=q[key[0]],p[key[1]]
    h=hashlib.sha256(json.dumps({'question':source_q['text'],'context':source_q['context'],
                                 'title':source_p['title'],'abstract':source_p['abstract']},
                                ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    assert h==a['input_sha256']
    assert [x['text'] for x in a['query_spans']]==concepts[key[0]]
    spanids=[x['span_id'] for x in a['query_spans']]
    assert len(set(spanids))==len(spanids)
    assert Counter(spanids)==Counter(x['query_span_id'] for x in a['alignments'])
    for x in a['query_spans']:
        assert source_q['text'][x['start']:x['end']]==x['text']
        spans+=1
    for z in a['alignments']:
        for x in z['paper_spans']:
            assert source_p[x['field']][x['start']:x['end']]==x['text']
            spans+=1
    fixed_key=(key[0],a['guideline_version'])
    if fixed_key in fixed:
        assert fixed[fixed_key]==a['query_spans']
    fixed[fixed_key]=a['query_spans']
cal=json.loads((ROOT/'calibration-pairs.json').read_text())
for pair in cal['pairs']:
    qid=pair['question_id']
    expected=min(q[qid]['gold_paper_ids'],key=lambda pid:hashlib.sha256((cal['seed']+'|'+qid+'|'+pid).encode()).hexdigest())
    assert pair['paper_id']==expected
assert {(x['question_id'],x['paper_id']) for x in records['annotations']}=={(x['question_id'],x['paper_id']) for x in cal['pairs']}
m=json.loads((ROOT/'manifest.json').read_text())
assert m['selected_total_pairs']==len(all_pairs)
assert m['unique_target_papers']==len(p)
assert m['annotation_progress']['annotated_pairs']==len(records['annotations'])
assert m['metadata_progress']==dict(Counter(x['metadata_status'] for x in p.values()))
for name,h in m['calibration_artifact_sha256'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
summary={'status':'passed','records':{name:len(rows) for name,rows in records.items()},
         'validated_spans':spans,'selected_gold_pairs':len(all_pairs),
         'checks':['schema subset used by records.schema.json','IDs and gold membership',
                   'Unicode span offsets','one alignment per fixed query concept',
                   'annotation input hashes','deterministic calibration target sampling',
                   'manifest counts and artifact hashes'],
         'limitation':'Structural validation does not validate scientific judgments or supply human review.'}
(ROOT/'validation-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False))
