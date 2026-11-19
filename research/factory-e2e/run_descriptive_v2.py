"""Paired v2 prompt experiment: six fixed inputs from the completed v1 run."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import copy, importlib.util, json, os, sys, html

BASE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('full_descriptive_engine',BASE/'run_full_descriptive.py')
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
ROOT=engine.ROOT
OUT=BASE/'descriptive-v2-paired-20261116';SOURCE=BASE/'full-descriptive-20261115'
IDS=['N01','N08','N09','N14','N22','N23']

def prepare():
 OUT.mkdir(exist_ok=False);old=engine.read_json(SOURCE/'manifest.json')
 entries=[copy.deepcopy(e) for e in old['entries'] if e['id'] in IDS]
 assert len(entries)==6 and sum(len(e['targets']) for e in entries)==23
 assert all(not e['pending'] for e in entries)
 prompt=ROOT/'code/graph_pilot/prompts/group-query-descriptive-rewrite-v2-draft.md'
 judge=(SOURCE/'judge-prompt.md').read_bytes();assert engine.digest(judge)==old['judge_sha256']
 (OUT/'judge-prompt.md').write_bytes(judge);(OUT/'rewrite-prompt.md').write_bytes(prompt.read_bytes())
 previous_feedback=engine.read_json(SOURCE/'original-search-feedback.json')
 feedback={key:previous_feedback[key] for key in IDS}
 engine.write_json(OUT/'original-search-feedback.json',feedback)
 m={**old,'created_at':engine.now(),'entries':entries,'max_http_requests':1000,'max_hours':8,
    'rewrite_sha256':engine.digest(prompt.read_bytes()),'scope':'Paired six-input v2 comparison: only rewrite instruction changes; same original inputs, feedback, targets, generation and judge settings.',
    'files':{str(p):engine.digest(p.read_bytes()) for p in [Path(__file__).resolve(),BASE/'run_full_descriptive.py',prompt,ROOT/'code/graph_pilot/durable_llm.py',ROOT/'code/graph_pilot/direct_retrieval.py',SOURCE/'manifest.json',SOURCE/'original-search-feedback.json']}}
 engine.write_json(OUT/'manifest.json',m)
 print(json.dumps({'questions':6,'old_target_pairs':23,'feedback_identical_to_v1':True,'max_http_attempts':1000,'max_hours':8}),flush=True)

def report(summary):
 prior={r['id']:r for r in engine.read_json(SOURCE/'summary.json')['table_rows']}
 lines=['# Сравнение промптов описательного переформулирования v1/v2','',
        'Шесть одинаковых исходных вопросов, те же аспекты, поисковая обратная связь и прежние цели. Изменена инструкция генерации. Судья исходный true/false. Это один ответ генератора на вход, а не оценка устойчивости по повторам.','',
        '| ID | Целей | v1: цели true | v2: цели true | v1: BM25/LSA top-20 | v2: BM25/LSA top-20 | v2: новых true старый+новый пул | Контроль v2 |',
        '|---|---:|---:|---:|---|---|---:|---|']
 for row in summary['table_rows']:
  old=prior[row['id']]['variants'][0];new=row['variants'][0] if row['variants'] else None
  if new:
   hits=lambda v:'/'.join(str(sum(x<=20 for x in v['ranks'][m].values())) for m in ('bm25','tfidf_lsa'))
   c=new['controls'];lines.append(f"| {row['id']} | {new['target_count']} | {old['true_count']} | {new['true_count']} | {hits(old)} | {hits(new)} | {c['true_count']} | {c['checked']}/{c['total']} |")
  else:lines.append(f"| {row['id']} | {row['initial_target_count']} | {old['true_count']} | ошибка | — | — | — | — |")
 lines+=['','## Формулировки','']
 for row in summary['table_rows']:
  lines+=['### '+row['id'],'','Исходный: '+row['question'],'','v1: '+prior[row['id']]['variants'][0]['question'],'','v2: '+(row['variants'][0]['question'] if row['variants'] else 'Генерация не завершена'),'']
 (OUT/'comparison.md').write_text('\n'.join(lines)+'\n')
 body='<h1>Описательное переформулирование: v1 и v2</h1><p>Одинаковые шесть исходных входов; изменён только промпт генератора. Все числа по исходному булеву судье.</p>'
 body+='<table><tr><th>Вопрос</th><th>v1</th><th>v2</th></tr>'
 for row in summary['table_rows']:
  a=prior[row['id']]['variants'][0];b=row['variants'][0] if row['variants'] else None
  def cell(v):
   if not v:return 'Генерация не завершена'
   c=v['controls'];ranktext='<br>'.join(m+': '+', '.join(map(str,v['ranks'][m].values())) for m in ('bm25','tfidf_lsa'))
   return '<p>'+html.escape(v['question'])+'</p><p>Прежних целей true: '+str(v['true_count'])+'/'+str(v['target_count'])+'</p><p>'+ranktext+'</p><p>Контроль: '+str(c['true_count'])+' новых true; '+str(c['checked'])+'/'+str(c['total'])+' проверено</p>'
  body+='<tr><td><b>'+row['id']+'</b><p>'+html.escape(row['question'])+'</p></td><td>'+cell(a)+'</td><td>'+cell(b)+'</td></tr>'
 (OUT/'comparison.html').write_text('<!doctype html><meta charset="utf-8"><title>Описательный промпт v1/v2</title><style>body{font:15px/1.5 system-ui;margin:24px;color:#17212b}table{border-collapse:collapse;width:100%;table-layout:fixed}td,th{border:1px solid #ccd4db;padding:14px;vertical-align:top;overflow-wrap:anywhere}th{background:#eaf2f7}p{margin:8px 0}</style>'+body+'</table>')

class Paired(engine.Batch):
 def execute(self):
  entries=self.m['entries'];old=engine.read_json(OUT/'original-search-feedback.json')
  with ThreadPoolExecutor(max_workers=3) as pool:entries=list(pool.map(lambda e:self.generate(e,old),entries))
  new=self.search_batch(entries,'rewritten_question','rewritten-search.json')
  with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(lambda e:self.evaluate(e,old,new),entries))
  summary={'status':'finished','finished_at':engine.now(),'http_attempts':self.journal.budget['http_attempts'],'table_rows':rows,
           'generated_descriptive':sum('rewritten_question' in e for e in entries),'paired_with':str(SOURCE.relative_to(ROOT))}
  engine.write_json(OUT/'summary.json',summary);report(summary)
  print(json.dumps({k:v for k,v in summary.items() if k!='table_rows'}),flush=True)

def run():
 engine.OUT=OUT
 with engine.exclusive_run(OUT):
  m=engine.read_json(OUT/'manifest.json')
  for p,h in m['files'].items():assert engine.digest(Path(p).read_bytes())==h,p
  assert engine.digest((OUT/'rewrite-prompt.md').read_bytes())==m['rewrite_sha256']
  assert engine.digest((OUT/'judge-prompt.md').read_bytes())==m['judge_sha256']
  engine.write_json(OUT/'started.json',{'pid':os.getpid(),'started_at':engine.now()})
  try:Paired(m).execute()
  except Exception as exc:
   engine.write_json(OUT/'failure.json',{'error_type':type(exc).__name__,'time':engine.now()});raise

if __name__=='__main__':{'prepare':prepare,'run':run}[sys.argv[1]]()
