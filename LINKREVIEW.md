# LinkReview

★ — ключевые работы. Полные библиографические записи — в [paper/references.bib](paper/references.bib).

Для препринтов указан год первой публикации на arXiv; он может отличаться от года конференционной версии. Для журнальных и конференционных записей указан год соответствующей публикации. Elicit — веб-сервис, Undermind — технический отчёт компании; они выделены как отдельные типы источников.

## 1. Ближайшие бенчмарки и датасеты

От этих работ нужно отстраиваться при формулировке новизны.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| ★ Multi-Turn Agentic Scientific Literature Search via Workflow Induction (PaperPilot) | 2026 | Li et al. | [arXiv](https://arxiv.org/abs/2607.00597) | Агент строит граф поисковых операций (keyword search, citation expansion, фильтры); направления predecessor / successor / sibling. Есть обучение агента. Терминологический разрыв не выделен как отдельный источник сложности. |
| ★ AutoResearchBench: Benchmarking AI Agents on Complex Scientific Literature Discovery | 2026 | Xiong et al. | [arXiv](https://arxiv.org/abs/2604.25256), [code](https://github.com/CherYou/AutoResearchBench) | 1000 сложных задач поиска статей, multi-hop через цитирования, подавление лексических подсказок, проверки минимальной достаточности. Многошаговые переходы по цитированиям здесь уже есть. Сложность держится на размытии формулировки, а не на терминологическом разрыве; у агента нет графовых инструментов. |
| ★ SciNet: Evaluating AI Agents in Relation-Aware Scientific Literature Retrieval | 2025 | Shao et al. | [arXiv](https://arxiv.org/abs/2601.03260), [code](https://github.com/tsinghua-fib-lab/SciNet) | Таксономия ego-centric / pair-wise / path-wise задач по графу OpenAlex, включая восстановление путей развития идей. Занимает пространство «типов графовых вопросов», поэтому новизну нельзя строить на одной таксономии или многошаговости. |
| ★ PaSa: An LLM Agent for Comprehensive Academic Paper Search | 2025 | He et al. | [arXiv](https://arxiv.org/abs/2501.10120), [code](https://github.com/bytedance/pasa) | Ближайший аналог фабрики: ~35 тыс. синтетических запросов, агент с раскрытием ссылок, RL-обучение. Эталон задаётся одним шагом назад (ссылки из Related Work одной статьи), а запрос генерируется из того же абзаца, где стоят ссылки, поэтому лексический разрыв минимален по построению. |
| LitSearch: A Retrieval Benchmark for Scientific Literature Search | 2024 | Ajith et al. | [arXiv](https://arxiv.org/abs/2407.18940), [code](https://github.com/princeton-nlp/LitSearch) | Запросы, сгенерированные по контекстам цитирования, и запросы от авторов статей. Обычно 1–2 целевые статьи на запрос, композиции свидетельств нет. |
| SPAR: Scholar Paper Retrieval with LLM-based Agents for Enhanced Academic Search | 2025 | Shi et al. | [arXiv](https://arxiv.org/abs/2507.15245) | Мультиагентный поиск с RefChain exploration и эволюцией запроса; SPARBench — бенчмарк с экспертной оценкой релевантности. |
| ★ Rethinking Reasoning-Intensive Retrieval: Evaluating and Advancing Retrievers in Agentic Search Systems (BRIGHT-Pro) | 2026 | Zhao et al. | [arXiv](https://arxiv.org/abs/2605.04018) | Оценка ретриверов как построения «портфеля» взаимодополняющих свидетельств в статическом и агентском режимах. Ближайший аналог по идее композиции, но без графа цитирований и без научного корпуса. |

## 2. Поисковые системы и агенты для научной литературы

Кандидаты в бейзлайны и контекст практической значимости.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| ★ Structurally-bounded Agentic Graph Exploration for Evidence-Grounded Scholarly DeepSearch (Crase) | 2026 | Hazra et al. | [arXiv](https://arxiv.org/abs/2608.24809), [code](https://github.com/RadiantCrystal/CRASE) | Один раунд поиска seed-статей, фиксированная окрестность 1.5 хопа, отсев рёбер по entailment, PageRank с учётом свежести. Главный бейзлайн «фиксированного расширения». Структурно не достаёт цели дальше 1.5 хопа и чувствителен к плохим seed-статьям, то есть к терминологическому разрыву. |
| Language agents achieve superhuman synthesis of scientific knowledge (PaperQA2) | 2024 | Skarlinski et al. | [arXiv](https://arxiv.org/abs/2409.13740), [code](https://github.com/Future-House/paper-qa) | Агент с инструментом обхода цитирований. Показывает, что графовые инструменты у агентов уже есть, а набора задач, выделяющего их пользу при терминологическом разрыве, нет. |
| OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented LMs (ScholarQABench) | 2024 | Asai et al. | [arXiv](https://arxiv.org/abs/2411.14199), [code](https://github.com/AkariAsai/OpenScholar) | Поиск и синтез ответа по литературе. Помогает разграничить поиск статей и генерацию ответа. |
| LitLLM: A Toolkit for Scientific Literature Review | 2024 | Agarwal et al. | [arXiv](https://arxiv.org/abs/2402.01788) | Поиск, переранжирование и генерация Related Work. Периферия. |
| Benchmarking the Undermind Search Assistant | 2024 | Hartke, Ramette | [Отчёт компании](https://www.undermind.ai/whitepaper.pdf) | Коммерческий агент; тезис о том, что keyword-поиск пропускает работы с другой терминологией. Результаты — внутреннее сравнение вендора. |
| Elicit | — | Elicit | [elicit.com](https://elicit.com) | Коммерческий поиск без совпадения ключевых слов. Подтверждает практическую значимость проблемы; методология не раскрыта. |
| Which academic search systems are suitable for systematic reviews or meta-analyses? Evaluating retrieval qualities of Google Scholar, PubMed, and 26 other resources | 2020 | Gusenbauer, Haddaway | [DOI](https://doi.org/10.1002/jrsm.1378) | Сравнение 28 академических поисковых систем: Google Scholar не подходит как основной инструмент полного поиска. |
| The Semantic Scholar Open Data Platform | 2023 | Kinney et al. | [arXiv](https://arxiv.org/abs/2301.10140) | Описание графа и API Semantic Scholar — вероятного источника данных. |

## 3. Терминологический разрыв и ограничения эмбеддингов

Обоснование того, почему текстового и dense-поиска недостаточно.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| The vocabulary problem in human-system communication | 1987 | Furnas et al. | [DOI](https://doi.org/10.1145/32206.32212) | Каноническое описание vocabulary mismatch: люди редко называют одно понятие одинаково. |
| ★ Fish Oil, Raynaud's Syndrome, and Undiscovered Public Knowledge | 1986 | Swanson | [DOI](https://doi.org/10.1353/pbm.1986.0087) | Модель ABC: взаимодополняющие знания лежат в не связанных между собой литературах с разным языком. Концептуальный предок нашей постановки. |
| SPECTER: Document-level Representation Learning using Citation-informed Transformers | 2020 | Cohan et al. | [arXiv](https://arxiv.org/abs/2004.07180), [code](https://github.com/allenai/specter) | Эмбеддинги статей, обученные на цитированиях. Граф сжат в меру близости, структура пути теряется. |
| SciRepEval: A Multi-Format Benchmark for Scientific Document Representations (SPECTER2) | 2022 | Singh et al. | [arXiv](https://arxiv.org/abs/2211.13308), [code](https://github.com/allenai/scirepeval) | Текущий стандарт научных эмбеддингов; dense-бейзлайн. |
| BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of Information Retrieval Models | 2021 | Thakur et al. | [arXiv](https://arxiv.org/abs/2104.08663), [code](https://github.com/beir-cellar/beir) | Dense-ретриверы в zero-shot часто уступают BM25, в том числе на научных наборах. |
| DORIS-MAE: Scientific Document Retrieval using Multi-level Aspect-based Queries | 2023 | Wang et al. | [arXiv](https://arxiv.org/abs/2310.04678) | Сложные многоаспектные научные запросы; эмбеддинги на них заметно слабее. |
| BRIGHT: A Realistic and Challenging Benchmark for Reasoning-Intensive Retrieval | 2024 | Su et al. | [arXiv](https://arxiv.org/abs/2407.12883), [code](https://github.com/xlang-ai/BRIGHT) | Поиск, требующий рассуждения сверх поверхностного сходства; сильные эмбеддеры резко падают. |
| ★ On the Theoretical Limitations of Embedding-Based Retrieval (LIMIT) | 2025 | Weller et al. | [arXiv](https://arxiv.org/abs/2508.21038) | Размерность эмбеддинга ограничивает, какие top-k множества документов вообще можно вернуть. Теоретический аргумент для задач с ответом-множеством. |
| ★ Same Problem, Different Field: Cross-Domain Solution Import via Domain-Stripped Computational Fingerprints | 2026 | Kulikowski | [arXiv](https://arxiv.org/abs/2609.07595), [code](https://github.com/ErykKul/same-problem-different-field) | Одна задача под разными именами в разных областях; научные эмбеддинги проигрывают TF-IDF. Прямая опора для оси «терминологический разрыв» и пример проверки, что задача именно про терминологию. |
| Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE) | 2022 | Gao et al. | [arXiv](https://arxiv.org/abs/2212.10496), [code](https://github.com/texttron/hyde) | LLM генерирует гипотетический документ на языке корпуса. Сильный text-only способ обойти разрыв словаря без графа. |
| Evaluating the Robustness of Retrieval Pipelines with Query Variation Generators | 2021 | Penha et al. | [arXiv](https://arxiv.org/abs/2111.13057) | Таксономия вариаций запроса при сохранении намерения. Пример проверки того, что переформулировка сохраняет смысл запроса. |

## 4. Граф цитирований и контекст цитирования

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| Guidelines for snowballing in systematic literature studies and a replication in software engineering | 2014 | Wohlin | [DOI](https://doi.org/10.1145/2601248.2601268) | Методология backward/forward snowballing; обоснование того, что обход ссылок — стандартная практика. |
| ★ MIR: Methodology Inspiration Retrieval for Scientific Research Problems | 2025 | Garikaparthi et al. | [arXiv](https://arxiv.org/abs/2506.00249), [code](https://github.com/Anikethh/Methodology-Inspiration-Retrieval) | Граф цитирований с разметкой намерения используется для поиска методологических предшественников за пределами семантической близости. |
| HyBIRD: Hyperbolic Bridge Retrieval and Diagnosis for Methodology Inspiration Retrieval | 2026 | Yang et al. | [arXiv](https://arxiv.org/abs/2606.28336) | Продолжение направления MIR: поиск методологических связей между научными работами. |
| CiteME: Can Language Models Accurately Cite Scientific Claims? | 2024 | Press et al. | [arXiv](https://arxiv.org/abs/2407.12861) | Найти цитируемую статью по контексту цитирования; близкий по механике бенчмарк. |
| Structural Scaffolds for Citation Intent Classification in Scientific Publications (SciCite) | 2019 | Cohan et al. | [arXiv](https://arxiv.org/abs/1904.01608), [code](https://github.com/allenai/scicite) | Классификация назначения цитирования (background / method / result). Для оси «семантика отношения». |
| MultiCite: Modeling realistic citations requires moving beyond the single-sentence single-label setting | 2021 | Lauscher et al. | [arXiv](https://arxiv.org/abs/2107.00414), [code](https://github.com/allenai/multicite) | Контекст цитирования часто занимает несколько предложений. Важно для извлечения того, что заимствовано по ребру. |
| OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts | 2022 | Priem et al. | [arXiv](https://arxiv.org/abs/2205.01833) | Открытый граф научных публикаций; альтернативный источник данных. |

## 5. Многошаговость, композиция и шорткаты

Работы о многошаговых задачах и обходных способах решения; помогают различать длину пути генерации и число шагов, необходимых для поиска ответа.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| ★ Compositional Questions Do Not Necessitate Multi-hop Reasoning | 2019 | Min et al. | [arXiv](https://arxiv.org/abs/1906.02900) | Большая часть «многошаговых» вопросов решается по одному фрагменту. Главный риск для нашего бенчмарка: связный подграф не означает необходимости нескольких статей. |
| ★ MuSiQue: Multihop Questions via Single-hop Question Composition | 2021 | Trivedi et al. | [arXiv](https://arxiv.org/abs/2108.00573), [code](https://github.com/StonyBrookNLP/musique) | Композиция вопросов из одношаговых с фильтрацией шорткатов. Показывает, почему длина пути генерации сама по себе не гарантирует многошагового решения. |
| HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question Answering | 2018 | Yang et al. | [arXiv](https://arxiv.org/abs/1809.09600), [code](https://github.com/hotpotqa/hotpot) | Разметка supporting facts; предок раздельной оценки свидетельств. |
| MultiHop-RAG: Benchmarking Retrieval-Augmented Generation for Multi-Hop Queries | 2024 | Tang et al. | [arXiv](https://arxiv.org/abs/2401.15391), [code](https://github.com/yixuantt/MultiHop-RAG) | Раздельная оценка извлечения свидетельств и ответа по нескольким документам. |
| BrowseComp: A Simple Yet Challenging Benchmark for Browsing Agents | 2025 | Wei et al. | [arXiv](https://arxiv.org/abs/2504.12516) | Принцип «трудно найти, легко проверить» и построение вопроса от ответа. |

## 6. Агентский харнесс и обучение

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| ReAct: Synergizing Reasoning and Acting in Language Models | 2022 | Yao et al. | [arXiv](https://arxiv.org/abs/2210.03629) | Базовая схема цикла «рассуждение — действие — наблюдение» для харнесса. |
| Search-R1: Training LLMs to Reason and Leverage Search Engines with Reinforcement Learning | 2025 | Jin et al. | [arXiv](https://arxiv.org/abs/2503.09516), [code](https://github.com/PeterGriffinJin/Search-R1) | RL-обучение агента с поисковым инструментом; рецепт на случай, если дойдём до обучения. |

## 7. Соседние задачи

Задевают тему слабо; оставлены для полноты.

| Работа | Год | Авторы | Ссылки | Суть и связь с нашей работой |
|---|---|---|---|---|
| OpenNovelty: An LLM-powered Agentic System for Verifiable Scholarly Novelty Assessment | 2026 | Zhang et al. | [arXiv](https://arxiv.org/abs/2601.01576) | Оценка новизны через плоский семантический поиск. Полезные детали: защита от инъекций в тексте статей, проверка цитат, определение даты публикации. |
| PaperAsk: A Benchmark for Reliability Evaluation of LLMs in Paper Search and Reading | 2025 | Wu et al. | [arXiv](https://arxiv.org/abs/2510.22242) | Надёжность LLM в работе со статьями (поиск цитирований, чтение). Примеры типичных ошибок для раздела об оценке. |
| PRISM: A Multi-Dimensional Benchmark for Evaluating LLM Peer Reviewers | 2026 | Ngoc Phan Phuoc Loc et al. | [arXiv](https://arxiv.org/abs/2605.26730) | Бенчмарк качества научных рецензий: глубина анализа, оценка новизны, выявление недостатков и конструктивность. Контекст оценки научных агентов. |
| NoveltyRank: A Retrieval-Augmented Framework for Conceptual Novelty Estimation in AI Research | 2025 | Yan et al. | [arXiv](https://arxiv.org/abs/2512.14738) | Оценка концептуальной новизны с извлечением связанных работ. Соседняя задача для поисковой обвязки. |
| MemoNoveltyAgent: A Historical Research Memory-Aware Agent Workflow for Paper Novelty Assessment | 2026 | Hou et al. | [arXiv](https://arxiv.org/abs/2603.20884) | Агентская оценка новизны с памятью о предшествующих исследованиях. Соседняя задача. |
| ScholarPeer: A Context-Aware Multi-Agent Framework for Automated Peer Review | 2026 | Goyal et al. | [arXiv](https://arxiv.org/abs/2601.22638) | Мультиагентная система автоматического рецензирования с учётом контекста литературы. Соседняя задача. |

## Выводы обзора

Существующие работы покрывают по отдельности: синтетические запросы по одному шагу ссылок (PaSa, LitSearch), многошаговые задачи по цитированиям (AutoResearchBench, SciNet), агентов с раскрытием цитирований (PaSa, PaperPilot, PaperQA2), фиксированное расширение графа (Crase) и композицию свидетельств без графа (BRIGHT-Pro). Эмбеддинги, в том числе обученные на цитированиях, плохо переносят терминологический разрыв (Same Problem, Different Field) и ограничены теоретически для ответов-множеств (LIMIT).

Незанятым остаётся сочетание:

1. **фабрики задач** на многошаговых путях графа цитирований, вдоль которых меняется терминология, так что целевые статьи не находятся прямым поиском, но достижимы переходами по ссылкам и цитированиям;
2. **путей по ссылкам и цитированиям в обе стороны** (references и citations), связывающих стартовую статью с целевыми;
3. **контролируемого сравнения** текстового поиска, фиксированного расширения (Crase) и агентского обхода, показывающего, при каких длинах пути граф цитирований помогает.

Базовые методы для сравнения: Crase (фиксированное расширение по графу цитирований), PaSa (поисковый агент с раскрытием ссылок) и Google Scholar (существующая поисковая система без явного обхода графа пользователем или агентом).

В принятой постановке промежуточные статьи могут находиться прямым поиском. Правильность задачи проверяется по трём условиям: соответствие целей запросу, недоступность целей прямым поиском и вход в путь. Необходимость всех шагов пути не является отдельным требованием.
