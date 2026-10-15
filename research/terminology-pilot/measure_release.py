"""Apply the frozen query-only lexical rule to every released target pair.

No model API, reranking, target-dependent term selection, or random sampling.
Full-body scores exist only where a fetched and verified text exists. Unknown
bodies are null, not estimates extrapolated from the pilot.
"""
import gzip,hashlib,json,math,sys
from datetime import datetime,timezone
from collections import Counter,defaultdict
from pathlib import Path
from statistics import mean,median
from automatic_terms import extract
from measure_terms import ROOT,tokens,lemmas,lemma_word

OUT=ROOT/'release-run'
STRICT='body_no_references_no_related_work'
VIEWS=['title_abstract','body_no_references',STRICT]
def jl(path):return [json.loads(x) for x in path.read_text().splitlines() if x]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def stable(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def write(path,text):
    temporary=path.with_suffix(path.suffix+'.writing');temporary.write_text(text);temporary.replace(path)
def dump(path,rows):write(path,''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
def num(x):return '—' if x is None else f'{100*x:.1f}%'
def table(head,rows):
    def esc(x):return str(x).replace('|','\\|').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(head)+' |','|'+'---|'*len(head)]+['| '+' | '.join(map(esc,r))+' |' for r in rows])

def main():
    config=json.loads((ROOT/'automatic-term-config.v1.json').read_text());variant=config['selected_variant']
    Q=jl(OUT/'questions.jsonl');P=jl(OUT/'papers.jsonl');pby={p['paper_id']:p for p in P}
    pilotq={q['question_id'] for q in jl(ROOT/'questions.jsonl')}
    full={p['paper_id']:p for p in jl(ROOT/'fulltexts.jsonl')};rw={p['paper_id']:p for p in jl(ROOT/'related-work-splits.jsonl')}
    if (OUT/'fulltexts.jsonl').exists():full.update({p['paper_id']:p for p in jl(OUT/'fulltexts.jsonl')})
    collection=json.loads((OUT/'collection-progress.json').read_text()) if (OUT/'collection-progress.json').exists() else {'status':'not_started'}
    previous={};reused=0;recomputed=0
    if '--reuse-verified' in sys.argv:
        old=json.loads((OUT/'summary.json').read_text())
        for key,name in [('query_file_sha256','questions.jsonl'),('paper_file_sha256','papers.jsonl'),('metric_file_sha256','pair-metrics.jsonl')]:
            assert old[key]==sha(OUT/name),(key,'Cached input or metric file changed')
        assert old['normalization_config_sha256']==sha(ROOT/'metric-config.v1.json')
        assert old['automatic_terms_config_sha256']==sha(ROOT/'automatic-term-config.v1.json')
        locked=json.loads((OUT/'runner-code-lock.json').read_text())
        for name in ['automatic_terms.py','measure_terms.py','section_text.py','stopwords.v1.json','related-work-boundaries.v1.json','reference-boundaries.v1.json']:
            assert locked[name]==sha(ROOT/name),(name,'Metric or extraction rule changed')
        previous={(r['question_id'],r['paper_id']):r for r in jl(OUT/'pair-metrics.jsonl')}
    # Reuse precise pilot bibliography splits, including reviewed exceptions.
    refbounds=json.loads((ROOT/'reference-boundaries.v1.json').read_text())
    from measure_terms import split_references
    terms={};features={};termsrows=[]
    for q in Q:
        spans=extract(q['text'],variant);words=sorted({w for s in spans for w in tokens(s['text'],query=True)})
        phrases=[tokens(s['text'],query=True) for s in spans];allwords=sorted(set(tokens(q['text'],query=True)))
        assert all(q['text'][s['start']:s['end']]==s['text'] for s in spans)
        terms[q['question_id']]=spans
        features[q['question_id']]={'words':words,'phrases':phrases,'allwords':allwords}
        termsrows.append({'question_id':q['question_id'],'spans':spans,'words':words,'word_count':len(words),'empty':not words,'calibration_question':q['question_id'] in pilotq})
    dump(OUT/'query-terms.jsonl',termsrows)
    reverse=defaultdict(list)
    for q in Q:
        for pid in q['gold_paper_ids']:reverse[pid].append(q)
    results=[]
    def measure(text,feat,reason=None):
        words=feat['words']
        if text is None or not words:return {'status':'missing_text' if text is None else 'empty_query_vocabulary','reason':reason or 'No automatically extracted noun phrase','word_coverage':None,'word_gap':None,'exact_coverage':None,'phrase_coverage':None,'content_word_coverage':None}
        dt=tokens(text);ds=set(dt);dl=set(lemmas(dt));joined=' '+' '.join(lemmas(dt))+' '
        found=[w for w in words if lemma_word(w) in dl];missing=[w for w in words if lemma_word(w) not in dl]
        assert not set(found)&set(missing) and set(found)|set(missing)==set(words)
        phrasehits=[(' '+' '.join(lemmas(p))+' ') in joined for p in feat['phrases']]
        coverage=len(found)/len(words)
        return {'status':'ok','word_coverage':coverage,'word_gap':1-coverage,'exact_coverage':sum(w in ds for w in words)/len(words),
                'phrase_coverage':sum(phrasehits)/len(phrasehits) if phrasehits else None,
                'content_word_coverage':sum(lemma_word(w) in dl for w in feat['allwords'])/len(feat['allwords']) if feat['allwords'] else None,
                'query_word_count':len(words),'found_words':found,'missing_words':missing,'whole_phrase_hits':phrasehits}
    metric_temp=OUT/'pair-metrics.jsonl.writing';out=metric_temp.open('w')
    for index,p in enumerate(P):
        pid=p['paper_id'];ta=p['title']+'\n'+p['abstract'] if p.get('title') and p.get('abstract') else None
        views={'title_abstract':ta,'body_no_references':None,STRICT:None};f=full.get(pid)
        if f and f.get('body_bundle_path') and f['status']=='ready':
            path=ROOT/f['body_bundle_path'];assert sha(path)==f['body_bundle_sha256']
            with gzip.open(path,'rt') as gz:content=json.load(gz)
            prefix=(ta or p.get('title') or '')+'\n'
            views['body_no_references']=prefix+content['body_no_references']
            if content[STRICT] is not None:views[STRICT]=prefix+content[STRICT]
        elif f and f['status']=='ready':
            prefix=(ta or p.get('title') or '')+'\n';raw=(ROOT/f['text_path']).read_text()
            if pid in refbounds:
                b=refbounds[pid];assert b['text_sha256']==f['text_sha256'];ranges=b.get('reference_ranges',[[b.get('reference_start'),b.get('reference_end')]])
                parts=[];last=0
                for a,z in ranges:parts.append(raw[last:a]);last=z
                parts.append(raw[last:]);body='\n'.join(parts)
            elif f.get('format')=='html':body=(ROOT/f['body_path']).read_text()
            else:body,_,_=split_references(raw)
            if body is not None:views['body_no_references']=prefix+body
            info=rw[pid]
            if info.get('text_path'):
                assert sha(ROOT/info['text_path'])==info['text_sha256'];views[STRICT]=prefix+(ROOT/info['text_path']).read_text()
        for q in reverse[pid]:
            qid=q['question_id'];feat=features[qid]
            row={'question_id':qid,'paper_id':pid,'benchmark':q['benchmark'],'task_type':q['original_record'].get('type'),'calibration_question':qid in pilotq,'metadata_identity_flag':bool(p.get('metadata_notes')),'views':{}}
            for v in VIEWS:
                reason='Title or abstract unavailable' if v=='title_abstract' else ('Full text was not fetched for this target' if not f else (rw.get(pid,{}).get('reason') or f.get('reason') or 'Section extraction unavailable'))
                inputhash=stable({'spans':terms[qid],'text':views[v]})
                cached=previous.get((qid,pid),{}).get('views',{}).get(v)
                if cached and cached['input_sha256']==inputhash:
                    value=dict(cached);reused+=1
                else:
                    value=measure(views[v],feat,reason);recomputed+=1
                value['input_sha256']=inputhash;row['views'][v]=value
            values=[row['views'][v]['word_coverage'] for v in ['title_abstract',STRICT,'body_no_references']]
            if all(x is not None for x in values):assert values[0]<=values[1]+1e-12<=values[2]+2e-12,(qid,pid)
            out.write(json.dumps(row,ensure_ascii=False)+'\n');results.append(row)
        if index%5000==0:print('articles',index,'pairs',len(results),flush=True)
    out.close()
    assert len(results)==sum(len(q['gold_paper_ids']) for q in Q)
    assert len({(r['question_id'],r['paper_id']) for r in results})==len(results)
    metric_temp.replace(OUT/'pair-metrics.jsonl')
    def macro(rows,view,key='word_coverage'):
        byq=defaultdict(list)
        for r in rows:
            val=r['views'][view].get(key)
            if val is not None:byq[r['question_id']].append(val)
        return mean(mean(v) for v in byq.values()) if byq else None
    def group(r):return r['benchmark']+(':'+r['task_type'] if r['benchmark']=='autoresearchbench' else '')
    groups=[('scholarquest','ScholarQuest'),('autoresearchbench:deep','AutoResearchBench Deep'),('autoresearchbench:wide','AutoResearchBench Wide'),('paperpilot','PaperPilot')]
    qresults=[]
    for q in Q:
        rows=[r for r in results if r['question_id']==q['question_id']]
        qresults.append({'question_id':q['question_id'],'benchmark':q['benchmark'],'gold_targets':len(rows),'calibration_question':q['question_id'] in pilotq,
                         'views':{v:{'available_pairs':sum(r['views'][v]['status']=='ok' for r in rows),'mean_word_coverage':macro(rows,v),'mean_word_gap':macro(rows,v,'word_gap'),'mean_phrase_coverage':macro(rows,v,'phrase_coverage')} for v in VIEWS}})
    dump(OUT/'question-metrics.jsonl',qresults)
    remaining=[r for r in results if not r['calibration_question']];available=[r for r in remaining if r['views']['title_abstract']['status']=='ok']
    common=[r for r in remaining if all(r['views'][v]['status']=='ok' for v in VIEWS)]
    summary={'run_id':'terminology-release-v1-2026-10-12','questions':len(Q),'remaining_questions':len(Q)-len(pilotq),'pairs':len(results),'remaining_pairs':len(remaining),
             'computed_at_utc':datetime.now(timezone.utc).isoformat(),
             'unique_target_records':len(P),'metadata_status_counts':dict(Counter(p['metadata_status'] for p in P)),
             'remaining_available_TA_pairs':len(available),'remaining_common_body_pairs':len(common),
             'algorithm':'query-only POS noun phrases -> unique original words -> unique-analysis WordNet noun normalization -> query word coverage; gap = 1 - coverage',
             'normalization_config_sha256':sha(ROOT/'metric-config.v1.json'),'automatic_terms_config_sha256':sha(ROOT/'automatic-term-config.v1.json'),
             'source_inventory_sha256':sha(OUT/'inventory.json'),'query_file_sha256':sha(OUT/'questions.jsonl'),'paper_file_sha256':sha(OUT/'papers.jsonl'),
             'metric_file_sha256':sha(OUT/'pair-metrics.jsonl'),'query_terms_file_sha256':sha(OUT/'query-terms.jsonl'),'question_metrics_file_sha256':sha(OUT/'question-metrics.jsonl'),
             'remaining_TA_word_coverage':macro(remaining,'title_abstract'),'remaining_TA_phrase_coverage':macro(remaining,'title_abstract','phrase_coverage'),
             'remaining_TA_word_gap':macro(remaining,'title_abstract','word_gap'),'status':'completed_on_available_inputs',
             'full_body_coverage':'Successfully collected texts only; missing full texts are null, not zero.',
             'body_collection_status':collection['status'],'body_inventory_counts':dict(Counter(f['status'] for f in full.values())),
             'human_validated_metric_winner':False,'paid_model_calls':0,'empty_vocabulary_questions':sum(x['empty'] for x in termsrows),
             'reused_identical_input_views':reused,'recomputed_views':recomputed}
    write(OUT/'summary.json',json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    flagged=[r for r in available if r['metadata_identity_flag']]
    unflagged=[r for r in available if not r['metadata_identity_flag']]
    blocks=['# Массовое сравнение словаря вопросов и целевых статей',
      f'Алгоритм применён ко всем **{len(Q)} вопросам и {len(results):,} парам** из тех же зафиксированных релизов. '
      f'Основная таблица ниже исключает 30 вопросов настройки: остаются **{len(Q)-len(pilotq)} вопросов / {len(remaining):,} пар**. '
      'Новые вопросы не отбирались по удобству или результату. У 60 исходных строк AutoResearchBench нет ID ответа, поэтому они не образуют пары. Crase не подменяется другим набором. '
      'PaperPilot — доступный 50-строчный CSV, соответствие каноническому тесту не подтверждено.',
      f'**Охват текущего снимка:** значения по заголовкам и аннотациям получены для {len(available):,} из {len(remaining):,} пар оставшихся вопросов. '+
      ('Сбор остановлен по просьбе пользователя ограничить длительность эксперимента. Срез зафиксирован в `frozen-slice.json`; автоматического возобновления нет. '
       if collection['status']=='frozen_time_limited' else 'Недостающие метаданные и полные тексты стоят в возобновляемом сборе; API arXiv возвращал HTTP 429. ')+
      'Ниже приведены результаты по фактически доступным данным, а не вымышленные значения для всего релиза. '
      'Текущее состояние фонового процесса записывается в `driver-progress.json`, состояние текстов — в `collection-progress.json`.',
      '## Зафиксированный алгоритм',
      '1. Выделить именные группы с определениями фиксированным POS-теггером NLTK, используя только запрос. Удалить служебные слова и фиксированную оболочку поиска.\n'
      '2. Взять разные исходные слова этих групп; нормализовать существительные только при единственном словарном анализе WordNet.\n'
      '3. Посчитать долю слов, найденных в статье. **Лексическое расхождение = 100% − найденная доля.**\n'
      '4. Отдельно сохранить точное покрытие без нормализации, совпадение групп целиком и контроль по всем содержательным словам.',
      'Этот алгоритм не использует генеративную модель, платные токены или подстройку терминов под целевую статью. '
      'Отбор именных групп согласован с пилотным словарём лучше двух проверенных альтернатив, но пилотный словарь не является независимой экспертной разметкой. '
      'Совпадение измеряет написанный словарь, а не смысловую эквивалентность и не успешность поиска. Отрицательные темы сохраняются как упомянутая лексика; проверка отрицательных требований здесь не проводится. '
      '**Известное ограничение автоматического отбора:** слово `using` может попасть в термин, а отдельные выражения — склеиться в одну группу. '
      'В этом срезе правило сохранено; показатели предварительные, объективность оценки терминологического разрыва не установлена.',
      '## Результат по заголовкам и аннотациям на оставшихся вопросах',
      'Усреднение: сначала по доступным целям вопроса, затем по вопросам. Пропущенные пары не считаются нулём. '
      'У каждого набора указано, сколько данных действительно вошло в оценку.',
      table(['Набор','Вопросов с оценкой / всего','Пар с оценкой / всего','Совпадение слов','Расхождение слов','Группы целиком'],
        [[name,f"{len({r['question_id'] for r in rows if r['views']['title_abstract']['status']=='ok'})} / {len({r['question_id'] for r in rows})}",
          f"{sum(r['views']['title_abstract']['status']=='ok' for r in rows)} / {len(rows)}",num(macro(rows,'title_abstract')),num(macro(rows,'title_abstract','word_gap')),num(macro(rows,'title_abstract','phrase_coverage'))]
         for key,name in groups for rows in [[r for r in remaining if group(r)==key]]]),
      '## Проверка расхождений названий',
      f'У {len(flagged)} доступных пар есть флаг расхождения названия из релиза и названия по ID. Это не доказанные ошибки ID: возможны сокращения или смена версии. Исходные цели сохранены, ниже показана проверка без флагов.',
      table(['Оставшиеся вопросы: заголовок + аннотация','Пар','Совпадение слов'],[['Все доступные пары',len(available),num(macro(available,'title_abstract'))],['Без флагов расхождения названий',len(unflagged),num(macro(unflagged,'title_abstract'))]]),
      '## Что получилось сравнить по полному тексту',
      f'Надёжно очищенный полный текст сейчас имеется для {len(common)} пар оставшихся вопросов. '
      f'Состояние сбора: `{collection["status"]}`. Использованы уже собранные статьи пилота и успешно полученные новые тексты. '
      'Это **доступное подмножество, а не полная полнотекстовая выборка релизов**. '
      'Тексты остальных целей ещё не загружены или недоступны; их показатели записаны как пропуски. На подмножестве, определяемом доступностью источников, нельзя делать вывод о полном бенчмарке.',
      table(['Одинаковые доступные пары','Пар','Совпадение слов','Расхождение слов','Группы целиком'],
        [[{'title_abstract':'Заголовок + аннотация','body_no_references':'Без библиографии',STRICT:'Без библиографии и явно выделенного Related Work'}[v],len(common),num(macro(common,v)),num(macro(common,v,'word_gap')),num(macro(common,v,'phrase_coverage'))] for v in VIEWS]),
      '## Проверки и файлы',
      'Проверены: все ID пар, отсутствие дубликатов, границы автоматически выделенных выражений в исходном вопросе, диапазоны значений, фиксированные знаменатели и вложенность доступных текстовых представлений. '
      'Во всех строках сохраняются исходные найденные и отсутствующие слова; пропуск сопровождается причиной.',
      '- `questions.jsonl` — оригинальные вопросы и полный список опубликованных целей.\n'
      '- `query-terms.jsonl` — автоматические выражения и их точные границы.\n'
      '- `pair-metrics.jsonl` — все пары, три представления, показатели и найденные/отсутствующие слова.\n'
      '- `question-metrics.jsonl` — сводка по каждому вопросу.\n'
      '- [Все исходные вопросы, автоматически выделенные выражения и показатели](question-results.md).\n'
      '- `summary.json`, `inventory.json` — охват, источники, хеши и ограничения.\n'
      '- `excluded-questions.jsonl` — исходные вопросы без целевого ID, сохранённые с причиной.\n'
      '- `papers.jsonl` и `cache/` — локальные метаданные и ответы источников; крупные входные данные исключены из Git.',
      '[Пилот: полная сетка правил и частей текста](../metric-comparison.md).']
    write(OUT/'report.md','\n\n'.join(blocks)+'\n')
    details=['# Все вопросы массового прогона','[Сводный отчёт и определения](report.md). В каждой строке указано число доступных целей. '
             'Подмножества целей разных представлений могут различаться; разность таких средних не считается эффектом удаления разделов. '
             'В сводном отчёте полнотекстовые сравнения выполняются только на одинаковых парах.']
    qrby={x['question_id']:x for x in qresults}
    for q in Q:
        qid=q['question_id'];qr=qrby[qid]
        details += ['## '+qid+(' — вопрос настройки' if qid in pilotq else ''),
                    '\n'.join('> '+line for line in q['text'].splitlines()),
                    '**Автоматические именные группы:** '+'; '.join(s['text'] for s in terms[qid])+'.',
                    table(['Часть статьи','Доступных целей / всех','Совпадение слов','Расхождение слов','Группы целиком'],[
                       [{'title_abstract':'Заголовок + аннотация','body_no_references':'Без библиографии',STRICT:'Без библиографии и Related Work'}[v],
                        f"{qr['views'][v]['available_pairs']} / {qr['gold_targets']}",num(qr['views'][v]['mean_word_coverage']),num(qr['views'][v]['mean_word_gap']),num(qr['views'][v]['mean_phrase_coverage'])] for v in VIEWS])]
    write(OUT/'question-results.md','\n\n'.join(details)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
