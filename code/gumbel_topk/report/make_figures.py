"""Publication figures and tables from the frozen Lomonosov-2 measurements."""
import csv
import hashlib
import json
import os
from pathlib import Path
import statistics

os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/gumbel-report-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
import numpy as np

REPO = Path(__file__).resolve().parents[3]
RUN = REPO / 'research/factory-step1-pilot/lomonosov2-20261115'
OUT = REPO / 'output/pdf/gumbel-topk-report'
SIZES = [100000, 1000000, 10000000, 100000000]
KS = [20, 1000, 10000]
PS = [1, 2, 4, 8, 14]
WEIGHTS = ['uniform', 'skewed']
COLORS = ['#2563A6', '#16837A', '#D28B28', '#9250A6']
MARKERS = ['o', 's', '^', 'D']
INK = '#202B36'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, provenance, measurements = {}, [], []
    for path in sorted((RUN / 'raw-final/results').glob('full-*/report.json')):
        blob = path.read_bytes()
        d = json.loads(blob)
        assert d['environment_label'] == 'lomonosov2'
        job = d['environment']['SLURM_JOB_ID']
        provenance.append({'path': str(path.relative_to(REPO)),
                           'sha256': hashlib.sha256(blob).hexdigest(),
                           'job_id': job, 'environment': d['environment']})
        for r in d['results']:
            key = (r['n'], r['k'], r['weight_pattern'], r['threads'])
            assert key not in rows
            assert r['matches_one_thread']
            ts = r['native']['timings']
            assert len(ts) == 7 and r['native']['warmup'] == 1
            assert r['native']['threads_used'] == r['threads']
            assert r['native']['seed'] == 42
            totals = [t['total_seconds'] for t in ts]
            # A phase fraction is calculated within each run before taking its median.
            fraction = statistics.median(t['merge_seconds'] / t['total_seconds'] for t in ts)
            rows[key] = {'n': r['n'], 'k': r['k'], 'weights': r['weight_pattern'],
                         'p': r['threads'], 'job_id': job,
                         'median_s': statistics.median(totals),
                         'mean_s': statistics.mean(totals),
                         'min_s': min(totals), 'max_s': max(totals),
                         'stdev_s': statistics.stdev(totals),
                         'merge_fraction': fraction,
                         'native': r['native']}
            for i, t in enumerate(ts, 1):
                measurements.append({'n': r['n'], 'k': r['k'], 'weights': r['weight_pattern'],
                                     'p': r['threads'], 'repeat': i, 'job_id': job, **t})
    expected = {(n, k, w, p) for n in SIZES for k in KS for w in WEIGHTS for p in PS}
    assert set(rows) == expected
    for key, row in rows.items():
        baseline = rows[key[:3] + (1,)]
        assert row['native']['selected'] == baseline['native']['selected']
        row['speedup'] = baseline['median_s'] / row['median_s']
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.labelcolor': INK, 'text.color': INK,
                         'xtick.color': '#56616D', 'ytick.color': '#56616D',
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.edgecolor': '#C9D0D6', 'axes.linewidth': .7,
                         'svg.fonttype': 'none', 'savefig.facecolor': 'white'})
    fig, axes = plt.subplots(2, 3, figsize=(10.0, 6.0), sharex=True, sharey=True)
    fig.subplots_adjust(left=.071, right=.988, bottom=.105, top=.785, wspace=.18, hspace=.48)
    fig.text(.071, .966, 'Сильная масштабируемость Gumbel-Top-k', fontsize=17, weight='bold')
    handles = [Line2D([], [], color=c, marker=marker, lw=2, markersize=4,
                      label=r'$n=10^{%d}$' % exponent)
               for c, marker, exponent in zip(COLORS, MARKERS, [5, 6, 7, 8])]
    handles.append(Line2D([], [], color='#7D8791', ls='--', lw=1.2, label=r'$S=P$'))
    fig.legend(handles=handles, loc='upper left', bbox_to_anchor=(.062, .927),
               ncol=5, frameon=False, handlelength=2.1, columnspacing=1.65)
    fig.text(.071, .841, 'Одинаковые веса:  wᵢ = 1', fontsize=11.5, weight='bold')
    fig.text(.071, .438, r'Различающиеся веса:  $w_i=10^{(\mathrm{ID}\ \mathrm{mod}\ 7)-3}$', fontsize=11.5, weight='bold')
    for wi, w in enumerate(WEIGHTS):
        for ki, k in enumerate(KS):
            ax = axes[wi, ki]
            ax.set_axisbelow(True)
            ax.grid(axis='y', color='#E6EAEF', lw=.65)
            ax.plot([1, 14], [1, 14], ls='--', color='#9099A2', lw=1.15, zorder=1)
            for n, color, marker in zip(SIZES, COLORS, MARKERS):
                ax.plot(PS, [rows[n, k, w, p]['speedup'] for p in PS],
                        color=color, lw=1.8, marker=marker, ms=4.1, markeredgecolor='white',
                        markeredgewidth=.45, zorder=3)
            ax.set_title('k = {:,}'.format(k).replace(',', ' '), fontsize=12, loc='left', pad=5)
            ax.set_xlim(.6, 14.5)
            ax.set_ylim(0, 15.3)
            ax.set_xticks(PS)
            ax.set_yticks([0, 4, 8, 12, 14])
            ax.tick_params(labelsize=10.5, length=3)
            if ki == 0:
                ax.set_ylabel('Ускорение T(1) / T(P)', fontsize=10)
            if wi == 1:
                ax.set_xlabel('Число потоков P', fontsize=10)
    for ext in ['png', 'svg']:
        fig.savefig(str(OUT / ('strong-scaling.' + ext)), dpi=260)
    plt.close(fig)

    cmap = LinearSegmentedColormap.from_list('phase', ['#F2F5F8', '#B8D0E2', '#23618E'])
    fig, axes = plt.subplots(1, 2, figsize=(10.7, 2.65))
    fig.subplots_adjust(left=.071, right=.875, bottom=.2, top=.72, wspace=.3)
    fig.text(.071, .90, 'Объединение и сортировка при P = 14', fontsize=15, weight='bold')
    for wi, w in enumerate(WEIGHTS):
        ax = axes[wi]
        values = np.array([[100 * rows[n, k, w, 14]['merge_fraction'] for k in KS] for n in SIZES])
        im = ax.imshow(values, cmap=cmap, vmin=0, vmax=65, aspect='auto')
        ax.set_xticks(range(3), ['20', '1 000', '10 000'])
        ax.set_yticks(range(4), [r'$10^5$', r'$10^6$', r'$10^7$', r'$10^8$'])
        ax.tick_params(length=0, labelsize=10)
        ax.set_xlabel('Размер выборки k', fontsize=10, labelpad=5)
        ax.set_ylabel('Число элементов n', fontsize=10)
        ax.set_title('Одинаковые веса' if w == 'uniform' else 'Различающиеся веса',
                     fontsize=10.5, loc='left', pad=8)
        for spine in ax.spines.values():
            spine.set_visible(False)
        for i in range(4):
            for j in range(3):
                v = values[i, j]
                label = '<0,1%' if v < .05 else '{:.1f}%'.format(v).replace('.', ',')
                ax.text(j, i, label, ha='center', va='center', fontsize=10.5,
                        color='white' if v > 40 else INK)
    cax = fig.add_axes([.905, .24, .014, .45])
    cb = fig.colorbar(im, cax=cax, ticks=[0, 20, 40, 60])
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=9, length=0)
    cb.set_label('Доля времени, %', fontsize=10, labelpad=7)
    for ext in ['png', 'svg']:
        fig.savefig(str(OUT / ('merge-share.' + ext)), dpi=260)
    plt.close(fig)

    with (OUT / 'measurements.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['n', 'k', 'weights', 'p', 'repeat', 'job_id',
                                              'local_seconds', 'merge_seconds', 'total_seconds'])
        writer.writeheader(); writer.writerows(measurements)
    public_rows = [{k: v for k, v in rows[key].items() if k != 'native'} for key in sorted(rows)]
    data = {'statistic': 'median of 7 measured repetitions after 1 warmup',
            'phase_share_statistic': 'median of within-run merge_seconds/total_seconds',
            'sources': provenance, 'rows': public_rows}
    (OUT / 'plot-data.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('Created two figures, all 120 points and 840 raw measurements:', OUT)


if __name__ == '__main__':
    main()
