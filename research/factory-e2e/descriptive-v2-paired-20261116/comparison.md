# Сравнение промптов описательного переформулирования v1/v2

Шесть одинаковых исходных вопросов, те же аспекты, поисковая обратная связь и прежние цели. Изменена инструкция генерации. Судья исходный true/false. Это один ответ генератора на вход, а не оценка устойчивости по повторам.

| ID | Целей | v1: цели true | v2: цели true | v1: BM25/LSA top-20 | v2: BM25/LSA top-20 | v2: новых true старый+новый пул | Контроль v2 |
|---|---:|---:|---:|---|---|---:|---|
| N01 | 2 | 2 | 2 | 2/2 | 2/2 | 1 | 34/34 |
| N08 | 4 | 3 | 3 | 4/4 | 4/4 | 0 | 34/35 |
| N09 | 7 | 5 | 2 | 6/4 | 5/2 | 0 | 43/44 |
| N14 | 4 | 4 | 4 | 4/2 | 2/2 | 1 | 49/49 |
| N22 | 3 | 3 | 3 | 3/3 | 2/3 | 2 | 29/29 |
| N23 | 3 | 2 | 2 | 2/1 | 2/2 | 0 | 34/34 |

## Формулировки

### N01

Исходный: How can the initial scale and optional offset of a uniform quantizer be determined by minimizing expected mean-squared quantization error under a parametric or empirical distributional model of the tensor values, in order to reduce run-to-run variance in final accuracy during quantization-aware training at 2–4 bit and avoid the outlier sensitivity of min-max initialization?

v1: How can the initial scale and optional offset of a uniform (equally-spaced) quantizer be determined by minimizing the expected mean-squared quantization error under a parametric or empirical distributional model of the tensor values, to reduce run-to-run variance in final accuracy during quantization-aware training at 2–4 bit and avoid the outlier sensitivity of initialization that sets the quantization range from the min and max of the observed values?

v2: How should the initial scale and offset of an equally-spaced quantizer for 2–4-bit tensor values be chosen by minimizing the expected squared distance between continuous and quantized values under an assumed or empirically estimated probability distribution, in order to reduce run-to-run spread in final accuracy during quantization-aware training and to avoid the sensitivity to extreme values that results from setting the quantization range from the observed minimum and maximum?

### N08

Исходный: How can a variational free energy computed over a sequence of future latent variables under a factored generative model be decomposed into an expected information gain term (KL divergence between posterior and prior beliefs over hidden states or model parameters) and a pragmatic term measuring divergence between policy-conditioned predicted observations and a preference distribution over desired outcomes, so that exploration and exploitation are driven by a single tractable objective without a separate scalar reward signal or heuristic exploration bonus?

v1: How can a variational free energy over a sequence of future latent variables, computed under a factored generative model, be decomposed into an expected information-gain term (the KL divergence between posterior and prior beliefs over hidden states or model parameters) and a pragmatic term measuring the divergence between policy-conditioned predicted observations and a preference distribution over desired outcomes, so that exploration and exploitation are driven by a single tractable objective without a separate scalar reward signal or a heuristic exploration bonus?

v2: In sequential decision-making with a factored probabilistic generative model of environment dynamics, how does the variational free energy over a sequence of future latent variables decompose into (i) a term quantifying expected uncertainty reduction over hidden states and model parameters, given by the KL divergence between the posterior and prior distributions, and (ii) a term measuring the divergence between policy-conditioned predicted observations and a distribution encoding preferred outcomes, so that minimizing this single tractable objective simultaneously drives exploration and exploitation without a separate scalar reward signal or heuristic exploration bonus?

### N09

Исходный: How can evolutionary search over populations of short discrete action sequences, evaluated by rolling them out in a forward model, serve as a real-time planning mechanism for sequential control tasks without requiring a separately trained policy network?

v1: How can evolutionary search over populations of short discrete action sequences, evaluated by rolling each candidate out in a forward model, serve as a real-time planning mechanism for sequential control tasks without requiring a separately trained policy network?

v2: In sequential control tasks with a discrete action space, how can per-step planning be achieved by maintaining a population of short candidate action sequences, iteratively improving them through mutation and recombination, and evaluating each candidate by sequentially applying a learned dynamics model to predict the full state trajectory—so that actions are selected within a fixed computation budget at each decision step without relying on a separately trained action-selection network?

### N14

Исходный: How can the quadratic time and memory cost of full 2D cross-position mixing over a spatial grid of h×w tokens in high-resolution image feature maps be reduced by decomposing the interaction into two sequential 1D mixing operations—one that mixes all positions along the height axis independently for each column and a second that mixes all positions along the width axis independently for each row—while preserving a global receptive field spanning both spatial dimensions?

v1: How can the quadratic time and memory cost of full 2D cross-position mixing over a spatial grid of h×w tokens in high-resolution image feature maps be reduced by decomposing the interaction into two sequential 1D mixing operations—one that mixes all positions along the height axis independently for each column and a second that mixes all positions along the width axis independently for each row—while preserving a global receptive field spanning both spatial dimensions?

v2: How can the quadratic time and memory cost of computing full pairwise interactions over all h×w tokens in a high-resolution 2D image feature map be reduced by factoring the cross-position interaction into two sequential single-axis passes—a first pass that combines all positions along the height direction within each column and a second pass that combines all positions along the width direction within each row—while still ensuring that every output position is influenced by all input positions across both spatial dimensions?

### N22

Исходный: How can a single-resolution transformer token sequence be converted into a multi-scale feature pyramid by successively merging 2×2 spatially neighboring tokens into a single token with doubled channel dimension via a learned linear projection, producing progressively coarser feature maps suitable for dense prediction heads in object detection and semantic segmentation?

v1: How can a transformer token sequence at a single resolution be converted into a multi-scale feature pyramid by successively merging 2×2 spatially neighboring tokens into a single token with doubled channel dimension via a learned linear projection, producing progressively coarser feature maps suitable for dense prediction heads in object detection and semantic segmentation?

v2: How can a transformer producing a single spatial resolution of token features be structured so that, between successive stages, the feature vectors of a 2×2 block of spatially adjacent tokens are concatenated and mapped by a learned linear projection to a single token with doubled channel dimension, yielding a hierarchy of feature maps at progressively coarser resolutions suitable for dense prediction heads in object detection and semantic segmentation?

### N23

Исходный: How does inserting a small-kernel depthwise 2D convolution into the position-wise feed-forward sub-layer of a vision transformer block—reshaping the token sequence to a spatial feature map, applying a per-channel spatial aggregation between channel-expanding and channel-reducing linear projections, and reshaping back—affect image classification and dense prediction accuracy, when the block retains a separate global self-attention mechanism for long-range dependency modeling?

v1: How does adding a small-kernel depthwise 2D convolution to the position-wise feed-forward sub-layer of a vision transformer block—applying per-channel spatial aggregation between the channel-expanding and channel-reducing linear projections after reshaping the token sequence into a spatial feature map—affect image classification and dense prediction accuracy when the block retains a separate global self-attention mechanism for long-range dependency modeling?

v2: In vision transformer blocks that retain a global self-attention mechanism for long-range dependencies, what is the effect on image classification and dense prediction accuracy when a small-kernel 2D convolution applied independently to each feature channel (with no cross-channel mixing) is inserted between the channel-expanding and channel-reducing linear projections of the per-token feed-forward sub-layer, operating on the token sequence after reshaping it into a spatial feature map?

