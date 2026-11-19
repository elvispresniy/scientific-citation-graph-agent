import pytest

from graph_pilot import latex_to_text
from graph_pilot.latex_to_text import latex_to_index_text


def clean(body, preamble=''):
    return latex_to_index_text(preamble + '\\begin{document}\n' + body + '\n\\end{document}')


@pytest.mark.parametrize('formula', [
    r'$\frac{x}{y}+\sqrt{z}$', r'$$\frac{x}{y}+\sqrt{z}$$',
    r'\(\frac{x}{y}+\sqrt{z}\)', r'\[\frac{x}{y}+\sqrt{z}\]',
    r'\begin{equation}\frac{x}{y}+\sqrt{z}\label{eq:x}\end{equation}',
    r'\begin{equation*}\text{loss}=\frac{1}{n}\sum_i x_i\end{equation*}',
    r'\begin{align}a&=\frac{x}{y}\\b&=\sqrt{z}\end{align}',
    r'\begin{alignat*}{2}a&=b & c&=d\end{alignat*}',
    r'\begin{cases}x & x>0\\0 & x\leq0\end{cases}',
    r'\ensuremath{\frac{x}{y}+\sqrt{z}}',
    '$' + r'\frac{x}{y}+' * 100 + '$',
    '$$' + r'\sqrt{x}+\frac{a}{b}+' * 150 + '$$',
])
def test_math_preserved_exactly(formula):
    result = clean('Before ' + formula + ' after.')
    assert formula in result['text']
    assert result['text'].startswith('Before ') and result['text'].endswith(' after.')


@pytest.mark.parametrize('env', ['table', 'table*', 'longtable', 'tabularx', 'figure', 'figure*'])
def test_tabular_and_float_content_preserved_exactly(env):
    block = ('\\begin{' + env + '}[ht]\n' +
             r'\caption{Accuracy}\label{tab:results}' + '\n' +
             r'\begin{tabular}{cc}Method & Score \\ Baseline & 0.97 \\ \multicolumn{2}{c}{Result}' +
             '\n' + r'\end{tabular}\end{' + env + '}')
    result = clean('Introduction.\n' + block + '\nConclusion.')
    assert block in result['text']
    assert '0.97' in result['text'] and r'\multicolumn{2}{c}{Result}' in result['text']


def test_nested_table_environments_and_comment_closers():
    block = '\\begin{table}\n% \\end{table}\n\\begin{table}0.97\\end{table}\n\\end{table}'
    assert block in clean(block)['text']
    math = '$$x\n% $$ ignored\n+ y$$'
    assert math in clean(math)['text']


def test_custom_macros_definitions_arguments_and_dependencies():
    preamble = (r'\newcommand{\base}{ScientificMethod}' + '\n' +
                r'\newcommand{\method}[1][default]{\base-#1}' + '\n' +
                r'\newcommand{\unused}{UnusedValue}')
    result = clean(r'We use \method[fast]{} with \textbf{good results}.', preamble)
    assert r'We use \method[fast]{}' in result['text']
    assert r'\newcommand{\base}{ScientificMethod}' in result['text']
    assert r'\newcommand{\method}[1][default]{\base-#1}' in result['text']
    assert 'UnusedValue' not in result['text']
    assert 'good results' in result['text'] and r'\textbf' not in result['text']
    assert {d['name'] for d in result['macro_definitions']} == {'base', 'method'}


@pytest.mark.parametrize('definition', [
    r'\newcommand\method{ScientificMethod}', r'\renewcommand*{\method}[2]{#1-#2}',
    r'\providecommand{\method}{ScientificMethod}', r'\def\method#1{ScientificMethod-#1}',
    r'\gdef\method{ScientificMethod}', r'\DeclareMathOperator{\method}{ScientificMethod}',
    r'\let\method=\base',
])
def test_supported_declaration_forms_retained(definition):
    result = clean(r'We use \method{x}{y}.', definition)
    assert definition in result['text']
    assert r'\method{x}{y}' in result['text']


