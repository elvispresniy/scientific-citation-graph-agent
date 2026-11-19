"""Read-only aggregation of question status; no inference or relabeling."""
from pathlib import Path
import json, html, hashlib
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'research/factory-e2e'
OUT=BASE/'question-status-20261115'
NIGHT=BASE/'night-20'

def read(p):return json.loads(p.read_text())
def esc(s):return html.escape(str(s))
def ranks(methods,ids):
 return {m:{pid:v['target_ranks'][pid] for pid in sorted(ids)} for m,v in methods.items()}
def rank_state(methods,ids):
 if not ids:return 'Нет подтверждённых целей; требуется разбор'
 pairs=[min(methods[m]['target_ranks'][pid] for m in ('bm25','tfidf_lsa')) for pid in ids]
 if all(r>20 for r in pairs):return 'Перспективный по рангам: все прежние цели вне top-20 обоих методов; не принят окончательно'
 if all(r<=20 for r in pairs):return 'Все прежние цели доступны в объединённом top-20; кандидат на переформулирование'
 return 'Смешанный случай: часть прежних целей в top-20, часть вне; решение открыто'
def controls(q,fresh=None):
 targets=set(q['targets']);pool={x['paper_id'] for m in q['methods'].values() for x in m['top_20']}-targets
 known={v['paper_id']:v['verdict'] for v in q.get('verdicts',[]) if v.get('status')=='completed'}
 if fresh is not None:
  for v in fresh:
   if v['status']=='completed':known[v['paper_id']]=v['verdict']
 checked=pool&known.keys();yes=sorted(pid for pid in checked if known[pid] is True)
 return {'true_count':len(yes),'true_ids':yes,'checked':len(checked),'total':len(pool),'complete':len(checked)==len(pool)}

OUT.mkdir(exist_ok=True)
source=read(NIGHT/'summary.json')['questions']
rewrite=read(BASE/'review-20261115/rewrite-judge-v1/summary.json')['rows']
fresh=read(BASE/'same-prompt-top20-20261115/summary.json')['results']
rows=[]
for n,q in enumerate(source,1):
 variants=[]
 for v in rewrite:
  if v['question_number']!=n or v['variant']!='conceptual':continue
  preserved=v['all_old_targets_true'] is True
  distant=preserved and all(v['methods'][m]['target_ranks'][pid]>20 for m in ('bm25','tfidf_lsa') for pid in v['frozen_old_targets'])
  state=('Перспективная переформулировка: все прежние цели true и вне top-20 обоих методов' if distant else
         'Прежние цели сохранены, но остаются ответы в top-20' if preserved else 'Неуспешная переформулировка: не все прежние цели сохранили true')
  variants.append({'variant':v['variant'],'question':v['question'],'state':state,'true_count':len(v['true_ids']),
                   'false_ids':v['false_ids'],'errors':len(v['errors']),'target_count':len(v['frozen_old_targets']),
                   'all_old_targets_true':preserved,'ranks':ranks(v['methods'],v['frozen_old_targets']),
                   'controls':{'status':'not_checked','true_count':None}})
 c=controls(q,[v for v in fresh if v['question_number']==n])
 state=rank_state(q['methods'],q['targets'])
 if variants:state='Есть переформулировки; '+str(sum(v['all_old_targets_true'] for v in variants))+'/'+str(len(variants))+' сохранили все прежние цели. '+state
 if c['true_count']>=3:state+='; исходная версия отклоняется: >=3 новых true'
 rows.append({'id':f'N{n:02d}','section':'Ночная серия — 27 вопросов с завершённым судьёй','question':q['question'],
              'state':state,'initial_target_count':len(q['targets']),'initial_target_ids':q['targets'],
              'ranks':ranks(q['methods'],q['targets']),'variants':variants,'original_controls':c,
              'source':str((NIGHT/q['artifact']).relative_to(ROOT))})
