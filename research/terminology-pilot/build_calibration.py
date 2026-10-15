"""Materialize LLM-reviewed decisions with exact Unicode offsets; no model calls."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read_jsonl(name):
    return [json.loads(line) for line in (ROOT / name).read_text().splitlines() if line]

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def span(text, snippet):
    start = text.find(snippet)
    if start < 0:
        raise ValueError(f"Evidence absent from source: {snippet!r}")
    return {"text": snippet, "start": start, "end": start + len(snippet)}

questions = {x['question_id']: x for x in read_jsonl('questions.jsonl')}
papers = {x['paper_id']: x for x in read_jsonl('papers.jsonl')}
concepts = json.loads((ROOT / 'query-concepts.v1.json').read_text())
decisions = json.loads((ROOT / 'calibration-decisions.v1.json').read_text())
selection = json.loads((ROOT / 'calibration-pairs.json').read_text())
# Explicit query-only kinds; no decisions based on a target's vocabulary.
kinds = {
 'scholarquest:BQ_000320': ['term','constraint'],
 'scholarquest:BQ_000598': ['term','named_entity'],
 'scholarquest:BQ_001612': ['term','constraint'],
 'scholarquest:BQ_002222': ['term','named_entity'],
 'scholarquest:BQ_000223': ['term','term','constraint','term'],
 'autoresearchbench:row_000412': ['constraint','constraint','term','term','constraint','term','number','phrase','constraint'],
 'autoresearchbench:row_000236': ['constraint','term','term','phrase','term','term','term','constraint','constraint'],
 'autoresearchbench:row_000222': ['constraint','term','constraint','term','constraint','term','constraint','term','constraint'],
 'autoresearchbench:row_000672': ['constraint','term','term','term','term','term','term','constraint','constraint','constraint'],
 'autoresearchbench:row_000794': ['constraint','term','constraint','term','constraint','constraint','constraint','named_entity','named_entity','term'],
 'autoresearchbench:row_000251': ['constraint','constraint','term','term','constraint','term','constraint','constraint','term','number'],
 'autoresearchbench:row_000415': ['term','term','constraint','constraint','term','phrase','term','constraint','constraint','constraint','constraint','constraint'],
 'autoresearchbench:row_000904': ['constraint','term','term','term','term','constraint','term','constraint'],
 'autoresearchbench:row_000878': ['constraint','term','term','term','term','constraint','term','term','term','constraint'],
 'autoresearchbench:row_000611': ['term','constraint','term','term','constraint','term','term','constraint','constraint'],
 'paperpilot:case_035': ['constraint','term'],
 'paperpilot:case_039': ['constraint','term','constraint'],
 'paperpilot:case_037': ['constraint','term','term','named_entity'],
 'paperpilot:case_004': ['term','term','constraint'],
 'paperpilot:case_042': ['term','constraint'],
 'paperpilot:case_007': ['constraint','constraint'],
 'paperpilot:case_038': ['constraint','term'],
 'paperpilot:case_001': ['constraint','constraint','term'],
 'paperpilot:case_019': ['constraint','term','term'],
 'paperpilot:case_036': ['constraint','term','constraint'],
}
annotations = []
for pair in selection['pairs']:
    qid, pid = pair['question_id'], pair['paper_id']
    q, p, d = questions[qid], papers[pid], decisions[qid]
    assert p['metadata_status'] == 'ready', pid
    assert len(d['alignments']) == len(concepts[qid]), qid
    query_spans, alignments = [], []
    qkinds = kinds.get(qid, ['term'] * len(concepts[qid]))
    assert len(qkinds) == len(concepts[qid]), qid
    for i, (term, alignment, kind) in enumerate(zip(concepts[qid], d['alignments'], qkinds), 1):
        sid = f'q{i:02d}'
        query_spans.append({**span(q['text'], term), 'span_id': sid, 'kind': kind, 'importance': 'core'})
        evidence = [{**span(p[e['field']], e['text']), 'field': e['field']} for e in alignment['evidence']]
        alignments.append({'query_span_id': sid, 'match_type': alignment['match_type'],
                           'paper_spans': evidence, 'notes': alignment['notes']})
    annotations.append({
        'record_type': 'annotation', 'schema_version': '1.0',
        'annotation_id': f"calibration-v1:{qid}:{pid}", 'question_id': qid, 'paper_id': pid,
        'annotator_id': 'codex-llm', 'annotation_method': 'llm',
        'guideline_version': '1.0-calibration', 'revision': 1, 'status': 'complete',
        'input_sha256': digest({'question': q['text'], 'context': q['context'],
                                 'title': p['title'], 'abstract': p['abstract']}),
        'query_spans': query_spans, 'alignments': alignments,
        **{k: d[k] for k in ('scientific_correspondence','needs_full_text','confidence','notes')}
    })
(ROOT / 'annotations.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in annotations))

# The review view is generated from the same source strings/offsets as the JSONL.
def cell(s):
    return s.replace('|', '\\|').replace('\n', ' ')
def quote(s):
    return '\n'.join('> ' + line for line in s.splitlines())
def paper_url(p):
    if p['paper_id'].startswith('arxiv:'):
        return 'https://arxiv.org/abs/' + p['identifiers']['arxiv']
    return 'https://www.semanticscholar.org/paper/' + p['identifiers']['s2']

counts = Counter(z['match_type'] for a in annotations for z in a['alignments'])
science = Counter(a['scientific_correspondence'] for a in annotations)
report = [f"""# Калибровочная разметка: 30 вопросов, 30 пар

