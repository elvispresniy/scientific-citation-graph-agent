"""Bounded, offline size measurement of raw and merged local arXiv LaTeX."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import gzip
import importlib.util
from itertools import combinations, islice
import json
from pathlib import Path
import statistics
import time


def percentile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)


def summarize(records, prefix):
    valid = [r for r in records if prefix + '_tokens' in r]
    if not valid:
        return {'n': 0}
    tokens = [r[prefix + '_tokens'] for r in valid]
    pairs = [a + b for a, b in combinations(tokens, 2)]
    return {
        'n': len(valid), 'mean_tokens': statistics.mean(tokens), 'median_tokens': statistics.median(tokens),
        'p90_tokens': percentile(tokens, .9), 'p95_tokens': percentile(tokens, .95), 'max_tokens': max(tokens),
        'mean_characters': statistics.mean(r[prefix + '_characters'] for r in valid),
        'mean_utf8_bytes': statistics.mean(r[prefix + '_utf8_bytes'] for r in valid),
        'over_100000_tokens': sum(v > 100000 for v in tokens),
        'over_100000_fraction': sum(v > 100000 for v in tokens) / len(tokens),
        'over_200000_tokens': sum(v > 200000 for v in tokens),
        'longest_paper_id': max(valid, key=lambda r: r[prefix + '_tokens'])['paper_id'],
        'all_sample_pairs': len(pairs),
        'pairs_over_196000_article_tokens': sum(v > 196000 for v in pairs),
        'over_100000_papers': [{'paper_id': r['paper_id'], 'tokens': r[prefix + '_tokens']}
                               for r in valid if r[prefix + '_tokens'] > 100000],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parquet', type=Path, action='append', required=True)
    parser.add_argument('--merger', type=Path, required=True, help='Trusted local compile_arxiv.py')
    parser.add_argument('--cleaner', type=Path, help='Trusted local latex_to_text.py; use as-is after merging')
    parser.add_argument('--cleaned-dir', type=Path, help='New directory for optional cleaned gzip JSON artifacts')
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--expected-tokenizer-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output file')
    if args.cleaned_dir and (not args.cleaner or args.cleaned_dir.exists()):
        parser.error('--cleaned-dir requires --cleaner and a new directory')
    tokenizer_sha256 = hashlib.sha256(args.tokenizer.read_bytes()).hexdigest()
    if tokenizer_sha256 != args.expected_tokenizer_sha256:
        parser.error('Tokenizer SHA-256 does not match')
    import pyarrow.parquet as pq
    import tokenizers
    tokenizer = tokenizers.Tokenizer.from_file(str(args.tokenizer))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    spec = importlib.util.spec_from_file_location('measurement_trusted_merger', args.merger)
    merger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(merger)
    cleaner = None
    if args.cleaner:
        spec = importlib.util.spec_from_file_location('measurement_trusted_cleaner', args.cleaner)
        cleaner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cleaner)
    if args.cleaned_dir:
        args.cleaned_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {
        'date': '2026-10-24',
        'sampling': 'First 64 rows of first/middle/last row groups per file; nonrandom convenience sample.',
        'limitation': 'Conditional on successful merging; not a population estimate or source coverage estimate.',
        'tokenizer': {'model': 'Qwen/Qwen3.8-27B', 'sha256': tokenizer_sha256,
                      'tokenizers_version': tokenizers.__version__, 'add_special_tokens': False,
                      'chat_template': False, 'truncation': False,
                      'server_tokenizer_identity_verified': False},
        'merger': {'path': str(args.merger.resolve()),
                   'sha256': hashlib.sha256(args.merger.read_bytes()).hexdigest(),
                   'policy': 'process_row defaults; include bibliography, macros and inlined styles; no text cleaning'},
        'files': [],
    }
    if cleaner:
        report['cleaner'] = {'path': str(args.cleaner.resolve()),
                             'sha256': hashlib.sha256(args.cleaner.read_bytes()).hexdigest(),
                             'function': 'latex_to_index_text(merged_latex); defaults, no modifications',
                             'counted_payload': 'text only; citations and sections stored separately',
                             'cleaned_dir': str(args.cleaned_dir.resolve()) if args.cleaned_dir else None}

    def measure(record, prefix, text):
        record[prefix + '_tokens'] = len(tokenizer.encode(text, add_special_tokens=False).ids)
        record[prefix + '_characters'] = len(text)
        record[prefix + '_utf8_bytes'] = len(text.encode())

    for path in args.parquet:
        pf = pq.ParquetFile(path)
        groups = sorted({0, pf.num_row_groups // 2, pf.num_row_groups - 1})
        records = []
        for group in groups:
            if time.monotonic() - started > 240:
                raise TimeoutError('Measurement exceeded 240 seconds')
            row_index = 0
            for batch in islice(pf.iter_batches(batch_size=16, row_groups=[group],
                                              columns=['id', 'latex'], use_threads=False), 4):
                for source in batch.to_pylist():
                    record = {'paper_id': source['id'], 'row_group': group, 'row_index': row_index}
                    row_index += 1
                    raw = source['latex']
                    if not isinstance(raw, str) or not raw.strip():
                        record['merge_status'] = 'no_source'
                    elif len(raw.encode()) > 64 * 1024 ** 2:
                        record['merge_status'] = 'source_size_guard'
                    else:
                        measure(record, 'raw', raw)
                        result = merger.process_row(source['id'], raw)
                        record['merge_status'] = result['status']
                        if result['status'] == 'ok' and result.get('merged_latex', '').strip():
                            measure(record, 'merged', result['merged_latex'])
                            if cleaner:
                                cleaned = cleaner.latex_to_index_text(result['merged_latex'])
                                measure(record, 'cleaned', cleaned['text'])
                                record['cleaned_citations'] = cleaned['n_citations']
                                record['cleaned_sections'] = cleaned['n_sections']
                                record['cleaned_empty'] = not cleaned['text'].strip()
                                record['cleaned_token_reduction_fraction'] = 1 - record['cleaned_tokens'] / record['merged_tokens']
                                if args.cleaned_dir:
                                    name = hashlib.sha256((str(path.resolve()) + '|' + source['id']).encode()).hexdigest()
                                    destination = args.cleaned_dir / (name + '.json.gz')
                                    with gzip.open(destination, 'wt') as stream:
                                        json.dump({'paper_id': source['id'], 'source_file': str(path.resolve()),
                                                   'merged_latex_sha256': hashlib.sha256(result['merged_latex'].encode()).hexdigest(),
                                                   'cleaner_sha256': report['cleaner']['sha256'],
                                                   'offset_scope': 'cleaner offsets refer to intermediate transformations, not final text',
                                                   'cleaner_result': cleaned}, stream, ensure_ascii=False)
                                    record['cleaned_artifact'] = str(destination.resolve())
                    records.append(record)
            print(f'{path.name} row group {group}: {row_index} rows', flush=True)
        result = {'path': str(path.resolve()), 'bytes': path.stat().st_size,
                  'mtime_ns': path.stat().st_mtime_ns, 'row_groups': groups, 'rows': len(records),
                  'merge_status': dict(Counter(r['merge_status'] for r in records)),
                  'raw': summarize(records, 'raw'), 'merged_ok': summarize(records, 'merged'), 'records': records}
        if cleaner:
            compared = [r for r in records if 'cleaned_tokens' in r]
            result['cleaned'] = summarize(records, 'cleaned')
            result['cleaned_empty'] = sum(r['cleaned_empty'] for r in compared)
            result['cleaned_total_token_reduction_fraction'] = 1 - sum(r['cleaned_tokens'] for r in compared) / sum(r['merged_tokens'] for r in compared) if compared else None
        report['files'].append(result)
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'files': [{k: v for k, v in f.items() if k != 'records'} for f in report['files']],
                      'elapsed_seconds': report['elapsed_seconds']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
