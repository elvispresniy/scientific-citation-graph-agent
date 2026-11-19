"""Adapter from unchanged step-1 eligibility metrics to the native Gumbel sampler."""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import sqlite3
import subprocess
import time

from . import factory_step1 as baseline


NATIVE_VERSION = 'gumbel-topk-splitmix64-v1'


def candidate_key(paper_id):
    return int.from_bytes(hashlib.sha256(paper_id.encode('utf-8')).digest()[:8], 'little')


def export_candidates(candidates, path):
    """Export only eligible rows. Detect ID/hash collisions instead of silently merging."""
    mapping = {}
    lines = []
    for row in sorted((c for c in candidates if c['eligible']), key=lambda c: c['paper_id']):
        weight = row['weight']
        if isinstance(weight, bool) or not isinstance(weight, (float, int)) or not math.isfinite(weight) or weight <= 0:
            raise ValueError('Eligible candidate weights must be finite and positive')
        key = candidate_key(row['paper_id'])
        if key in mapping:
            raise ValueError('Duplicate paper ID or SHA-256/64 collision')
        mapping[key] = row
        lines.append(f'{key}\t{float(weight):.17g}\n')
    payload = ''.join(lines).encode('utf-8')
    Path(path).write_bytes(payload)
    return mapping, hashlib.sha256(payload).hexdigest()


def invoke(binary, input_path, *, k, seed, threads, repeat=1, warmup=0):
    if type(threads) is not int or not 1 <= threads <= 1024:
        raise ValueError('threads must be an integer in 1..1024')
    if type(repeat) is not int or not 1 <= repeat <= 10000:
        raise ValueError('repeat must be an integer in 1..10000')
    command = [str(Path(binary).resolve()), '--input', str(Path(input_path).resolve()),
               '--k', str(k), '--seed', str(seed % (1 << 64)), '--threads', str(threads),
               '--repeat', str(repeat), '--warmup', str(warmup)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f'Native sampler failed: {result.stderr.strip()}')
    payload = json.loads(result.stdout)
    if payload['algorithm_version'] != NATIVE_VERSION:
        raise ValueError('Native sampler version mismatch; rebuild the binary')
    return payload


def run(database, config, output, *, binary, threads=1, repeat=1):
    started = time.perf_counter()
    database, output, binary = (Path(p).resolve() for p in (database, output, binary))
    if output.exists():
        raise FileExistsError(f'Use a new output directory: {output}')
    if not binary.is_file():
        raise FileNotFoundError(f'Build the native sampler first: {binary}')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA cache_size=-16384')
        connection.execute('BEGIN')
        candidates, counts, fingerprints = baseline.analyze(connection, config)
    analyzed = time.perf_counter()
    # A failed invocation leaves an inspectable input, never overwrites another run.
    output.mkdir(parents=True, exist_ok=False)
    input_path = output / 'eligible.tsv'
    mapping, input_sha256 = export_candidates(candidates, input_path)
    exported = time.perf_counter()
    native = invoke(binary, input_path, k=config.K, seed=config.rng_seed,
                    threads=threads, repeat=repeat)
    sampled = time.perf_counter()
    chosen = native['selected']
    if native['n'] != len(mapping) or len(chosen) != min(config.K, len(mapping)):
        raise ValueError('Native sampler returned an invalid count')
    if len({r['id'] for r in chosen}) != len(chosen) or any(r['id'] not in mapping for r in chosen):
        raise ValueError('Native sampler returned duplicate or unknown IDs')
    selected = [{**mapping[r['id']], 'draw': i + 1, 'gumbel_score': r['score']}
                for i, r in enumerate(chosen)]
    report = {
        'purpose': 'factory step 1; native sampling validation, not a scientific benchmark',
        'algorithm_version': NATIVE_VERSION,
        'config': asdict(config), 'snapshot_id': config.snapshot_id, 'database': str(database),
        'degree_scope': 'induced snapshot defined by nodes; valid unique edges only',
        'readability_scope': 'available status in source index; no text read during selection',
        'candidate_order': 'canonical paper_id ascending; random keys depend on ID, not row position',
        'counts': counts, 'fingerprints': fingerprints,
        'selected': selected, 'selected_count': len(selected),
        'selected_ids_sha256': baseline.digest_rows(c['paper_id'] for c in selected),
        'stop_reason': 'K_reached' if len(selected) == config.K else 'candidate_pool_exhausted',
        'rng': {'implementation': 'SplitMix64 keyed by SHA-256/64 paper ID and uint64 seed; 52-bit open-interval midpoints',
                'seed_uint64': config.rng_seed % (1 << 64),
                'id_encoding': 'first 8 SHA-256 bytes of UTF-8 paper_id, little-endian; collisions rejected',
                'tie_break': 'smaller uint64 ID first',
                'historical_sequence': 'same sampling distribution in ideal arithmetic, different draws from MT19937'},
        'implementation': {
            'adapter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'analyzer_sha256': hashlib.sha256(Path(baseline.__file__).read_bytes()).hexdigest(),
            'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
            'input_sha256': input_sha256,
            'python_version': platform.python_version(), 'platform': platform.platform()},
        'timings': {'analysis_seconds': analyzed - started, 'export_seconds': exported - analyzed,
                    'native_process_seconds': sampled - exported,
                    'scope': 'analysis separate; native kernel excludes TSV read and process startup; artifacts written afterwards'},
        'native': native, 'elapsed_seconds': sampled - started,
    }
    (output / 'config.json').write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2) + '\n')
    (output / 'candidates.jsonl').write_text(''.join(baseline.encoded(c) + '\n' for c in candidates))
    (output / 'selected.jsonl').write_text(''.join(baseline.encoded(c) + '\n' for c in selected))
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report
