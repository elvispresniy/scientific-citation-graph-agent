"""Two-page course report. Requires reportlab; figures are built separately."""
from pathlib import Path
import json
from html import escape

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / 'output/pdf/gumbel-topk-report'
W, H = A4
MARGIN = 51
WIDTH = W - 2 * MARGIN
INK = colors.HexColor('#17212B')
MUTED = colors.HexColor('#56616C')
BLUE = colors.HexColor('#294E6B')
ALGOWIKI = ('https://algowiki-project.org/ru/Участник:Gulyakov_nikita/'
            'Параллельная_взвешенная_выборка_без_возвращения_методом_Gumbel-Top-k')


def main():
    fontroot = Path('/System/Library/Fonts/Supplemental')
    pdfmetrics.registerFont(TTFont('Body', str(fontroot / 'Times New Roman.ttf')))
    pdfmetrics.registerFont(TTFont('Body-Bold', str(fontroot / 'Times New Roman Bold.ttf')))
    pdfmetrics.registerFont(TTFont('Body-Italic', str(fontroot / 'Times New Roman Italic.ttf')))
    pdfmetrics.registerFontFamily('Body', normal='Body', bold='Body-Bold', italic='Body-Italic')
    style = ParagraphStyle('body', fontName='Body', fontSize=10.6, leading=13.1,
                           textColor=INK, spaceAfter=5.5)
    small = ParagraphStyle('small', parent=style, fontSize=8.9, leading=11.1,
                           textColor=MUTED, spaceAfter=6)
    heading = ParagraphStyle('heading', parent=style, fontName='Body-Bold',
                             fontSize=12, leading=15, textColor=BLUE, spaceAfter=5)
    title = ParagraphStyle('title', parent=style, fontName='Body-Bold',
                           fontSize=17.5, leading=21, spaceAfter=7)
    cell = ParagraphStyle('cell', parent=style, fontSize=9.7, leading=11.8, spaceAfter=0)
    data = json.loads((OUT / 'plot-data.json').read_text())
    rows = {(r['n'], r['k'], r['weights'], r['p']): r for r in data['rows']}
    c = canvas.Canvas(str(OUT / 'gumbel-topk-gulyakov-417.pdf'), pagesize=A4, pageCompression=1)
    c.setTitle('Параллельная реализация Gumbel-Top-k')
    c.setAuthor('Гуляков Никита Сергеевич')
    y = H - MARGIN

    def paragraph(text, sty=style, gap=None):
        nonlocal y
        obj = Paragraph(text, sty)
        _, h = obj.wrap(WIDTH, H)
        obj.drawOn(c, MARGIN, y - h)
        y -= h + (sty.spaceAfter if gap is None else gap)

    def table(values, widths, header=False):
        nonlocal y
        cells = [[Paragraph(str(v), cell) for v in row] for row in values]
        t = Table(cells, colWidths=widths, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('LINEBELOW', (0, 0), (-1, -1), .35, colors.HexColor('#DDE3E8'))]
        if header:
            commands += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EEF3F7')),
                         ('LINEBELOW', (0, 0), (-1, 0), .7, BLUE)]
        else:
            commands += [('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F3F5F7'))]
        t.setStyle(TableStyle(commands))
        _, h = t.wrap(WIDTH, H)
        t.drawOn(c, MARGIN, y - h)
        y -= h + 9

    def figure(name, caption):
        nonlocal y
        image = ImageReader(str(OUT / name))
        iw, ih = image.getSize()
        h = WIDTH * ih / iw
        c.drawImage(image, MARGIN, y - h, width=WIDTH, height=h, mask='auto')
        y -= h + 4
        paragraph(caption, small)

    def footer(page):
        c.setStrokeColor(colors.HexColor('#DDE3E8'))
        c.line(MARGIN, 34, W - MARGIN, 34)
        c.setFillColor(MUTED)
        c.setFont('Body', 8.5)
        c.drawString(MARGIN, 21, 'Гуляков Н. С. | Группа 417')
        c.drawRightString(W - MARGIN, 21, str(page))

    paragraph('Параллельная реализация Gumbel-Top-k', title)
    paragraph('Практическое задание по курсу «Суперкомпьютеры и параллельная обработка данных»', small, 5)
    paragraph('Гуляков Никита Сергеевич, группа 417 · 15 ноября 2026 года', style, 10)
    paragraph('1. Задача и реализация', heading)
    paragraph('Исследуется взвешенная выборка k различных элементов из n кандидатов. '
              'Задача связана с отбором статей-затравок в проекте по поиску научной литературы. '
              'Для параллельной реализации выбран Gumbel-Top-k: оценки кандидатов вычисляются независимо.')
    paragraph('Каждому элементу сопоставляется оценка z<sub>i</sub> = ln w<sub>i</sub> − ln(−ln u<sub>i</sub>). '
              'В реализации u<sub>i</sub> получается из ID и seed с помощью SplitMix64. '
              'Каждый поток обрабатывает свой блок входа и хранит локальные лучшие k элементов в куче. '
              'Затем один поток объединяет локальные результаты и сортирует итоговую выборку.')
    paragraph('2. Условия эксперимента', heading)
    table([
        ['<b>Вычислитель</b>', '«Ломоносов-2», один узел на задание'],
        ['<b>Процессор и память</b>', 'Intel Xeon E5-2697 v3, 14 физических ядер, 64 ГБ ОЗУ'],
        ['<b>Программная среда</b>', 'CentOS 7.6; GCC 12.3.0, C++17, OpenMP (libgomp)'],
        ['<b>Параметры сборки</b>', '-O3 -std=c++17 -fopenmp'],
        ['<b>Привязка потоков</b>', 'OMP_PLACES=cores, OMP_PROC_BIND=close, OMP_DYNAMIC=FALSE']
    ], [130, WIDTH - 130])
    paragraph('Входы синтетические: ID от 0 до n−1; n = 10<super>5</super>, '
              '10<super>6</super>, 10<super>7</super>, 10<super>8</super>; '
              'k = 20, 1000, 10000.<br/>Веса равны 1 либо 10<super>(ID mod 7)−3</super>; '
              'seed = 42. Число потоков P: 1, 2, 4, 8 и 14.')
    paragraph('Для каждой конфигурации выполнены один прогрев и семь замеров. T(P) - медиана времени ядра; '
              'генерация входа и ввод-вывод исключены. Измеряются вычисление оценок, локальный отбор, '
              'объединение и сортировка. База T(1) получена тем же бинарным файлом в один поток. '
              'Выбранные ID и оценки совпали при всех P.')
    figure('strong-scaling.png', 'Рис. 1. Ускорение S(P) = T(1)/T(P) при фиксированных n, k и весах. '
           'Пунктиром показана линия S = P.')
    assert y > 40, 'Page 1 overflow: {}'.format(y)
    print('Page 1 final y:', round(y, 1))
    footer(1); c.showPage(); y = H - MARGIN
    paragraph('3. Результаты', heading)
    figure('merge-share.png', 'Рис. 2. Медиана доли фазы объединения и сортировки в полном времени ядра '
           'при P = 14; доля вычислена отдельно для каждого из семи замеров.')
    paragraph('При n = 10<super>8</super> ускорение на 14 потоках составило 12,0-14,1. '
              'В таблице приведены времена и ускорения для этого размера входа.')
    values = [['<b>Веса</b>', '<b>k</b>', '<b>T(1), с</b>', '<b>T(14), с</b>', '<b>S(14)</b>']]
    def fmt(value, digits):
        return ('{:.' + str(digits) + 'f}').format(value).replace('.', ',')
    for w in ['uniform', 'skewed']:
        for k in [20, 1000, 10000]:
            a, b = rows[100000000, k, w, 1], rows[100000000, k, w, 14]
            values.append(['Одинаковые' if w == 'uniform' else 'Различающиеся',
                           '{:,}'.format(k).replace(',', ' '), fmt(a['median_s'], 3),
                           fmt(b['median_s'], 3), fmt(b['speedup'], 2)])
    table(values, [135, 65, 97, 97, WIDTH - 394], header=True)
    paragraph('На меньшем входе n = 10<super>5</super> при k = 10<super>4</super> ускорение '
              'составило лишь 2,39-2,54. При P = 14 объединение и сортировка занимают около 63% '
              'времени ядра (рис. 2). Эта фаза выполняется последовательно, а число поступающих '
              'в неё элементов растёт с количеством локальных куч. Поэтому увеличение P '
              'не устраняет это ограничение.')
    paragraph('Материалы для воспроизведения', heading)
    paragraph('К отчёту приложены исходники C++ и Makefile, скрипты запуска SLURM, '
              '840 исходных замеров в measurements.csv и таблица plot-data.json. '
              'Все точки графиков получены из основной серии заданий 1871954-1871959.')
    paragraph('Описание алгоритма: <link href="' + escape(ALGOWIKI, quote=True) +
              '" color="#294E6B"><u>страница автора в AlgoWiki</u></link>.', small)
    assert y > 45, 'Page 2 overflow: {}'.format(y)
    print('Page 2 final y:', round(y, 1))
    footer(2); c.save()
    print('Created', OUT / 'gumbel-topk-gulyakov-417.pdf')
    md = '''# Параллельная реализация Gumbel-Top-k

Практическое задание по курсу «Суперкомпьютеры и параллельная обработка данных».

Гуляков Никита Сергеевич, группа 417. 15 ноября 2026 года.

## 1. Задача и реализация

Исследуется взвешенная выборка k различных элементов из n кандидатов. Задача связана с отбором статей-затравок в проекте по поиску научной литературы. Для параллельной реализации выбран Gumbel-Top-k: оценки кандидатов вычисляются независимо.

Каждому элементу сопоставляется оценка zᵢ = ln wᵢ − ln(−ln uᵢ). В реализации uᵢ получается из ID и seed с помощью SplitMix64. Каждый поток обрабатывает свой блок входа и хранит локальные лучшие k элементов в куче. Затем один поток объединяет локальные результаты и сортирует итоговую выборку.

## 2. Условия эксперимента

| Параметр | Значение |
| --- | --- |
| Вычислитель | «Ломоносов-2», один узел на задание |
| Процессор и память | Intel Xeon E5-2697 v3, 14 физических ядер, 64 ГБ ОЗУ |
| Программная среда | CentOS 7.6; GCC 12.3.0, C++17, OpenMP (libgomp) |
| Параметры сборки | `-O3 -std=c++17 -fopenmp` |
| Привязка потоков | `OMP_PLACES=cores`, `OMP_PROC_BIND=close`, `OMP_DYNAMIC=FALSE` |

Входы синтетические: ID от 0 до n−1; n = 10⁵, 10⁶, 10⁷, 10⁸; k = 20, 1000, 10000. Веса равны 1 либо 10^((ID mod 7)−3); seed = 42. Число потоков P: 1, 2, 4, 8 и 14.

Для каждой конфигурации выполнены один прогрев и семь замеров. T(P) - медиана времени ядра; генерация входа и ввод-вывод исключены. Измеряются вычисление оценок, локальный отбор, объединение и сортировка. База T(1) получена тем же бинарным файлом в один поток. Выбранные ID и оценки совпали при всех P.

![Сильная масштабируемость](strong-scaling.png)

Рис. 1. Ускорение S(P) = T(1)/T(P) при фиксированных n, k и весах. Пунктиром показана линия S = P.

## 3. Результаты

![Доля объединения и сортировки](merge-share.png)

Рис. 2. Медиана доли фазы объединения и сортировки в полном времени ядра при P = 14; доля вычислена отдельно для каждого из семи замеров.

При n = 10⁸ ускорение на 14 потоках составило 12,0-14,1. В таблице приведены времена и ускорения для этого размера входа.

| Веса | k | T(1), с | T(14), с | S(14) |
| --- | ---: | ---: | ---: | ---: |
'''
    for row in values[1:]:
        md += '| ' + ' | '.join(row) + ' |\n'
    md += '''
На меньшем входе n = 10⁵ при k = 10⁴ ускорение составило лишь 2,39-2,54. При P = 14 объединение и сортировка занимают около 63% времени ядра (рис. 2). Эта фаза выполняется последовательно, а число поступающих в неё элементов растёт с количеством локальных куч. Поэтому увеличение P не устраняет это ограничение.

## Материалы для воспроизведения

К отчёту приложены исходники C++ и Makefile, скрипты запуска SLURM, 840 исходных замеров в measurements.csv и таблица plot-data.json. Все точки графиков получены из основной серии заданий 1871954-1871959.

Описание алгоритма: [страница автора в AlgoWiki](''' + ALGOWIKI + ''').
'''
    (OUT / 'report.md').write_text(md)


if __name__ == '__main__':
    main()
