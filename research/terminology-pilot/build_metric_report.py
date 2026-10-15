"""Generate readable comparison tables from measured values (no model judgments)."""
import json
import math
from collections import Counter,defaultdict
from pathlib import Path
from statistics import mean,median
from measure_terms import METHODS,VIEWS

ROOT=Path(__file__).resolve().parent

def load(name):return [json.loads(x) for x in (ROOT/name).read_text().splitlines() if x]
def cell(s):return str(s).replace('|','\\|').replace('\n',' ')
def table(headers,rows):
 return '\n'.join(['| '+' | '.join(headers)+' |','|'+'---|'*len(headers)]+['| '+' | '.join(cell(x) for x in row)+' |' for row in rows])
def number(v,method='words_lemma'):
 if v is None:return '—'
 return f'{v:.3f}' if method in ('jaccard','idf_cosine') else f'{100*v:.1f}%'
def score(p,view,method='words_lemma',scope='scientific_terms'):
 x=p['views'][view]['scores'] if scope=='scientific_terms' else p['content_word_scores'][view]
 return x.get(method)
def macro(rows,view,method='words_lemma',scope='scientific_terms'):
 byq=defaultdict(list)
 for p in rows:
  v=score(p,view,method,scope)
  if v is not None:byq[p['question_id']].append(v)
 return mean(mean(v) for v in byq.values()) if byq else None

Q=load('questions.jsonl');qby={q['question_id']:q for q in Q};qnum={q['question_id']:i for i,q in enumerate(Q,1)}
P=load('papers.jsonl');pby={p['paper_id']:p for p in P}
R=load('term-pairs.jsonl');run=json.loads((ROOT/'metric-run.json').read_text())
F=load('fulltexts.jsonl');fby={x['paper_id']:x for x in F}
T=json.loads((ROOT/'query-terms.v2.json').read_text());terms={x['question_id']:x['terms'] for x in T['questions']}
CONTROL=json.loads((ROOT/'metric-behavior-checks.json').read_text())
core=[p for p in R if all(score(p,v) is not None for v in ['title_abstract','body_no_references_no_related_work','body_no_references'])]
trusted=[p for p in core if not pby[p['paper_id']].get('metadata_notes')]
allta=[p for p in R if score(p,'title_abstract') is not None]
core_q=len({p['question_id'] for p in core})
GROUPS=[('scholarquest','ScholarQuest'),('autoresearchbench:deep','AutoResearchBench: поиск одной работы'),
        ('autoresearchbench:wide','AutoResearchBench: подбор набора работ'),('paperpilot','PaperPilot')]
def group(p):
 q=qby[p['question_id']]
 return q['benchmark']+(':'+q['original_record']['type'] if q['benchmark']=='autoresearchbench' else '')

def availability(rows):
 return [len({p['question_id'] for p in rows}),len(rows),
         sum(score(p,'title_abstract') is not None for p in rows),
         sum(score(p,'body_no_references_no_related_work') is not None for p in rows),
         sum(score(p,'body_no_references') is not None for p in rows)]

