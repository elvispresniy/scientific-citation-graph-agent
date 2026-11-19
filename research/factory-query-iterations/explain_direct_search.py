"""Attribute saved direct-search scores to query features and ablate BM25 terms."""
import numpy as np

from graph_pilot.step2_features import digest, read_json, write_json
from run_direct_search import BASE, bm25_components, describe_ranks, load_index


def contributions(features, values):
    order = np.lexsort((features, -values))
    return [{'feature': str(features[i]), 'contribution': float(values[i])}
            for i in order if values[i] > 0]


def main():
    source = BASE / 'direct-search-v1/results.json'
    baseline = read_json(source)
    index = load_index()
    if index.manifest_hash != baseline['index_manifest_sha256']:
        raise ValueError('Index differs from the direct-search run')
    ids = np.array(list(index.rows))
    queries = [q['question'] for q in baseline['questions']]
    raw = index.vectorizer.transform(queries)
    projected = index.svd.transform(raw)
    norms = np.linalg.norm(projected, axis=1)
    lsa_features = index.vectorizer.get_feature_names_out()
    vocabulary, query_terms, weights = bm25_components(index, ids, queries)
    results = []
    for i, q in enumerate(baseline['questions']):
        targets = [index.rows[pid][0] for pid in q['targets']]
        words = np.array(sorted(query_terms[i]))
        columns = [vocabulary[word] for word in words]
        scores = weights[:, columns].sum(axis=1)
        before = describe_ranks(ids, scores, q['targets'])
        if before != q['methods']['bm25']:
            raise ValueError(f'BM25 ranking differs for {q["group"]} question {q["question_number"]}')
        target_weights = weights[np.ix_(targets, columns)]
        bm25_terms = contributions(words, target_weights.mean(axis=0))
        removed = [item['feature'] for item in bm25_terms[:3]]
        kept_columns = [vocabulary[word] for word in words if word not in removed]
        after = describe_ranks(ids, weights[:, kept_columns].sum(axis=1), q['targets'])

        row = raw[i:i + 1]
        # Expand the dot product in LSA space back into the query's active TF-IDF features.
        lsa_values = ((index.vectors[targets] @ index.svd.components_[:, row.indices])
                      * (row.data / norms[i]))
        cosine = index.vectors[targets] @ (projected[i] / norms[i])
        if not np.allclose(lsa_values.sum(axis=1), cosine, rtol=1e-5, atol=1e-6):
            raise ValueError('LSA contributions do not sum to the cosine scores')
        results.append({'group': q['group'], 'question_number': q['question_number'],
                        'bm25_mean_positive_contributions': bm25_terms,
                        'lsa_mean_positive_contributions': contributions(lsa_features[row.indices], lsa_values.mean(axis=0)),
                        'bm25_ablation': {'removed': removed, 'target_ranks': after['target_ranks'],
                                          'target_hits': after['target_hits']},
                        'per_target': {pid: {
                            'bm25': contributions(words, target_weights[j]),
                            'tfidf_lsa': contributions(lsa_features[row.indices], lsa_values[j]),
                        } for j, pid in enumerate(q['targets'])}})
    output = BASE / 'direct-search-attribution-v1'
    output.mkdir(exist_ok=False)
    write_json(output / 'results.json', {'direct_search_sha256': digest(source.read_bytes()), 'questions': results})


if __name__ == '__main__':
    main()