11 октября 2026. Это **предварительная разметка, выполненная языковой моделью**, без независимой человеческой проверки.

Для каждого из 30 вопросов взята одна статья, которую авторы соответствующего бенчмарка включили в правильный ответ. Сравнивались **текст вопроса и название с аннотацией этой статьи**. Вся выборка содержит 593 такие пары; остальные 563 пока не размечены. Из ScholarQuest, AutoResearchBench и PaperPilot разобрано по 10 вопросов. Crase пока не включён в разметку: точные данные этого бенчмарка недоступны.

## Что видно на этом этапе

- **Вопрос может требовать сведений, которых нет в аннотации статьи.** Особенно наглядно это видно в AutoResearchBench, в части Deep — задачах на поиск одной конкретной работы по подробным признакам. Например, вопрос № 11 описывает промежуточный шаг доказательства и числовую константу, а вопрос № 16 — содержание сносок и соотношение времени работы методов. Названия и аннотации выбранных статей этих подробностей не приводят. Поэтому отсутствие совпадающих слов здесь ещё не говорит, что авторы и исследователь используют разную терминологию: мы можем просто сравнивать вопрос с недостаточно подробным текстом.

- **В опубликованном списке ответов встречаются расхождения между названием статьи и ссылкой на неё.** В PaperPilot для вопроса № 29 в данных указано название «Document Grounded Generation: A Survey» — то есть обзор работ. Однако идентификатор статьи, используемый как ссылка в базе Semantic Scholar, возвращает другую по названию работу: «Pointwise Mutual Information Based Metric and Decoding Strategy for Faithful Generation in Document Grounded Dialogs». В её аннотации описано предложение новой метрики и способа генерации ответов, а не обзор литературы. Такое расхождение нужно проверить до оценки сходства: возможно, мы сопоставляем вопрос с неверной статьёй. При этом небольшая разница в названии сама по себе ещё не доказывает ошибку ссылки. В подробных карточках сохранены оба названия.

- **Совпадение общего предмета не подтверждает все требования вопроса.** Например, в ScholarQuest вопрос № 7 требует статью с оценкой на конкретном наборе данных «IAM Online Handwriting Database», а аннотация выбранной статьи называет только «IAM database». По этому сокращённому обозначению нельзя уверенно установить, тот ли это набор. Другой пример — вопрос № 8: он требует работы о байесовских сетях, исключающие скрытые марковские модели. Отсутствие упоминания последних в аннотации не доказывает, что они исключены из всей статьи. Такие пары требуют дополнительной проверки, даже если отдельные термины совпадают.