def test_definitions_in_body_and_unknown_macros_not_deleted():
    body = r'\newcommand{\method}{ScientificMethod} We use \method. Also \unknown{}[x]{a}{b}.'
    result = clean(body)
    assert r'\newcommand{\method}{ScientificMethod}' in result['text']
    assert r'\method.' in result['text']
    assert r'\unknown{}[x]{a}{b}' in result['text']


def test_used_style_macros_retained_without_whole_style():
    preamble = ('% [merge: begin sty local.sty]\n' +
                r'\newcommand{\method}{ScientificMethod}' + '\n' +
                r'\usepackage{SomeLargeStyle}' + '\n% [merge: end sty local.sty]\n')
    result = clean(r'We use \method.', preamble)
    assert r'\newcommand{\method}{ScientificMethod}' in result['text']
    assert 'SomeLargeStyle' not in result['text']


def test_cyclic_macro_dependencies_terminate_and_comments_are_ignored():
    preamble = (r'\newcommand{\a}{\b}' + '\n' + r'\newcommand{\b}{\a}' +
                '\n% \\newcommand{\\fake}{NoDefinition}\n')
    result = clean(r'Use \a.', preamble)
    assert {d['name'] for d in result['macro_definitions']} == {'a', 'b'}
    assert 'NoDefinition' not in result['text']


def test_formatting_citations_and_refs_still_work():
    result = clean(r'\section{Intro}\textbf{Result} \cite{p1} and \ref{eq:1}.' + '\n% remove me\n' +
                   r'\begin{thebibliography}{1}\bibitem{p1} An author, Title.\end{thebibliography}')
    assert '# Intro' in result['text'] and 'Result' in result['text']
    assert '[cite:p1]' in result['text'] and '[ref:eq:1]' in result['text']
    assert result['n_citations'] == 1 and result['n_sections'] == 1
    assert 'remove me' not in result['text'] and 'An author' not in result['text']


def test_escaped_dollars_placeholder_collision_and_incomplete_regions():
    body = r'Cost \$5. !LATEXPRESERVED0!. $\frac{1}{2}$'
    assert body in clean(body)['text']
    incomplete = r'Before \begin{equation}\frac{x}{y}'
    assert incomplete in clean(incomplete)['text']


def test_every_protected_block_is_present_in_final_text():
    body = r'\begin{table}\caption{Results} A & 0.97\end{table} $\frac{x}{y}$ and \custom{x}.'
    result = clean(body)
    assert result['preserved_blocks']
    assert all(block['latex'] in result['text'] for block in result['preserved_blocks'])


def test_comments_between_macro_definition_parts():
    definition = '\\newcommand% definition\n{\\method}% name\n[1]% argument\n{Scientific-#1}'
    result = clean(r'We use \method{x}.', definition)
    assert definition in result['text'] and r'\method{x}' in result['text']


def test_protected_content_inside_formatting_and_optional_labels():
    result = clean(r'\thanks{A result $\alpha>0$}' +
                   r'\vspace*{\fill}\item[$x>0$] Positive. ' +
                   r'\begin{theorem}[Case $y=1$] Statement.\end{theorem}')
    for literal in [r'$\alpha>0$', r'$x>0$', r'$y=1$', r'\fill']:
        assert literal in result['text']
    assert all(block['latex'] in result['text'] for block in result['preserved_blocks'])


def test_formula_adjacent_to_control_word_is_not_absorbed():
    result = clean(r'\noindent$\frac{x}{y}$ and \centering\(\sqrt{z}\).')
    assert r'$\frac{x}{y}$' in result['text'] and r'\(\sqrt{z}\)' in result['text']
    assert all(block['latex'] in result['text'] for block in result['preserved_blocks'])


def test_conservative_fallback_does_not_silently_lose_a_block(monkeypatch):
    body = r'Result: \begin{equation}\frac{x}{y}\end{equation}'
    monkeypatch.setattr(latex_to_text, '_process_generic_commands', lambda text, prefix: 'lost')
    result = clean(body)
    assert result['preservation_fallback']
    assert result['text'] == body
    assert all(block['latex'] in result['text'] for block in result['preserved_blocks'])