report=[
 '# Насколько совпадает словарь вопроса и целевой статьи',
 '**Что измерено:** совпадение научных слов и выражений запроса со словами и выражениями статьи. '
 'Эти числа оценивают наблюдаемое совпадение словаря; поисковые системы не запускались.',
 f'Расчёт выполнен для **всех {len(R)} сохранённых пар по {len(Q)} вопросам**: по 10 вопросов ScholarQuest, AutoResearchBench и PaperPilot. '
 'Для каждого вопроса сохранены все опубликованные целевые статьи. PaperPilot представлен публичным CSV из 50 задач; его соответствие каноническому тесту статьи не подтверждено. Crase остаётся вне расчёта: [репозиторий](https://github.com/RadiantCrystal/CRASE) пока не публикует точные задачи. '
 'Для каждого доступного текста посчитана сетка из **15 показателей**. Недоступные тексты и ненадёжные границы разделов помечаем пропуском, а не нулевым совпадением.',
 '### Покрытие словаря при осторожной нормализации',
 f'Одинаковое подмножество: {len(core)} пар / {core_q} вопросов. Правила нормализации и знаменатели объяснены ниже.',
 table(['Где ищем','Найдено слов запроса','Лексическое расхождение','Найдены целые научные выражения'],
       [[VIEWS[v],number(macro(core,v)),number(1-macro(core,v)) if core else '—',number(macro(core,v,'phrases_lemma'))]
        for v in ['title_abstract','body_no_references','body_no_references_no_related_work']]),
 'Как читать результат:\n\n'
 f'- В кратком описании найдены в среднем {number(macro(core,"title_abstract"))} учитываемых слов, '
 f'в тексте без библиографии и Related Work — {number(macro(core,"body_no_references_no_related_work"))}. Часть исходного несовпадения объясняется тем, что заголовок и аннотация короче статьи.\n'
 f'- Без библиографии и Related Work совпадают {number(macro(core,"body_no_references_no_related_work"))} отдельных слов, '
 f'но только {number(macro(core,"body_no_references_no_related_work","phrases_lemma"))} целых научных выражений. Наличие слов и наличие сформулированного термина — разные результаты.\n'
 '- Оставшиеся ненайденные слова могут быть обозначены иначе, отсутствовать в доступном извлечении или относиться к условиям, которые конкретная цель не покрывает. '
 'По одному проценту нельзя различить эти причины.',
 '## 1. Что считается термином и совпадением',
 'Из вопроса выделены названия методов, научные задачи, объекты, технические свойства и описательные научные выражения. '
 'Фразы «найди статью», даты, аффилиации авторов и указания «в сноске» не входят в основной словарь. '
 'Темы, которые вопрос явно просит исключить, сохранены отдельно и не входят в его основной показатель: '
 'статья не должна получать низкий балл лишь за отсутствие запрещённой темы. '
 'Альтернативные методы и примеры из вопроса остаются в словаре; их отсутствие означает несовпадение словаря, а не нарушение обязательного требования.',
 'Список терминов составлен языковой моделью по текстам вопросов и сохранён с точными границами фрагментов. '
 'Это проверяемый список, но не независимая человеческая разметка. '
 'Процедура не была строго слепой: часть статей ранее просматривалась в качественном пилоте; список терминов не меняется от одной цели вопроса к другой. '
 'Чтобы видеть влияние такого отбора, ниже отдельно сравнивается расчёт по всем содержательным словам вопроса.',
 'Для словесного покрытия знаменатель — **число разных слов в выделенных научных выражениях запроса**. '
 'Если из 10 разных слов в статье найдены 7, покрытие равно 70%, а ненайденная доля — 30%. '
 'Повторение слова в вопросе или статье не увеличивает его вес. '
 'Для нескольких вариантов нормализации список исходных слов в знаменателе остаётся одним и тем же.',
 'Значение 100% означает, что все учитываемые слова найдены. Оно не означает, что статья удовлетворяет всем условиям вопроса. '
 'Например, слова «graph» и «learning» могут находиться далеко друг от друга. Для этого отдельно считаются совпадения словосочетаний.',
 '## 2. По каким правилам сравнивались термины',
 'Все варианты используют одинаковое приведение регистра, типографики и фиксированный список служебных слов. '
 'Для проверок целых выражений также игнорируется пунктуация; совпадение означает соседство оставшихся токенов, а не синтаксический разбор предложения. Слова не заменяются синонимами по усмотрению модели во время расчёта. '
 'Для каждой пары сохранены найденные и отсутствующие слова, поэтому результат можно проверить.',
]
method_rows=[]
for key,(name,desc) in METHODS.items():
 unit='0–1, не процент совпавших терминов' if key in ('jaccard','idf_cosine') else '0–100%'
 method_rows.append([name,desc,unit])