# Include generated questions whose judge pass failed; do not invent a complete target set.
done={q['artifact'] for q in source};pending=0
for f in sorted(NIGHT.glob('seeds/*/groups/*/compose/completed.json')):
 for number,q in enumerate(read(f)['value']['questions'],1):
  d=f.parent.parent/f'question-{number:03d}';rel=str(d.relative_to(NIGHT))
  if rel in done:continue
  pending+=1;partials=[]
  for p in sorted(d.glob('attempt-*/partial-verdicts.json')):partials=read(p)['verdicts']
  comp=q['answer_paper_ids'];saved=read(d/'search/completed.json')['value'];mr={}
  for m,v in saved.items():
   byid={pid:i+1 for i,pid in enumerate(v['ranked_ids'])};mr[m]={'target_ranks':{pid:byid[pid] for pid in comp}}
  trueids=[v['paper_id'] for v in partials if v.get('verdict') is True]
  rows.append({'id':f'U{pending:02d}','section':'Ночная серия — незавершённые проверки','question':q['question'],
   'state':'Проверка судьи не завершена; полный исходный набор целей не установлен',
   'initial_target_count':None,'composer_target_count':len(comp),'initial_target_ids':[],
   'partial_true_count':len(trueids),'ranks':ranks(mr,comp),'rank_note':'Ранги кандидатов композитора, не окончательных целей судьи',
   'variants':[],'original_controls':{'status':'unresolved_target_set'},'source':str(d.relative_to(ROOT))})
# Earlier completed pilot: use its original judge targets, not composer suggestions.
pilot=ROOT/'research/factory-query-iterations'
search=read(pilot/'direct-search-v1/results.json')['questions'];judge=read(pilot/'judge-subgraph-v1/summary.json')['results']
for n,q in enumerate(search,1):
 verdicts=[v for v in judge if v['group']==q['group'] and v['question_number']==q['question_number']]
 qq={**q,'verdicts':verdicts}; c=controls(qq)
 rows.append({'id':f'P{n:02d}','section':'Ранний pilot-v1 — 5 вопросов','question':q['question'],
              'state':rank_state(q['methods'],q['targets']),'initial_target_count':len(q['targets']),
              'initial_target_ids':q['targets'],'ranks':ranks(q['methods'],q['targets']),'variants':[],
              'original_controls':c,'source':f'research/factory-query-iterations/pilot-v1/{q["group"]}/questions.json'})

# A new completed batch overrides active versions; prior experiments remain in history.
full_batch=BASE/'full-descriptive-20261115/summary.json'
if full_batch.exists():
 batch=read(full_batch)
 if batch.get('status')=='finished':
  replacements={r['id']:r for r in batch['table_rows']}
  rows=[replacements.get(r['id'],r) for r in rows]

labels={'descriptive_generated':'Описательная','short_explicit':'Короткая с терминами','conceptual':'Описательная','descriptive_conditions_retained':'Описательная с подробными условиями'}
def control_text(c):
 if c.get('status')=='unresolved_target_set':return 'Не определено: набор целей судьи не завершён'
 if c.get('status')=='not_checked':return 'Не проверено'
 if c['complete']:return f"{c['true_count']} новых true; проверено {c['checked']}/{c['total']}"
 return f"Пока найдено {c['true_count']} true; проверено {c['checked']}/{c['total']}. Остальные не проверены"
def rank_html(r):
 return '<br>'.join('<b>'+('BM25' if m=='bm25' else 'TF-IDF + LSA')+':</b> '+('; '.join(f'<span title="{esc(pid)}">{rank}</span>' for pid,rank in vals.items()) or '—') for m,vals in r.items())
