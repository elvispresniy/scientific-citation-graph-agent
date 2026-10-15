"""Reproducible lexical comparison grid. No inference APIs or model downloads.

All percentages are coverage of observable query vocabulary, not relevance or
semantic equivalence. Frozen query-only scientific spans are one input view;
full content-word queries provide a term-selection sensitivity control.
"""
import argparse
import bisect
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import nltk
from nltk.stem import SnowballStemmer
from nltk.corpus import wordnet
from section_text import split_html, split_pdf, VERSION as RELATED_VERSION

ROOT=Path(__file__).resolve().parent
nltk.data.path.insert(0,str(ROOT/'fulltext-cache/nltk_data'))
RUN='terminology-grid-v2-2026-10-12'
STEM=SnowballStemmer('english')
STOP_SPEC=json.loads((ROOT/'stopwords.v1.json').read_text())
STOP=set(STOP_SPEC['words'])
BOILER=set(STOP_SPEC['query_boilerplate_words'])
ALIASES={
 'mcmc':'markov chain monte carlo',
 'rl':'reinforcement learning',
 'gnn':'graph neural network', 'gnns':'graph neural networks',
 'cnn':'convolutional neural network', 'cnns':'convolutional neural networks',
 'nlp':'natural language processing',
}
SPLIT_VERSION='references-heading-and-appendix-recovery-v2'
METHODS={
 'words_exact':('Слова: точное совпадение','Доля различных слов научных терминов запроса, найденных в статье; регистр и типографика не учитываются.'),
 'words_lemma':('Слова: осторожная нормализация','Покрытие слов после словарной нормализации существительных WordNet: меняем форму только при единственном возможном результате; неоднозначные и неизвестные формы оставляем.'),
 'words_stem':('Слова: после стемминга','Та же доля после Snowball English: сводим грамматические и некоторые производные формы к общей основе.'),
 'words_idf':('Стемминг и вес редкости','Покрытие основ слов, где редкие слова имеют больший вес. Веса зафиксированы по доступным названиям и аннотациям целей.'),
 'words_alias':('Стемминг и сокращения','Покрытие основ слов после раскрытия явно заданного малого словаря сокращений; словарь одинаков для всех текстовых частей.'),
 'bigrams_stem':('Пары слов: с порядком','Доля различных соседних пар содержательных слов внутри терминов, найденных в таком же порядке после стемминга. Для однословных терминов учитывается само слово.'),
 'phrases_exact':('Термины целиком: точные слова','Доля выделенных научных выражений, найденных подряд после удаления служебных слов, без морфологической нормализации.'),
 'phrases_lemma':('Термины целиком: осторожная нормализация','Доля выделенных научных выражений, найденных подряд после однозначной словарной нормализации существительных и удаления служебных слов.'),
 'phrases_stem':('Термины целиком: стемминг','Доля выделенных выражений, найденных целиком подряд после стемминга и удаления служебных слов. Длинное описание считается одной фразой.'),
 'local_terms_10':('Термины рядом: окно 10 слов','Доля выражений, все основы слов которых найдены в окне из 10 содержательных слов, без требования порядка.'),
 'local_terms':('Термины рядом: окно 30 слов','Доля выражений, все основы слов которых найдены в окне из 30 содержательных слов, без требования порядка.'),
 'local_terms_100':('Термины рядом: окно 100 слов','Доля выражений, все основы слов которых найдены в окне из 100 содержательных слов, без требования порядка.'),
 'char_trigrams':('Фрагменты слов: по 3 символа','Доля различных трёхсимвольных фрагментов слов запроса, найденных в словах статьи. Это допускает частичное совпадение слова.'),
 'jaccard':('Жаккар: общий словарь','Число общих основ слов делится на число разных основ в объединении запроса и статьи. Симметричная мера; длинная статья увеличивает знаменатель.'),
 'idf_cosine':('Косинус: векторы редкости','Косинус бинарных векторов присутствия основ слов с IDF-весами. Это не нейросетевая семантическая модель; длина и посторонний словарь влияют на результат.'),
}
VIEWS={
 'title':'Заголовок', 'abstract':'Аннотация', 'title_abstract':'Заголовок + аннотация',
 'full_text':'Весь извлечённый текст', 'body_no_references':'Текст без библиографии',
 'references':'Только библиография',
 'body_no_references_no_related_work':'Без библиографии и явно выделенного Related Work',
}