report.append(table(['Способ измерения','Что именно считается совпадением','Шкала'],method_rows))
report += [
 '**Осторожная нормализация** использует словарь WordNet и изменяет слово только при единственном найденном варианте существительного. '
 'Например, `triangulations` переходит в `triangulation`; неоднозначные и неизвестные формы остаются как есть. '
 'Это не полноценный контекстный морфологический анализ, поэтому некоторые настоящие варианты написания могут остаться разными. '
 'Стемминг — более широкое механическое удаление окончаний и суффиксов, а не доказательство эквивалентности терминов.',
 '**Вариант со стеммингом и сокращениями:** сокращения раскрываются только по сохранённому малому словарю: MCMC, RL, GNN/GNNs, CNN/CNNs, NLP. '
 'Он не содержит свободно придуманных синонимов и не охватывает все значения сокращений в науке. '
 'Показатель с сокращениями служит дополнительной проверкой, а не универсальным определителем смысла.',
 '**Вес редкости** рассчитан один раз по 584 доступным названиям и аннотациям целей и одинаков для всех частей текста. '
 'Это небольшой специально отобранный корпус, поэтому такой вес нельзя считать объективной важностью слова во всей научной литературе.',
 '## 3. Где искались совпадения',
 '- **Заголовок** — только название статьи.\n'
 '- **Аннотация** — только опубликованная аннотация.\n'
 '- **Заголовок + аннотация** — объединение этих двух полей.\n'
 '- **Без библиографии и Related Work** — метаданные и извлечённый текст после удаления списка литературы и явно выделенных обзорных разделов; остальные приложения и сноски сохраняются.\n'
 '- **Текст без библиографии** — то же представление, но список литературы удалён; приложения после него сохраняются при обнаружении их границы.\n'
 '\nТекст с библиографией и сама библиография сохранены только в машинных диагностических данных; из основных таблиц они убраны.',
 'Метаданные добавлены к полному тексту явно, чтобы сравнивать расширение одного и того же доступного представления. '
 'Для этих показателей присутствия повтор заголовка или аннотации не меняет результат. '
 'HTML извлекается из элемента статьи, библиография — из отдельного структурного блока. '
 'В PDF текст извлекается программой pdftotext, а библиография отделяется по заголовкам или явно проверенным и сохранённым границам. '
 'Там, где граница не найдена, результат «без библиографии» не подменяется результатом по всему файлу.',
 table(['Набор','Вопросов','Всего пар','Есть заголовок + аннотация','Есть текст без библиографии и Related Work','Есть текст без библиографии'],
       [[name,*availability([p for p in R if group(p)==key])] for key,name in GROUPS]
       +[['Всего',*availability(R)]]),
 f'Полные тексты получены для **{sum(f["status"]=="ready" for f in F)} из {len(P)} уникальных статей**. '
 f'Источники извлечения: HTML — {sum(f["status"]=="ready" and f.get("format")=="html" for f in F)}, '
 f'PDF — {sum(f["status"]=="ready" and f.get("format","pdf")=="pdf" for f in F)}. '
 'В локальном журнале сохранены адреса источников, контрольные суммы и причины пропусков. Речь об извлечённом машиночитаемом тексте: надписи внутри изображений без OCR и некоторые формулы могут не попасть в него.',
 '## 4. Главная таблица: одинаковые пары, разные правила и части текста',
 f'В этой таблице используются **одни и те же {len(core)} пар, охватывающие {core_q} вопросов**: '
 'для них доступны заголовок, аннотация и оба варианта очищенного полного текста. '
 'Поэтому разницу между колонками нельзя объяснить сменой набора статей.',
 'Сначала результат усредняется по целевым статьям каждого вопроса, затем — по вопросам. '
 'Так вопрос с 100 целями не получает в 100 раз больший вес, чем вопрос с одной целью. '
 'Проценты ниже — среднее покрытие, а не доля решённых задач. Для Жаккара и косинуса приведён коэффициент от 0 до 1. '
 '**Больший результат не означает более качественную метрику:** мягкое правило легко увеличивает число совпадений за счёт ложных соответствий.',
 table(['Способ измерения','Заголовок','Аннотация','Заголовок + аннотация','Без библиографии','Без библиографии и Related Work'],
       [[name,*[number(macro(core,v,key),key) for v in VIEWS]] for key,(name,_) in METHODS.items()]),
 'Порядок колонок: заголовок, аннотация, их объединение, текст без библиографии, текст без библиографии и Related Work. '
 'Строки с разными знаменателями не следует считать оценками одного и того же события: 70% совпавших слов и 70% совпавших словосочетаний означают разную строгость проверки.',
 '## 5. Что меняется по бенчмаркам',
 'Здесь показано покрытие слов при осторожной нормализации. В каждой строке сравниваются одинаковые пары; '
 'усреднение снова сначала по статьям вопроса, затем по вопросам.',
 table(['Набор','Общих пар','Заголовок + аннотация','Без библиографии','Без библиографии и Related Work'],
       [[name,len(rows:= [p for p in core if group(p)==key]),
         *[number(macro(rows,v)) for v in ['title_abstract','body_no_references','body_no_references_no_related_work']]] for key,name in GROUPS]),
 'Небольшая выборка позволяет сравнить способы измерения на конкретных вопросах. '
 'Она не предназначена для оценки распространённости терминологического разрыва во всём бенчмарке.',
 '## 6. Насколько результат зависит от выделения терминов и сомнительных ссылок',
 table(['Вариант расчёта','Пар','Вопросов','Заголовок + аннотация','Без библиографии','Без библиографии и Related Work'],[
  ['Научные термины, общие пары',len(core),core_q,*[number(macro(core,v)) for v in ['title_abstract','body_no_references','body_no_references_no_related_work']]],
  ['Все содержательные слова вопроса, те же пары',len(core),core_q,*[number(macro(core,v,scope='all_content_words')) for v in ['title_abstract','body_no_references','body_no_references_no_related_work']]],
  ['Научные термины, без расхождений названий',len(trusted),len({p['question_id'] for p in trusted}),*[number(macro(trusted,v)) for v in ['title_abstract','body_no_references','body_no_references_no_related_work']]],
  ['Научные термины, все доступные заголовки + аннотации',len(allta),len({p['question_id'] for p in allta}),number(macro(allta,'title_abstract')),'другой набор пар','другой набор пар'],
 ]),
 'Вариант «все содержательные слова» удаляет только служебные слова и фиксированную оболочку запроса; '
 'в нём остаются аффилиации, даты, численные подсказки и другие условия. '
 'Разница с основной строкой показывает влияние отбора научного словаря. '
 'Вариант без расхождений названий — проверка устойчивости: расхождение не всегда означает неверную статью, поэтому исходные записи не удалены.',
]
# Count only additional words, not all words present somewhere in bibliography.
new_body=[];ref_only=[]
for p in core:
 ta=set(p['views']['title_abstract']['found_lemma_words'])
 body=set(p['views']['body_no_references']['found_lemma_words'])
 full=set(p['views']['body_no_references_no_related_work']['found_lemma_words'])
 den=len(p['views']['title_abstract']['query_words'])
 new_body.append({'question_id':p['question_id'],'v':len(body-ta)/den})
 ref_only.append({'question_id':p['question_id'],'v':len(body-full)/den})
