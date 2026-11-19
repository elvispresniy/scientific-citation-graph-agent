"""Compare TF-IDF/LSA and BM25 over the frozen local paper index."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sklearn.preprocessing import normalize

from graph_pilot.step2_features import Lexicon, TopicIndex, digest, read_json, write_json
from run_queries import BASE, ROOT


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


def load_index():
    research = ROOT / 'research'
    return TopicIndex(research / 'factory-step2-pilot/index-001', Lexicon(research / 'terminology-pilot'),
                      compatibility=research / 'factory-step2-iterations/index-001-compatibility-sources-20261026.json')


def main():
    index = load_index()
    ids = np.array(list(index.rows))
    source = BASE / 'pilot-v1'
    judge_path = BASE / 'judge-subgraph-v1/summary.json'
    judge = read_json(judge_path)['results']
    questions = []
    for group in read_json(source / 'manifest.json')['groups']:
        name = group['name']
        path = source / name / 'questions.json'
        for number, q in enumerate(read_json(path)['questions'], 1):
            targets = [r['paper_id'] for r in judge if r['group'] == name
                       and r['question_number'] == number and r.get('verdict') is True]
            questions.append({'group': name, 'question_number': number, 'question': q['question'],
                              'questions_sha256': digest(path.read_bytes()), 'targets': sorted(targets)})

    queries = [q['question'] for q in questions]
    query_vectors = normalize(index.svd.transform(index.vectorizer.transform(queries)))
    lsa = query_vectors @ index.vectors.T
    bm25 = bm25_scores(index, ids, queries)
    for i, q in enumerate(questions):
        q['methods'] = {name: describe_ranks(ids, matrix[i], q['targets'])
                        for name, matrix in [('tfidf_lsa', lsa), ('bm25', bm25)]}
    output = BASE / 'direct-search-v1'
    output.mkdir(exist_ok=False)
    write_json(output / 'results.json', {'index_manifest_sha256': index.manifest_hash,
               'snapshot': index.manifest['graph']['snapshot_id'], 'indexed_papers': len(ids),
               'unavailable_papers': len(index.manifest['unavailable']),
               'judge_summary_sha256': digest(judge_path.read_bytes()),
               'tfidf_lsa': {'components': index.manifest['effective_components'], 'score': 'cosine'},
               'bm25': {'k1': K1, 'b': B, 'terms': 'unique query unigrams',
                        'tokenization': 'frozen TF-IDF preprocessor, tokenizer and stop words'},
               'ties': 'paper_id ascending', 'questions': questions})


if __name__ == '__main__':
    main()
