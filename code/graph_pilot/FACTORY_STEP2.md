# Шаг 2 MVP: критерии и расширение

Исполнитель: `graph_pilot.factory_step2`. До выбора статьи модель не вызывается.
Публичный API графа не изменён; SQLite открывается read-only.

## Реализованный расчёт

- TF-IDF (1–2-граммы, английские stopwords, sublinear TF) + TruncatedSVD/LSA.
  Корпус — все читаемые nodes снимка; индекс строится один раз.
- Аспект карточки: problem + mechanism_or_approach + conventional_terms.term/meaning.
  T — максимальный косинус кандидата с аспектами, ограниченный [0,1].
- G = 1 − coverage слов author_terms именно того аспекта, который дал T.
  Frozen нормализация terminology-pilot: NFKC, токены, stopwords, однозначная
  WordNet noun normalization. Знаменатель — различные исходные слова.
- d — входящая степень в локальном снимке; m — медиана d всей доступной границы.
  M = 1 / (1 + abs(d−m)/max(1,m)).
- S = T × (gap_weight × G + (1−gap_weight) × M), по умолчанию gap_weight=0.5.
  Максимум по всем доступным соседям обоих направлений; shortlist/top-k нет.

Unknown T/G/S сохраняются как null. Сначала выбирается максимальный определённый
score; если таких нет — воспроизводимый fallback по sha256(seed|ID). Такая же
развязка для равенства S. Это техническая политика MVP: неполные профили могут
рассматриваться позже, но не превращаются в научные отказы.
Если косинус вычислен и T=0, итог S=0 определён независимо от неизвестного G;
сам G остаётся null. Нулевой/OOV-вектор — другая ситуация: T неизвестен.

R/Jaccard/классификатор ролей в score не включены. Контексты сохраняются со
src/dst. LSA и равные веса — временный baseline, не проверенная оптимальность.

## Подготовка и команды

На 26 октября индекс `research/factory-step2-pilot/index-001` уже построен
для текущего снимка: 10000 статей, 40000 TF-IDF признаков, 128 LSA компонент.
Загрузка и хеши проверены. Повторять index для этого снимка не требуется;
ниже команда для построения нового индекса при изменении данных/параметров.

После автономных runtime fixes старый индекс загружается с явным
`--index-compatibility research/factory-step2-iterations/index-001-compatibility-sources-20261026.json`.
Report проверяет exact hashes индекса, baseline/current features и численную
подготовку по snapshot; это не отключение проверки версии. Для заново построенного
текущим кодом индекса флаг не нужен. Исторический индекс не переписывается.

Из корня проекта, Python с `code/graph_pilot/requirements-step2.txt`.
Frozen WordNet и stoplist берутся из terminology-pilot, хеши проверяются;
скачиваний нет. Каждый output должен быть новым каталогом.

```bash
PYTHONPATH=code python3 -m graph_pilot.factory_step2 index \
  --db research/unarxive-pilot/graph.sqlite \
  --config code/graph_pilot/configs/step2-index-local.json \
  --output research/factory-step2-pilot/index-001
```

