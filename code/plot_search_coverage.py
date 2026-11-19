"""Plot saved target ranks without invoking retrieval or a language model."""
import json
import os
from pathlib import Path
from statistics import mean, stdev
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'citation-graph-matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'research/factory-e2e/question-status-20261115/questions-status.json'


def main():
    rows = json.loads(SOURCE.read_text())['rows']
    paired = [row for row in rows
              if row['variants'] and row['variants'][0].get('all_old_targets_true')]
    if len(paired) != 26 or sum(row['initial_target_count'] for row in paired) != 62:
        raise ValueError('The saved paired cohort differs from the reported 26 questions and 62 pairs')

    depths = [1, 2, 5, 10, 20, 50, 100]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2), sharey=True, layout='constrained')
    for ax, method, title in zip(axes, ['bm25', 'tfidf_lsa'], ['BM25', 'TF-IDF/LSA']):
        for rewritten, label, color, style in [
            (False, 'Исходный запрос', '#3569a8', '-'),
            (True, 'Описательная версия', '#b35a19', '--'),
        ]:
            ranks = [(row['variants'][0]['ranks'] if rewritten else row['ranks'])[method]
                     for row in paired]
            for row, target_ranks in zip(paired, ranks):
                if set(target_ranks) != set(row['initial_target_ids']):
                    raise ValueError(f'Targets changed for {row["id"]}')
            errors = [[100 * sum(rank > depth for rank in target_ranks.values()) / len(target_ranks)
                       for target_ranks in ranks] for depth in depths]
            averages = [mean(values) for values in errors]
            spread = [stdev(values) for values in errors]
            ax.plot(depths, averages, color=color, linestyle=style, marker='o',
                    markersize=3, label=label)
            ax.fill_between(depths, [max(0, avg - sd) for avg, sd in zip(averages, spread)],
                            [min(100, avg + sd) for avg, sd in zip(averages, spread)],
                            color=color, alpha=0.12, linewidth=0)
        ax.set_title(title)
        ax.set_xscale('log')
        ax.set_xticks([1, 5, 20, 100], ['1', '5', '20', '100'])
        ax.set_ylim(0, 100)
        ax.set_xlabel('Глубина выдачи k')
        ax.grid(alpha=0.2)
        ax.spines[['top', 'right']].set_visible(False)
    axes[0].set_ylabel('Доля пропущенных целей, %')
    axes[0].legend(fontsize=8, loc='upper right')
    output = ROOT / 'paper/figures'
    fig.savefig(output / 'search-target-coverage.png', dpi=220)
    fig.savefig(output / 'search-target-coverage.svg', metadata={'Date': None})
    plt.close(fig)


if __name__ == '__main__':
    main()