- **В этих 30 парах пока не установлен случай, когда одно и то же научное понятие действительно названо разными специальными терминами.** Найдены обычные синонимы, сокращения, описательные формулировки и более частные разновидности методов. Для части условий сведений недостаточно. Это наблюдение о первом небольшом проходе; оно не позволяет заключить, что терминологического разрыва нет во всём бенчмарке.

## Что означают метки и их количества

Метка ставится **отдельному ключевому понятию или условию вопроса**, а не всему вопросу и не статье целиком. Для него ищется соответствующий фрагмент в названии или аннотации статьи. Один вопрос может содержать несколько таких понятий, каждое со своей меткой.

Например, в вопросе № 1 выделены два понятия: «mesh generation» — построение сетки, и «Delaunay triangulation» — триангуляция Делоне. Для первого найдено синонимичное «grid-generation», а для второго — та же формулировка во множественном числе. Эта одна пара даёт **две метки разных типов**.

Всего в 30 парах размечено **146 понятий и условий**. Ниже числа относятся именно к ним:

- **Точное совпадение — {counts['exact']} (`exact`).** Термин присутствует в статье в той же форме; различие регистра букв допускается. Например, «binary symmetric channel» из вопроса № 4 дословно встречается в аннотации статьи. Это совпадение конкретного термина, а не подтверждение всей пары.

- **Та же формулировка с грамматическим изменением — {counts['inflection']} (`inflection`).** Например, «Delaunay triangulation» в вопросе № 1 и «Delaunay triangulations» в статье отличаются только единственным и множественным числом. Нового научного обозначения здесь нет.

- **Сокращение и его расшифровка — {counts['abbreviation']} (`abbreviation`).** Например, в вопросе № 10 используется «MCMC», а в аннотации — «Markov Chain Monte Carlo». Различаются записи названия метода, а не сам метод.

- **Обычное синонимичное выражение — {counts['synonym']} (`synonym`).** Например, «mesh generation» и «grid-generation» в паре № 1 обозначают построение сетки. Это обычная вариативность словаря в данном контексте; её отдельно отличаем от смены специальной терминологии между научными направлениями.

- **Описание понятия или его конкретная разновидность — {counts['descriptive']} (`descriptive`).** Например, вопрос № 3 говорит о «deep learning» в целом, а статья описывает конкретную «deep siamese network» — глубокую сиамскую сеть. Эта метка также используется, когда статья описывает требуемую возможность без того же термина. Для составного условия она может покрывать лишь часть требования; какая именно часть подтверждена, указано в комментарии. Она не означает, что сопоставленные выражения полностью взаимозаменяемы.

- **Подтверждённая смена специального термина — {counts['terminology_shift']} (`terminology_shift`).** Эту метку можно ставить, когда установлено, что разные научные обозначения относятся к одному и тому же понятию. Простого отсутствия общих слов или общей тематики для неё недостаточно. В текущем проходе таких подтверждённых случаев нет.

- **Соответствие не видно в названии и аннотации — {counts['not_visible']} (`not_visible`).** Например, вопрос № 11 требует определённую числовую константу из доказательства, но аннотация её не приводит. Метка означает нехватку свидетельства в просмотренных полях. Она не утверждает, что условия нет в полном тексте или что статья не подходит.

- **Есть связанное выражение, но соответствие не установлено — {counts['uncertain']} (`uncertain`).** Например, «IAM database» в паре № 7 связано с указанным в вопросе названием набора данных, но не позволяет подтвердить, что это именно «IAM Online Handwriting Database». В отличие от предыдущей метки, здесь есть конкретный фрагмент для сопоставления, однако его недостаточно для уверенного решения.

## Насколько статья отвечает вопросу целиком

Помимо отдельных терминов, каждой из **30 пар** присвоена общая предварительная оценка. Эти количества имеют другой знаменатель: речь уже о парах «вопрос — статья», а не о 146 понятиях.

- **Соответствие подтверждается доступным текстом — {science['supported']} пар (`supported`).** Основное содержание запроса подтверждено названием и аннотацией. Например, в паре № 1 явно описано построение сеток по Делоне.