Индекс: manifest.json, transform.joblib, vectors.npy, подготовленные тексты и
словари в papers/*.json.gz. Загружать только свой локально построенный индекс:
joblib использует pickle. Тексты читаются потоково, векторы через mmap;
кэш нормализации ограничен. Начальные параметры: 128 компонент, 40000 признаков,
min_df=2, seed=42; для малого корпуса эффективное число компонент явно записывается.
Для unarXive используется структурное тело без библиографии; для прочих
источников текстовый вид, включая неподтверждённое удаление библиографии,
указывается в manifest. Неподготовленный Parquet read-only reader не ремонтирует.

Начальные карточки — JSON-массив `{paper_id, card}` с каноническими ID.
Можно использовать готовые или получить их для явно заданного исходного набора:

```bash
PYTHONPATH=code python3 -m graph_pilot.factory_step2 bootstrap \
  --index research/factory-step2-pilot/index-001 \
  --index-compatibility research/factory-step2-iterations/index-001-compatibility-sources-20261026.json \
  --initial-ids arxiv:2001.00001 arxiv:2001.00002 \
  --config code/graph_pilot/configs/factory-step2-local.json \
  --llm-config code/graph_pilot/configs/step2-llm.example.json \
  --ask-key --output research/factory-step2-pilot/initial-001
```

ID в примере — placeholders: заменить на выбранную затравку и допущенные работы.
Их число не зашито; результаты шага 1.5 автоматически не интерпретируются.
bootstrap вызывает LLM только для явно заданных исходных ID. Итог — cards.json;
при ошибке остаётся partial-cards.json, полного итогового файла нет.

Локальный выбор при готовых исходных карточках, без LLM-клиента:

```bash
PYTHONPATH=code python3 -m graph_pilot.factory_step2 dry-run \
  --db research/unarxive-pilot/graph.sqlite \
  --index research/factory-step2-pilot/index-001 \
  --index-compatibility research/factory-step2-iterations/index-001-compatibility-sources-20261026.json \
  --cards research/factory-step2-pilot/initial-001/cards.json \
  --config code/graph_pilot/configs/factory-step2-local.json \
  --output research/factory-step2-pilot/dry-001
```

Для полного прохода заменить dry-run на run, добавить
`--llm-config code/graph_pilot/configs/step2-llm.example.json --ask-key`
и новый output. Секрет также передаётся через GRAPH_LLM_API_KEY; в артефакты
он не пишется. Промпты и конфигурации раздельные.

## После выбора и сохранение состояния

Выбор записывается до первого модельного запроса. В LLM идут полный подготовленный
текст выбранной статьи и все текущие карточки. Два бинарных критерия допуска
соединяются AND; terminology_gap — независимый флаг. Reason перед решением,
доступные provider reasoning сохраняются. Буквальных проверок цитат нет.

При успехе отдельный вызов создаёт карточку из исходного текста; только потом
вместе фиксируются карточка и допуск, открываются соседи. При отказе память
не меняется, ID никогда не выбирается повторно в этом запуске. Сбой/неполный
JSON/переполнение контекста не выдаются за научный отказ.

Активные пути промптов — в `configs/factory-step2-local.json`. Карточка v6 —
описательный научный профиль: задачи, операции, условия и качественные выводы.
Она не восстанавливает точные формулы теорем/метрик и не является проверенной
заменой исходной статьи. Source audits нашли локальные ложные усиления даже
в прозе и пропуски вторичных линий; влияние на допуск оценивается отдельно.
Общий дополнительный source-verifier исследован, но в основной цикл не включён.

`admission_focus=none` — default. Экспериментальный `matched_aspect_first`
передаёт уже вычисленный аспект после выбора кандидата, сохраняя все карточки;
ему нужен промпт с `{{comparison_focus}}`. Выигрыш качества этим вариантом
не установлен, поэтому основной путь его не использует.

Технические лимиты конфига: 20 рассмотренных, 10 новых допусков; исходные карточки
не считаются. Перед итерацией резервируются два запроса: допуск + возможная
карточка. При 429 повторов нет. Контекст проверяется только перед вызовом,
корпусные длины заново не измеряются, текст/память не обрезаются.
Работавший step2 LLM example: qwen38_27b, 16384 выходных токена, 600 секунд,
temperature=1, top_p=0.95, effort=medium. Это бюджет, а не гарантия применения
effort сервером или научной правильности. Для независимых прогонов в автономной
проверке максимум 3 одновременных запроса, внутри одного обхода порядок строгий.

Для unarXive frontier и bootstrap проверяют наличие основного тела и связь
исходника с замороженным кэшем. Аннотация с пустыми/пунктуационными остатками
или распознанными TeX layout options — `unavailable`, без LLM и научного отказа.
Порога по длине нет; наличие тела не доказывает его полноту. При `aspects: []`
валидный ответ сохраняется как `card_unavailable`, допуск не фиксируется.

Parser сначала требует строгий JSON. Только literal control characters внутри
строк допускают lossless повтор разбора с `strict=False`; duplicate keys,
nonfinite, запятые и escape по-прежнему проверяются. Исходный ответ не меняется,
факт нормализации записывается отдельно. Это не повтор запроса модели.
Для карточки допускается ещё одна lossless нормализация: только непустой объект
`{statement, concern}` внутри списков conditions/unclear соединяется в строку
с сохранением обоих полей. С 31 октября 2026 также разворачивается элемент
author_terms/conventional_terms, если это список ровно из одного точного
`{term, meaning}` (адаптер `card-list-serialization-v2`, поле `rules`).
Другие формы не чинятся. Исходный completion,
диагностика нормализации и хеши сохраняются; научные значения не редактируются.

Остановки (с 31 октября 2026), проверяются перед каждым выбором в этом порядке:
`review_budget` — только если `max_reviewed` задан (в local config `null`);
`accept_budget` — `max_accepted=20` новых допусков, начальные карточки не считаются;
`rejection_patience` — `max_consecutive_rejections=3` отказа подряд (`null`
отключает), допуск обнуляет счёт; `empty_frontier`; `request_budget`;
`context_overflow` — запрос допуска или возможный запрос карточки для выбранной
статьи не помещается в контекст. Последний случай — чистая остановка до создания
итерации: без LLM-запроса и pending, детали в `context-overflow.json`.
Её различает `Step2ContextGuard`. `probe_modules.py` не меняется: это
замороженная зависимость индекса. Другие ошибки guard по-прежнему дают
`stopped_on_error`.

После чистой остановки по бюджету run можно продолжить с `--resume`, тем же
output и исходным cards. Разрешено изменить budgets и `max_consecutive_rejections`, но не менять модель,
sampling, научные параметры, индекс, код или промпты. max_requests при resume
считается суммарным. Отказы сохраняются. После ошибки/pending автоматический
resume запрещён, чтобы не повторять модельный запрос.

Артефакты: manifest/initial-cards/state; в iterations/ — ranking всех кандидатов,
messages/context/completion/reasoning, assessment и успешная card. Индекс и тексты
проверяются по хешам, источник графа не изменяется.

## Проверка

```bash
PYTHONPATH=code python3 -m pytest code/graph_pilot/tests/test_factory_step2.py -q
```

Тесты используют фиктивную модель и не обращаются к LLM-серверу. Проверяют
вычисления, память и порядок вызовов. Научное качество требует отдельного прогона.
На 26 октября после runtime fixes/default v6: 254 теста пакета проходят.
Реальные ограниченные итерации и научные audits: `research/factory-step2-iterations/`;
история решений и готовность — `research/factory-experiment-registry.md`.