def cells(row):
 variants=row['variants'];n=row['initial_target_count']
 target=str(n) if n is not None else 'Не установлен<br>Композитор предложил '+str(row['composer_target_count'])+'; частичных true: '+str(row['partial_true_count'])
 rankcell='<b>До переформулирования</b><br>'+rank_html(row['ranks'])
 if row.get('rank_note'):rankcell='<em>'+esc(row['rank_note'])+'</em><br>'+rankcell
 if row['initial_target_ids']:rankcell+='<details><summary>Порядок статей для рангов</summary>'+ '<br>'.join(esc(pid) for pid in sorted(row['initial_target_ids']))+'</details>'
 rewritten=[];passing=[];controls_cell=[];states=[]
 for v in variants:
  label=labels[v['variant']]
  rewritten.append('<b>'+label+'</b><p>'+esc(v['question'])+'</p>')
  passing.append('<b>Прежние цели:</b> '+f"{v['true_count']} из {v['target_count']} получили true; false: {len(v['false_ids'])}; ошибок: {v['errors']}")
  states.append('<b>'+label+':</b> '+esc(v['state']))
  rankcell+='<hr><b>После переформулирования</b><br>'+rank_html(v['ranks'])
  if v.get('unchanged'):rewritten.append('<em>Генератор оставил исходный вопрос без изменения.</em>')
  controls_cell.append('<b>Старая + новая выдача:</b> '+esc(control_text(v['controls'])))
  c=v['controls']
  if c.get('complete') is False and 'total' in c:controls_cell.append('<strong class=warning>Незавершённых проверок: '+str(c['total']-c['checked'])+'. Это не false.</strong>')
  if c.get('true_ids'):controls_cell.append('<details><summary>Статьи с дополнительным true</summary>'+'<br>'.join(esc(pid) for pid in c['true_ids'])+'</details>')
  if v['controls'].get('breakdown'):
   names={'old':'В старом top-20','new':'В новом top-20','old_only':'Только в старом','new_only':'Только в новом','both':'В обоих'}
   controls_cell.append('<div class=breakdown>'+ '<br>'.join('<b>'+names[k]+':</b> '+esc(control_text(c)) for k,c in v['controls']['breakdown'].items())+'</div>')
 if variants:
  controls_cell.append('<details><summary>Справочно: исходный вопрос</summary>'+esc(control_text(row['original_controls']))+'</details>')
 else:controls_cell=[esc(control_text(row['original_controls']))]
 return [f'<b>{row["id"]}</b><p>{esc(row["question"])}</p>',esc(row['state'])+('<hr><p>'+'</p><p>'.join(states)+'</p>' if states else ''),target,rankcell,'<hr>'.join(rewritten) or 'Не проводилось','<br><br>'.join(passing) or 'Не применимо','<br><br>'.join(controls_cell)]
