"""Query-only automatic term candidates; no document-dependent filtering.

POS noun phrases are candidates, not a claim of semantic equivalence or a
replacement for an expert terminology annotation. Negated topics remain present
vocabulary; their matching does not mean satisfying a negated requirement.
"""
import hashlib,json,re
from pathlib import Path
import nltk
from nltk.tokenize import TreebankWordTokenizer
from measure_terms import ROOT,tokens,STOP,BOILER,lemma_word

VERSION='pos-noun-phrases-v1'
TOKENIZER=TreebankWordTokenizer()
GENERIC={'paper','papers','article','articles','publication','publications','work','works','study','studies','research','researcher','researchers',
         'author','authors','affiliation','affiliations','journal','journals','conference','conferences','year','years','example','examples',
         'question','questions','list','lists','literature','survey','surveys','review','reviews'}

def extract(text,variant='noun_phrases'):
    offsets=list(TOKENIZER.span_tokenize(text));words=[text[a:b] for a,b in offsets]
    tags=nltk.pos_tag(words,lang='eng')
    if variant=='content_words':return [{'text':w,'start':a,'end':b} for (a,b),w in zip(offsets,words) if tokens(w,query=True)]
    chunks=[];current=[]
    def flush():
        nonlocal current
        # A phrase must end in a noun; remove trailing participles/adjectives.
        while current and not tags[current[-1]][1].startswith('NN'):current.pop()
        if current and any(tags[i][1].startswith('NN') and tokens(words[i],query=True) and words[i].casefold() not in GENERIC for i in current):
            if variant=='nouns_only':
                for i in current:
                    if tags[i][1].startswith('NN') and words[i].casefold() not in GENERIC:
                        a,b=offsets[i];chunks.append({'text':text[a:b],'start':a,'end':b})
            else:
                a=offsets[current[0]][0];b=offsets[current[-1]][1];chunks.append({'text':text[a:b],'start':a,'end':b})
        current=[]
    for i,(word,tag) in enumerate(tags):
        keep=(tag.startswith(('NN','JJ')) or tag in ('VBG','VBN')) and bool(tokens(word,query=True)) and word.casefold() not in GENERIC
        if keep:current.append(i)
        else:flush()
    flush()
    return chunks

def calibrate():
    qs={q['question_id']:q for q in map(json.loads,(ROOT/'questions.jsonl').read_text().splitlines())}
    manual=json.loads((ROOT/'query-terms.v2.json').read_text())['questions']
    rows=[];scores={}
    from statistics import mean
    for variant in ('nouns_only','noun_phrases','content_words'):
        values=[]
        for m in manual:
            text=qs[m['question_id']]['text'];spans=extract(text,variant)
            selected={lemma_word(w) for s in spans for w in tokens(s['text'],query=True)}
            reference={lemma_word(w) for s in m['terms'] if s['role']=='mentioned' for w in tokens(s['text'])}
            hit=selected&reference;precision=len(hit)/len(selected) if selected else 0;recall=len(hit)/len(reference) if reference else 0
            f1=2*precision*recall/(precision+recall) if precision+recall else 0
            values.append((precision,recall,f1));rows.append({'question_id':m['question_id'],'variant':variant,'spans':spans,'precision':precision,'recall':recall,'f1':f1,'extra_words':sorted(selected-reference),'missed_words':sorted(reference-selected)})
        scores[variant]={'precision':mean(v[0] for v in values),'recall':mean(v[1] for v in values),'f1':mean(v[2] for v in values)}
    winner=max(scores,key=lambda k:scores[k]['f1'])
    tagger=ROOT/'fulltext-cache/nltk_data/taggers/averaged_perceptron_tagger_eng'
    config={'version':VERSION,'selected_variant':winner,'selection':'highest mean per-question token F1 against the frozen pilot vocabulary; not independent human validation',
            'scores':scores,'nltk_version':nltk.__version__,'tagger_files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tagger.glob('*.json'))},
            'generic_query_nouns':sorted(GENERIC),'negation_policy':'Measure mentioned vocabulary including negated topics; no claim of constraint satisfaction.',
            'calibration_input_sha256':hashlib.sha256((ROOT/'query-terms.v2.json').read_bytes()).hexdigest(),'calibration_questions':30,'human_validation':False}
    (ROOT/'automatic-term-config.v1.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'automatic-term-calibration.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    print(json.dumps(config,ensure_ascii=False))

if __name__=='__main__':calibrate()
