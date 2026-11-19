"""Fixed-input strong-scaling experiments; synthetic rows are explicitly labelled."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path(__file__).parent / 'build/gumbel_topk')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sizes', type=int, nargs='+', default=[100_000, 1_000_000, 10_000_000])
    parser.add_argument('--threads', type=int, nargs='+', default=[1, 2, 4, 8])
    parser.add_argument('--k', type=int, nargs='+', default=[20])
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--repeat', type=int, default=7)
    parser.add_argument('--warmup', type=int, default=1)
    parser.add_argument('--weight-pattern', nargs='+', choices=['uniform', 'skewed'], default=['uniform'])
    parser.add_argument('--environment-label', choices=['local', 'lomonosov2'], default='local')
    args = parser.parse_args()
    if min(args.sizes) < 1 or min(args.threads) < 1 or min(args.k) < 0 or args.repeat < 1 or args.warmup < 0:
        parser.error('Invalid sizes, threads, k, repeat or warmup')
    if 1 not in args.threads:
        parser.error('Include --threads 1 for a same-language serial baseline')
    if args.environment_label == 'lomonosov2' and not os.environ.get('SLURM_JOB_ID'):
        parser.error('Lomonosov-2 measurements must run inside a SLURM job')
    affinity = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    if affinity is not None and max(args.threads) > len(affinity):
        parser.error('Requested more threads than CPUs in the process affinity mask')
    if args.output.exists():
        parser.error('Use a new output directory')
    args.output.mkdir(parents=True)
    binary = args.binary.resolve()
    results = []
    cases = [(n, k, pattern) for n in args.sizes for k in args.k for pattern in args.weight_pattern]
    single_case_format = len(args.k) == 1 and len(args.weight_pattern) == 1
    for n, k, pattern in cases:
        reference = None
        baseline = None
        for p in sorted(set(args.threads)):
            command = [str(binary), '--synthetic', str(n), '--weight-pattern', pattern,
                       '--k', str(k), '--seed', str(args.seed % (1 << 64)), '--threads', str(p),
                       '--repeat', str(args.repeat), '--warmup', str(args.warmup)]
            wall = time.perf_counter()
            process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     universal_newlines=True, check=True)
            native = json.loads(process.stdout)
            process_seconds = time.perf_counter() - wall
            if native['threads_used'] != p:
                raise RuntimeError('Runtime did not provide requested thread count')
            if (native['n'] != n or native['k_requested'] != k or
                    len(native['selected']) != min(n, k)):
                raise RuntimeError('Native input or output dimensions differ from the requested case')
            if reference is None:
                reference = native['selected']
            if native['selected'] != reference:
                raise RuntimeError('IDs or scores differ from the one-thread reference')
            median = statistics.median(t['total_seconds'] for t in native['timings'])
            if p == 1:
                baseline = median
            row = {'n': n, 'k': k, 'weight_pattern': pattern, 'threads': p, 'median_kernel_seconds': median,
                   'median_local_seconds': statistics.median(t['local_seconds'] for t in native['timings']),
                   'median_merge_seconds': statistics.median(t['merge_seconds'] for t in native['timings']),
                   'speedup': baseline / median, 'efficiency': baseline / median / p,
                   'matches_one_thread': True, 'process_seconds': process_seconds,
                   'command': command, 'native': native}
            results.append(row)
            print(f'N={n:,} K={k:,} weights={pattern} p={p}: {median:.6f}s, speedup={row["speedup"]:.3f}', flush=True)
            name = f'n{n}-p{p}.json' if single_case_format else f'n{n}-k{k}-{pattern}-p{p}.json'
            (args.output / name).write_text(json.dumps(row, indent=2) + '\n')
    report = {'schema_version': 2, 'purpose': 'kernel strong-scaling experiment on synthetic inputs',
              'environment_label': args.environment_label,
              'input': {'kind': 'synthetic', 'ids': 'uint64 0..N-1',
                        'weight_patterns': args.weight_pattern, 'sizes': args.sizes,
                        'ks': args.k, 'seed_uint64': args.seed % (1 << 64),
                        'weight_definitions': {'uniform': '1', 'skewed': '10**(id%7-3)'}},
              'timing_scope': 'in-memory keys, local heaps, merge and allocation; excludes input generation, I/O and process startup',
              'environment': {'platform': platform.platform(), 'logical_cpus': os.cpu_count(),
                              'hostname': platform.node(), 'python': sys.version,
                              'cpu_affinity': affinity,
                              'binary': str(binary), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                              'SLURM_JOB_ID': os.environ.get('SLURM_JOB_ID'),
                              'SLURM_JOB_NODELIST': os.environ.get('SLURM_JOB_NODELIST'),
                              'OMP_DYNAMIC': os.environ.get('OMP_DYNAMIC'),
                              'OMP_PROC_BIND': os.environ.get('OMP_PROC_BIND'),
                              'OMP_PLACES': os.environ.get('OMP_PLACES')},
              'results': results}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Gumbel-Top-k strong scaling', '',
             f'Environment: {args.environment_label}. Synthetic inputs; native one-thread baseline.', '',
             '| N | K | Weights | Threads | Kernel, s (median) | Speedup | Efficiency | Exact match |',
             '|---:|---:|:---|---:|---:|---:|---:|:---:|']
    for row in results:
        lines.append(f'| {row["n"]:,} | {row["k"]:,} | {row["weight_pattern"]} | {row["threads"]} | {row["median_kernel_seconds"]:.6f} | '
                     f'{row["speedup"]:.3f} | {row["efficiency"]:.3f} | yes |')
    (args.output / 'summary.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