def mean_q(values):
 b=defaultdict(list)
 for x in values:b[x['question_id']].append(x['v'])
 return mean(mean(x) for x in b.values()) if b else None
report += [
 '## 7. Насколько Related Work увеличивает совпадение',
 f'После исключения библиографии покрытие равно {number(macro(core,"body_no_references"))}; '
 f'после дополнительного исключения Related Work — {number(macro(core,"body_no_references_no_related_work"))}. '
 f'Разница составляет {100*mean_q(ref_only):.1f} процентного пункта. Здесь считаются только слова, которые исчезли из доступного представления после удаления обзорных разделов, а не все слова, встретившиеся в Related Work.',
 'Библиография привносит названия других работ, а Related Work — их описание и сопоставление. '
 'Поэтому текст без обоих компонентов лучше соответствует задаче изучения словаря самой целевой статьи. '
 'При этом оставшиеся введение, обсуждение и другие разделы тоже могут описывать чужие результаты: структурное удаление разделов не является разметкой авторства каждого утверждения.',
 '## 8. Проверки поведения показателей на понятных примерах',
 'Это искусственные диагностические примеры с заранее указанным изменением, а не оценка качества на человеческой разметке. '
 'Они проверяют, что именно реагирует на окончания, расстояние между словами, сокращения и посторонний текст.',
 table(['Изменение','Точные слова','Осторожная нормализация','Стемминг','С сокращениями','Словосочетание: осторожная нормализация'],
       [[c['name'],*[number(c['scores'][m]) for m in ['words_exact','words_lemma','words_stem','words_alias','phrases_lemma']]] for c in CONTROL['cases']]),
 '- `Delaunay triangulation` и `Delaunay triangulations`: нормализация убирает различие числа.\n'
 '- `deep RL` и `deep reinforcement learning`: полное соответствие требует явного раскрытия RL.\n'
 '- `graph` и `learning` с 45 посторонними словами между ними: покрытие отдельных слов полное, но словосочетания нет. Окна 10 и 30 не засчитывают такое расстояние, окно 100 уже засчитывает.\n'
 '- `organ` и `organize`: используемый стеммер объединяет разные слова; осторожная нормализация этого не делает.\n'
 '- `increase efficiency` и `efficiency does not increase`: совпадение слов сохраняется при изменении смысла. '
 'Следовательно, слово «расхождение» в этом отчёте относится к наблюдаемому словарю, а не автоматически к научной несовместимости.',
 'При добавлении постороннего словаря покрытие запроса в контрольном примере сохраняется, '
 f'а Жаккар меняется с {number(CONTROL["cases"][0]["scores"]["jaccard"],"jaccard")} '
 f'до {number(CONTROL["cases"][-1]["scores"]["jaccard"],"jaccard")}; '
 f'косинус — с {number(CONTROL["cases"][0]["scores"]["idf_cosine"],"idf_cosine")} '
 f'до {number(CONTROL["cases"][-1]["scores"]["idf_cosine"],"idf_cosine")}. '
 'Это объясняет, почему симметричные меры не стоит брать главным показателем присутствия терминов короткого вопроса в длинной статье.',
 '## 9. Какой метод предлагается выбрать',
 'Критерии выбора: понятный знаменатель; возможность проверить каждое совпадение; устойчивость к добавлению постороннего текста; '
 'минимум неподтверждённых замен слов; явное разделение слов и составных терминов. '
 'Точность относительно человеческого понимания смысла не включается в доказанные критерии: независимого эталона здесь нет.',
 table(['Вариант','Что полезно','Почему это основной или дополнительный показатель'],[
  ['Точные слова','Максимально буквальная, воспроизводимая исходная точка','Основной контроль; различает даже единственное и множественное число.'],
  ['Осторожная нормализация слов','Убирает часть грамматических различий и сохраняет проверяемый список слов','Предлагаемый основной показатель присутствия словаря.'],
  ['Целые выражения с осторожной нормализацией','Проверяет сочетание слов, а не их присутствие в разных местах','Обязательный показатель рядом с основным; длинное описание может быть сформулировано другими словами.'],
  ['Стемминг, сокращения, вес редкости','Показывают чувствительность к более мягким правилам','Дополнительные варианты: возможны ложные объединения, многозначные сокращения и зависимость от выбранного корпуса.'],
  ['Символьные фрагменты','Обнаруживают части похожих написаний','Не равны совпадению научных терминов.'],
  ['Жаккар и косинус','Сопоставляют словари документов целиком','Дополнительные меры: штрафуют длинную статью за посторонний словарь.'],
 ]),
 '**Основной показатель — доля слов научных терминов запроса, найденных в статье после осторожной словарной нормализации.** '
 'Формула: `покрытие = 100% × число найденных разных слов / число разных слов в научных выражениях запроса`. '
 'Расхождение записывается как `100% − покрытие`. '
 'Он отвечает непосредственно на вопрос о присутствии словаря запроса, не штрафует статью за дополнительный словарь, '
 'имеет фиксированный знаменатель и позволяет показать каждое найденное или отсутствующее слово.',
 'Для него следует хранить **два основных результата: по заголовку с аннотацией и по тексту без библиографии и Related Work**. '
 'Разница между ними показывает, какая часть первоначального расхождения объясняется ограниченностью краткого описания статьи. '
 'Основной полнотекстовый результат теперь исключает и библиографию, и явно выделенный Related Work; вариант только без библиографии показывает влияние обзорного раздела.',
 '**Обязательное дополнение — доля научных выражений, найденных целиком с той же осторожной нормализацией.** '
 'Она различает совпадение слов в разных местах и совпадение словосочетания. '
 'Эти два числа следует показывать рядом, не смешивая произвольными весами в один «общий балл». '
 'Точное совпадение без нормализации также сохраняется как воспроизводимая исходная точка.',
 'Предложение основано на соответствии показателя измеряемому свойству и диагностических проверках. '
 '**Мы пока не установили, какой метод лучше всех согласуется с независимым человеческим пониманием терминологического разрыва:** '
 'такой проверенной разметки здесь нет. Низкое словарное покрытие само по себе не доказывает, что разные обозначения относятся к одному понятию. '
 'Для этого нужен отдельный содержательный разбор. Число вроде косинуса эмбеддингов не заменяло бы такую проверку.',
 '## 10. Все 30 вопросов: сравнение на уровне вопроса',
 'В колонке «общих / всех пар» указано, сколько целевых статей вошло в сопоставление трёх представлений. '
 'Все проценты в строке рассчитаны по этому общему подмножеству. '
 'Исходный вопрос и результаты каждой его целевой статьи находятся в подробном приложении.',
]
summaries=[
 'Построение сеток по Делоне','Перцептрон без нейросетевой тематики',
 'Поиск изображений и извлечение признаков','Коды для двоичного симметричного канала',
 'Интерполяция при обработке изображений','Извлечение информации: обучение с частичной разметкой',
 'Распознавание рукописного текста на заданном наборе данных','Байесовские сети без скрытых марковских моделей',
 'Безопасность браузера Chrome','Вычислительная эффективность вариационных методов',
 'Рекурсивная оценка ошибки и объём выборки','Монотонная регрессия и отклонение распределений',
 'Шум, полиномиальный метод и производные','Социально-семантические графы и распространение информации',
 'Децентрализованная оптимизация','Агрегирование метрики и время работы',
 'Радиоканалы, антенны и скорость вычислений','Инженерия физических кубитов',
 'Приближённые графовые алгоритмы с ограниченными ресурсами','Обучение языковых агентов работе с инструментами',
 'Масштабируемое обучение представлений графов','Развитие глубокого обучения с подкреплением',
 'Обзоры свойств графовых нейросетей','Предобучение для переноса на языковые задачи',
 'Обучение с подкреплением по готовым данным','Развитие пошаговых рассуждений языковых моделей',
 'Наборы данных для оценки обучения на графах','Развитие Transformer для языковых моделей',
 'Обзоры языковых моделей с поиском документов','Развитие графовых сетей с вниманием']
