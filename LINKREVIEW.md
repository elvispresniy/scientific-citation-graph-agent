# LinkReview

★ — ключевые работы; `TODO` — поля, которые нужно сверить по первоисточнику.

## 1. Ближайшие бенчмарки и датасеты

От этих работ нужно отстраиваться при формулировке новизны.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| ★ PaperPilot: Multi-Turn Agentic Scientific Literature Search via Workflow Induction | 2026 | TODO | [arXiv](https://arxiv.org/abs/2607.00597) | Агент строит граф поисковых операций (keyword search, citation expansion, фильтры); направления predecessor / successor / sibling. Есть обучение агента. Терминологический разрыв не выделен как отдельный источник сложности. |
| ★ AutoResearchBench | 2026 | Xiong et al. | [arXiv](https://arxiv.org/abs/2604.25256), [code](https://github.com/CherYou/AutoResearchBench) | 1000 сложных задач поиска статей, multi-hop через цитирования, подавление лексических подсказок, проверки минимальной достаточности. Многошаговые переходы по цитированиям здесь уже есть. Сложность держится на размытии формулировки, а не на терминологическом разрыве; у агента нет графовых инструментов. |
| ★ SciNetBench | 2026 | TODO | [arXiv](https://arxiv.org/abs/2601.03260), [code](https://github.com/tsinghua-fib-lab/SciNet) | Таксономия ego-centric / pair-wise / path-wise задач по графу OpenAlex, включая восстановление путей развития идей. Занимает пространство «типов графовых вопросов», поэтому новизну нельзя строить на одной таксономии или многошаговости. |
| ★ PaSa / AutoScholarQuery | 2025 | He et al. | [arXiv](https://arxiv.org/abs/2501.10120), [code](https://github.com/bytedance/pasa) | Ближайший аналог фабрики: ~35 тыс. синтетических запросов, агент с раскрытием ссылок, RL-обучение. Эталон задаётся одним шагом назад (ссылки из Related Work одной статьи), а запрос генерируется из того же абзаца, где стоят ссылки, поэтому лексический разрыв минимален по построению. |
| LitSearch | 2024 | Ajith et al. | [arXiv](https://arxiv.org/abs/2407.18940), [code](https://github.com/princeton-nlp/LitSearch) | Запросы, сгенерированные по контекстам цитирования, и запросы от авторов статей. Обычно 1–2 целевые статьи на запрос, композиции свидетельств нет. |
| SPAR / SPARBench | 2025 | Shi et al. (TODO: сверить) | TODO | Мультиагентный поиск с RefChain exploration и эволюцией запроса; бенчмарк с экспертной оценкой релевантности. |
| ★ BRIGHT-Pro: Rethinking Reasoning-Intensive Retrieval | 2026 | Zhao et al. | [arXiv](https://arxiv.org/abs/2605.04018) | Оценка ретриверов как построения «портфеля» взаимодополняющих свидетельств в статическом и агентском режимах. Ближайший аналог по идее композиции, но без графа цитирований и без научного корпуса. |

## 2. Поисковые системы и агенты для научной литературы

Кандидаты в бейзлайны и контекст практической значимости.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| ★ Crase: Structurally-bounded Agentic Graph Exploration for Scholarly DeepSearch | 2026 | Hazra et al. | [arXiv](https://arxiv.org/abs/2608.24809), [code](https://github.com/RadiantCrystal/CRASE) | Один раунд поиска seed-статей, фиксированная окрестность 1.5 хопа, отсев рёбер по entailment, PageRank с учётом свежести. Главный бейзлайн «фиксированного расширения». Структурно не достаёт цели дальше 1.5 хопа и чувствителен к плохим seed-статьям, то есть к терминологическому разрыву. |
| PaperQA2 | 2024 | Skarlinski et al. | [arXiv](https://arxiv.org/abs/2409.13740), [code](https://github.com/Future-House/paper-qa) | Агент с инструментом обхода цитирований. Показывает, что графовые инструменты у агентов уже есть, а набора задач, выделяющего их пользу при терминологическом разрыве, нет. |
| OpenScholar / ScholarQABench | 2024 | Asai et al. | [arXiv](https://arxiv.org/abs/2411.14199), [code](https://github.com/AkariAsai/OpenScholar) | Поиск и синтез ответа по литературе. Помогает разграничить поиск статей и генерацию ответа. |
| LitLLM | 2024 | Agarwal et al. | [arXiv](https://arxiv.org/abs/2402.01788) | Поиск, переранжирование и генерация Related Work. Периферия. |
| Undermind whitepaper | TODO | Undermind | TODO | Коммерческий агент; тезис о том, что keyword-поиск пропускает работы с другой терминологией. Результаты — внутреннее сравнение вендора. |
| Elicit | — | Elicit | [elicit.com](https://elicit.com) | Коммерческий поиск без совпадения ключевых слов. Подтверждает практическую значимость проблемы; методология не раскрыта. |
| Which academic search systems are suitable for systematic reviews? | 2020 | Gusenbauer, Haddaway | [DOI](https://doi.org/10.1002/jrsm.1378) | Сравнение 28 академических поисковых систем: Google Scholar не подходит как основной инструмент полного поиска. |
| The Semantic Scholar Open Data Platform | 2023 | Kinney et al. | [arXiv](https://arxiv.org/abs/2301.10140) | Описание графа и API Semantic Scholar — вероятного источника данных. |

## 3. Терминологический разрыв и ограничения эмбеддингов

Обоснование того, почему текстового и dense-поиска недостаточно.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| The Vocabulary Problem in Human-System Communication | 1987 | Furnas et al. | [DOI](https://doi.org/10.1145/32206.32212) | Каноническое описание vocabulary mismatch: люди редко называют одно понятие одинаково. |
| ★ Fish Oil, Raynaud's Syndrome, and Undiscovered Public Knowledge | 1986 | Swanson | [DOI](https://doi.org/10.1353/pbm.1986.0087) | Модель ABC: взаимодополняющие знания лежат в не связанных между собой литературах с разным языком. Концептуальный предок нашей постановки. |
| SPECTER | 2020 | Cohan et al. | [arXiv](https://arxiv.org/abs/2004.07180), [code](https://github.com/allenai/specter) | Эмбеддинги статей, обученные на цитированиях. Граф сжат в меру близости, структура пути теряется. |
| SciRepEval / SPECTER2 | 2023 | Singh et al. | [arXiv](https://arxiv.org/abs/2211.13308), [code](https://github.com/allenai/scirepeval) | Текущий стандарт научных эмбеддингов; dense-бейзлайн. |
| BEIR | 2021 | Thakur et al. | [arXiv](https://arxiv.org/abs/2104.08663), [code](https://github.com/beir-cellar/beir) | Dense-ретриверы в zero-shot часто уступают BM25, в том числе на научных наборах. |
| DORIS-MAE | 2023 | Wang et al. | [arXiv](https://arxiv.org/abs/2310.04678) | Сложные многоаспектные научные запросы; эмбеддинги на них заметно слабее. |
| BRIGHT | 2024 | Su et al. | [arXiv](https://arxiv.org/abs/2407.12883), [code](https://github.com/xlang-ai/BRIGHT) | Поиск, требующий рассуждения сверх поверхностного сходства; сильные эмбеддеры резко падают. |
| ★ On the Theoretical Limitations of Embedding-Based Retrieval (LIMIT) | 2025 | Weller et al. | [arXiv](https://arxiv.org/abs/2508.21038) | Размерность эмбеддинга ограничивает, какие top-k множества документов вообще можно вернуть. Теоретический аргумент для задач с ответом-множеством. |
| ★ Same Problem, Different Field | 2026 | Kulikowski | [arXiv](https://arxiv.org/abs/2609.07595), [code](https://github.com/ErykKul/same-problem-different-field) | Одна задача под разными именами в разных областях; научные эмбеддинги проигрывают TF-IDF. Прямая опора для оси «терминологический разрыв» и пример проверки, что задача именно про терминологию. |
| HyDE | 2022 | Gao et al. | [arXiv](https://arxiv.org/abs/2212.10496), [code](https://github.com/texttron/hyde) | LLM генерирует гипотетический документ на языке корпуса. Сильный text-only способ обойти разрыв словаря без графа. |
| Evaluating the Robustness of Retrieval Pipelines with Query Variation Generators | 2022 | Penha et al. | [arXiv](https://arxiv.org/abs/2111.13057) | Таксономия вариаций запроса при сохранении намерения. Пример проверки того, что переформулировка сохраняет смысл запроса. |

## 4. Граф цитирований и контекст цитирования

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| Guidelines for Snowballing in Systematic Literature Studies | 2014 | Wohlin | [DOI](https://doi.org/10.1145/2601248.2601268) | Методология backward/forward snowballing; обоснование того, что обход ссылок — стандартная практика. |
| ★ MIR: Methodology Inspiration Retrieval | 2025 | Garikaparthi et al. | [arXiv](https://arxiv.org/abs/2506.00249), [code](https://github.com/Anikethh/Methodology-Inspiration-Retrieval) | Граф цитирований с разметкой намерения используется для поиска методологических предшественников за пределами семантической близости. Продолжение: HyBIRD ([arXiv](https://arxiv.org/abs/2606.28336)). |
| CiteME | 2024 | Press et al. | [arXiv](https://arxiv.org/abs/2407.12861) | Найти цитируемую статью по контексту цитирования; близкий по механике бенчмарк. |
| SciCite | 2019 | Cohan et al. | [arXiv](https://arxiv.org/abs/1904.01608), [code](https://github.com/allenai/scicite) | Классификация назначения цитирования (background / method / result). Для оси «семантика отношения». |
| MultiCite | 2022 | Lauscher et al. | [arXiv](https://arxiv.org/abs/2107.00414), [code](https://github.com/allenai/multicite) | Контекст цитирования часто занимает несколько предложений. Важно для извлечения того, что заимствовано по ребру. |
| OpenAlex | 2022 | Priem et al. | [arXiv](https://arxiv.org/abs/2205.01833) | Открытый граф научных публикаций; альтернативный источник данных. |

## 5. Многошаговость, композиция и шорткаты

Методология построения задач, которые действительно требуют нескольких источников.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| ★ Compositional Questions Do Not Necessitate Multi-hop Reasoning | 2019 | Min et al. | [arXiv](https://arxiv.org/abs/1906.02900) | Большая часть «многошаговых» вопросов решается по одному фрагменту. Главный риск для нашего бенчмарка: связный подграф не означает необходимости нескольких статей. |
| ★ MuSiQue | 2022 | Trivedi et al. | [arXiv](https://arxiv.org/abs/2108.00573), [code](https://github.com/StonyBrookNLP/musique) | Композиция вопросов из одношаговых с фильтрацией шорткатов. Ближайший аналог проверки, что шаги пути нужны для решения. |
| HotpotQA | 2018 | Yang et al. | [arXiv](https://arxiv.org/abs/1809.09600), [code](https://github.com/hotpotqa/hotpot) | Разметка supporting facts; предок раздельной оценки свидетельств. |
| MultiHop-RAG | 2024 | Tang, Yang | [arXiv](https://arxiv.org/abs/2401.15391), [code](https://github.com/yixuantt/MultiHop-RAG) | Раздельная оценка извлечения свидетельств и ответа по нескольким документам. |
| BrowseComp | 2025 | Wei et al. | [arXiv](https://arxiv.org/abs/2504.12516) | Принцип «трудно найти, легко проверить» и построение вопроса от ответа. |

## 6. Агентский харнесс и обучение

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| ReAct | 2022 | Yao et al. | [arXiv](https://arxiv.org/abs/2210.03629) | Базовая схема цикла «рассуждение — действие — наблюдение» для харнесса. |
| Search-R1 | 2025 | Jin et al. | [arXiv](https://arxiv.org/abs/2503.09516), [code](https://github.com/PeterGriffinJin/Search-R1) | RL-обучение агента с поисковым инструментом; рецепт на случай, если дойдём до обучения. |

## 7. Соседние задачи

Задевают тему слабо; оставлены для полноты.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| OpenNovelty | 2026 | TODO | [arXiv](https://arxiv.org/abs/2601.01576) | Оценка новизны через плоский семантический поиск. Полезные детали: защита от инъекций в тексте статей, проверка цитат, определение даты публикации. |
| PaperAsk | TODO | TODO | TODO | Надёжность LLM в работе со статьями (поиск цитирований, чтение). Примеры типичных ошибок для раздела об оценке. |
| PRISM, NoveltyRank, MemoNoveltyAgent, ScholarPeer | 2025–2026 | TODO | TODO | Агенты оценки новизны и рецензирования на плоском retrieval, без обхода графа. |

## Выводы обзора

Существующие работы покрывают по отдельности: синтетические запросы по одному шагу ссылок (PaSa, LitSearch), многошаговые задачи по цитированиям (AutoResearchBench, SciNetBench), агентов с раскрытием цитирований (PaSa, PaperPilot, PaperQA2), фиксированное расширение графа (Crase) и композицию свидетельств без графа (BRIGHT-Pro). Эмбеддинги, в том числе обученные на цитированиях, плохо переносят терминологический разрыв (Same Problem, Different Field) и ограничены теоретически для ответов-множеств (LIMIT).

Незанятым остаётся сочетание:

1. **фабрики задач** на многошаговых путях графа цитирований, вдоль которых меняется терминология, так что целевые статьи не находятся прямым поиском, но достижимы переходами по ссылкам и цитированиям;
2. **многошаговых связей в обе стороны** (references и citations) с проверкой, что шаги действительно нужны для решения, а не только использованы при генерации (Min et al., MuSiQue);
3. **контролируемого сравнения** текстового поиска, фиксированного расширения (Crase) и агентского обхода, показывающего, при каких длинах пути граф цитирований помогает.

Базовые методы для сравнения: Crase (фиксированное расширение по графу цитирований), PaSa (поисковый агент с раскрытием ссылок) и Google Scholar (существующая поисковая система без обхода графа).