- **Подтверждена только часть требований — {science['partial']} пар (`partial`).** Часть условий видна, остальные требуют проверки. Например, в паре № 8 подтверждена тема байесовских сетей, но не исключение скрытых марковских моделей. Это не оценка статьи как «частично правильного ответа» по полному тексту.

- **Недостаточно сведений для оценки пары — {science['uncertain']} пар (`uncertain`).** В первую очередь это подробные вопросы AutoResearchBench Deep, для которых нужны доказательства, сноски или таблицы. Здесь по аннотации нельзя уверенно подтвердить или отвергнуть ответ.

- **Доступный текст не подтверждает ожидаемый тип ответа — {science['not_supported']} пара (`not_supported`).** Это описанная выше пара № 29: вопрос требует обзор, а по опубликованной ссылке получена статья с новым исследовательским методом. Оценка предварительная, поскольку сначала нужно разобраться с расхождением названия и идентификатора.

## Как читать подробные карточки

В каждой карточке ниже приведены исходный вопрос, название и оригинальная аннотация выбранной статьи. Таблица показывает выделенное понятие вопроса, тип соответствия, точный фрагмент статьи и объяснение решения. Отсутствие фрагмента обозначено знаком «—».

В конце карточки дана оценка всей пары и указано, нужны ли дополнительные сведения: полный текст, библиография, сведения об авторах или дата публикации. Уверенность относится к принятому решению о разметке: например, можно быть уверенным, что данных недостаточно. Завершённая разметка языковой моделью ещё не является проверенным человеком эталоном.

## Пары"""]
for n, a in enumerate(annotations,1):
    q,p = questions[a['question_id']],papers[a['paper_id']]
    report += [f"### {n}. {a['question_id']}", '**Оригинальный вопрос:**', quote(q['text'])]
    if q['context']:
        report += ['**Контекст:** ' + json.dumps(q['context'], ensure_ascii=False)]
    report += [f"**Цель:** [{p['title']}]({paper_url(p)}) — `{p['paper_id']}`."]
    if p.get('released_title'):
        report += ['**Название в релизе:** ' + p['released_title'] + '.']
    report += ['**Оригинальный abstract:**', quote(p['abstract'])]
    table = ['| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |', '|---|---|---|---|']
    byid = {x['span_id']:x for x in a['query_spans']}
    for z in a['alignments']:
        ev = '; '.join(e['field'] + ': «' + e['text'] + '»' for e in z['paper_spans']) or '—'
        table.append('| ' + ' | '.join(map(cell,[byid[z['query_span_id']]['text'],z['match_type'],ev,z['notes']])) + ' |')
    report.append('\n'.join(table))
    report += [f"**Соответствие:** `{a['scientific_correspondence']}`; нужны дополнительные источники: "
               + ('да' if a['needs_full_text'] else 'нет') + f"; уверенность: `{a['confidence']}`.", a['notes']]
(ROOT / 'annotation-review.md').write_text('\n\n'.join(report) + '\n')

manifest = json.loads((ROOT / 'manifest.json').read_text())
manifest.update({
 'annotation_status':'initial_llm_calibration_complete; human review pending; remaining gold pairs pending',
 'annotation_progress': {'annotated_pairs':len(annotations),'pending_pairs':manifest['selected_total_pairs']-len(annotations),
                         'questions_covered':len({a['question_id'] for a in annotations}),
                         'query_concepts':sum(len(a['query_spans']) for a in annotations),
                         'annotation_method':'llm','human_validated_pairs':0,
                         'calibration_selection':'calibration-pairs.json'},
 'metadata_status': f"title + abstract retrieved for {sum(p['metadata_status']=='ready' for p in papers.values())}/{len(papers)} unique targets; remaining records partial",
 'metadata_progress': dict(Counter(p['metadata_status'] for p in papers.values())),
 'calibration_artifact_sha256': {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                               for name in ['query-concepts.v1.json','calibration-pairs.json',
                                            'calibration-decisions.v1.json','annotations.jsonl']}
})
(ROOT / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(f'Wrote {len(annotations)} annotations; {sum(counts.values())} alignments; {dict(counts)}')