qrows=[]
for q in Q:
 rows=[p for p in core if p['question_id']==q['question_id']]
 summary=summaries[qnum[q['question_id']]-1]
 if len(summary)>95:summary=summary[:92]+'…'
 qrows.append([f"№ {qnum[q['question_id']]}: {summary}",f"{len(rows)} / {len(q['gold_paper_ids'])}",
               number(macro(rows,'title_abstract')),number(macro(rows,'title_abstract','phrases_lemma')),
               number(macro(rows,'body_no_references')),number(macro(rows,'body_no_references','phrases_lemma')),
               number(macro(rows,'body_no_references_no_related_work')),number(macro(rows,'body_no_references_no_related_work','phrases_lemma'))])
report.append('Краткий текст — заголовок + аннотация; содержание — текст без библиографии. «Слова» и «фразы» используют осторожную нормализацию.')
report.append(table(['Вопрос','Общих / всех пар','Слова в кратком тексте','Фразы в кратком тексте','Слова в содержании','Фразы в содержании','Слова без библиографии и Related Work','Фразы без библиографии и Related Work'],qrows))
report += [
 '## Данные и воспроизведение',
 '- [Подробное приложение: оригинальные вопросы, все целевые статьи и найденные слова](term-match-details.md).\n'
 '- `metrics.jsonl` — каждый показатель для каждой пары и части текста, включая явные пропуски.\n'
 '- `term-pairs.jsonl` — показатели и списки найденных/отсутствующих слов по парам.\n'
 '- `query-terms.v2.json`, `stopwords.v1.json`, `aliases.v1.json`, `idf.v1.json`, `metric-config.v1.json` — точные входные правила.\n'
 '- `fulltexts.jsonl`, `reference-splits.jsonl`, `related-work-splits.jsonl` — источники полных текстов и способы исключения разделов.\n'
 '- `metric-behavior-checks.json` — результаты диагностических примеров.\n'
 '- Полные тексты хранятся локально в `fulltext-cache/`; они не включены в отчёт и Git. Их можно получить повторно загрузчиком.',
 '```sh\npython3 research/terminology-pilot/measure_terms.py\npython3 research/terminology-pilot/check_metric_behavior.py\npython3 research/terminology-pilot/build_metric_report.py\n```',
 'Описание нормализации и её ограничений: [Introduction to Information Retrieval](https://nlp.stanford.edu/IR-book/html/htmledition/normalization-equivalence-classing-of-terms-1.html). '
 'Словарные формы: [NLTK WordNet](https://www.nltk.org/api/nltk.stem.wordnet.html). '
 'Алгоритм стемминга: [Snowball English](https://snowballstem.org/algorithms/english/stemmer.html); точная версия использованной реализации NLTK записана в конфигурации. '
 'Идея веса редкости: [Inverse document frequency](https://nlp.stanford.edu/IR-book/html/htmledition/inverse-document-frequency-1.html). '
 'Все численные результаты в отчёте получены локальными скриптами по сохранённым данным.',
]
# Align numerical column order with the header, independently of VIEWS insertion order.
examples=[
 ('scholarquest:BQ_001749','arxiv:1512.00307',
  'В вопросе — `Delaunay triangulation`, в аннотации — `Delaunay triangulations`. '
  'Словарь снимает различие числа: точное покрытие ниже нормализованного. '
  'Но целиком найдены не все выражения вопроса: слова про построение сеток сформулированы иначе.'),
 ('scholarquest:BQ_000320','arxiv:0809.1978',
  'В вопросе — `Perceptron algorithm`, в названии — `perceptrons`. '
  'Используемый словарь не распознал множественное число этого технического слова; стеммер распознал. '
  'Это реальный пропуск осторожной нормализации, который нельзя скрывать за удачным искусственным примером. '
  'Слово `algorithm` в этом кратком тексте также не найдено.'),
 ('scholarquest:BQ_000320','arxiv:0712.4050',
  'Слова `perceptron` и `algorithm` оба есть, но целого выражения `Perceptron algorithm` нет. '
  'Аннотация отдельно обсуждает перцептрон и message-passing algorithm для другой схемы. '
  'Полное покрытие отдельных слов не подтверждает совпадения составного термина.'),
]
example_blocks=['### Реальные пары: что стоит за процентами']
for qid,pid,explanation in examples:
 pair=next(p for p in R if p['question_id']==qid and p['paper_id']==pid)
 paper=pby[pid];values=pair['views']['title_abstract']['scores']
 example_blocks += ['**Вопрос:** '+qby[qid]['text'],
  '**Целевая статья:** ['+paper['title']+'](https://arxiv.org/abs/'+paper['identifiers']['arxiv']+').',
  table(['Точные слова','Осторожная нормализация','Стемминг','Целые выражения: осторожная нормализация'],
        [[number(values[m]) for m in ['words_exact','words_lemma','words_stem','phrases_lemma']]]),
  explanation]