def load(name):
 return [json.loads(x) for x in (ROOT/name).read_text().splitlines() if x]
def sha(data):
 if not isinstance(data,bytes): data=data.encode()
 return hashlib.sha256(data).hexdigest()
def stable(value):
 return sha(json.dumps(value,ensure_ascii=False,sort_keys=True))
def clean(text):
 text=unicodedata.normalize('NFKC',text).replace('\u00ad','')
 text=re.sub(r'(?<=[A-Za-z])-\s*\n\s*(?=[a-z])','',text)
 text=text.replace('’',"'")
 return text

def tokens(text,query=False,stop=True):
 raw=re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?",clean(text).lower())
 raw=[re.sub(r"'s$",'',x) for x in raw]
 return [x for x in raw if (not stop or x not in STOP) and (not query or x not in BOILER)]
@lru_cache(maxsize=300000)
def stem_word(word):
 return STEM.stem(word) if word.isalpha() else word
def stems(items):
 return [stem_word(x) for x in items]
@lru_cache(maxsize=300000)
def lemma_word(word):
 if not word.isalpha():return word
 forms=wordnet._morphy(word,wordnet.NOUN)
 return forms[0] if len(forms)==1 else word
def lemmas(items):
 return [lemma_word(x) for x in items]
def expanded(items):
 out=set(items)
 for word in items:
  if word in ALIASES: out.update(tokens(ALIASES[word]))
 return set(stems(out))
def grams(items):
 return {word[i:i+3] for word in items for i in range(max(0,len(word)-2))}

def split_references(text):
 """Keep appendices after the bibliography when an explicit heading is found."""
 lines=text.splitlines(keepends=True)
 starts=[]; pos=0
 refpattern=re.compile(r'^(?:(?:\d+(?:\.\d+)*|[IVX]+)\.?\s*)?(?:references?|bibliography|literaturecited)(?:andnotes)?$',re.I)
 apppattern=re.compile(r'^(?:(?i:appendi(?:x|ces)\b.*|supplement(?:ary|al)\b.*)|[A-Z](?:\.\d+)*\.?\s+(?i:Proof|Additional|Supplementary|Experimental|Implementation|Details|Derivation|More|Extended|Theoretical|Ablation|Data|Training|Further|Main)\b.*)$')
 for i,line in enumerate(lines):
  # Letter-spaced PDF headings such as "R EFERENCES" are accepted.
  compact=re.sub(r'\s+','',line.strip()).rstrip('.:')
  if refpattern.fullmatch(compact): starts.append((i,pos))
  pos+=len(line)
 if not starts:
  return None,None,{'status':'heading_not_found','version':SPLIT_VERSION}
 # A table-of-contents hit is normally earlier than the midpoint. Prefer last heading;
 # duplicate headings are disclosed for review.
 idx,start=starts[-1]
 after=sum(len(x) for x in lines[:idx+1]); end=len(text); appendix=None
 for j in range(idx+1,len(lines)):
  candidate=lines[j].strip()
  if re.fullmatch(r'[A-Z]\.?',candidate):
   following=next((z.strip() for z in lines[j+1:j+4] if z.strip()),'')
   candidate+=' '+following
  if apppattern.match(candidate):
   end=sum(len(x) for x in lines[:j]);appendix=lines[j].strip();break
 return text[:start]+text[end:],text[after:end],{
  'status':'split','version':SPLIT_VERSION,'reference_start':start,'reference_end':end,
  'heading':lines[idx].strip(),'heading_candidates':len(starts),
  'appendix_recovered':appendix,
  'warning':'Heuristic section split; bibliography boundaries are not independently human validated.'}

