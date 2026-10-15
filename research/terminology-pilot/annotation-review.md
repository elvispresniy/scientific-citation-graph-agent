# Калибровочная разметка: 30 вопросов, 30 пар

**Новый численный этап:** [полная сетка сравнения словаря и частей текста](metric-comparison.md). Ниже сохранён отдельный качественный проход по 30 калибровочным парам.

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

- **Точное совпадение — 5 (`exact`).** Термин присутствует в статье в той же форме; различие регистра букв допускается. Например, «binary symmetric channel» из вопроса № 4 дословно встречается в аннотации статьи. Это совпадение конкретного термина, а не подтверждение всей пары.

- **Та же формулировка с грамматическим изменением — 1 (`inflection`).** Например, «Delaunay triangulation» в вопросе № 1 и «Delaunay triangulations» в статье отличаются только единственным и множественным числом. Нового научного обозначения здесь нет.

- **Сокращение и его расшифровка — 3 (`abbreviation`).** Например, в вопросе № 10 используется «MCMC», а в аннотации — «Markov Chain Monte Carlo». Различаются записи названия метода, а не сам метод.

- **Обычное синонимичное выражение — 2 (`synonym`).** Например, «mesh generation» и «grid-generation» в паре № 1 обозначают построение сетки. Это обычная вариативность словаря в данном контексте; её отдельно отличаем от смены специальной терминологии между научными направлениями.

- **Описание понятия или его конкретная разновидность — 49 (`descriptive`).** Например, вопрос № 3 говорит о «deep learning» в целом, а статья описывает конкретную «deep siamese network» — глубокую сиамскую сеть. Эта метка также используется, когда статья описывает требуемую возможность без того же термина. Для составного условия она может покрывать лишь часть требования; какая именно часть подтверждена, указано в комментарии. Она не означает, что сопоставленные выражения полностью взаимозаменяемы.

- **Подтверждённая смена специального термина — 0 (`terminology_shift`).** Эту метку можно ставить, когда установлено, что разные научные обозначения относятся к одному и тому же понятию. Простого отсутствия общих слов или общей тематики для неё недостаточно. В текущем проходе таких подтверждённых случаев нет.

- **Соответствие не видно в названии и аннотации — 64 (`not_visible`).** Например, вопрос № 11 требует определённую числовую константу из доказательства, но аннотация её не приводит. Метка означает нехватку свидетельства в просмотренных полях. Она не утверждает, что условия нет в полном тексте или что статья не подходит.

- **Есть связанное выражение, но соответствие не установлено — 22 (`uncertain`).** Например, «IAM database» в паре № 7 связано с указанным в вопросе названием набора данных, но не позволяет подтвердить, что это именно «IAM Online Handwriting Database». В отличие от предыдущей метки, здесь есть конкретный фрагмент для сопоставления, однако его недостаточно для уверенного решения.

## Насколько статья отвечает вопросу целиком

Помимо отдельных терминов, каждой из **30 пар** присвоена общая предварительная оценка. Эти количества имеют другой знаменатель: речь уже о парах «вопрос — статья», а не о 146 понятиях.

- **Соответствие подтверждается доступным текстом — 8 пар (`supported`).** Основное содержание запроса подтверждено названием и аннотацией. Например, в паре № 1 явно описано построение сеток по Делоне.

- **Подтверждена только часть требований — 16 пар (`partial`).** Часть условий видна, остальные требуют проверки. Например, в паре № 8 подтверждена тема байесовских сетей, но не исключение скрытых марковских моделей. Это не оценка статьи как «частично правильного ответа» по полному тексту.

- **Недостаточно сведений для оценки пары — 5 пар (`uncertain`).** В первую очередь это подробные вопросы AutoResearchBench Deep, для которых нужны доказательства, сноски или таблицы. Здесь по аннотации нельзя уверенно подтвердить или отвергнуть ответ.

- **Доступный текст не подтверждает ожидаемый тип ответа — 1 пара (`not_supported`).** Это описанная выше пара № 29: вопрос требует обзор, а по опубликованной ссылке получена статья с новым исследовательским методом. Оценка предварительная, поскольку сначала нужно разобраться с расхождением названия и идентификатора.

## Как читать подробные карточки

В каждой карточке ниже приведены исходный вопрос, название и оригинальная аннотация выбранной статьи. Таблица показывает выделенное понятие вопроса, тип соответствия, точный фрагмент статьи и объяснение решения. Отсутствие фрагмента обозначено знаком «—».

В конце карточки дана оценка всей пары и указано, нужны ли дополнительные сведения: полный текст, библиография, сведения об авторах или дата публикации. Уверенность относится к принятому решению о разметке: например, можно быть уверенным, что данных недостаточно. Завершённая разметка языковой моделью ещё не является проверенным человеком эталоном.

## Пары

### 1. scholarquest:BQ_001749

**Оригинальный вопрос:**

> Which papers study mesh generation using Delaunay triangulation?

