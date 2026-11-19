"""Frozen-index BM25/LSA diagnostics shared by the autonomous runner."""
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from sklearn.preprocessing import normalize

K1 = 1.2
B = 0.75
CUTOFFS = (10, 20, 100)


def bm25_components(index, ids, queries):
    preprocess = index.vectorizer.build_preprocessor()
    tokenize = index.vectorizer.build_tokenizer()
    stop_words = index.vectorizer.get_stop_words()

    def terms(text):
        return (word for word in tokenize(preprocess(text)) if word not in stop_words)

    query_terms = [set(terms(query)) for query in queries]
    vocabulary = {word: col for col, word in enumerate(sorted(set.union(*query_terms)))}
    counts = np.zeros((len(ids), len(vocabulary)), dtype=np.float64)
    lengths = np.empty(len(ids), dtype=np.int64)
    def document_counts(pid):
        frequencies = Counter(terms(index.item(pid)['paper']['text']))
        return sum(frequencies.values()), {vocabulary[word]: frequencies[word]
                                          for word in frequencies.keys() & vocabulary.keys()}

    with ThreadPoolExecutor(max_workers=12) as pool:
        for start in range(0, len(ids), 256):
            for i, (length, matches) in enumerate(pool.map(document_counts, ids[start:start + 256]), start):
                lengths[i] = length
                for col, count in matches.items():
                    counts[i, col] = count

    df = np.count_nonzero(counts, axis=0)
    idf = np.log1p((len(ids) - df + 0.5) / (df + 0.5))
    length_penalty = K1 * (1 - B + B * lengths / lengths.mean())
    weights = idf * (K1 + 1) * counts / (counts + length_penalty[:, None])
    return vocabulary, query_terms, weights


def bm25_scores(index, ids, queries):
    vocabulary, query_terms, weights = bm25_components(index, ids, queries)
    return np.stack([weights[:, [vocabulary[word] for word in sorted(words)]].sum(axis=1)
                     for words in query_terms])


def describe_ranks(ids, scores, targets):
    order = np.lexsort((ids, -scores))
    ranks = np.empty(len(ids), dtype=np.int64)
    ranks[order] = np.arange(1, len(ids) + 1)
    by_id = dict(zip(ids, ranks.tolist()))
    target_ranks = {pid: by_id[pid] for pid in sorted(targets)}
    return {'target_ranks': target_ranks,
            'target_hits': {f'@{k}': sum(rank <= k for rank in target_ranks.values()) for k in CUTOFFS},
            'top_20': [{'paper_id': str(ids[i]), 'score': float(scores[i])} for i in order[:20]]}


def search(index, question, targets=()):
    ids = np.array(list(index.rows))
    vector = normalize(index.svd.transform(index.vectorizer.transform([question])))
    scores = vector @ index.vectors.T
    return {"tfidf_lsa": describe_ranks(ids, scores[0], targets),
            "bm25": describe_ranks(ids, bm25_scores(index, ids, [question])[0], targets)}


def ranked_search(index, question):
    """Save full order once; later targets can be ranked without re-reading all texts."""
    ids = np.array(list(index.rows))
    vector = normalize(index.svd.transform(index.vectorizer.transform([question])))
    scores = {'tfidf_lsa': (vector @ index.vectors.T)[0],
              'bm25': bm25_scores(index, ids, [question])[0]}
    result = {}
    for method, values in scores.items():
        order = np.lexsort((ids, -values))
        result[method] = {'ranked_ids': ids[order].tolist(),
                          'top_20': [{'paper_id': str(ids[i]), 'score': float(values[i])} for i in order[:20]]}
    return result


def target_ranks(methods, targets):
    result = {}
    for method, value in methods.items():
        ranks = {pid: rank for rank, pid in enumerate(value['ranked_ids'], 1) if pid in targets}
        result[method] = {'target_ranks': ranks,
                          'target_hits': {f'@{k}': sum(rank <= k for rank in ranks.values()) for k in CUTOFFS},
                          'top_20': value['top_20']}
    return result


def distances(graph, sources):
    adjacency = {}
    for src, dst in graph.db.execute("SELECT src,dst FROM edges"):
        adjacency.setdefault(src, set()).add(dst)
        adjacency.setdefault(dst, set()).add(src)
    distance = dict.fromkeys(sources, 0)
    frontier = deque(sorted(sources))
    while frontier:
        pid = frontier.popleft()
        for neighbor in sorted(adjacency.get(pid, ())):
            if neighbor not in distance:
                distance[neighbor] = distance[pid] + 1
                frontier.append(neighbor)
    return distance