headers=['Вопрос','Класс состояния (предварительный)','Количество целевых статей изначально','Места в поиске — исходные и после переформулирования','Вопрос после переформулирования','Сколько исходных статей всё ещё проходит','Сколько нецелевых статей из top-20 проходит судью']
intro='''<h1>Статус всех сохранённых вопросов — 16 ноября 2026</h1>
<p>27 завершённых вопросов night-20 (N01–N27), 4 первоначально незавершённых вопроса той же серии (U01–U04), 5 вопросов раннего pilot-v1 (P01–P05). Всего 36 исходных вопросов; у 6 ночных вопросов есть 14 переформулировок. Нумерация N совпадает с прежней таблицей 27 вопросов.</p>
<p><b>Изначальные цели</b> — статьи, получившие true у исходного булева судьи до переформулирования; не список предложений композитора. Прежние цели фиксированы: новые true не добавлены автоматически. Для вопросов, оставшихся незавершёнными, окончательное число целей неизвестно.</p>
<p><b>Проверка top-20</b> — объединение BM25 и TF-IDF+LSA, без дубликатов и без прежних целей. Использован только исходный судья true/false, без A/B-аудита. Для 6 исходных вопросов есть свежий полный прогон 178 контрольных пар; для остальных указана фактическая неполная проверка ночного/раннего судьи. Для переформулировок новые top-20 ещё не проверялись. «Не проверено» не равно нулю.</p>
<p>Граница приемлемой сложности остаётся открытой. «Вне top-20» здесь описывает измеренные ранги, а не является новым утверждённым фильтром. Классы состояния предварительные. Рабочее правило: ≥3 новых true отклоняют формулировку; для 1–2 решение открыто. Ноль сам по себе не означает принятие. Ошибки не являются false.</p>
<p>Ранги перечислены в одинаковом порядке ID статей для обоих методов; ID виден при наведении и в раскрывающемся списке. Ранги переформулировок относятся ко всем прежним целям, включая получившие false. Варианты и их проверки не смешиваются.</p>'''
variant_count=sum(len(r['variants']) for r in rows)
rewritten_count=sum(bool(r['variants']) for r in rows)
intro=intro.replace('у 6 ночных вопросов есть 14 переформулировок',f'у {rewritten_count} вопросов есть {variant_count} выбранных описательных версий')
if full_batch.exists() and read(full_batch).get('status')=='finished':
 intro=intro.replace('Для переформулировок новые top-20 ещё не проверялись.', 'Для описательных версий проверялось объединение старого и нового top-20 обоих методов; фактическое покрытие и ошибки указаны в строках.')
 intro+='<p>Текущие описательные версии получены новым промптом в full-descriptive-20261115. Сравнительные короткие варианты и прежние описательные эксперименты сохранены в истории, но не показаны как активные альтернативы. U01–U04 сохраняют исходные ID; результат восстановления указан в их строках.</p>'
if full_batch.exists() and batch.get('status')=='finished':
 variants=[v for r in rows for v in r['variants']]
 preserved=[v for v in variants if v['all_old_targets_true']]
 clean=[v for v in preserved if v['controls']['complete'] and v['controls']['true_count']==0]
 incomplete=[v for v in variants if not v['controls']['complete']]
 checked=sum(v['controls']['checked'] for v in variants);total=sum(v['controls']['total'] for v in variants)
 finished=datetime.fromisoformat(batch['finished_at']).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M МСК')
 cards=[(str(len(variants)),'описательных версий'),(str(len(preserved)),'сохранили все прежние цели'),(str(len(clean)),'сохранили цели и полный контроль без новых true'),(str(len(incomplete)),'с неполным контролем'),(f'{checked}/{total}','контрольных пар проверено'),(str(batch['http_attempts']),'HTTP-попыток')]
 intro=intro.replace('<h1>Статус всех сохранённых вопросов — 16 ноября 2026</h1>','')
 intro='<h1>Статус вопросов — результаты описательного прогона</h1><p><b>Прогон завершён: '+finished+'.</b> Таблица содержит итоговые данные, включая ошибки незавершённых проверок.</p><div class=metrics>'+''.join('<div><strong>'+v+'</strong><span>'+label+'</span></div>' for v,label in cards)+'</div>'+intro
 intro+='<p><b>Как читать результаты:</b> сохранение целей и ноль новых true ещё не означают принятую трудную задачу. Ранги до и после показаны прямо в строке. Числа старой и новой выдач пересекаются — их нельзя складывать. «2 из 2 true» означает два отдельных булевых ответа судьи, а не новый формат его ответа. Три U-вопроса без завершённого исходного судьи остаются явно отмеченными.</p>'
 comparisons=[]
 for method,label in [('bm25','BM25'),('tfidf_lsa','TF-IDF + LSA')]:
  subset=[(r,v) for r in rows for v in r['variants'] if v['all_old_targets_true']]
  denominator=sum(v['target_count'] for r,v in subset)
  before=sum(sum(rank<=20 for rank in r['ranks'][method].values()) for r,v in subset)
  after=sum(sum(rank<=20 for rank in v['ranks'][method].values()) for r,v in subset)
  comparisons.append(label+': '+str(before)+'/'+str(denominator)+' → '+str(after)+'/'+str(denominator))
 intro+='<p><b>Цели в top-20 до → после</b> на одинаковых целевых наборах сохранивших все цели вопросов: '+'; '.join(comparisons)+'.</p>'
 intro=intro.replace('Для 6 исходных вопросов есть свежий полный прогон 178 контрольных пар; для остальных указана фактическая неполная проверка ночного/раннего судьи.', 'Данные дополнены расширенным прогоном: полнота контроля и число дополнительных true указаны отдельно для каждой формулировки.')