**Цель:** [Multi-resolution unstructured grid-generation for geophysical applications on the sphere](https://arxiv.org/abs/1512.00307) — `arxiv:1512.00307`.

**Оригинальный abstract:**

> An algorithm for the generation of non-uniform unstructured grids on ellipsoidal geometries is described. This technique is designed to generate high quality triangular and polygonal meshes appropriate for general circulation modelling on the sphere, including applications to atmospheric and ocean simulation, and numerical weather predication. Using a recently developed Frontal-Delaunay-refinement technique, a method for the construction of high-quality unstructured ellipsoidal Delaunay triangulations is introduced. A dual polygonal grid, derived from the associated Voronoi diagram, is also optionally generated as a by-product. Compared to existing techniques, it is shown that the Frontal-Delaunay approach typically produces grids with near-optimal element quality and smooth grading characteristics, while imposing relatively low computational expense. Initial results are presented for a selection of uniform and non-uniform ellipsoidal grids appropriate for large-scale geophysical applications. The use of user-defined mesh-sizing functions to generate smoothly graded, non-uniform grids is discussed.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| mesh generation | synonym | title: «grid-generation» | Mesh generation ↔ grid-generation: обычная вариативность обозначения построения сетки в этом контексте. |
| Delaunay triangulation | inflection | abstract: «Delaunay triangulations» | Различается число существительного. |

**Соответствие:** `supported`; нужны дополнительные источники: нет; уверенность: `high`.

Генерация треугольных сеток по Делоне прямо описана. Grid/mesh здесь обычные обозначения сетки, а не установленный междисциплинарный разрыв.

### 2. scholarquest:BQ_000320

**Оригинальный вопрос:**

> I am looking for papers on the Perceptron algorithm that exclude neural networks from their scope.

**Цель:** [Negative spherical perceptron](https://arxiv.org/abs/1306.3980) — `arxiv:1306.3980`.

**Оригинальный abstract:**

> In this paper we consider the classical spherical perceptron problem. This problem and its variants have been studied in a great detail in a broad literature ranging from statistical physics and neural networks to computer science and pure geometry. Among the most well known results are those created using the machinery of statistical physics in \cite{Gar88}. They typically relate to various features ranging from the storage capacity to typical overlap of the optimal configurations and the number of incorrectly stored patterns. In \cite{SchTir02,SchTir03,TalBook} many of the predictions of the statistical mechanics were rigorously shown to be correct. In our own work \cite{StojnicGardGen13} we then presented an alternative way that can be used to study the spherical perceptrons as well. Among other things we reaffirmed many of the results obtained in \cite{SchTir02,SchTir03,TalBook} and thereby confirmed many of the predictions established by the statistical mechanics. Those mostly relate to spherical perceptrons with positive thresholds (which we will typically refer to as the positive spherical perceptrons). In this paper we go a step further and attack the negative counterpart, i.e. the perceptron with negative thresholds. We present a mechanism that can be used to analyze many features of such a model. As a concrete example, we specialize our results for a particular feature, namely the storage capacity. The results we obtain for the storage capacity seem to indicate that the negative case could be more combinatorial in nature and as such a somewhat harder challenge than the positive counterpart.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| Perceptron algorithm | uncertain | abstract: «classical spherical perceptron problem» | Модель spherical perceptron связана с перцептроном, но постановка задачи не тождественна Perceptron algorithm. |
| exclude neural networks from their scope | uncertain | abstract: «statistical physics and neural networks» | Упоминание neural networks относится к литературе; оно не подтверждает и не опровергает исключение этой темы из содержания самой работы. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `medium`.

Статья посвящена spherical perceptron, но это не обязательно классический алгоритм обновления весов Perceptron. Исключение neural networks по аннотации установить нельзя.

### 3. scholarquest:BQ_001805

**Оригинальный вопрос:**

> Which papers explore visual content-based indexing and retrieval using deep learning for feature extraction?

**Цель:** [Image similarity using Deep CNN and Curriculum Learning](https://arxiv.org/abs/1709.08761) — `arxiv:1709.08761`.

**Оригинальный abstract:**

> Image similarity involves fetching similar looking images given a reference image. Our solution called SimNet, is a deep siamese network which is trained on pairs of positive and negative images using a novel online pair mining strategy inspired by Curriculum learning. We also created a multi-scale CNN, where the final image embedding is a joint representation of top as well as lower layer embedding's. We go on to show that this multi-scale siamese network is better at capturing fine grained image similarities than traditional CNN's.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| visual content-based indexing and retrieval | descriptive | abstract: «fetching similar looking images given a reference image» | Описана retrieval-часть составного требования; indexing не подтверждён. |
| deep learning | descriptive | abstract: «a deep siamese network» | Конкретная разновидность deep learning, а не другое название всей области. |
| feature extraction | descriptive | abstract: «the final image embedding is a joint representation of top as well as lower layer embedding's» | Описано построение признакового представления изображения; термин feature extraction не употреблён. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `medium`.

Поиск похожих изображений и нейросетевое представление явно видны; отдельный компонент indexing в аннотации не описан.

### 4. scholarquest:BQ_002338

**Оригинальный вопрос:**

> Which papers evaluate error-correcting codes over the binary symmetric channel?

**Цель:** [LP/SDP Hierarchy Lower Bounds for Decoding Random LDPC Codes](https://arxiv.org/abs/1410.4241) — `arxiv:1410.4241`.

**Оригинальный abstract:**

> Random (dv,dc)-regular LDPC codes are well-known to achieve the Shannon capacity of the binary symmetric channel (for sufficiently large dv and dc) under exponential time decoding. However, polynomial time algorithms are only known to correct a much smaller fraction of errors. One of the most powerful polynomial-time algorithms with a formal analysis is the LP decoding algorithm of Feldman et al. which is known to correct an Omega(1/dc) fraction of errors. In this work, we show that fairly powerful extensions of LP decoding, based on the Sherali-Adams and Lasserre hierarchies, fail to correct much more errors than the basic LP-decoder. In particular, we show that:
>   1) For any values of dv and dc, a linear number of rounds of the Sherali-Adams LP hierarchy cannot correct more than an O(1/dc) fraction of errors on a random (dv,dc)-regular LDPC code.
>   2) For any value of dv and infinitely many values of dc, a linear number of rounds of the Lasserre SDP hierarchy cannot correct more than an O(1/dc) fraction of errors on a random (dv,dc)-regular LDPC code.
>   Our proofs use a new stretching and collapsing technique that allows us to leverage recent progress in the study of the limitations of LP/SDP hierarchies for Maximum Constraint Satisfaction Problems (Max-CSPs). The problem then reduces to the construction of special balanced pairwise independent distributions for Sherali-Adams and special cosets of balanced pairwise independent subgroups for Lasserre.
>   Some of our techniques are more generally applicable to a large class of Boolean CSPs called Min-Ones. In particular, for k-Hypergraph Vertex Cover, we obtain an improved integrality gap of $k-1-ε$ that holds after a \emph{linear} number of rounds of the Lasserre hierarchy, for any k = q+1 with q an arbitrary prime power. The best previous gap for a linear number of rounds was equal to $2-ε$ and due to Schoenebeck.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| error-correcting codes | descriptive | abstract: «Random (dv,dc)-regular LDPC codes» | LDPC — конкретное семейство error-correcting codes. Это отношение частного к общему, не синоним и не терминологический разрыв. |
| binary symmetric channel | exact | abstract: «binary symmetric channel» |  |

**Соответствие:** `supported`; нужны дополнительные источники: нет; уверенность: `high`.

Оба научных аспекта видны; статья теоретически анализирует ограничения декодирования, а не только экспериментально оценивает коды.

### 5. scholarquest:BQ_000906

**Оригинальный вопрос:**

> Which papers evaluate interpolation methods in the context of image processing?

**Цель:** [Video Frame Interpolation Transformer](https://arxiv.org/abs/2111.13817) — `arxiv:2111.13817`.

**Оригинальный abstract:**

> Existing methods for video interpolation heavily rely on deep convolution neural networks, and thus suffer from their intrinsic limitations, such as content-agnostic kernel weights and restricted receptive field. To address these issues, we propose a Transformer-based video interpolation framework that allows content-aware aggregation weights and considers long-range dependencies with the self-attention operations. To avoid the high computational cost of global self-attention, we introduce the concept of local attention into video interpolation and extend it to the spatial-temporal domain. Furthermore, we propose a space-time separation strategy to save memory usage, which also improves performance. In addition, we develop a multi-scale frame synthesis scheme to fully realize the potential of Transformers. Extensive experiments demonstrate the proposed model performs favorably against the state-of-the-art methods both quantitatively and qualitatively on a variety of benchmark datasets.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| interpolation methods | descriptive | abstract: «Transformer-based video interpolation framework» | Конкретный метод интерполяции видеокадров. |
| image processing | descriptive | abstract: «multi-scale frame synthesis scheme» | Синтез промежуточных кадров — частная задача обработки изображений; совпадение не буквальное. |

**Соответствие:** `supported`; нужны дополнительные источники: нет; уверенность: `medium`.

Рассматривается интерполяция видеокадров; запрос допускает широкое понимание image processing, включающее обработку кадров.

### 6. scholarquest:BQ_001361

**Оригинальный вопрос:**

> Which papers study information extraction using semi-supervised learning?

**Цель:** [Variational Sequential Labelers for Semi-Supervised Learning](https://arxiv.org/abs/1906.09535) — `arxiv:1906.09535`.

**Оригинальный abstract:**

> We introduce a family of multitask variational methods for semi-supervised sequence labeling. Our model family consists of a latent-variable generative model and a discriminative labeler. The generative models use latent variables to define the conditional probability of a word given its context, drawing inspiration from word prediction objectives commonly used in learning word embeddings. The labeler helps inject discriminative information into the latent space. We explore several latent variable configurations, including ones with hierarchical structure, which enables the model to account for both label-specific and word-specific information. Our models consistently outperform standard sequential baselines on 8 sequence labeling datasets, and improve further with unlabeled data.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| information extraction | uncertain | abstract: «sequence labeling» | Sequence labeling шире отдельных задач information extraction; нужны названия задач, например NER, в полном тексте. |
| semi-supervised learning | exact | title: «Semi-Supervised Learning» | Регистронезависимое совпадение; исходный текст сохранён. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `medium`.

Semi-supervised learning явно подтверждён. Sequence labeling может обслуживать information extraction, но без названий задач и наборов в аннотации это не установлено.

### 7. scholarquest:BQ_000598

**Оригинальный вопрос:**

> Which papers evaluate online handwriting recognition on the IAM Online Handwriting Database?

**Цель:** [Illegible Text to Readable Text: An Image-to-Image Transformation using Conditional Sliced Wasserstein Adversarial Networks](https://arxiv.org/abs/1910.05425) — `arxiv:1910.05425`.

**Оригинальный abstract:**

> Automatic text recognition from ancient handwritten record images is an important problem in the genealogy domain. However, critical challenges such as varying noise conditions, vanishing texts, and variations in handwriting make the recognition task difficult. We tackle this problem by developing a handwritten-to-machine-print conditional Generative Adversarial network (HW2MP-GAN) model that formulates handwritten recognition as a text-Image-to-text-Image translation problem where a given image, typically in an illegible form, is converted into another image, close to its machine-print form. The proposed model consists of three-components including a generator, and word-level and character-level discriminators. The model incorporates Sliced Wasserstein distance (SWD) and U-Net architectures in HW2MP-GAN for better quality image-to-image transformation. Our experiments reveal that HW2MP-GAN outperforms state-of-the-art baseline cGAN models by almost 30 in Frechet Handwritten Distance (FHD), 0.6 on average Levenshtein distance and 39% in word accuracy for image-to-image translation on IAM database. Further, HW2MP-GAN improves handwritten recognition word accuracy by 1.3% compared to baseline handwritten recognition models on the IAM database.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| online handwriting recognition | uncertain | abstract: «handwritten recognition as a text-Image-to-text-Image translation problem» | Рукописное распознавание по изображениям не тождественно online handwriting recognition; слово online в описании метода отсутствует. |
| IAM Online Handwriting Database | uncertain | abstract: «IAM database» | Общее IAM database нельзя приравнивать к IAM Online Handwriting Database: это может быть другой ресурс IAM. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Видны распознавание изображений рукописного текста и IAM database. Это не подтверждает online recognition по траекториям пера или использование именно IAM OnDB. Возможное несоответствие gold-цели требует проверки.

### 8. scholarquest:BQ_001612

**Оригинальный вопрос:**

> I am looking for papers on Bayesian networks that exclude hidden Markov models from their scope.

**Цель:** [Bayesian network learning with cutting planes](https://arxiv.org/abs/1202.3713) — `arxiv:1202.3713`.

**Оригинальный abstract:**

> The problem of learning the structure of Bayesian networks from complete discrete data with a limit on parent set size is considered. Learning is cast explicitly as an optimisation problem where the goal is to find a BN structure which maximises log marginal likelihood (BDe score). Integer programming, specifically the SCIP framework, is used to solve this optimisation problem. Acyclicity constraints are added to the integer program (IP) during solving in the form of cutting planes. Finding good cutting planes is the key to the success of the approach -the search for such cutting planes is effected using a sub-IP. Results show that this is a particularly fast method for exact BN learning.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| Bayesian networks | exact | abstract: «Bayesian networks» |  |
| exclude hidden Markov models from their scope | not_visible | — | Hidden Markov models не упомянуты. Это не свидетельство их исключения из scope полного текста. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Обучение структуры Bayesian networks подтверждено. Отсутствие HMM в аннотации недостаточно для проверки отрицательного ограничения по всей работе.

### 9. scholarquest:BQ_002222

**Оригинальный вопрос:**

> Which papers evaluate browser security measures in the context of Chrome?

**Цель:** [Did I Vet You Before? Assessing the Chrome Web Store Vetting Process through Browser Extension Similarity](https://arxiv.org/abs/2406.00374) — `arxiv:2406.00374`.

**Оригинальный abstract:**

> Web browsers, particularly Google Chrome and other Chromium-based browsers, have grown in popularity over the past decade, with browser extensions becoming an integral part of their ecosystem. These extensions can customize and enhance the user experience, providing functionality that ranges from ad blockers to, more recently, AI assistants. Given the ever-increasing importance of web browsers, distribution marketplaces for extensions play a key role in keeping users safe by vetting submissions that display abusive or malicious behavior. In this paper, we characterize the prevalence of malware and other infringing extensions in the Chrome Web Store (CWS), the largest distribution platform for this type of software. To do so, we introduce SimExt, a novel methodology for detecting similarly behaving extensions that leverages static and dynamic analysis, Natural Language Processing (NLP) and vector embeddings. Our study reveals significant gaps in the CWS vetting process, as 86% of infringing extensions are extremely similar to previously vetted items, and these extensions take months or even years to be removed. By characterizing the top kinds of infringing extension, we find that 83% are New Tab Extensions (NTEs) and raise some concerns about the consistency of the vetting labels assigned by CWS analysts. Our study also reveals that only 1% of malware extensions flagged by the CWS are detected as malicious by anti-malware engines, indicating a concerning gap between the threat landscape seen by CWS moderators and the detection capabilities of the threat intelligence community.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| browser security measures | descriptive | abstract: «keeping users safe by vetting submissions that display abusive or malicious behavior» | Описана конкретная мера безопасности: проверка расширений до распространения. |
| Chrome | exact | title: «Chrome» |  |

**Соответствие:** `supported`; нужны дополнительные источники: нет; уверенность: `high`.

Проверка безопасности расширений Chrome — конкретный вид browser security measures; это не пример разрыва терминологии.

### 10. scholarquest:BQ_000223

**Оригинальный вопрос:**

> Which papers report that variational methods outperform traditional MCMC methods in terms of computational efficiency?

**Цель:** [Approximate Bayesian inference for cumulative probit regression models](https://arxiv.org/abs/2511.06967) — `arxiv:2511.06967`.

**Оригинальный abstract:**

> Ordinal categorical data are routinely encountered in many practical applications. When the primary goal is to construct a regression model for ordinal outcomes, cumulative link models represent one of the most popular choices to link the cumulative probabilities of the response with a set of covariates through a parsimonious linear predictor, shared across response categories. As the number of observations grows, standard sampling algorithms for Bayesian inference scale poorly, making posterior computation increasingly challenging for large datasets. In this article, we propose three scalable algorithms for approximating the posterior distribution of the regression coefficients in cumulative probit models relying on Variational Bayes and Expectation Propagation. We compare the proposed approaches with inference based on Markov Chain Monte Carlo, demonstrating superior computational performance and remarkable accuracy. Finally, we illustrate the utility of the proposed algorithms on a challenging case study to investigate the structure of a criminal network.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| variational methods | descriptive | abstract: «Variational Bayes» | Конкретный вариационный подход; это специализация, а не синоним всех variational methods. |
| traditional MCMC methods | abbreviation | abstract: «Markov Chain Monte Carlo» | Расшифровка MCMC; квалификатор traditional не конкретизирован. |
| outperform | descriptive | abstract: «demonstrating superior computational performance» | Выражает преимущество предлагаемых подходов в сравнении с MCMC. |
| computational efficiency | synonym | abstract: «computational performance» | В контексте сравнительной вычислительной стоимости; время и ресурсы в аннотации не приведены. |

**Соответствие:** `supported`; нужны дополнительные источники: нет; уверенность: `high`.

Сравнение вариационного приближения с MCMC по вычислительной производительности прямо заявлено.

### 11. autoresearchbench:row_000412

**Оригинальный вопрос:**

> I am trying to identify a paper where all authors share a single engineering department at a West Coast US university. Deep in the convergence proof, the authors unroll a recursive error bound to a depth set by rounding up half the base-two logarithm of a planning horizon parameter. During the simplification of this unrolled expression, an intermediate sufficient condition on a sample-count threshold features a constant that equals exactly the square of ten and one-half, multiplied by the square of a parameter that bounds the branching factor of the system's dynamics. This constant is later superseded by a stronger requirement involving a four-digit integer in the numerator. What is the title of this paper?

**Цель:** [A Sample-Efficient Algorithm for Episodic Finite-Horizon MDP with Constraints](https://arxiv.org/abs/2009.11348) — `arxiv:2009.11348`.

**Оригинальный abstract:**

> Constrained Markov Decision Processes (CMDPs) formalize sequential decision-making problems whose objective is to minimize a cost function while satisfying constraints on various cost functions. In this paper, we consider the setting of episodic fixed-horizon CMDPs. We propose an online algorithm which leverages the linear programming formulation of finite-horizon CMDP for repeated optimistic planning to provide a probably approximately correct (PAC) guarantee on the number of episodes needed to ensure an $ε$-optimal policy, i.e., with resulting objective value within $ε$ of the optimal value and satisfying the constraints within $ε$-tolerance, with probability at least $1-δ$. The number of episodes needed is shown to be of the order $\tilde{\mathcal{O}}\big(\frac{|S||A|C^{2}H^{2}}{ε^{2}}\log\frac{1}δ\big)$, where $C$ is the upper bound on the number of possible successor states for a state-action pair. Therefore, if $C \ll |S|$, the number of episodes needed have a linear dependence on the state and action space sizes $|S|$ and $|A|$, respectively, and quadratic dependence on the time horizon $H$.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| all authors share a single engineering department | not_visible | — | Аффилиации отсутствуют в выбранном представлении. |
| West Coast US university | not_visible | — | Аффилиации отсутствуют в выбранном представлении. |
| convergence proof | not_visible | — | PAC guarantee видна, но наличие и содержание convergence proof не представлены. |
| recursive error bound | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| rounding up half the base-two logarithm of a planning horizon parameter | not_visible | — | В формуле есть H, но правило глубины рекурсии не дано. |
| sample-count threshold | descriptive | abstract: «The number of episodes needed is shown to be of the order» | Показана асимптотическая потребность в эпизодах; конкретный промежуточный sample-count threshold не виден. |
| square of ten and one-half | not_visible | — | Числовая константа 10.5² не приведена. |
| parameter that bounds the branching factor | descriptive | abstract: «the upper bound on the number of possible successor states for a state-action pair» | Описательная связь с branching factor динамики; параметр обозначен C. |
| four-digit integer in the numerator | not_visible | — | Четырёхзначная константа не приведена. |

**Соответствие:** `uncertain`; нужны дополнительные источники: да; уверенность: `high`.

Большинство идентифицирующих условий относится к аффилиациям и промежуточным шагам доказательства; их нет в title + abstract. Нельзя трактовать это как установленный терминологический разрыв.

### 12. autoresearchbench:row_000236

**Оригинальный вопрос:**

> A paper cites a work from a major machine learning venue around 2020 that solves ordering-related optimization subproblems via an algorithm rooted in monotonic regression through iterative pooling of adjacent constraint violations. In the citing paper, evaluation tables report deviation metrics from a theoretical baseline distribution, with certain stratified subgroups showing values clustered near single digits except for one outlier exceeding thirty. Identify this citing paper.

**Цель:** [Training Uncertainty-Aware Classifiers with Conformalized Deep Learning](https://arxiv.org/abs/2205.05878) — `arxiv:2205.05878`.

**Оригинальный abstract:**

> Deep neural networks are powerful tools to detect hidden patterns in data and leverage them to make predictions, but they are not designed to understand uncertainty and estimate reliable probabilities. In particular, they tend to be overconfident. We begin to address this problem in the context of multi-class classification by developing a novel training algorithm producing models with more dependable uncertainty estimates, without sacrificing predictive power. The idea is to mitigate overconfidence by minimizing a loss function, inspired by advances in conformal inference, that quantifies model uncertainty by carefully leveraging hold-out data. Experiments with synthetic and real data demonstrate this method can lead to smaller conformal prediction sets with higher conditional coverage, after exact calibration with hold-out data, compared to state-of-the-art alternatives.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| major machine learning venue around 2020 | not_visible | — | Нужна библиография цитирующей статьи. |
| ordering-related optimization subproblems | not_visible | — | Условие относится к цитируемой работе. |
| monotonic regression | not_visible | — | Условие относится к цитируемой работе. |
| iterative pooling of adjacent constraint violations | not_visible | — | Условие относится к цитируемой работе. |
| deviation metrics | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| theoretical baseline distribution | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| stratified subgroups | uncertain | abstract: «higher conditional coverage» | Conditional coverage может измеряться по группам, но stratified subgroups явно не описаны. |
| single digits | not_visible | — | Численные результаты таблиц отсутствуют. |
| outlier exceeding thirty | not_visible | — | Численные результаты таблиц отсутствуют. |

**Соответствие:** `uncertain`; нужны дополнительные источники: да; уверенность: `high`.

Идентифицирующие ссылка, алгоритм цитируемой работы и численные ячейки таблиц не видны. Общая тема uncertainty-aware classification не подтверждает эти детали.

### 13. autoresearchbench:row_000222

**Оригинальный вопрос:**

> I'm searching for a methodological paper where, in an appendix comparison, a polynomial-smoothed baseline method completely failed at moderate noise levels by hallucinating a spurious quadratic interaction term with a small negative coefficient. The same work required switching to periodic activation functions and a shallower architecture when handling equations with higher-order spatial derivatives. The corresponding author is affiliated with a laboratory in Shenzhen named after a major Chinese national technology initiative. What is this paper's title?

**Цель:** [DL-PDE: Deep-learning based data-driven discovery of partial differential equations from discrete and noisy data](https://arxiv.org/abs/1908.04463) — `arxiv:1908.04463`.

**Оригинальный abstract:**

> In recent years, data-driven methods have been developed to learn dynamical systems and partial differential equations (PDE). The goal of such work is discovering unknown physics and the corresponding equations. However, prior to achieving this goal, major challenges remain to be resolved, including learning PDE under noisy data and limited discrete data. To overcome these challenges, in this work, a deep-learning based data-driven method, called DL-PDE, is developed to discover the governing PDEs of underlying physical processes. The DL-PDE method combines deep learning via neural networks and data-driven discovery of PDE via sparse regressions. In the DL-PDE, a neural network is first trained, and then a large amount of meta-data is generated, and the required derivatives are calculated by automatic differentiation. Finally, the form of PDE is discovered by sparse regression. The proposed method is tested with physical processes, governed by groundwater flow equation, convection-diffusion equation, Burgers equation and Korteweg-de Vries (KdV) equation, for proof-of-concept and applications in real-world engineering settings. The proposed method achieves satisfactory results when data are noisy and limited.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| appendix comparison | not_visible | — | Требуется приложение. |
| polynomial-smoothed baseline method | not_visible | — | Baseline не назван. |
| moderate noise levels | uncertain | abstract: «when data are noisy and limited» | Наличие шума подтверждено, но moderate levels и отказ baseline не установлены. |
| spurious quadratic interaction term | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| small negative coefficient | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| periodic activation functions | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| shallower architecture | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| higher-order spatial derivatives | uncertain | abstract: «the required derivatives are calculated by automatic differentiation» | Производные упомянуты, но higher-order spatial derivatives и требование смены активации не указаны. |
| laboratory in Shenzhen | not_visible | — | Аффилиации отсутствуют в выбранном представлении. |

**Соответствие:** `uncertain`; нужны дополнительные источники: да; уверенность: `high`.

Тема PDE discovery и работа с шумом согласуются с вопросом, но идентифицирующие детали baseline, коэффициента, архитектуры и лаборатории не видны.

### 14. autoresearchbench:row_000672

**Оригинальный вопрос:**

> From 2009 to 2025, find key papers in Computational Social Science and Cultural Analytics that model culture, politics, or media ecosystems as socio-semantic, heterogeneous, or multilayer graphs. Specifically, focus on studies that analyze meso-scale structure (e.g., communities, homophily) or diffusion cascades using large time-stamped digital traces. Note: The evaluation should prioritize observational methods with simple null models (shuffles, randomization) rather than end-to-end predictive machine learning.

**Цель:** [Socio-semantic dynamics in a blog network](https://arxiv.org/abs/0909.3080) — `arxiv:0909.3080`.

**Оригинальный abstract:**

> The blogosphere can be construed as a knowledge network made of bloggers who are interacting through a social network to share, exchange or produce information. We claim that the social and semantic dimensions are essentially co-determined and propose to investigate the co-evolutionary dynamics of the blogosphere by examining two intertwined issues: First, how does knowledge distribution drive new interactions and thus influence the social network topology? Second, which role structural network properties play in the information circulation in the system? We adopt an empirical standpoint by analyzing the semantic and social activity of a portion of the US political blogosphere, monitored on a period of four months.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| 2009 to 2025 | not_visible | — | Год известен из идентификатора, но не входит в title + abstract. |
| Computational Social Science and Cultural Analytics | descriptive | abstract: «semantic and social activity of a portion of the US political blogosphere» | Частный предмет computational social science; само название дисциплины не употреблено. |
| culture, politics, or media ecosystems | descriptive | abstract: «US political blogosphere» | Политическая медиасреда — частный случай одного из альтернативных предметов запроса. |
| socio-semantic, heterogeneous, or multilayer graphs | descriptive | title: «Socio-semantic» | Совпадает socio-semantic из одной альтернативы; graph в вопросе выражен как network. Это составное соответствие, не inflection всего фрагмента. |
| meso-scale structure | not_visible | — | Топология сети упомянута, но уровень meso-scale не установлен. |
| communities, homophily | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| diffusion cascades | uncertain | abstract: «information circulation» | Циркуляция информации не обязательно анализ diffusion cascades. |
| large time-stamped digital traces | uncertain | abstract: «monitored on a period of four months» | Временное наблюдение подтверждено; large traces и временные метки отдельных событий не установлены. |
| observational methods with simple null models | uncertain | abstract: «We adopt an empirical standpoint» | Empirical не устанавливает использование простых null models. |
| rather than end-to-end predictive machine learning | not_visible | — | Отсутствие predictive ML в аннотации не доказывает отрицательное ограничение. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Социально-семантический граф политической блогосферы и временное наблюдение видны. Масштаб данных, meso-scale анализ и null models не установлены. Типичный случай неполноты abstract, а не доказанный терминологический разрыв.

### 15. autoresearchbench:row_000794

**Оригинальный вопрос:**

> From 2022 to 2025, which recent papers on classical, non–deep-learning federated or decentralized optimization propose theoretically grounded algorithms based on augmented Lagrangian, primal–dual, or gradient-tracking methods? Specifically, I am looking for works that evaluate under non-IID client data and communication-constrained network topologies, and that compare against standard federated learning baselines such as FedAvg, proximal methods (e.g., FedProx), or ADMM-style approaches.

**Цель:** [DFedADMM: Dual Constraints Controlled Model Inconsistency for Decentralized Federated Learning](https://arxiv.org/abs/2308.08290) — `arxiv:2308.08290`.

**Оригинальный abstract:**

> To address the communication burden issues associated with federated learning (FL), decentralized federated learning (DFL) discards the central server and establishes a decentralized communication network, where each client communicates only with neighboring clients. However, existing DFL methods still suffer from two major challenges: local inconsistency and local heterogeneous overfitting, which have not been fundamentally addressed by existing DFL methods. To tackle these issues, we propose novel DFL algorithms, DFedADMM and its enhanced version DFedADMM-SAM, to enhance the performance of DFL. The DFedADMM algorithm employs primal-dual optimization (ADMM) by utilizing dual variables to control the model inconsistency raised from the decentralized heterogeneous data distributions. The DFedADMM-SAM algorithm further improves on DFedADMM by employing a Sharpness-Aware Minimization (SAM) optimizer, which uses gradient perturbations to generate locally flat models and searches for models with uniformly low loss values to mitigate local heterogeneous overfitting. Theoretically, we derive convergence rates of $\small \mathcal{O}\Big(\frac{1}{\sqrt{KT}}+\frac{1}{KT(1-ψ)^2}\Big)$ and $\small \mathcal{O}\Big(\frac{1}{\sqrt{KT}}+\frac{1}{KT(1-ψ)^2}+ \frac{1}{T^{3/2}K^{1/2}}\Big)$ in the non-convex setting for DFedADMM and DFedADMM-SAM, respectively, where $1 - ψ$ represents the spectral gap of the gossip matrix. Empirically, extensive experiments on MNIST, CIFAR10 and CIFAR100 datesets demonstrate that our algorithms exhibit superior performance in terms of both generalization and convergence speed compared to existing state-of-the-art (SOTA) optimizers in DFL.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| 2022 to 2025 | not_visible | — | Год не входит в title + abstract. |
| classical, non–deep-learning federated or decentralized optimization | uncertain | abstract: «decentralized federated learning» | Federated/decentralized optimization присутствует; non-deep-learning не подтверждено, приводятся MNIST/CIFAR эксперименты. |
| theoretically grounded algorithms | descriptive | abstract: «we derive convergence rates» | Теоретическая обоснованность выражена доказуемыми скоростями сходимости. |
| augmented Lagrangian, primal–dual, or gradient-tracking methods | descriptive | abstract: «primal-dual optimization (ADMM)» | Прямо названа одна из альтернатив метода; типографика hyphen/dash отличается. |
| non-IID client data | descriptive | abstract: «decentralized heterogeneous data distributions» | Heterogeneous data distributions — описательное соответствие non-IID; конкретные клиентские распределения требуют проверки. |
| communication-constrained network topologies | descriptive | abstract: «each client communicates only with neighboring clients» | Конкретное ограничение топологии коммуникаций. |
| compare against standard federated learning baselines | uncertain | abstract: «compared to existing state-of-the-art (SOTA) optimizers in DFL» | Сравнение есть, но стандартный набор baseline из запроса не перечислен. |
| FedAvg | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| FedProx | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| ADMM-style approaches | descriptive | title: «ADMM» | Совпадает название базового метода; это ещё не подтверждает сравнение с ADMM baseline. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Primal-dual ADMM и децентрализованная связь явно видны. Non-deep-learning условие, точные baseline и временной интервал по title + abstract не подтверждены.

### 16. autoresearchbench:row_000251

**Оригинальный вопрос:**

> A paper contains a footnote that cites a specific table from a mid-2010s study to clarify the distinction between instance-level and aggregated forms of a harmonic-mean performance measure. In a separate footnote, it extends a predecessor's formulation by dropping a unit-cardinality restriction on an association set. Empirical timing comparisons of three approaches on a single accelerator show the costliest method's per-batch duration is roughly 3.6 times that of the least costly. What is the title of this paper?

**Цель:** [Learning Optimal Tree Models Under Beam Search](https://arxiv.org/abs/2006.15408) — `arxiv:2006.15408`.

**Оригинальный abstract:**

> Retrieving relevant targets from an extremely large target set under computational limits is a common challenge for information retrieval and recommendation systems. Tree models, which formulate targets as leaves of a tree with trainable node-wise scorers, have attracted a lot of interests in tackling this challenge due to their logarithmic computational complexity in both training and testing. Tree-based deep models (TDMs) and probabilistic label trees (PLTs) are two representative kinds of them. Though achieving many practical successes, existing tree models suffer from the training-testing discrepancy, where the retrieval performance deterioration caused by beam search in testing is not considered in training. This leads to an intrinsic gap between the most relevant targets and those retrieved by beam search with even the optimally trained node-wise scorers. We take a first step towards understanding and analyzing this problem theoretically, and develop the concept of Bayes optimality under beam search and calibration under beam search as general analyzing tools for this purpose. Moreover, to eliminate the discrepancy, we propose a novel algorithm for learning optimal tree models under beam search. Experiments on both synthetic and real data verify the rationality of our theoretical analysis and demonstrate the superiority of our algorithm compared to state-of-the-art methods.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| footnote | not_visible | — | Требуется полный текст. |
| mid-2010s study | not_visible | — | Требуется ссылка из footnote. |
| instance-level and aggregated forms | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| harmonic-mean performance measure | not_visible | — | F1 или harmonic mean не указаны. |
| unit-cardinality restriction | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| association set | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| timing comparisons | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| single accelerator | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| per-batch duration | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| 3.6 times | not_visible | — | Соотношение времени отсутствует. |

**Соответствие:** `uncertain`; нужны дополнительные источники: да; уверенность: `high`.

Все отличительные признаки относятся к footnotes и таблице времени; в abstract их нет. Нельзя присвоить нулевую смысловую близость только по отсутствию этих деталей.

### 17. autoresearchbench:row_000415

**Оригинальный вопрос:**

> A paper references a propagation study from a selective communications journal where field measurements used narrow-beam directional antennas with roughly ten-degree apertures to characterize dense urban paths. That foundational study grouped multipath arrivals using an iterative centroid-based algorithm terminating when angular separation between adjacent clusters fell within a statistical tolerance of two spread units. In the citing work, the optimizer's step size decays by a factor exceeding one-half at four evenly spaced training milestones. Inference on a consumer-grade graphics accelerator from the mid-twenty-tens achieves sub-ten-microsecond latency per sample. Identify this citing work.

**Цель:** [Deep Denoising Neural Network Assisted Compressive Channel Estimation for mmWave Intelligent Reflecting Surfaces](https://arxiv.org/abs/2006.02201) — `arxiv:2006.02201`.

**Оригинальный abstract:**

> Integrating large intelligent reflecting surfaces (IRS) into millimeter-wave (mmWave) massive multi-input-multi-ouput (MIMO) has been a promising approach for improved coverage and throughput. Most existing work assumes the ideal channel estimation, which can be challenging due to the high-dimensional cascaded MIMO channels and passive reflecting elements. Therefore, this paper proposes a deep denoising neural network assisted compressive channel estimation for mmWave IRS systems to reduce the training overhead. Specifically, we first introduce a hybrid passive/active IRS architecture, where very few receive chains are employed to estimate the uplink user-to-IRS channels. At the channel training stage, only a small proportion of elements will be successively activated to sound the partial channels. Moreover, the complete channel matrix can be reconstructed from the limited measurements based on compressive sensing, whereby the common sparsity of angular domain mmWave MIMO channels among different subcarriers is leveraged for improved accuracy. Besides, a complex-valued denoising convolution neural network (CV-DnCNN) is further proposed for enhanced performance. Simulation results demonstrate the superiority of the proposed solution over state-of-the-art solutions.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| propagation study | uncertain | abstract: «millimeter-wave (mmWave)» | Радиоканальная тематика согласуется, но конкретная propagation study и ссылка не представлены. |
| narrow-beam directional antennas | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| ten-degree apertures | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| dense urban paths | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| multipath arrivals | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| iterative centroid-based algorithm | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| angular separation | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| two spread units | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| step size decays | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| four evenly spaced training milestones | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| consumer-grade graphics accelerator | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| sub-ten-microsecond latency per sample | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |

**Соответствие:** `uncertain`; нужны дополнительные источники: да; уверенность: `high`.

Тематика mmWave каналов связана с propagation, однако факты из цитируемой работы и параметры обучения/latency в abstract отсутствуют.

### 18. autoresearchbench:row_000904

**Оригинальный вопрос:**

> From 2000 to January 2026, which contemporary quantum‑hardware research papers focus on hardware‑level qubit engineering—especially superconducting or other physically implemented qubit modalities—and use Hamiltonian models or circuit‑level physical derivations rather than data‑driven methods? Specifically, I am looking for work that evaluates qubit designs using coherence or device‑quality metrics and proposes foundational device or architecture innovations.

**Цель:** [A Quantum Engineer's Guide to Superconducting Qubits](https://arxiv.org/abs/1904.06560) — `arxiv:1904.06560`.

**Оригинальный abstract:**

> The aim of this review is to provide quantum engineers with an introductory guide to the central concepts and challenges in the rapidly accelerating field of superconducting quantum circuits. Over the past twenty years, the field has matured from a predominantly basic research endeavor to one that increasingly explores the engineering of larger-scale superconducting quantum systems. Here, we review several foundational elements -- qubit design, noise properties, qubit control, and readout techniques -- developed during this period, bridging fundamental concepts in circuit quantum electrodynamics (cQED) and contemporary, state-of-the-art applications in gate-model quantum computation.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| 2000 to January 2026 | not_visible | — | Год не входит в title + abstract. |
| quantum‑hardware research | descriptive | abstract: «superconducting quantum circuits» | Конкретный вид quantum hardware. |
| hardware‑level qubit engineering | descriptive | abstract: «qubit design, noise properties, qubit control, and readout techniques» | Компоненты инженерии кубита. |
| superconducting or other physically implemented qubit modalities | descriptive | title: «Superconducting Qubits» | Прямо реализована одна из альтернатив физических модальностей. |
| Hamiltonian models or circuit‑level physical derivations | uncertain | abstract: «circuit quantum electrodynamics (cQED)» | Теоретическая физическая основа названа, но Hamiltonian/circuit derivations в тексте не показаны. |
| rather than data‑driven methods | not_visible | — | Отсутствие data-driven methods в аннотации не доказывает исключение. |
| coherence or device‑quality metrics | uncertain | abstract: «noise properties» | Noise — связанное свойство; оценка coherence/device-quality metrics не заявлена. |
| foundational device or architecture innovations | uncertain | abstract: «we review several foundational elements» | Обзор основ не равнозначен предложению собственных фундаментальных инноваций. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Hardware qubit engineering подтверждено, но целевая работа — review. Она обсуждает foundational elements, что не равно требованию самой предлагать foundational innovations; нужны полный текст и уточнение строгости запроса.

### 19. autoresearchbench:row_000878

**Оригинальный вопрос:**

> From 2014 to February 2026, which theoretical computer science papers analyze graph approximation problems in sublinear, streaming, or distributed (MPC) models, especially those that use communication‑complexity or sketching‑based techniques? Specifically, I am looking for work that focuses on theoretical guarantees—such as approximation ratios, space bounds, and pass or round complexity—rather than empirical datasets or experimental evaluations.

**Цель:** [Hidden Permutations to the Rescue: Multi-Pass Semi-Streaming Lower Bounds for Approximate Matchings](https://arxiv.org/abs/2310.05728) — `arxiv:2310.05728`.

**Оригинальный abstract:**

> We prove that any semi-streaming algorithm for $(1-ε)$-approximation of maximum bipartite matching requires \[ Ω(\frac{\log{(1/ε)}}{\log{(1/β)}}) \] passes, where $β\in (0,1)$ is the largest parameter so that an $n$-vertex graph with $n^β$ edge-disjoint induced matchings of size $Θ(n)$ exist (such graphs are referred to as RS graphs). Currently, it is known that \[ Ω(\frac{1}{\log\log{n}}) \leqslant β\leqslant 1-Θ(\frac{\log^*{n}}{\log{n}}) \] and closing this huge gap between upper and lower bounds has remained a notoriously difficult problem in combinatorics.
>   Under the plausible hypothesis that $β= Ω(1)$, our lower bound result provides the first pass-approximation lower bound for (small) constant approximation of matchings in the semi-streaming model, a longstanding open question in the graph streaming literature.
>   Our techniques are based on analyzing communication protocols for compressing (hidden) permutations. Prior work in this context relied on reducing such problems to Boolean domain and analyzing them via tools like XOR Lemmas and Fourier analysis on Boolean hypercube. In contrast, our main technical contribution is a hardness amplification result for permutations through concatenation in place of prior XOR Lemmas. This result is proven by analyzing permutations directly via simple tools from group representation theory combined with detailed information-theoretic arguments, and can be of independent interest.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| 2014 to February 2026 | not_visible | — | Год не входит в title + abstract. |
| theoretical computer science | descriptive | abstract: «semi-streaming algorithm» | Конкретная задача теоретической информатики; это отношение частного к общему. |
| graph approximation problems | descriptive | abstract: «approximation of maximum bipartite matching» | Конкретная graph approximation problem. |
| sublinear, streaming, or distributed (MPC) models | descriptive | abstract: «semi-streaming model» | Одна из альтернатив вычислительной модели. |
| communication‑complexity or sketching‑based techniques | descriptive | abstract: «communication protocols for compressing (hidden) permutations» | Техника коммуникационных протоколов; не синоним всех communication-complexity/sketching методов. |
| theoretical guarantees | descriptive | abstract: «We prove that any semi-streaming algorithm» | Явно заявлен доказуемый lower bound. |
| approximation ratios | descriptive | abstract: «pass-approximation lower bound» | Приближение связано с ограничением числа проходов. |
| space bounds | not_visible | — | Конкретная space bound в аннотации не выписана; semi-streaming задаёт модель, а не явную оценку. |
| pass or round complexity | descriptive | abstract: «passes» | Число проходов связано с приведённой формулой lower bound. |
| rather than empirical datasets or experimental evaluations | not_visible | — | Эксперименты не упомянуты; их отсутствие в полном тексте не доказано. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Научное ядро теоретической graph streaming задачи подтверждено. Год и отсутствие экспериментальной части в полном тексте не проверялись.

### 20. autoresearchbench:row_000611

**Оригинальный вопрос:**

> Which recent machine learning and NLP papers (2024–2025) study agentic large language models for tool use and structured reasoning, going beyond simple step-by-step prompting? In particular, I am looking for work that: (1) uses multi-stage training (e.g., supervised fine-tuning plus preference learning or reinforcement learning), (2) compares against standard tool-use baselines, and (3) evaluates on multi-step tool-invocation or planning-focused benchmarks.

**Цель:** [DiaTool-DPO: Multi-Turn Direct Preference Optimization for Tool-Augmented Large Language Models](https://arxiv.org/abs/2504.02882) — `arxiv:2504.02882`.

**Оригинальный abstract:**

> Tool-Augmented Larage Language Models (TA-LLMs) have shown promise in real-world applications, but face challenges in handling incomplete queries and out-of-scope requests. While existing approaches rely mainly on Supervised Fine-Tuning with expert trajectories, we propose DiaTool-DPO, a novel method that enhances TA-LLM's dialogue capabilities through Direct Preference Optimization. We model TA-LLM interactions as a Markov Decision Process with 5 distinct dialogue states and categorize user queries into 3 types based on their state transition trajectories. We automatically construct paired trajectory datasets of correct and incorrect dialogue flows and introduce a specialized objective loss for dialogue control. Our comprehensive evaluation demonstrates that DiaTool-DPO approaches GPT-4o's performance (94.8% in information gathering, 91% in tool call rejection) with substantial improvements over baseline (44% and 9.6% respectively) while maintaining core functionality. Our approach opens new possibilities for developing TA-LLMs that can handle diverse real-world scenarios without requiring additional expert demonstrations or human labeling.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| machine learning and NLP | descriptive | abstract: «Tool-Augmented Larage Language Models» | Конкретная работа ML/NLP; опечатка Larage сохранена из источника. |
| 2024–2025 | not_visible | — | Год не входит в title + abstract. |
| agentic large language models | descriptive | abstract: «Tool-Augmented Larage Language Models (TA-LLMs)» | Частный вид agentic LLM; термин не полностью взаимозаменяем с agentic. |
| tool use and structured reasoning | descriptive | abstract: «dialogue control» | Видны tool/dialogue control; structured reasoning в общем смысле не заявлено. |
| going beyond simple step-by-step prompting | descriptive | abstract: «Direct Preference Optimization» | Обучение через DPO выходит за пределы одного prompting; это соответствие подхода, не синоним фразы. |
| multi-stage training | uncertain | abstract: «While existing approaches rely mainly on Supervised Fine-Tuning with expert trajectories, we propose DiaTool-DPO» | SFT упомянут как существующий подход; полный multi-stage pipeline авторов здесь не описан. |
| supervised fine-tuning plus preference learning or reinforcement learning | descriptive | abstract: «Direct Preference Optimization» | Подтверждена preference-learning часть альтернативы, но не сочетание с SFT. |
| compares against standard tool-use baselines | uncertain | abstract: «substantial improvements over baseline» | Сравнение есть; принадлежность baseline к стандартному набору tool-use методов не установлена. |
| multi-step tool-invocation or planning-focused benchmarks | uncertain | title: «Multi-Turn» | Multi-turn взаимодействие не гарантирует использование multi-step tool-invocation или planning benchmarks. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Tool-augmented LLM, DPO и сравнение с baseline видны. Полная последовательность SFT→DPO и конкретные multi-step benchmarks в abstract не установлены.

### 21. paperpilot:case_035

**Оригинальный вопрос:**

> Find methods that compete with GraphSAGE for scalable or inductive graph representation learning.

**Контекст:** {"reference_arxiv_id": "1706.02216", "reference_title": "Inductive Representation Learning on Large Graphs", "reference_source_url": "https://arxiv.org/abs/1706.02216", "search_direction": "baselines_competitors"}

**Цель:** [AdjMix: simplifying and attending graph convolutional networks](https://www.semanticscholar.org/paper/6810af56467a5bc907cda0ad2414f56ed5aa182a) — `s2:6810af56467a5bc907cda0ad2414f56ed5aa182a`.

**Название в релизе:** Simplifying Graph Convolutional Networks.

**Оригинальный abstract:**

> Simple graph convolution (SGC) achieves competitive classification accuracy to graph convolutional networks (GCNs) in various tasks while being computationally more efficient and fitting fewer parameters. However, the width of SGC is narrow due to the over-smoothing of SGC with higher power, which limits the learning ability of graph representations. Here, we propose AdjMix, a simple and attentional graph convolutional model, that is scalable to wider structure and captures more nodes features information, by simultaneously mixing the adjacency matrices of different powers. We point out that the key factor of over-smoothing is the mismatched weights of adjacency matrices, and design AdjMix to address the over-smoothing of SGC and GCNs by adjusting the weights to matching values. Experiments on citation networks including Pubmed, Citeseer, and Cora show that our AdjMix improves over SGC by 2.4%, 2.2%, and 3.2%, respectively, while achieving same performance in terms of parameters and complexity, and obtains better performance in terms of classification accuracy, parameters, and complexity, compared to other baselines.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| compete with GraphSAGE | not_visible | — | GraphSAGE не упомянут; сравнение с SGC/GCN не устанавливает конкуренцию именно с GraphSAGE. |
| scalable or inductive graph representation learning | descriptive | abstract: «scalable to wider structure» | Заявлена масштабируемость модели графовых представлений; inductive setting не подтверждён. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Graph representations и масштабируемость заявлены. GraphSAGE и inductive setting не видны. Дополнительно релиз называет Simplifying Graph Convolutional Networks, а S2 ID возвращает AdjMix: это проблема идентичности цели, не терминологии.

### 22. paperpilot:case_039

**Оригинальный вопрос:**

> Find follow-up deep RL papers that extend the DQN line.

**Контекст:** {"reference_arxiv_id": "1312.5602", "reference_title": "Playing Atari with Deep Reinforcement Learning", "reference_source_url": "https://arxiv.org/abs/1312.5602", "search_direction": "followup_work"}

**Цель:** [Rainbow: Combining Improvements in Deep Reinforcement Learning](https://www.semanticscholar.org/paper/0ab3f7ecbdc5a33565a234215604a6ca9d155a33) — `s2:0ab3f7ecbdc5a33565a234215604a6ca9d155a33`.

**Оригинальный abstract:**

>
>
>  The deep reinforcement learning community has made several independent improvements to the DQN algorithm. However, it is unclear which of these extensions are complementary and can be fruitfully combined. This paper examines six extensions to the DQN algorithm and empirically studies their combination. Our experiments show that the combination provides state-of-the-art performance on the Atari 2600 benchmark, both in terms of data efficiency and final performance. We also provide results from a detailed ablation study that shows the contribution of each component to overall performance.
>

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| follow-up | descriptive | abstract: «several independent improvements to the DQN algorithm» | Последующее развитие базового алгоритма выражено содержательно, без слова follow-up. |
| deep RL | abbreviation | title: «Deep Reinforcement Learning» | RL = reinforcement learning. |
| extend the DQN line | descriptive | abstract: «six extensions to the DQN algorithm» | Содержательно подтверждает развитие DQN line. |

**Соответствие:** `supported`; нужны дополнительные источники: нет; уверенность: `high`.

Расширения DQN прямо заявлены; это ясный положительный пример, не терминологический разрыв.

### 23. paperpilot:case_037

**Оригинальный вопрос:**

> Find survey or review papers that contextualize expressive power and design choices in GNNs.

**Контекст:** {"reference_arxiv_id": "1810.00826", "reference_title": "How Powerful are Graph Neural Networks?", "reference_source_url": "https://arxiv.org/abs/1810.00826", "search_direction": "survey_review"}

**Цель:** [A Survey on Graph Neural Networks and Graph Transformers in Computer Vision: A Task-Oriented Perspective](https://www.semanticscholar.org/paper/741a7faf9dbefd418cda878c61c5b839ecc02977) — `s2:741a7faf9dbefd418cda878c61c5b839ecc02977`.

**Название в релизе:** Graph Transformer Networks: A Survey.

**Оригинальный abstract:**

> Graph Neural Networks (GNNs) have gained momentum in graph representation learning and boosted the state of the art in a variety of areas, such as data mining (e.g., social network analysis and recommender systems), computer vision (e.g., object detection and point cloud learning), and natural language processing (e.g., relation extraction and sequence learning), to name a few. With the emergence of Transformers in natural language processing and computer vision, graph Transformers embed a graph structure into the Transformer architecture to overcome the limitations of local neighborhood aggregation while avoiding strict structural inductive biases. In this paper, we present a comprehensive review of GNNs and graph Transformers in computer vision from a task-oriented perspective. Specifically, we divide their applications in computer vision into five categories according to the modality of input data, i.e., 2D natural images, videos, 3D data, vision + language, and medical images. In each category, we further divide the applications according to a set of vision tasks. Such a task-oriented taxonomy allows us to examine how each task is tackled by different GNN-based approaches and how well these approaches perform. Based on the necessary preliminaries, we provide the definitions and challenges of the tasks, in-depth coverage of the representative approaches, as well as discussions regarding insights, limitations, and future directions.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| survey or review papers | descriptive | abstract: «a comprehensive review» | Прямо подтверждён один из альтернативных типов публикации. |
| expressive power | not_visible | — | В title + abstract соответствие не найдено; это не оценка полного текста. |
| design choices | descriptive | abstract: «embed a graph structure into the Transformer architecture» | Конкретное архитектурное решение; обзор всех design choices этим не подтверждён. |
| GNNs | abbreviation | title: «Graph Neural Networks» | Расшифровка GNNs. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Тип обзорной работы, GNN и обсуждение проектных решений видны; expressive power не заявлена. Название из релиза отличается от возвращённого по S2 ID; тождество работы нужно проверить.

### 24. paperpilot:case_004

**Оригинальный вопрос:**

> Find strong competing pretraining methods that solve similar NLP transfer tasks around the same era as T5.

**Контекст:** {"reference_arxiv_id": "1910.10683", "reference_title": "T5: Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer", "reference_source_url": "https://arxiv.org/abs/1910.10683", "search_direction": "baselines_competitors"}

**Цель:** [UL2: Unifying Language Learning Paradigms](https://www.semanticscholar.org/paper/b21670e8061a06ab97e7d6052c9345a326e84ff8) — `s2:b21670e8061a06ab97e7d6052c9345a326e84ff8`.

**Оригинальный abstract:**

> Existing pre-trained models are generally geared towards a particular class of problems. To date, there seems to be still no consensus on what the right architecture and pre-training setup should be. This paper presents a unified framework for pre-training models that are universally effective across datasets and setups. We begin by disentangling architectural archetypes with pre-training objectives -- two concepts that are commonly conflated. Next, we present a generalized&unified perspective for self-supervision in NLP and show how different pre-training objectives can be cast as one another and how interpolating between different objectives can be effective. We then propose Mixture-of-Denoisers (MoD), a pre-training objective that combines diverse pre-training paradigms together. We furthermore introduce a notion of mode switching, wherein downstream fine-tuning is associated with specific pre-training schemes. We conduct extensive ablative experiments to compare multiple pre-training objectives and find that our method pushes the Pareto-frontier by outperforming T5&GPT-like models across multiple diverse setups. By scaling our model up to 20B parameters, we achieve SOTA performance on 50 well-established supervised finetuning based NLP tasks. Our model also achieve strong results at in-context learning, outperforming 175B GPT-3 on zero-shot SuperGLUE and tripling the performance of T5-XXL on one-shot summarization. On 0-shot MMLU, UL2 20B outperforms T0 and T5 models. UL2 20B also works well with chain-of-thought prompting and reasoning, making it an appealing choice for research into reasoning at a small to medium scale of 20B parameters. Finally, we apply FLAN instruction tuning to the UL2 20B model, achieving MMLU and Big-Bench scores competitive to FLAN-PaLM 62B. We release Flax-based T5X checkpoints for the UL2 20B&Flan-UL2 20B.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| competing pretraining methods | descriptive | abstract: «our method pushes the Pareto-frontier by outperforming T5&GPT-like models» | Заявлено сравнение предлагаемого pre-training метода с T5. |
| NLP transfer tasks | descriptive | abstract: «50 well-established supervised finetuning based NLP tasks» | Перенос через fine-tuning на NLP задачи. |
| same era as T5 | not_visible | — | Дата и допустимая длительность same era не заданы в title + abstract. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Конкуренция с T5 и NLP transfer подтверждены. Неопределённое same era требует отдельного критерия по датам, который нельзя извлечь из abstract.

### 25. paperpilot:case_042

**Оригинальный вопрос:**

> Find papers that solve offline RL but with clearly different approaches than sequence modeling.

**Контекст:** {"reference_arxiv_id": "2106.01345", "reference_title": "Decision Transformer: Reinforcement Learning via Sequence Modeling", "reference_source_url": "https://arxiv.org/abs/2106.01345", "search_direction": "similar_task_different_approach"}

**Цель:** [BRAC+: Improved Behavior Regularized Actor Critic for Offline Reinforcement Learning](https://www.semanticscholar.org/paper/ac215cee04eb7a5c41b8973c335ad5e82a836b3a) — `s2:ac215cee04eb7a5c41b8973c335ad5e82a836b3a`.

**Название в релизе:** BRAC: Behavior Regularized Actor Critic.

**Оригинальный abstract:**

> Online interactions with the environment to collect data samples for training a Reinforcement Learning (RL) agent is not always feasible due to economic and safety concerns. The goal of Offline Reinforcement Learning is to address this problem by learning effective policies using previously collected datasets. Standard off-policy RL algorithms are prone to overestimations of the values of out-of-distribution (less explored) actions and are hence unsuitable for Offline RL. Behavior regularization, which constraints the learned policy within the support set of the dataset, has been proposed to tackle the limitations of standard off-policy algorithms. In this paper, we improve the behavior regularized offline reinforcement learning and propose BRAC+. First, we propose quantification of the out-of-distribution actions and conduct comparisons between using Kullback-Leibler divergence versus using Maximum Mean Discrepancy as the regularization protocol. We propose an analytical upper bound on the KL divergence as the behavior regularizer to reduce variance associated with sample based estimations. Second, we mathematically show that the learned Q values can diverge even using behavior regularized policy update under mild assumptions. This leads to large overestimations of the Q values and performance deterioration of the learned policy. To mitigate this issue, we add a gradient penalty term to the policy evaluation objective. By doing so, the Q values are guaranteed to converge. On challenging offline RL benchmarks, BRAC+ outperforms the baseline behavior regularized approaches by 40%~87% and the state-of-the-art approach by 6%.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| offline RL | exact | abstract: «Offline RL» |  |
| different approaches than sequence modeling | descriptive | abstract: «behavior regularized offline reinforcement learning» | Другой механизм: регуляризация policy/Q, а не sequence modeling. Вывод учитывает anchor Decision Transformer. |

**Соответствие:** `supported`; нужны дополнительные источники: нет; уверенность: `high`.

Offline RL и behavior-regularized actor-critic дают содержательно другой подход по сравнению с Decision Transformer из контекста. В релизе BRAC, по ID — BRAC+: существенная разница цели сохраняется отдельно.

### 26. paperpilot:case_007

**Оригинальный вопрос:**

> Find later reasoning papers that build on chain-of-thought prompting.

**Контекст:** {"reference_arxiv_id": "2201.11903", "reference_title": "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models", "reference_source_url": "https://arxiv.org/abs/2201.11903", "search_direction": "followup_work"}

**Цель:** [Program of Thoughts Prompting: Disentangling Computation from Reasoning for Numerical Reasoning Tasks](https://www.semanticscholar.org/paper/6c943670dca38bfc7c8b477ae7c2d1fba1ad3691) — `s2:6c943670dca38bfc7c8b477ae7c2d1fba1ad3691`.

**Оригинальный abstract:**

> Recently, there has been significant progress in teaching language models to perform step-by-step reasoning to solve complex numerical reasoning tasks. Chain-of-thoughts prompting (CoT) is by far the state-of-art method for these tasks. CoT uses language models to perform both reasoning and computation in the multi-step `thought' process. To disentangle computation from reasoning, we propose `Program of Thoughts' (PoT), which uses language models (mainly Codex) to express the reasoning process as a program. The computation is relegated to an external computer, which executes the generated programs to derive the answer. We evaluate PoT on five math word problem datasets (GSM, AQuA, SVAMP, TabMWP, MultiArith) and three financial-QA datasets (FinQA, ConvFinQA, TATQA) for both few-shot and zero-shot setups. Under both few-shot and zero-shot settings, PoT can show an average performance gain over CoT by around 12\% across all the evaluated datasets. By combining PoT with self-consistency decoding, we can achieve SoTA performance on all math problem datasets and near-SoTA performance on financial datasets. All of our data and code are released in Github https://github.com/wenhuchen/Program-of-Thoughts

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| later reasoning papers | uncertain | title: «Numerical Reasoning Tasks» | Reasoning подтверждено; позже ли anchor — по этим полям не установить. |
| build on chain-of-thought prompting | descriptive | abstract: «Chain-of-thoughts prompting (CoT)»; abstract: «To disentangle computation from reasoning, we propose `Program of Thoughts' (PoT)» | Связь с CoT устанавливается соседними предложениями о Chain-of-thoughts prompting и вычислениях; PoT — новый метод, не синоним CoT. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Развитие CoT в PoT описано прямо. Отношение later требует проверки даты вне title + abstract.

### 27. paperpilot:case_038

**Оригинальный вопрос:**

> Find benchmark or dataset papers for evaluating modern graph learning methods.

**Контекст:** {"reference_arxiv_id": "2005.00687", "reference_title": "Open Graph Benchmark: Datasets for Machine Learning on Graphs", "reference_source_url": "https://arxiv.org/abs/2005.00687", "search_direction": "benchmark_evaluation"}

**Цель:** [TUDataset: A collection of benchmark datasets for learning with graphs](https://www.semanticscholar.org/paper/3302081b8878de505b69900e22b8137c5d931be7) — `s2:3302081b8878de505b69900e22b8137c5d931be7`.

**Оригинальный abstract:**

> Recently, there has been an increasing interest in (supervised) learning with graph data, especially using graph neural networks. However, the development of meaningful benchmark datasets and standardized evaluation procedures is lagging, consequently hindering advancements in this area. To address this, we introduce the TUDataset for graph classification and regression. The collection consists of over 120 datasets of varying sizes from a wide range of applications. We provide Python-based data loaders, kernel and graph neural network baseline implementations, and evaluation tools. Here, we give an overview of the datasets, standardized evaluation procedures, and provide baseline experiments. All datasets are available at this http URL. The experiments are fully reproducible from the code available at this http URL.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| benchmark or dataset papers | descriptive | abstract: «we introduce the TUDataset for graph classification and regression» | Работа представляет dataset, а не только использует чужой набор. |
| graph learning methods | descriptive | abstract: «kernel and graph neural network baseline implementations» | Конкретные методы graph learning, для которых предоставлены baseline/evaluation tools. |

**Соответствие:** `supported`; нужны дополнительные источники: нет; уверенность: `high`.

Статья явно представляет набор graph benchmarks и evaluation tools. Слово modern не имеет отдельного датированного критерия в вопросе.

### 28. paperpilot:case_001

**Оригинальный вопрос:**

> Find follow-up work that builds directly on the Transformer architecture introduced in this paper for large-scale language modeling.

**Контекст:** {"reference_arxiv_id": "1706.03762", "reference_title": "Attention Is All You Need", "reference_source_url": "https://arxiv.org/abs/1706.03762", "search_direction": "followup_work"}

**Цель:** [RoBERTa: A Robustly Optimized BERT Pretraining Approach](https://www.semanticscholar.org/paper/077f8329a7b6fa3b7c877a57b81eb6c18b5f87de) — `s2:077f8329a7b6fa3b7c877a57b81eb6c18b5f87de`.

**Оригинальный abstract:**

> Language model pretraining has led to significant performance gains but careful comparison between different approaches is challenging. Training is computationally expensive, often done on private datasets of different sizes, and, as we will show, hyperparameter choices have significant impact on the final results. We present a replication study of BERT pretraining (Devlin et al., 2019) that carefully measures the impact of many key hyperparameters and training data size. We find that BERT was significantly undertrained, and can match or exceed the performance of every model published after it. Our best model achieves state-of-the-art results on GLUE, RACE and SQuAD. These results highlight the importance of previously overlooked design choices, and raise questions about the source of recently reported improvements. We release our models and code.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| follow-up work | descriptive | abstract: «a replication study of BERT pretraining (Devlin et al., 2019)» | Видно продолжение BERT; прямое отношение к Transformer anchor этим не доказано. |
| builds directly on the Transformer architecture | not_visible | — | Transformer не назван; знание архитектуры BERT из весов не заменяет текстовое свидетельство. |
| large-scale language modeling | descriptive | abstract: «Language model pretraining» | Language modeling виден; масштаб обосновывается лишь косвенно computationally expensive/data size, без размеров модели. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

Language model pretraining и развитие BERT видны. Transformer architecture и прямое отношение к anchor Attention Is All You Need не установлены из abstract; нельзя восстанавливать их из памяти модели.

### 29. paperpilot:case_019

**Оригинальный вопрос:**

> Find survey or review papers on retrieval-augmented generation and related retrieval pipelines for LLMs.

**Контекст:** {"reference_arxiv_id": "2005.11401", "reference_title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", "reference_source_url": "https://arxiv.org/abs/2005.11401", "search_direction": "survey_review"}

**Цель:** [Pointwise Mutual Information Based Metric and Decoding Strategy for Faithful Generation in Document Grounded Dialogs](https://www.semanticscholar.org/paper/fdb0f24fdf31b703921e4044ea1f55d82074b56f) — `s2:fdb0f24fdf31b703921e4044ea1f55d82074b56f`.

**Название в релизе:** Document Grounded Generation: A Survey.

**Оригинальный abstract:**

> A major concern in using deep learning based generative models for document-grounded dialogs is the potential generation of responses that are not \textit{faithful} to the underlying document. Existing automated metrics used for evaluating the faithfulness of response with respect to the grounding document measure the degree of similarity between the generated response and the document's content. However, these automated metrics are far from being well aligned with human judgments. Therefore, to improve the measurement of faithfulness, we propose a new metric that utilizes (Conditional) Point-wise Mutual Information (PMI) between the generated response and the source document, conditioned on the dialogue. PMI quantifies the extent to which the document influences the generated response -- with a higher PMI indicating a more faithful response. We build upon this idea to create a new decoding technique that incorporates PMI into the response generation process to predict more faithful responses. Our experiments on the BEGIN benchmark demonstrate an improved correlation of our metric with human evaluation. We also show that our decoding technique is effective in generating more faithful responses when compared to standard decoding techniques on a set of publicly available document-grounded dialog datasets.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| survey or review papers | not_visible | — | Авторское описание we propose a new metric указывает на исследовательский вклад; survey/review не заявлен. |
| retrieval-augmented generation | uncertain | abstract: «document-grounded dialogs» | Document grounding не обязательно retrieval-augmented generation: retrieval компонент не описан. |
| retrieval pipelines for LLMs | not_visible | — | Retrieval pipeline для LLM в abstract не описан. |

**Соответствие:** `not_supported`; нужны дополнительные источники: да; уверенность: `high`.

По S2 ID возвращена исследовательская работа о PMI metric/decoding, а релиз называет Document Grounded Generation: A Survey. Статья не представлена как survey, RAG/retrieval pipeline не заявлены. Сначала нужно проверить или исправить ID, а не оценивать терминологический разрыв.

### 30. paperpilot:case_036

**Оригинальный вопрос:**

> Find later graph attention or attention-based GNN papers that follow GAT.

**Контекст:** {"reference_arxiv_id": "1710.10903", "reference_title": "Graph Attention Networks", "reference_source_url": "https://arxiv.org/abs/1710.10903", "search_direction": "followup_work"}

**Цель:** [How Attentive are Graph Attention Networks?](https://www.semanticscholar.org/paper/ab30672c8c5e4787f6a5985f26a8f281f0db2fb8) — `s2:ab30672c8c5e4787f6a5985f26a8f281f0db2fb8`.

**Название в релизе:** GATv2: How Attentive are Graph Attention Networks?.

**Оригинальный abstract:**

> Graph Attention Networks (GATs) are one of the most popular GNN architectures and are considered as the state-of-the-art architecture for representation learning with graphs. In GAT, every node attends to its neighbors given its own representation as the query. However, in this paper we show that GAT computes a very limited kind of attention: the ranking of the attention scores is unconditioned on the query node. We formally define this restricted kind of attention as static attention and distinguish it from a strictly more expressive dynamic attention. Because GATs use a static attention mechanism, there are simple graph problems that GAT cannot express: in a controlled problem, we show that static attention hinders GAT from even fitting the training data. To remove this limitation, we introduce a simple fix by modifying the order of operations and propose GATv2: a dynamic graph attention variant that is strictly more expressive than GAT. We perform an extensive evaluation and show that GATv2 outperforms GAT across 11 OGB and other benchmarks while we match their parametric costs. Our code is available at https://github.com/tech-srl/how_attentive_are_gats . GATv2 is available as part of the PyTorch Geometric library, the Deep Graph Library, and the TensorFlow GNN library.

| Понятие/условие вопроса | Тип | Свидетельство из статьи | Комментарий |
|---|---|---|---|
| later | not_visible | — | Отношение по времени требует даты вне выбранных полей. |
| graph attention or attention-based GNN papers | descriptive | abstract: «a dynamic graph attention variant» | Конкретный attention-based GNN. |
| follow GAT | descriptive | abstract: «a simple fix by modifying the order of operations and propose GATv2» | Прямое развитие GAT, а не только тематическая близость. |

**Соответствие:** `partial`; нужны дополнительные источники: да; уверенность: `high`.

GAT→GATv2 прямо описано; later по title + abstract не проверяется. Разница released title — добавленный префикс GATv2, а не доказанная подмена статьи.
