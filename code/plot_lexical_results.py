"""Render the approved frozen results; never download or rerun an experiment."""
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'citation-graph-matplotlib'))
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['svg.hashsalt'] = 'lexical-results-v1'
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def put(x, y, content):
    return r'\put(%g,%g){%s}' % (x, y, content)


def main():
    data = json.loads((ROOT / 'code/lexical-results.json').read_text())
    output = ROOT / 'paper/figures'
    output.mkdir(exist_ok=True)
    for view in data['views']:
        rows = view['rows']
        assert sum(row['pairs'] for row in rows) == view['available_pairs']
        # Complements of already published rounded coverage, not new model errors.
        gaps = [round(100 - row['coverage_percent'], 1) for row in rows]
        fig, ax = plt.subplots(figsize=(7.2, 3.8), layout='constrained')
        bars = ax.bar(range(len(rows)), gaps, width=.56, color='#3569a8', zorder=3)
        ax.set_ylim(0, 100)
        ax.set_xticks(range(len(rows)), [row['label'] for row in rows])
        ax.set_ylabel('Доля отсутствующих слов запроса, %')
        ax.set_title(view['title'], fontsize=12, pad=12)
        ax.set_yticks(range(0, 101, 20))
        ax.grid(axis='y', color='#d9dfe7', zorder=0)
        ax.spines[['top', 'right']].set_visible(False)
        for bar, value, row in zip(bars, gaps, rows):
            ax.text(bar.get_x() + bar.get_width()/2, value + 2,
                    f'{value:.1f}%'.replace('.', ','), ha='center', fontsize=11)
        fig.savefig(output / f"lexical-gap-{view['key']}.png", dpi=220)
        svg = output / f"lexical-gap-{view['key']}.svg"
        fig.savefig(svg, metadata={'Date': None})
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
        plt.close(fig)
        # Same figure as inline vector drawing for the single-file editor.
        lines = [r'\begingroup\setlength{\unitlength}{0.8mm}',
                 r'\begin{picture}(145,82)',
                 r'\put(17,14){\line(1,0){124}}', r'\put(17,14){\line(0,1){60}}']
        for tick in range(0, 101, 20):
            y = 14 + .6*tick
            lines += [put(7, y, r'\makebox(8,0)[r]{\scriptsize %d}' % tick),
                      put(17, y, r'\line(1,0){1}')]
        for x, value, row in zip([30, 61, 92, 123], gaps, rows):
            height = .6*value
            label = f'{value:.1f}'.replace('.', ',')
            lines += [put(x-7, 14, r'{\color[rgb]{0.21,0.41,0.66}\rule{14\unitlength}{%.2f\unitlength}}' % height),
                      put(x, 16+height, r'\makebox(0,0){\scriptsize ' + label + r'\%}'),
                      put(x, 8, r'\makebox(0,0){\scriptsize ' + row['label'] + '}')]
        lines += [r'\put(17,80){\makebox(0,0)[l]{\scriptsize Доля отсутствующих слов запроса, \%}}',
                  r'\end{picture}\endgroup']
        (output / f"lexical-gap-{view['key']}.tex").write_text('\n'.join(lines) + '\n')
        print('Rendered frozen result:', view['key'])


if __name__ == '__main__':
    main()
