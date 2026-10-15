"""Validate the full-release lexical run without adding semantic judgments."""
import hashlib,json,math
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parent/'release-run'
def jl(name):return [json.loads(x) for x in (ROOT/name).read_text().splitlines() if x]
def main():
    q={x['question_id']:x for x in jl('questions.jsonl')};p={x['paper_id']:x for x in jl('papers.jsonl')}
    terms={x['question_id']:x for x in jl('query-terms.jsonl')};expected={(qid,pid) for qid,x in q.items() for pid in x['gold_paper_ids']}
    assert terms.keys()==q.keys();seen=set();counts=Counter();values=0
    for qid,x in terms.items():
        for span in x['spans']:assert q[qid]['text'][span['start']:span['end']]==span['text']
        assert x['word_count']==len(x['words'])==len(set(x['words']))
    with (ROOT/'pair-metrics.jsonl').open() as f:
        for line in f:
            r=json.loads(line);key=(r['question_id'],r['paper_id']);assert key in expected and key not in seen;seen.add(key)
            assert r['paper_id'] in p
            for v,d in r['views'].items():
                counts[v+':'+d['status']]+=1
                if d['status']=='ok':
                    words=set(terms[r['question_id']]['words']);found=set(d['found_words']);missing=set(d['missing_words'])
                    assert found|missing==words and not found&missing
                    assert math.isclose(d['word_coverage'],len(found)/len(words)) and math.isclose(d['word_gap'],1-d['word_coverage'])
                    assert d['exact_coverage']<=d['word_coverage']+1e-12
                    for name in ('word_coverage','word_gap','exact_coverage','phrase_coverage','content_word_coverage'):
                        value=d[name];assert value is None or (math.isfinite(value) and 0<=value<=1+1e-12);values+=1
                else:assert d['word_coverage'] is None and d['word_gap'] is None and d['reason']
            v=[r['views'][k]['word_coverage'] for k in ('title_abstract','body_no_references_no_related_work','body_no_references')]
            if all(x is not None for x in v):assert v[0]<=v[1]+1e-12<=v[2]+2e-12
    assert seen==expected
    summary=json.loads((ROOT/'summary.json').read_text());assert summary['pairs']==len(seen) and summary['questions']==len(q)
    assert summary['query_file_sha256']==hashlib.sha256((ROOT/'questions.jsonl').read_bytes()).hexdigest()
    assert summary['paper_file_sha256']==hashlib.sha256((ROOT/'papers.jsonl').read_bytes()).hexdigest()
    for field,file in [('metric_file_sha256','pair-metrics.jsonl'),('query_terms_file_sha256','query-terms.jsonl'),('question_metrics_file_sha256','question-metrics.jsonl')]:
        assert summary[field]==hashlib.sha256((ROOT/file).read_bytes()).hexdigest()
    result={'status':'passed','questions':len(q),'pairs':len(seen),'view_status_counts':dict(counts),'numeric_checks':values,
            'checks':['every released target pair exactly once','original-query span offsets','found/missing word partitions','fixed denominators','gap = 1 - coverage','finite scores in range','null missing values','nested available text views','input hashes'],
            'limitation':'No independent expert validation of terminology equivalence, extraction boundaries or target relevance.'}
    (ROOT/'validation-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