position=next(i for i,x in enumerate(report) if x.startswith('## 9.'))
report.insert(position,'\n\n'.join(example_blocks))
missing_texts=[f for f in F if f['status']!='ready']
if missing_texts:
 notes_path=ROOT/'fulltext-unavailability-notes.v1.json'
 notes=json.loads(notes_path.read_text()) if notes_path.exists() else {}
 missing_rows=[]
 for f in missing_texts:
  p=pby[f['paper_id']]
  title=p['title'] or p['paper_id']
  note=notes.get(f['paper_id'],'Публичный полный текст не получен: источник не вернул доступный целый PDF/HTML. Точная ошибка записана в журнале загрузки.')
  missing_rows.append([title,note])
 position=next(i for i,x in enumerate(report) if x.startswith('## 4.'))
 report.insert(position,'**Статьи без полного текста:**\n\n'+table(['Целевая статья','Причина пропуска'],missing_rows))
version_rows=[]
for f in F:
 note=f.get('source_override',{}).get('version_note')
 if f['status']=='ready' and note:
  version_rows.append([pby[f['paper_id']]['title'],note,'[Полный текст]('+f['url']+')'])
if version_rows:
 position=next(i for i,x in enumerate(report) if x.startswith('## 4.'))
 report.insert(position,'**Явно выбранные версии текста:** в этих случаях сравнивается словарь доступной версии исходной цели. '
  'Отзыв статьи не скрывается; её научная корректность этим расчётом не подтверждается.\n\n'+table(['Статья','Версия и ограничение','Источник'],version_rows))