class Doc:
 def __init__(self,text):
  self.text=text
  self.tok=tokens(text)
  self.stem=stems(self.tok)
  self.lemma=lemmas(self.tok)
  self.lset=set(self.lemma)
  self.raw_joined=' '+' '.join(self.tok)+' '
  self.lemma_joined=' '+' '.join(self.lemma)+' '
  self.exact=set(self.tok);self.sset=set(self.stem)
  self.joined=' '+' '.join(self.stem)+' '
  self.bigram=set(zip(self.stem,self.stem[1:]))
  self.chars=grams(self.tok)
  self.alias=expanded(self.tok)
  for short,long in ALIASES.items():
   if (' '+' '.join(stems(tokens(long)))+' ') in self.joined:
    self.alias.update(stems([short]))
  self.positions=defaultdict(list)
  for i,t in enumerate(self.stem): self.positions[t].append(i)
 def local(self,phrase,window=30):
  wanted=set(phrase)
  if not wanted or not wanted<=self.sset: return False
  events=sorted((p,t) for t in wanted for p in self.positions[t])
  seen=Counter();left=0
  for right,(index,t) in enumerate(events):
   seen[t]+=1
   while events[right][0]-events[left][0]>=window:
    old=events[left][1];seen[old]-=1
    if seen[old]==0: del seen[old]
    left+=1
   if len(seen)==len(wanted): return True
  return False

def query_features(phrases):
 pt=[tokens(x) for x in phrases]
 raw={x for z in pt for x in z}
 ss=set(stems(raw));pstem=[stems(x) for x in pt]
 # Every listed scientific expression contributes at least one item, even if one word.
 pairs={tuple(z) if len(z)==1 else pair for z in pstem for pair in (list(zip(z,z[1:])) if len(z)>1 else [tuple(z)])}
 return {'raw':raw,'stem':ss,'phrases':pstem,'phrases_raw':pt,'phrases_lemma':[lemmas(x) for x in pt],'bigrams':pairs,'chars':grams(raw),'alias':expanded(raw)}

def scores(q,d,idf):
 def ratio(hit,total): return len(hit)/len(total) if total else None
 exact=q['raw']&d.exact;common=q['stem']&d.sset
 normalized={t for t in q['raw'] if stem_word(t) in d.sset}
 lemmatized={t for t in q['raw'] if lemma_word(t) in d.lset}
 alias_words={t for t in q['raw'] if stem_word(t) in d.alias}
 def w(t):return idf.get(t,idf['__unseen__'])
 den=sum(w(stem_word(t)) for t in q['raw'])
 alias=q['stem']&d.alias
 found_big={z for z in q['bigrams'] if (z[0] in d.sset if len(z)==1 else z in d.bigram)}
 phrase_hits=[bool(z) and (' '+' '.join(z)+' ') in d.joined for z in q['phrases']]
 local_hits=[d.local(z) for z in q['phrases']]
 union=q['stem']|d.sset
 dot=sum(w(t)**2 for t in common)
 norm=math.sqrt(sum(w(t)**2 for t in q['stem'])*sum(w(t)**2 for t in d.sset))
 values={
  'words_exact':ratio(exact,q['raw']),'words_lemma':ratio(lemmatized,q['raw']),'words_stem':ratio(normalized,q['raw']),
  'words_idf':sum(w(stem_word(t)) for t in normalized)/den if den else None,
  'words_alias':ratio(alias_words,q['raw']),
  'bigrams_stem':ratio(found_big,q['bigrams']),
  'phrases_exact':sum(bool(z) and (' '+' '.join(z)+' ') in d.raw_joined for z in q['phrases_raw'])/len(q['phrases_raw']) if q['phrases_raw'] else None,
  'phrases_lemma':sum(bool(z) and (' '+' '.join(z)+' ') in d.lemma_joined for z in q['phrases_lemma'])/len(q['phrases_lemma']) if q['phrases_lemma'] else None,
  'phrases_stem':sum(phrase_hits)/len(phrase_hits) if phrase_hits else None,
  'local_terms_10':sum(d.local(z,10) for z in q['phrases'])/len(q['phrases']) if q['phrases'] else None,
  'local_terms':sum(local_hits)/len(local_hits) if local_hits else None,
  'local_terms_100':sum(d.local(z,100) for z in q['phrases'])/len(q['phrases']) if q['phrases'] else None,
  'char_trigrams':ratio(q['chars']&d.chars,q['chars']),
  'jaccard':ratio(common,union), 'idf_cosine':dot/norm if norm else None,
 }
 details={
  'query_words':sorted(q['raw']),'found_exact':sorted(exact),'missing_exact':sorted(q['raw']-d.exact),
  'found_lemma_words':sorted(lemmatized),'missing_lemma_words':sorted(q['raw']-lemmatized),
  'found_normalized_words':sorted(normalized),'missing_normalized_words':sorted(q['raw']-normalized),
  'found_alias_words':sorted(alias_words),
  'query_stems':sorted(q['stem']),'found_stems':sorted(common),'missing_stems':sorted(q['stem']-d.sset),
  'found_with_aliases':sorted(alias),
  'query_stem_count':len(q['stem']),'document_word_count':len(d.tok),'document_unique_stems':len(d.sset),
  'whole_phrase_hits':phrase_hits,'local_phrase_hits':local_hits,
 }
 return values,details

