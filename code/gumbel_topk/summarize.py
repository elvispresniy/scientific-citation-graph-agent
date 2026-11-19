"""Validate and plot a completed matrix; never replace missing measurements."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--environment-label', choices=['local', 'lomonosov2'], default='lomonosov2')
    parser.add_argument('--sizes', type=int, nargs='+', default=[100000, 1000000, 10000000, 100000000])
    parser.add_argument('--k', type=int, nargs='+', default=[20, 1000, 10000])
    parser.add_argument('--threads', type=int, nargs='+', default=[1, 2, 4, 8, 14])
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output directory')
    expected = {(n, k, w, p) for n in args.sizes for k in args.k
                for w in ['uniform', 'skewed'] for p in args.threads}
    rows, sources = {}, []
    for path in args.reports:
        blob = path.read_bytes()
        report = json.loads(blob)
        if report.get('environment_label') != args.environment_label:
            raise ValueError('Unexpected environment label: ' + str(path))
        environment = report['environment']
        if args.environment_label == 'lomonosov2' and not environment.get('SLURM_JOB_ID'):
            raise ValueError('Missing SLURM job ID: ' + str(path))
        sources.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(blob).hexdigest(),
                        'environment': environment})
        for row in report['results']:
            key = row['n'], row['k'], row['weight_pattern'], row['threads']
            if key in rows:
                raise ValueError('Duplicate configuration: ' + str(key))
            if not row['matches_one_thread'] or row['native']['threads_used'] != row['threads']:
                raise ValueError('Invalid result: ' + str(key))
            rows[key] = row
    if set(rows) != expected:
        raise ValueError('Matrix mismatch: missing={}, unexpected={}'.format(
            sorted(expected - set(rows)), sorted(set(rows) - expected)))
    for key, row in rows.items():
        baseline = rows[key[:3] + (1,)]
        if row['native']['selected'] != baseline['native']['selected']:
            raise ValueError('Selection mismatch: ' + str(key))
        if row['native']['source_sha256'] != baseline['native']['source_sha256']:
            raise ValueError('Source mismatch: ' + str(key))
        ratio = baseline['median_kernel_seconds'] / row['median_kernel_seconds']
        if abs(row['speedup'] - ratio) > 1e-12 * max(1, abs(ratio)):
            raise ValueError('Invalid baseline: ' + str(key))

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    args.output.mkdir(parents=True)
    fig, axes = plt.subplots(2, len(args.k), figsize=(4.5 * len(args.k), 7), squeeze=False)
    for wi, pattern in enumerate(['uniform', 'skewed']):
        for ki, k in enumerate(args.k):
            ax = axes[wi][ki]
            for n in args.sizes:
                ax.plot(args.threads, [rows[n, k, pattern, p]['speedup'] for p in args.threads],
                        marker='o', label='N={:,}'.format(n))
            ax.plot(args.threads, args.threads, '--', color='0.65', label='Ideal')
            ax.set(title='K={:,}; {}'.format(k, pattern), xlabel='Threads P', ylabel='Speedup T(1)/T(P)')
            ax.set_xticks(args.threads)
            ax.grid(alpha=.25)
            ax.legend(fontsize=8)
    fig.suptitle('Gumbel-Top-k: synthetic inputs; ' + args.environment_label)
    fig.tight_layout(rect=(0, 0, 1, .95))
    fig.savefig(str(args.output / 'strong-scaling.png'), dpi=180)
    fig.savefig(str(args.output / 'strong-scaling.svg'))
    plt.close(fig)
    (args.output / 'sources.json').write_text(json.dumps(sources, indent=2) + '\n')
    lines = ['# Gumbel-Top-k: результаты полной матрицы', '',
             'Среда: {}. Данные синтетические. Все {} конфигураций проверены.'.format(
                 args.environment_label, len(rows)), '',
             'Время ядра исключает генерацию входов и I/O. База — тот же бинарный файл с P=1.', '',
             '![Strong scaling](strong-scaling.png)', '',
             '| N | K | Веса | T(1), с | T(Pmax), с | Pmax | Ускорение | Объединение в T(Pmax) |',
             '|---:|---:|:---|---:|---:|---:|---:|---:|']
    last = max(args.threads)
    for n in args.sizes:
        for k in args.k:
            for pattern in ['uniform', 'skewed']:
                one, many = rows[n, k, pattern, 1], rows[n, k, pattern, last]
                # Ratio of medians describes the phases; it is not the median per-run fraction.
                merge = many['median_merge_seconds'] / many['median_kernel_seconds']
                lines.append('| {:,} | {:,} | {} | {:.6f} | {:.6f} | {} | {:.3f} | {:.1%} |'.format(
                    n, k, pattern, one['median_kernel_seconds'], many['median_kernel_seconds'],
                    last, many['speedup'], merge))
    (args.output / 'summary.md').write_text('\n'.join(lines) + '\n')
    print('Validated {} configurations; saved {}'.format(len(rows), args.output))


if __name__ == '__main__':
    main()