RW=load('related-work-splits.jsonl');rwby={x['paper_id']:x for x in RW}
mixed={x['paper_id'] for x in RW if any(s.get('mixed_heading') for s in x.get('sections',[]))}
clean=[p for p in core if p['paper_id'] not in mixed]
rwcounts=Counter(x['status'] for x in RW)
position=next(i for i,x in enumerate(report) if x.startswith('## 4.'))
report.insert(position,'### Как удалён Related Work\n\n'
 'Удаляются явно озаглавленные Related Work(s), Prior/Previous Work, Related Literature/Studies и Literature Review, включая их подразделы. '
 'HTML-раздел удаляется по структуре документа; PDF — по заголовку и границе следующего раздела. '
 'Background и Preliminaries без упоминания Related Work сохраняются. Удаление зависит только от структуры статьи, а не от слов вопроса.\n\n'
 +table(['Что обнаружено','Уникальных статей'],[
  ['Выделенные обзорные разделы удалены',rwcounts['removed']],
  ['Явного раздела с таким заголовком не обнаружено: сохраняем остальной текст',rwcounts['no_explicit_section']],
  ['Ненадёжное извлечение: очищенный результат отсутствует',rwcounts['ambiguous']],
  ['Полный текст недоступен',rwcounts['unavailable']],
  ['Объединённые заголовки: удалён также Introduction/Background/Discussion и т. п.',len(mixed)]])
 +'\n\nОтсутствие отдельного заголовка не означает отсутствия обзора литературы во введении. '
 'Объединённые разделы удалены целиком, поэтому ниже есть проверка без таких статей. '
 'Пять PDF смешивают в извлечении колонки с Related Work и собственным методом/выводами; вместо неверного вырезания они помечены пропуском. '
 'Для трёх PDF без нумерации сохранены явно проверенные границы. Журнал содержит ID, заголовки, границы, контрольные суммы и причины пропусков.\n\n'
 +table(['Проверка объединённых разделов','Пар','Заголовок + аннотация','Без библиографии','Без библиографии и Related Work'],[
 ['Все общие пары',len(core),*[number(macro(core,v)) for v in ['title_abstract','body_no_references','body_no_references_no_related_work']]],
 ['Без статей с объединённым заголовком',len(clean),*[number(macro(clean,v)) for v in ['title_abstract','body_no_references','body_no_references_no_related_work']]]]))
ambiguous=[x for x in RW if x['status']=='ambiguous']
if ambiguous:
 position=next(i for i,x in enumerate(report) if x.startswith('## 4.'))
 report.insert(position,'**Где очищенный результат не рассчитан из-за порядка колонок:** при извлечении этих PDF обзорный раздел перемешался с собственным методом, Background или выводами.\n\n'
  +table(['Статья','Решение'],[[pby[x['paper_id']]['title'],'Показатель без Related Work оставлен пропуском; исходная статья сохранена'] for x in ambiguous]))

AUTO=json.loads((ROOT/'automatic-term-config.v1.json').read_text())
report.append('## Массовый алгоритмический прогон\n\n'
 'Для расширения за пределы 30 вопросов нужен автоматический отбор словаря: пилотные выражения были выделены LLM. '
 'Сравнены три правила, использующие только вопрос и фиксированный POS-теггер NLTK. '
 'Precision — доля автоматически выбранных слов, вошедших в пилотный словарь; recall — доля пилотных слов, которые правило сохранило; F1 — их гармоническое среднее. '
 'Сначала считаем показатели по вопросу, затем усредняем. Это согласие с текущим пилотом, а не с независимой экспертной разметкой.\n\n'
 +table(['Автоматический отбор','Precision','Recall','F1'],[[{'nouns_only':'Только существительные','noun_phrases':'Именные группы с определениями','content_words':'Все содержательные слова'}[k],*[number(v[m]) for m in ['precision','recall','f1']]] for k,v in AUTO['scores'].items()])
 +'\n\nЗафиксировано правило **именных групп с определениями**, затем осторожная нормализация слов и покрытие запроса. '
 'Для массового расчёта доля несовпадения равна 100% минус покрытие. Дополнительно сохраняются точное покрытие, совпадение групп целиком и контроль по всем содержательным словам. '
 'В массовом отборе упомянутые отрицанием темы не распознаются семантически и остаются частью наблюдаемого словаря; результат не оценивает выполнение отрицательных требований. '
 'Основной результат пилота и массовый результат не смешиваются: у них разный способ отбора терминов.\n\n'
 '[Массовые результаты и доступность данных](release-run/report.md).')

