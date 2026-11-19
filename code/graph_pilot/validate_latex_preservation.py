"""Validate the fixed cleaner on the previous local sample, without tokenization."""
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
from itertools import islice
import json
from pathlib import Path
import time


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--cleaner', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.artifacts.exists():
        parser.error('Use new output paths')
    import pyarrow.parquet as pq
    baseline = json.loads(args.baseline.read_text())
    merger_path = Path(baseline['merger']['path'])
    assert hashlib.sha256(merger_path.read_bytes()).hexdigest() == baseline['merger']['sha256']
    merger = module(merger_path, 'preservation_trusted_merger')
    cleaner = module(args.cleaner, 'preservation_trusted_cleaner')
    cleaner_hash = hashlib.sha256(args.cleaner.read_bytes()).hexdigest()
    args.artifacts.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    records, kinds = [], Counter()
    for file in baseline['files']:
        path = Path(file['path'])
        assert path.stat().st_size == file['bytes'] and path.stat().st_mtime_ns == file['mtime_ns']
        expected = {(r['row_group'], r['row_index']): r for r in file['records']}
        pf = pq.ParquetFile(path)
        for group in file['row_groups']:
            index = 0
            for batch in islice(pf.iter_batches(batch_size=16, row_groups=[group],
                                              columns=['id', 'latex'], use_threads=False), 4):
                for source in batch.to_pylist():
                    previous = expected[(group, index)]
                    index += 1
                    assert source['id'] == previous['paper_id']
                    if previous['merge_status'] != 'ok':
                        continue
                    if time.monotonic() - started > 240:
                        raise TimeoutError('Validation exceeded 240 seconds')
                    merged = merger.process_row(source['id'], source['latex'])
                    assert merged['status'] == 'ok' and merged['merged_latex'].strip()
                    result = cleaner.latex_to_index_text(merged['merged_latex'])
                    assert result['text'].strip(), source['id']
                    assert all(b['latex'] in result['text'] for b in result['preserved_blocks']), source['id']
                    assert all(d['latex'] in result['text'] for d in result['macro_definitions']), source['id']
                    counts = Counter(b['kind'] for b in result['preserved_blocks'])
                    kinds.update(counts)
                    name = hashlib.sha256((str(path.resolve()) + '|' + source['id']).encode()).hexdigest()
                    destination = args.artifacts / (name + '.json.gz')
                    with gzip.open(destination, 'wt') as stream:
                        json.dump({'paper_id': source['id'], 'source_file': str(path),
                                   'cleaner_sha256': cleaner_hash, 'cleaner_result': result}, stream,
                                  ensure_ascii=False)
                    records.append({'paper_id': source['id'], 'source_file': str(path),
                                    'preserved_blocks_by_kind': dict(counts),
                                    'retained_preamble_macros': len(result['macro_definitions']),
                                    'preservation_fallback': result['preservation_fallback'],
                                    'all_preserved_content_present': True,
                                    'artifact': str(destination.resolve())})
            print(f'{path.name}: checked row group {group}', flush=True)
    expected_ok = sum(file['merge_status'].get('ok', 0) for file in baseline['files'])
    assert len(records) == expected_ok
    report = {'purpose': 'content-preservation checks only; no text-length measurement or LLM calls',
              'baseline': str(args.baseline.resolve()), 'cleaner_sha256': cleaner_hash,
              'cleaner_path': str(args.cleaner.resolve()), 'articles_checked': len(records),
              'all_checks_passed': True, 'preserved_blocks_by_kind': dict(kinds),
              'preservation_fallback_articles': [r['paper_id'] for r in records if r['preservation_fallback']],
              'limitation': 'Checks protected-block retention; not proof of complete scientific equivalence',
              'elapsed_seconds': round(time.monotonic() - started, 3), 'records': records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, indent=2))


if __name__ == '__main__':
    main()