sections=[]
for section in dict.fromkeys(r['section'] for r in rows):
 body=''.join('<tr>'+''.join('<td>'+cell+'</td>' for cell in cells(r))+'</tr>' for r in rows if r['section']==section)
 sections.append('<h2>'+esc(section)+'</h2><div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+body+'</tbody></table></div>')
page='<!doctype html><html lang="ru"><meta charset="utf-8"><title>Статус вопросов</title><style>body{font:15px/1.5 system-ui;margin:24px;color:#17212b;background:#fafafa}p{max-width:1200px}.metrics{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.metrics div{padding:12px 16px;background:#eef4f8;border:1px solid #cddce7;max-width:220px}.metrics strong{display:block;font-size:25px}.metrics span{display:block}.warning{color:#9b4415;display:block}.breakdown{border-left:3px solid #cddce7;padding:8px;margin:8px 0;font-size:13px}.scroll{overflow:auto;max-height:85vh;border:1px solid #ccd2d8}table{border-collapse:collapse;background:white;table-layout:fixed;width:2700px}th,td{border:1px solid #d9dfe4;padding:12px;vertical-align:top;overflow-wrap:anywhere}th{position:sticky;top:0;background:#e9f0f5;z-index:2}th:nth-child(1){width:470px}th:nth-child(2){width:300px}th:nth-child(3){width:120px}th:nth-child(4){width:330px}th:nth-child(5){width:620px}th:nth-child(6){width:220px}th:nth-child(7){width:330px}tr:nth-child(even){background:#f6f9fb}summary{cursor:pointer;color:#165c87}details{margin-top:10px}hr{border:0;border-top:1px solid #ddd}td p{margin:8px 0}</style>'+intro+''.join(sections)+'</html>'
(OUT/'questions-status.html').write_text(page)
# Markdown keeps the same seven columns and full English texts.
md=['# Статус вопросов','', f'36 исходных вопросов; {variant_count} выбранных описательных версий. Все числа из исходного булева судьи; A/B не использованы.','', 'Начальные цели — после исходного судьи. Статусы по рангам предварительные; граница принятия не определена. Фактическое покрытие проверки старой и новой выдач указано по строкам.','']
for section in dict.fromkeys(r['section'] for r in rows):
 md+=['## '+section,'','| '+' | '.join(headers)+' |','|'+'---|'*7]
 for r in rows:
  if r['section']!=section:continue
  cc=cells(r)
  import re
  cc=[html.unescape(re.sub('<[^>]+>',' ',c)).replace('|','\\|').replace('\n',' ') for c in cc]
  md.append('| '+' | '.join(cc)+' |')
 md.append('')
(OUT/'questions-status.md').write_text('\n'.join(md)+'\n')
(OUT/'questions-status.json').write_text(json.dumps({'date':'2026-11-16','scope':dict(Counter(r['section'] for r in rows)),'rows':rows},ensure_ascii=False,indent=2)+'\n')
assert len(rows)==36 and all(len(r['variants'])<=1 for r in rows)
assert sum(r['initial_target_count'] for r in rows if r['id'].startswith('N'))==59
assert all(v['variant'] in ('conceptual','descriptive_generated') for r in rows for v in r['variants'])
print(json.dumps({'questions':len(rows),'night_completed':27,'night_incomplete':4,'early_pilot':5,'rewrite_variants':variant_count,'full_original_top20_controls':[r['id'] for r in rows if r['original_controls'].get('complete')], 'output':str(OUT)},ensure_ascii=False))