wrong=[v for v in VIEWS]
correct=['title','abstract','title_abstract','body_no_references','body_no_references_no_related_work']
for i,block in enumerate(report):
 if block.startswith('| Способ измерения | Заголовок |'):
  report[i]=table(['Способ измерения','Заголовок','Аннотация','Заголовок + аннотация','Без библиографии','Без библиографии и Related Work'],
        [[name,*[number(macro(core,v,key),key) for v in correct]] for key,(name,_) in METHODS.items()])
if run.get('development_partial_run'):
 report.insert(1,'**Промежуточный расчёт: сбор полных текстов продолжается. Итоговые значения будут пересчитаны после завершения загрузки.**')
(ROOT/'metric-comparison.md').write_text('\n\n'.join(report)+'\n')

# Detailed view: percentages are accompanied by countable missing-word lists.
detail=['# Подробности совпадения терминов по всем парам',
        '[Сводный отчёт и определения показателей](metric-comparison.md). '
        'Пропуск «—» означает недоступный текст или ненадёжные границы разделов. '
        'В словесных колонках используется осторожная словарная нормализация; '
        'списки ниже содержат исходные слова запроса, а не обрезанные основы.']
for q in Q:
 qid=q['question_id'];rows=[r for r in R if r['question_id']==qid]
 detail += [f"## Вопрос {qnum[qid]}. {q['benchmark']}", '\n'.join('> '+l for l in q['text'].splitlines()),
            '**Учитываемые научные выражения:** '+ '; '.join(z['text'] for z in terms[qid] if z['role']=='mentioned')+'.']
 excluded=[z['text'] for z in terms[qid] if z['role']=='excluded']
 if excluded:detail.append('**Явно исключённые темы, сохранённые отдельно:** '+'; '.join(excluded)+'.')
 if q.get('context'):
  detail.append('**Исходная опорная статья:** '+q['context'].get('reference_title','')+'. '
                'Её название не добавляется к словарю запроса молча; приведённые показатели относятся к самому вопросу.')
 values=[]
 for r in rows:
  p=pby[r['paper_id']]
  url='https://arxiv.org/abs/'+p['identifiers']['arxiv'] if 'arxiv' in p['identifiers'] else 'https://www.semanticscholar.org/paper/'+p['identifiers']['s2']
  title=f"[{p['title'] or r['paper_id']}]({url})"
  if p.get('metadata_notes'):title+=' (название требует проверки)'
  values.append([title,number(score(r,'title_abstract','words_exact')),number(score(r,'title_abstract')),
                  number(score(r,'title_abstract','phrases_lemma')),number(score(r,'body_no_references')),
                  number(score(r,'body_no_references','phrases_lemma')),number(score(r,'body_no_references_no_related_work')),number(score(r,'body_no_references_no_related_work','phrases_lemma'))])
 detail.append(table(['Целевая статья','Точные слова: заголовок + аннотация','Нормализованные слова: заголовок + аннотация',
                      'Целые фразы: заголовок + аннотация','Нормализованные слова: без библиографии','Целые фразы: без библиографии','Слова без библиографии и Related Work','Фразы без библиографии и Related Work'],values))
 detail.append('### Какие слова найдены и отсутствуют')
 for r in rows:
  p=pby[r['paper_id']];ta=r['views']['title_abstract'];body=r['views']['body_no_references'];strict=r['views']['body_no_references_no_related_work']
  detail.append('**'+(p['title'] or p['paper_id'])+'** (`'+p['paper_id']+'`).')
  def words(view,key):
   return ', '.join(view[key]) if key in view and view[key] else ('нет' if key in view else 'текст недоступен')
  detail.append('- Найдены в заголовке с аннотацией: '+words(ta,'found_lemma_words')+'.\n'
                '- Не найдены в заголовке с аннотацией: '+words(ta,'missing_lemma_words')+'.\n'
                '- Не найдены в тексте без библиографии: '+words(body,'missing_lemma_words')+'.\n'
                '- Не найдены без библиографии и Related Work: '+words(strict,'missing_lemma_words')+'.')
  if p.get('released_title'):detail.append('Название в релизе: '+p['released_title']+'.')
(ROOT/'term-match-details.md').write_text('\n\n'.join(detail)+'\n')
summary={'common_pairs':len(core),'common_questions':core_q,'primary_method':'words_lemma',
         'primary_TA':macro(core,'title_abstract'),'primary_body':macro(core,'body_no_references'),
         'primary_body_no_related_work':macro(core,'body_no_references_no_related_work'),'phrase_TA':macro(core,'title_abstract','phrases_lemma'),
         'phrase_body':macro(core,'body_no_references','phrases_lemma'),
         'phrase_body_no_related_work':macro(core,'body_no_references_no_related_work','phrases_lemma'),
         'additional_body_percentage_points':100*mean_q(new_body) if new_body else None,
         'related_work_only_percentage_points':100*mean_q(ref_only) if ref_only else None,
         'aggregation':'mean per question after mean over its available targets; same paired subset across views',
         'human_validated_metric_winner':False}
(ROOT/'metric-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False))
