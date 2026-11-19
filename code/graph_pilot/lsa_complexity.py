"""Measure saved-question retrieval quality at different LSA dimensions."""
import argparse
from datetime import datetime, timezone
import gzip
import importlib.metadata
import json
from pathlib import Path
from statistics import mean, stdev

import joblib
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from .direct_retrieval import describe_ranks
from .step2_features import ROOT, digest, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=ROOT / 'research/factory-step2-pilot/index-001')
    parser.add_argument('--questions', type=Path,
                        default=ROOT / 'research/factory-e2e/question-status-20261115/questions-status.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    manifest = read_json(args.index / 'manifest.json')
    source = read_json(args.questions)
    questions = [row for row in source['rows'] if row['initial_target_count'] is not None]
    if len(questions) != 33 or sum(row['initial_target_count'] for row in questions) != 86:
        raise ValueError('Expected the frozen 33 original questions and 86 target pairs')
    ids = np.array([row['paper_id'] for row in manifest['rows']])
    for name, expected in manifest['files'].items():
        if digest((args.index / name).read_bytes()) != expected:
            raise ValueError(f'Index checksum differs for {name}')
    vectorizer, frozen_svd = joblib.load(args.index / 'transform.joblib')
    if frozen_svd.random_state != 42 or manifest['effective_components'] != 128:
        raise ValueError('Expected the frozen 128-component index with random_state=42')

    inputs = {'index_manifest_sha256': digest((args.index / 'manifest.json').read_bytes()),
              'questions_sha256': digest(args.questions.read_bytes())}
    write_json(args.output / 'config.json', {
        **inputs, 'dimensions': [32, 64, 128, 256], 'random_state': 42, 'k': 20,
        'question_ids': [row['id'] for row in questions], 'target_pairs': 86,
        'packages': {name: importlib.metadata.version(name)
                     for name in ['numpy', 'scipy', 'scikit-learn', 'joblib']},
        'script_sha256': digest(Path(__file__).read_bytes()),
        'baseline': 'Frozen transform and document vectors at dimension 128',
        'spread': 'Sample standard deviation across questions; no seed averaging',
    })

    def texts():
        for row in manifest['rows']:
            raw = (args.index / row['artifact']).read_bytes()
            if digest(raw) != row['sha256']:
                raise ValueError(f'Text checksum differs for {row["paper_id"]}')
            yield json.loads(gzip.decompress(raw))['paper']['text']

    matrix = vectorizer.transform(texts())
    queries = vectorizer.transform([row['question'] for row in questions])
    dimensions = []
    with threadpool_limits(limits=4):
        for components in [32, 64, 128, 256]:
            if components == 128:
                svd = frozen_svd
                vectors = np.load(args.index / 'vectors.npy', allow_pickle=False)
            else:
                svd = TruncatedSVD(n_components=components, random_state=42)
                vectors = normalize(svd.fit_transform(matrix)).astype(np.float32)
            scores = normalize(svd.transform(queries)) @ vectors.T
            results = []
            for row, values in zip(questions, scores):
                ranked = describe_ranks(ids, values, row['initial_target_ids'])
                if components == 128 and ranked['target_ranks'] != row['ranks']['tfidf_lsa']:
                    raise ValueError(f'The frozen baseline does not reproduce ranks for {row["id"]}')
                hits = ranked['target_hits']['@20']
                results.append({'id': row['id'], 'target_count': row['initial_target_count'],
                                'target_ranks': ranked['target_ranks'], 'hits_at_20': hits,
                                'miss_rate_at_20': 1 - hits / row['initial_target_count']})
            errors = [row['miss_rate_at_20'] for row in results]
            dimensions.append({'components': components, 'questions': results,
                               'mean_miss_rate': mean(errors), 'sd_miss_rate': stdev(errors),
                               'hits_at_20': sum(row['hits_at_20'] for row in results)})

    if inputs['questions_sha256'] != digest(args.questions.read_bytes()):
        raise ValueError('Question inputs changed during execution')
    for name, expected in manifest['files'].items():
        if digest((args.index / name).read_bytes()) != expected:
            raise ValueError(f'Frozen index changed during execution: {name}')
    write_json(args.output / 'results.json', {
        **inputs, 'status': 'finished', 'finished_at': datetime.now(timezone.utc).isoformat(),
        'question_count': len(questions), 'target_pairs': 86, 'indexed_papers': len(ids),
        'baseline_ranks_reproduced': True, 'dimensions': dimensions,
    })
    print('Finished LSA dimension comparison; all frozen baseline target ranks reproduced.')


if __name__ == '__main__':
    main()
