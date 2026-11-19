"""Render the completed LSA dimension experiment from saved metrics."""
import argparse
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'citation-graph-matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    results = json.loads(args.results.read_text())
    if results['status'] != 'finished':
        raise ValueError('The dimension experiment has not finished')
    points = results['dimensions']
    dimensions = [point['components'] for point in points]
    average = [100 * point['mean_miss_rate'] for point in points]
    spread = [100 * point['sd_miss_rate'] for point in points]
    fig, ax = plt.subplots(figsize=(6.4, 3.4), layout='constrained')
    ax.plot(dimensions, average, color='#3569a8', marker='o')
    ax.fill_between(dimensions, [max(0, avg - sd) for avg, sd in zip(average, spread)],
                    [min(100, avg + sd) for avg, sd in zip(average, spread)],
                    color='#3569a8', alpha=0.16, linewidth=0)
    ax.set_xscale('log', base=2)
    ax.set_xticks(dimensions, [str(value) for value in dimensions])
    ax.set_ylim(0, 100)
    ax.set_xlabel('Число компонент LSA')
    ax.set_ylabel('Доля пропущенных целей в top-20, %')
    ax.grid(alpha=0.2)
    ax.spines[['top', 'right']].set_visible(False)
    output = ROOT / 'paper/figures'
    fig.savefig(output / 'lsa-complexity.png', dpi=220)
    fig.savefig(output / 'lsa-complexity.svg', metadata={'Date': None})
    plt.close(fig)


if __name__ == '__main__':
    main()