def build_idf(papers):
 df=Counter();n=0
 for p in papers:
  if p.get('title') and p.get('abstract'):
   n+=1;df.update(set(stems(tokens(p['title']+'\n'+p['abstract']))))
 weights={t:math.log((n+1)/(v+1))+1 for t,v in df.items()}
 weights['__unseen__']=math.log(n+1)+1
 spec={'formula':'ln((N+1)/(df+1))+1','N':n,'corpus':'unique target records with both title and abstract',
       'corpus_sha256':stable([{k:p[k] for k in ('paper_id','title','abstract')} for p in papers if p.get('title') and p.get('abstract')]),
       'weights':weights}
 (ROOT/'idf.v1.json').write_text(json.dumps(spec,ensure_ascii=False,sort_keys=True)+'\n')
 return weights,spec

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--partial',action='store_true');args=parser.parse_args()
 papers=load('papers.jsonl');pby={p['paper_id']:p for p in papers};questions=load('questions.jsonl')
 full={p['paper_id']:p for p in load('fulltexts.jsonl')}
 boundaries=json.loads((ROOT/'reference-boundaries.v1.json').read_text())
 related_boundaries=json.loads((ROOT/'related-work-boundaries.v1.json').read_text())
 if not args.partial: assert len(full)==len(papers),'Full-text fetch has not completed; use --partial for explicit development run.'
 term_spec=json.loads((ROOT/'query-terms.v2.json').read_text());terms={r['question_id']:r['terms'] for r in term_spec['questions']}
 idf,idfspec=build_idf(papers)
 (ROOT/'aliases.v1.json').write_text(json.dumps({'version':'1.0','aliases':ALIASES,'note':'Fixed small dictionary; no corpus-tailored synonyms, not an ontology or semantic relevance check.'},ensure_ascii=False,indent=2)+'\n')
 config={'tokenizer':'english-alphanumeric-v1','case':'lower','unicode':'NFKC',
         'stemmer':'nltk Snowball English','lemma_normalizer':'WordNet noun _morphy; unique analysis only',
         'wordnet_version':wordnet.get_version(),'wordnet_zip_sha256':sha((ROOT/'fulltext-cache/nltk_data/corpora/wordnet.zip').read_bytes()),'nltk_version':nltk.__version__,
         'stoplist_sha256':stable(STOP_SPEC),'query_terms_sha256':stable(term_spec),
         'alias_dictionary_sha256':stable(ALIASES),'idf_corpus_sha256':idfspec['corpus_sha256'],
         'reference_boundaries_sha256':stable(boundaries),'reference_split_version':SPLIT_VERSION,
         'related_work_boundaries_sha256':stable(related_boundaries),'related_work_split_version':RELATED_VERSION,
         'window_content_tokens':[10,30,100],'coverage_denominator':'distinct original query words, fixed across word coverage variants',
         'fulltext_prefix':'prepend metadata title+abstract to extracted article; binary presence metrics unaffected by duplicates'}
 (ROOT/'metric-config.v1.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
 metricfile=(ROOT/'metrics.jsonl').open('w');pairfile=(ROOT/'term-pairs.jsonl').open('w')
 splits=[];related_splits=[];count=0;paircount=0
 qby={q['question_id']:q for q in questions}
 reverse=defaultdict(list)
 for q in questions:
  for pid in q['gold_paper_ids']: reverse[pid].append(q)
 for p in papers:
  pid=p['paper_id'];f=full.get(pid,{'status':'pending'})
  ta=p['title']+'\n'+p['abstract'] if p.get('title') and p.get('abstract') else None
  views={'title':p.get('title'),'abstract':p.get('abstract'),'title_abstract':ta,
         'full_text':None,'body_no_references':None,'references':None,'body_no_references_no_related_work':None}
  split={'paper_id':pid,'status':f['status']}
  related={'paper_id':pid,'status':f['status']}
  if f['status']=='ready':
   raw=(ROOT/f['text_path']).read_text()
   assert sha((ROOT/f['text_path']).read_bytes())==f['text_sha256']
   if pid in boundaries:
    boundary=boundaries[pid];assert boundary['text_sha256']==f['text_sha256']
    ranges=boundary.get('reference_ranges',[[boundary.get('reference_start'),boundary.get('reference_end')]])
    kept=[];refparts=[];last=0
    for start,end in ranges:
     assert last<=start<end<=len(raw)
     kept.append(raw[last:start]);refparts.append(raw[start:end]);last=end
    kept.append(raw[last:]);body='\n'.join(kept);refs='\n'.join(refparts)
    info={'status':'split','version':'explicit-reviewed-boundary-v1','format':f.get('format','pdf'),'boundary':boundary}
   elif f.get('format')=='html' and f.get('has_references_element'):
    body=(ROOT/f['body_path']).read_text();refs=(ROOT/f['references_path']).read_text()
    info={'status':'split','version':'arxiv-html-bibliography-element-v1','format':'html',
          'warning':'Structural bibliography extraction; no PDF heading heuristic.'}
   else:
    body,refs,info=split_references(raw)
    info['format']=f.get('format','pdf')
   split.update(info)
   # Include released metadata when available to compare nested text views. Repetition
   # cannot affect set/coverage metrics; IDF cosine uses binary presence, not frequency.
   prefix=(ta or p.get('title') or '')+'\n'
   views['full_text']=prefix+raw
   if body is not None:
    views['body_no_references']=prefix+body
    views['references']=refs
    override=related_boundaries.get(pid)
    if override:
     assert override['body_sha256']==sha(body)
    if override and override.get('status')=='unreliable_extraction':
     strict=None;rwinfo={'status':'ambiguous','version':RELATED_VERSION,'reason':override['reason']}
    elif f.get('format')=='html':
     htmlbody,strict,rwinfo=split_html((ROOT/f['html_path']).read_text())
     assert htmlbody==body,(pid,'HTML extraction changed')
    else:
     strict,rwinfo=split_pdf(body,override)
    related.update(rwinfo);related['body_sha256']=sha(body)
    if strict is not None:
     path=ROOT/'fulltext-cache'/(pid.replace(':','_').replace('/','_')+'.no-related-work.txt')
     path.write_text(strict)
     related.update({'text_path':str(path.relative_to(ROOT)),'text_sha256':sha(strict),'body_characters':len(body),'kept_characters':len(strict)})
     views['body_no_references_no_related_work']=prefix+strict
  splits.append(split)
  related_splits.append(related)
  docs={v:Doc(text) for v,text in views.items() if text}
  for q in reverse[pid]:
   qid=q['question_id'];ts=[z['text'] for z in terms[qid] if z['role']=='mentioned']
   excluded=[z['text'] for z in terms[qid] if z['role']=='excluded']
   for z in terms[qid]:assert q['text'][z['start']:z['end']]==z['text']
   scopes={'scientific_terms':ts,'all_content_words':[' '.join(tokens(q['text'],query=True))]}
   result={'question_id':qid,'paper_id':pid,'benchmark':q['benchmark'],'scientific_terms':ts,
           'excluded_terms':excluded,'views':{},'content_word_scores':{},'fulltext_status':f['status'],'reference_split_status':split['status'],'related_work_split_status':related['status']}
   for scope,phrases in scopes.items():
    qf=query_features(phrases)
    for view in VIEWS:
     doc=docs.get(view)
     values,details=scores(qf,doc,idf) if doc else ({method:None for method in METHODS},{})
     if scope=='scientific_terms':
      result['views'][view]={'scores':values,**details}
     else:
      result['content_word_scores'][view]={m:values[m] for m in ('words_exact','words_lemma','words_stem','words_idf','words_alias')}
     input_hash=stable({'phrases':phrases,'text':views[view]})
     for method in METHODS:
      if scope=='all_content_words' and method not in ('words_exact','words_lemma','words_stem','words_idf','words_alias'):continue
      value=values[method];status='ok' if value is not None else 'missing_metadata'
      record={'record_type':'metric_result','schema_version':'1.0','run_id':RUN,
              'question_id':qid,'paper_id':pid,'metric_name':method,'metric_version':'1.0',
              'input_view':('terms__' if scope=='scientific_terms' else 'question__')+view,
              'input_sha256':input_hash,
              'preprocessing':{'config':'metric-config.v1.json','config_sha256':stable(config)},
              'score':value,'status':status,
              'details':{'query_scope':scope,'document_view':view,'metadata_identity_flag':bool(p.get('metadata_notes')),
                         'reference_split':split['status'],'related_work_split':related['status'],'missing_reason':None if status=='ok' else ('text unavailable or section boundaries unreliable' if doc is None else 'empty denominator')}}
      metricfile.write(json.dumps(record,ensure_ascii=False)+'\n');count+=1
   pairfile.write(json.dumps(result,ensure_ascii=False)+'\n');paircount+=1
 metricfile.close();pairfile.close()
 (ROOT/'reference-splits.jsonl').write_text(''.join(json.dumps(z,ensure_ascii=False)+'\n' for z in splits))
 (ROOT/'related-work-splits.jsonl').write_text(''.join(json.dumps(z,ensure_ascii=False)+'\n' for z in related_splits))
 summary={'run_id':RUN,'development_partial_run':args.partial,'pairs':paircount,'metric_records':count,
          'fulltext_records':len(full),'fulltext_ready':sum(x['status']=='ready' for x in full.values()),
          'reference_split_counts':dict(Counter(z['status'] for z in splits)),
          'related_work_split_counts':dict(Counter(z['status'] for z in related_splits)),
          'methods':{k:{'name':v[0],'description':v[1]} for k,v in METHODS.items()},'views':VIEWS,
          'scientific_term_spans':sum(len(x['terms']) for x in term_spec['questions']),
          'scientific_spans_exclude_diagnostic_requirements':True,
          'important_limitations':['No independent human term extraction or lexical gold standard.',
           'Corpus is a small selected target collection, not all arXiv. IDF is a sensitivity variant.',
           'PDF extraction and bibliography splitting can lose or misplace text.',
           'Presence of words does not establish semantic equivalence or satisfaction of constraints.']}
 (ROOT/'metric-run.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in summary.items() if k not in ('methods','views','important_limitations')},ensure_ascii=False))

if __name__=='__main__':main()
