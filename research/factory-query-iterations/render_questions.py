"""Render saved candidate questions and paper metadata; no inference or paper reading."""
import argparse
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def render(directory):
    manifest = read(directory / 'manifest.json')
    index = ROOT / 'research/factory-step2-pilot/index-001'
    rows = {r['paper_id']: r for r in read(index / 'manifest.json')['rows']}
    titles = {}

    def title(pid):
        if pid not in titles:
            paper = json.loads(gzip.decompress((index / rows[pid]['artifact']).read_bytes()))['paper']
            titles[pid] = ' '.join(paper['title'].split())
        return titles[pid]

    lines = ['# Пробные вопросы по группам шага 3', '',
             'Это исходные формулировки модели и кандидатные ответы по карточкам. '
             'Их научная точность, полнота и поисковая сложность независимо не проверены. '
             'Отсутствие статьи в ответе не означает установленную нерелевантность.', '',
             f"Модель: `{manifest['llm_config']['model']}`. "
             'Входы: исходные описания аспектов и полные карточки core-участников. '
             'Прогон шага 3 после правки его промпта не повторялся.', '']
    for group in manifest['groups']:
        path = directory / group['name']
        status = read(path / 'status.json') if (path / 'status.json').exists() else {'status': 'queued'}
        lines += [f"## {group['name']}", '',
                  f"Входных карточек: {group['input_cards']}. Статус: `{status['status']}`.", '']
        result = path / 'questions.json'
        if not result.exists():
            lines += ['Валидного результата пока нет.', '']
            continue
        questions = read(result)['questions']
        if not questions:
            lines += ['Модель вернула пустой список вопросов.', '']
        for number, question in enumerate(questions, 1):
            answers = question['answer_paper_ids']
            lines += [f'### Вопрос {number}', '', question['question'], '',
                      f'Кандидатных ответов: {len(answers)}.', '']
            for pid in answers:
                arxiv = pid.removeprefix('arxiv:')
                lines.append(f'- [{pid} — {title(pid)}](https://arxiv.org/abs/{arxiv})')
            excluded = sorted(set(group['paper_ids']) - set(answers))
            lines += ['', 'Не выбраны из входного пула: ' +
                      (', '.join(f'`{pid}`' for pid in excluded) if excluded else 'нет.') + '', '']
        lines += [f'Исходный результат: [questions.json]({group["name"]}/questions.json).', '']
    destination = directory / 'questions.md'
    destination.write_text('\n'.join(lines) + '\n')
    print(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    render(parser.parse_args().directory)
