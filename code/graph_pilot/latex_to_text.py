"""Convert merged LaTeX into a clean, index-friendly plain-text form.

Preserves:
    - Section structure as markdown-like headers
    - Citation markers  [cite:key1;key2]  with a lookup map to bibliography entries
    - Cross-refs        [ref:label]
    - URLs and captions
    - Math and figure/table blocks kept as original LaTeX
    - Custom macro calls and the used definitions (including dependencies)

Strips:
    - Preamble (before \\begin{document}) and merged .sty/.cls blocks
    - Formatting-only commands (\\textbf, \\emph, \\texttt, \\label, \\vskip, ...)
    - Comments outside preserved LaTeX blocks

Returns dict:
    {
      "text":        cleaned plaintext with markers,
      "citations":   {cite_key: {raw, doi, arxiv_id, url, short}},
      "sections":    [{"level": int, "title": str, "offset": int}],
    }
"""

import re
from typing import Optional


BEGIN_DOC_RE = re.compile(r'\\begin\{document\}')
END_DOC_RE = re.compile(r'\\end\{document\}')
BIB_ENV_RE = re.compile(r'\\begin\{thebibliography\}.*?\\end\{thebibliography\}', re.DOTALL)
MERGE_MARKER_RE = re.compile(r'^%\s*\[merge:.*$', re.MULTILINE)
STY_CLS_BLOCK_RE = re.compile(
    r'%\s*\[merge:\s*begin\s+(?:sty|cls)\s+[^\]]+\].*?%\s*\[merge:\s*end\s+(?:sty|cls)\s+[^\]]+\]',
    re.DOTALL,
)
BIB_BEGIN_BLOCK_RE = re.compile(r'%\s*\[merge:\s*begin\s+bib\s+([^\]]+)\](.*?)%\s*\[merge:\s*end\s+bib\s+\1\]', re.DOTALL)
COMMENT_LINE_RE = re.compile(r'(?<!\\)%.*')

# Commands to drop entirely (name + optional brace argument)
DROP_COMMANDS_NO_ARG = {
    'centering', 'clearpage', 'newpage', 'noindent', 'linebreak', 'pagebreak',
    'hline', 'toprule', 'midrule', 'bottomrule', 'smallskip', 'medskip', 'bigskip',
    'par', 'fi', 'else', 'sloppy', 'raggedright', 'raggedleft',
    'makeatletter', 'makeatother', 'maketitle', 'tableofcontents',
    'hfill', 'vfill', 'quad', 'qquad', 'relax', 'protect',
}
DROP_COMMANDS_ONE_ARG = {
    'label', 'vspace', 'hspace', 'vskip', 'hskip', 'setlength', 'addtolength',
    'documentclass', 'usepackage', 'bibliographystyle', 'bibliography', 'addbibresource',
    'input', 'include', 'includegraphics', 'graphicspath',
    'author', 'affiliation', 'thanks', 'and', 'date', 'setcounter', 'stepcounter',
    'DeclareMathOperator', 'RequirePackage', 'pdfoutput', 'special', 'hypersetup', 'urlstyle',
    'ifthenelse', 'IfFileExists', 'InputIfFileExists',
    'colorbox', 'cellcolor', 'rowcolor', 'columncolor',
    'ensuremath', 'protect',
}
# Commands taking TWO braced args, dropped WHOLE (including both args)
DROP_COMMANDS_TWO_ARGS = {
    'renewcommand', 'newcommand', 'providecommand', 'def', 'let',
    'newtheorem', 'theoremstyle', 'DeclareRobustCommand', 'newenvironment',
    'renewenvironment', 'captionof', 'fcolorbox', 'multicolumn', 'multirow',
    'DeclareCaptionType', 'DeclareCaptionFormat',
}
# Commands whose brace content should be KEPT (unwrap)
UNWRAP_COMMANDS = {
    'emph', 'textbf', 'textit', 'texttt', 'textsc', 'textrm', 'textsf', 'textup',
    'underline', 'text', 'mathrm', 'mathbf', 'mathit', 'mathsf',
    'title', 'abstract', 'paragraph',
}

# figure/table environments — strip whole content but keep captions
FLOAT_ENVS = ('figure', 'figure\\*', 'table', 'table\\*', 'wrapfigure', 'sidewaysfigure')


def _strip_comments(text: str) -> str:
    return '\n'.join(COMMENT_LINE_RE.sub('', line) for line in text.splitlines())


def _strip_preamble_and_sty(text: str) -> str:
    text = STY_CLS_BLOCK_RE.sub('', text)
    m = BEGIN_DOC_RE.search(text)
    if m:
        text = text[m.end():]
    m = END_DOC_RE.search(text)
    if m:
        text = text[:m.start()]
    return text


def _extract_and_remove_bibliography(text: str):
    """Return (text_without_bib, bib_raw, bib_format).

    bib_format: 'bib' | 'bbl' | 'thebibliography' | None.
    """
    # Prefer merge-marker block (our own annotation)
    m = BIB_BEGIN_BLOCK_RE.search(text)
    if m:
        raw = m.group(2)
        fmt = 'bib' if re.search(r'@\w+\s*\{', raw) else 'bbl'
        return text[:m.start()] + text[m.end():], raw, fmt
    m = BIB_ENV_RE.search(text)
    if m:
        return text[:m.start()] + text[m.end():], m.group(0), 'thebibliography'
    return text, '', None


# ---- Bibliography parsing --------------------------------------------------

BIBTEX_ENTRY_RE = re.compile(r'@\w+\s*\{\s*([^,\s}]+)\s*,(.*?)\n\}\s*(?=@|\Z)', re.DOTALL)
BIBTEX_FIELD_RE = re.compile(r'(\w+)\s*=\s*[\{"]([^{}"]*(?:\{[^{}]*\}[^{}"]*)*)[\}"]', re.DOTALL)
BIBITEM_RE = re.compile(r'\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}(.*?)(?=\\bibitem|\\end\{thebibliography\}|\Z)', re.DOTALL)

DOI_RE = re.compile(r'(?:doi[:=\s]*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s"\'}<>,]+)', re.IGNORECASE)
ARXIV_RE = re.compile(r'arxiv[:\s]*(\d{4}\.\d{4,5})', re.IGNORECASE)
URL_RE = re.compile(r'https?://[^\s"\'}<>,]+')


def _extract_url_doi_arxiv(chunk: str):
    doi = arxiv = url = None
    m = DOI_RE.search(chunk)
    if m:
        doi = m.group(1).rstrip('.,;:)')
    m = ARXIV_RE.search(chunk)
    if m:
        arxiv = m.group(1)
    m = URL_RE.search(chunk)
    if m:
        url = m.group(0).rstrip('.,;:)')
    return doi, arxiv, url


def _short_ref(fields: dict) -> str:
    """Build 'Author, Year, Title' short form from bib fields."""
    parts = []
    a = fields.get('author', '')
    if a:
        first = re.split(r'\s+and\s+', a, maxsplit=1)[0]
        parts.append(first.strip('{}. ').strip())
    y = fields.get('year', '')
    if y: parts.append(y.strip())
    t = fields.get('title', '')
    if t: parts.append(t.strip('{}').strip()[:120])
    return ' — '.join(parts) if parts else ''


def parse_bibliography(raw: str, fmt: Optional[str]) -> dict:
    if not raw or fmt is None:
        return {}
    out = {}
    if fmt == 'bib':
        for m in BIBTEX_ENTRY_RE.finditer(raw):
            key = m.group(1).strip()
            body = m.group(2)
            fields = {name.lower(): val.strip() for name, val in BIBTEX_FIELD_RE.findall(body)}
            doi, arxiv, url = _extract_url_doi_arxiv(body)
            doi = doi or fields.get('doi')
            url = url or fields.get('url')
            out[key] = {
                'raw': body.strip()[:600],
                'doi': doi,
                'arxiv_id': arxiv or fields.get('eprint'),
                'url': url,
                'short': _short_ref(fields),
            }
    else:  # 'bbl' or 'thebibliography'
        for m in BIBITEM_RE.finditer(raw):
            key = m.group(1).strip()
            body = m.group(2).strip()
            doi, arxiv, url = _extract_url_doi_arxiv(body)
            out[key] = {
                'raw': body[:600],
                'doi': doi,
                'arxiv_id': arxiv,
                'url': url,
                'short': re.sub(r'\s+', ' ', body[:200]).strip(),
            }
    return out


# ---- Body transformation ---------------------------------------------------

SECTION_RE = re.compile(r'\\(section|subsection|subsubsection|paragraph)\*?\s*\{([^}]*)\}')
CITE_RE = re.compile(r'\\(cite[tp]?|citep|citet|citeauthor|citeyear|autocite|parencite|textcite|footcite)\s*(?:\[[^\]]*\])?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}')
REF_RE = re.compile(r'\\(?:ref|eqref|autoref|Cref|cref)\s*\{([^}]+)\}')
URL_CMD_RE = re.compile(r'\\url\s*\{([^}]+)\}')
HREF_CMD_RE = re.compile(r'\\href\s*\{([^}]+)\}\s*\{([^}]*)\}')
CAPTION_RE = re.compile(r'\\caption(?:\[[^\]]*\])?\s*\{')
FOOTNOTE_RE = re.compile(r'\\footnote\s*\{')
ENV_BEGIN_RE = re.compile(r'\\begin\{([a-zA-Z*]+)\}(\s*\[[^\]]*\])?')

# Generic \cmd{arg} for drop/unwrap. Also match \@internal, \name'
GENERIC_CMD_RE = re.compile(r'\\(@?[a-zA-Z]+@?)\*?\s*(?:\[[^\]]*\])?\s*(\{)?')

# Math symbol commands (single letters, greek letters, common ops) — keep as-is if no arg
MATH_SYMBOLS_NO_ARG = {
    'alpha','beta','gamma','delta','epsilon','varepsilon','zeta','eta','theta','vartheta',
    'iota','kappa','lambda','mu','nu','xi','pi','varpi','rho','varrho','sigma','varsigma',
    'tau','upsilon','phi','varphi','chi','psi','omega',
    'Alpha','Beta','Gamma','Delta','Epsilon','Zeta','Eta','Theta','Iota','Kappa','Lambda',
    'Mu','Nu','Xi','Pi','Rho','Sigma','Tau','Upsilon','Phi','Chi','Psi','Omega',
    'infty','partial','nabla','sum','prod','int','oint','forall','exists','in','notin',
    'subset','supset','subseteq','supseteq','cup','cap','emptyset','neq','leq','geq',
    'll','gg','sim','approx','equiv','propto','rightarrow','leftarrow','Rightarrow',
    'Leftarrow','Leftrightarrow','uparrow','downarrow','pm','mp','times','cdot','circ',
    'star','ast','bullet','oplus','otimes','wedge','vee','langle','rangle','lceil','rceil',
    'lfloor','rfloor','hat','bar','tilde','dot','ddot','vec','check','breve','acute','grave',
    'ldots','cdots','vdots','ddots','prime','ell','hbar','Re','Im',
}


def _extract_braced(text: str, start: int) -> tuple:
    """Given text with text[start]=='{', find matching closing brace.
    Returns (content, end_pos_after_closing_brace)."""
    assert text[start] == '{'
    depth = 1
    i = start + 1
    while i < len(text) and depth > 0:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        i += 1
    return text[start + 1:i - 1], i


def _strip_float_envs(text: str) -> str:
    """Remove figure/table envs, keep only \\caption{...} contents."""
    for env in FLOAT_ENVS:
        pattern = re.compile(rf'\\begin\{{{env}\}}(.*?)\\end\{{{env}\}}', re.DOTALL)
        def repl(m):
            body = m.group(1)
            captions = []
            j = 0
            while True:
                cm = CAPTION_RE.search(body, j)
                if not cm: break
                content, end = _extract_braced(body, cm.end() - 1)
                captions.append(content.strip())
                j = end
            if captions:
                return '\n\n[Figure] ' + ' | '.join(captions) + '\n\n'
            return '\n\n'
        text = pattern.sub(repl, text)
    return text


def _replace_citations(text: str, cite_positions: list) -> str:
    def repl(m):
        keys = [k.strip() for k in m.group(2).split(',') if k.strip()]
        cite_positions.append((m.start(), keys))
        return '[cite:' + ';'.join(keys) + ']'
    return CITE_RE.sub(repl, text)


def _replace_refs(text: str) -> str:
    return REF_RE.sub(lambda m: f'[ref:{m.group(1).strip()}]', text)


def _replace_urls(text: str) -> str:
    text = URL_CMD_RE.sub(lambda m: m.group(1), text)
    text = HREF_CMD_RE.sub(lambda m: f'{m.group(2)} ({m.group(1)})' if m.group(2) else m.group(1), text)
    return text


def _replace_sections(text: str, sections: list) -> str:
    def repl(m):
        kind = m.group(1)
        title = m.group(2).strip()
        level = {'section': 1, 'subsection': 2, 'subsubsection': 3, 'paragraph': 4}[kind]
        sections.append({'level': level, 'title': title, 'offset': m.start()})
        return '\n\n' + '#' * level + ' ' + title + '\n\n'
    return SECTION_RE.sub(repl, text)


MATH_INLINE_RE = re.compile(r'\$[^$]{0,500}\$')
MATH_DISPLAY_RE = re.compile(r'\$\$[^$]{0,2000}\$\$')

def _process_generic_commands(text: str, protected_prefix=None) -> str:
    """Walk through and rewrite \\cmd{...} for drop/unwrap sets. Skip math regions."""
    out = []
    i = 0
    while i < len(text):
        mm = MATH_DISPLAY_RE.match(text, i) or MATH_INLINE_RE.match(text, i)
        if mm:
            out.append(mm.group(0))
            i = mm.end()
            continue
        m = GENERIC_CMD_RE.match(text, i)
        if not m:
            out.append(text[i])
            i += 1
            continue
        cmd = m.group(1)
        if m.group(2):  # has braced arg
            content1, end1 = _extract_braced(text, m.end() - 1)
            if cmd in DROP_COMMANDS_TWO_ARGS:
                # Consume an optional second brace (skipping whitespace/[opts] between)
                j = end1
                # skip whitespace and one [opts]
                while j < len(text) and text[j] in ' \t\n':
                    j += 1
                if j < len(text) and text[j] == '[':
                    # skip optional bracket
                    depth = 1; j += 1
                    while j < len(text) and depth > 0:
                        if text[j] == '[': depth += 1
                        elif text[j] == ']': depth -= 1
                        j += 1
                while j < len(text) and text[j] in ' \t\n':
                    j += 1
                if j < len(text) and text[j] == '{':
                    _, end2 = _extract_braced(text, j)
                    i = end2
                else:
                    i = end1
                if protected_prefix and protected_prefix in text[m.start():i]:
                    out.append(text[m.start():i])
            elif cmd in DROP_COMMANDS_ONE_ARG:
                if protected_prefix and protected_prefix in content1:
                    out.append(_process_generic_commands(content1, protected_prefix))
                i = end1
            else:
                out.append(_process_generic_commands(content1, protected_prefix))
                i = end1
        else:
            if cmd in MATH_SYMBOLS_NO_ARG:
                out.append(m.group(0))
            i = m.end()
    return ''.join(out)


def _cleanup_whitespace(text: str) -> str:
    # Drop lines that are ONLY a `{`, `}` or `{}` (orphan TeX grouping)
    text = re.sub(r'^\s*[{}]+\s*$', '', text, flags=re.MULTILINE)
    # Drop inline standalone `{}` / `}{` remnants
    text = re.sub(r'\{\s*\}', '', text)
    # Strip repeated `~` (non-breaking spaces from LaTeX)
    text = text.replace('~', ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _strip_env_wrappers(text: str) -> str:
    """Remove \\begin{env}[opts]...\\end{env} tags but keep inner content for
    text-bearing environments (itemize/enumerate/abstract/quote/...).
    """
    KEEP_ENVS_UNWRAP = {'abstract', 'quote', 'quotation', 'center', 'flushleft', 'flushright',
                        'itemize', 'enumerate', 'description', 'proof', 'theorem', 'lemma',
                        'corollary', 'definition', 'proposition', 'remark'}
    DROP_ENVS_KEEP_CONTENT = {'equation', 'equation*', 'align', 'align*', 'gather', 'gather*',
                              'multline', 'multline*', 'eqnarray', 'eqnarray*', 'displaymath'}
    # Replace \item with '- '
    text = re.sub(r'\\item\s*(?:\[([^\]]*)\])?',
                  lambda m: '\n- ' + (m.group(1) + ' ' if m.group(1) else ''), text)
    # Wrap-remove for known envs (leave content)
    for env in KEEP_ENVS_UNWRAP | DROP_ENVS_KEEP_CONTENT:
        text = re.sub(rf'\\begin\{{{re.escape(env)}\}}\s*(?:\[([^\]]*)\])?',
                      lambda m: '\n' + (m.group(1) + '\n' if m.group(1) else ''), text)
        text = re.sub(rf'\\end\{{{re.escape(env)}\}}', '\n', text)
    # For any remaining unknown envs, drop wrappers too (keep content)
    text = re.sub(r'\\begin\{[a-zA-Z*]+\}\s*(?:\[([^\]]*)\])?',
                  lambda m: '\n' + (m.group(1) + '\n' if m.group(1) else ''), text)
    text = re.sub(r'\\end\{[a-zA-Z*]+\}', '\n', text)
    return text


PRESERVED_ENVS = {
    'math', 'displaymath', 'equation', 'align', 'alignat', 'flalign', 'gather',
    'multline', 'eqnarray', 'split', 'aligned', 'alignedat', 'gathered',
    'subequations', 'matrix', 'pmatrix', 'bmatrix', 'Bmatrix', 'vmatrix', 'Vmatrix', 'cases',
    'table', 'tabular', 'tabularx', 'tabulary', 'longtable', 'supertabular',
    'xltabular', 'sidewaystable', 'threeparttable',
    'figure', 'wrapfigure', 'sidewaysfigure', 'tikzpicture',
}
MACRO_DEF_RE = re.compile(
    r'\\(?P<kind>newcommand|renewcommand|providecommand|DeclareRobustCommand|DeclareMathOperator|'
    r'def|gdef|edef|xdef|let)\*?(?:\s|%[^\n]*(?:\n|$))*'
    r'(?:\{\s*\\(?P<braced>[A-Za-z@]+)\s*\}|\\(?P<plain>[A-Za-z@]+))')
CONTROL_WORD_RE = re.compile(r'\\([A-Za-z@]+)')


def _escaped(text, position):
    previous = position - 1
    while previous >= 0 and text[previous] == '\\':
        previous -= 1
    return (position - previous - 1) % 2 == 1


def _in_comment(text, position):
    start = text.rfind('\n', 0, position) + 1
    return any(not _escaped(text, p) for p in range(start, position) if text[p] == '%')


def _balanced_end(text, start):
    opening, closing = text[start], {'{': '}', '[': ']'}[text[start]]
    depth, position = 1, start + 1
    while position < len(text):
        char = text[position]
        if char == '\\':
            position += 2
            continue
        if char == '%':
            newline = text.find('\n', position)
            position = len(text) if newline < 0 else newline + 1
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return None


def _skip_layout(text, position):
    while position < len(text):
        if text[position].isspace():
            position += 1
        elif text[position] == '%':
            newline = text.find('\n', position)
            position = len(text) if newline < 0 else newline + 1
        else:
            break
    return position


def _macro_definitions(text):
    """Retain declarations as data; never execute TeX or guess macro expansions."""
    definitions, consumed = [], 0
    for match in MACRO_DEF_RE.finditer(text):
        if match.start() < consumed or _escaped(text, match.start()):
            continue
        if _in_comment(text, match.start()):
            continue
        position = match.end()
        if match['kind'] == 'let':
            target = re.match(r'\s*=?\s*(?:\\[A-Za-z@]+|\\.|[^\s])', text[position:])
            end = position + target.end() if target else None
        else:
            if match['kind'] in ('def', 'gdef', 'edef', 'xdef'):
                position = text.find('{', position)
                if position < 0:
                    continue
            else:
                while True:
                    position = _skip_layout(text, position)
                    if position >= len(text) or text[position] != '[':
                        break
                    position = _balanced_end(text, position)
                    if position is None:
                        break
            end = _balanced_end(text, position) if position is not None and position < len(text) and text[position] == '{' else None
        if end is not None:
            definitions.append({'name': match['braced'] or match['plain'], 'start': match.start(),
                                'end': end, 'latex': text[match.start():end]})
            consumed = end
    return definitions


def _protect_content(text, macro_names):
    """Shield scientific LaTeX from all later formatting/whitespace rewrites."""
    prefix = '!LATEXPRESERVED'
    while prefix in text:
        prefix += 'X'
    blocks, output, cursor = [], [], 0
    definitions = {d['start']: d for d in _macro_definitions(text)}
    handled = (DROP_COMMANDS_NO_ARG | DROP_COMMANDS_ONE_ARG | DROP_COMMANDS_TWO_ARGS |
               UNWRAP_COMMANDS | {'begin', 'end', 'section', 'subsection', 'subsubsection',
               'cite', 'citet', 'citep', 'citeauthor', 'citeyear', 'autocite', 'parencite',
               'textcite', 'footcite', 'ref', 'eqref', 'autoref', 'Cref', 'cref', 'url', 'href'})
    tokens = re.compile(r'\\begin\s*\{([^}]+)\}|\$\$?|\\[\[(]|\\[A-Za-z@]+\*?|%')
    scan = 0
    while True:
        match = tokens.search(text, scan)
        if match is None:
            break
        start, end, token = match.start(), None, match.group(0)
        scan = match.end()
        if _escaped(text, start):
            continue
        if token == '%':
            newline = text.find('\n', start)
            scan = len(text) if newline < 0 else newline + 1
            continue
        kind = 'macro'
        if match.group(1) is not None and match.group(1).rstrip('*') in PRESERVED_ENVS:
            env = match.group(1)
            boundary = re.compile(r'\\(begin|end)\s*\{' + re.escape(env) + r'\}')
            depth = 1
            for close in boundary.finditer(text, match.end()):
                if _escaped(text, close.start()) or _in_comment(text, close.start()):
                    continue
                depth += 1 if close.group(1) == 'begin' else -1
                if depth == 0:
                    end = close.end()
                    break
            kind = 'environment'
            end = len(text) if end is None else end
        elif token in ('$', '$$', '\\(', '\\['):
            delimiter = {'\\(': '\\)', '\\[': '\\]'}.get(token, token)
            position = match.end()
            while True:
                close = text.find(delimiter, position)
                if close < 0:
                    end = len(text)  # Preserve an incomplete region instead of deleting it.
                    break
                if not _escaped(text, close) and not _in_comment(text, close):
                    end = close + len(delimiter)
                    break
                position = close + len(delimiter)
            kind = 'math'
        elif start in definitions:
            end = definitions[start]['end']
            kind = 'macro_definition'
        elif token.startswith('\\') and match.group(1) is None:
            name = token[1:].rstrip('*')
            if name in macro_names or name not in handled or name == 'ensuremath':
                end = match.end()
                # Keep all following optional/braced arguments, including empty ones.
                position = end
                while True:
                    while position < len(text) and text[position].isspace():
                        position += 1
                    if position >= len(text) or text[position] not in '[{':
                        break
                    closed = _balanced_end(text, position)
                    end = len(text) if closed is None else closed
                    position = end
                    if closed is None:
                        break
        if end is not None:
            output.extend((text[cursor:start], f'{prefix}{len(blocks)}!'))
            blocks.append({'kind': kind, 'latex': text[start:end]})
            cursor, scan = end, end
    output.append(text[cursor:])
    return ''.join(output), blocks, prefix


def latex_to_index_text(merged: str, files_dict: Optional[dict] = None) -> dict:
    definitions = _macro_definitions(merged)
    macro_names = {d['name'] for d in definitions}
    text = merged
    text = _strip_preamble_and_sty(text)
    text, bib_raw, bib_fmt = _extract_and_remove_bibliography(text)
    citations = parse_bibliography(bib_raw, bib_fmt)
    used = set(CONTROL_WORD_RE.findall(_strip_comments(text))) & macro_names
    while True:
        dependencies = {name for d in definitions if d['name'] in used
                        for name in CONTROL_WORD_RE.findall(d['latex'])} & macro_names
        if dependencies <= used:
            break
        used |= dependencies
    begin = BEGIN_DOC_RE.search(merged)
    style_ranges = [m.span() for m in STY_CLS_BLOCK_RE.finditer(merged)]
    retained = [d for d in definitions if d['name'] in used and
                ((begin is not None and d['start'] < begin.start()) or
                 any(start <= d['start'] < end for start, end in style_ranges))]
    body_source = text
    text, preserved_blocks, prefix = _protect_content(text, macro_names)
    text = MERGE_MARKER_RE.sub('', text)
    text = _strip_comments(text)
    text = _replace_urls(text)
    sections = []
    text = _replace_sections(text, sections)
    cite_positions = []
    text = _replace_citations(text, cite_positions)
    text = _replace_refs(text)
    # Envs must be stripped BEFORE generic-command processing so \begin{...}/\end{...}
    # aren't mis-parsed as generic \cmd{arg} calls.
    text = _strip_env_wrappers(text)
    text = _process_generic_commands(text, prefix)
    text = _cleanup_whitespace(text)
    text = re.sub(re.escape(prefix) + r'(\d+)!',
                  lambda m: preserved_blocks[int(m.group(1))]['latex'], text)
    preservation_fallback = any(block['latex'] not in text for block in preserved_blocks)
    if preservation_fallback:
        # Fail conservatively: retain the original body, rather than silently
        # losing scientific LaTeX inside an unexpected formatting construct.
        text = body_source.strip()
    if retained:
        text = '[LaTeX macro definitions]\n' + '\n'.join(d['latex'] for d in retained) + '\n\n' + text
    return {
        'text': text,
        'citations': citations,
        'sections': sections,
        'cite_positions': cite_positions,
        'n_citations': len(citations),
        'n_sections': len(sections),
        'preserved_blocks': preserved_blocks,
        'macro_definitions': [{'name': d['name'], 'latex': d['latex']} for d in retained],
        'macro_policy': 'Definitions and calls retained as LaTeX; no TeX execution or expansion',
        'offset_scope': 'Intermediate transformations; not final text coordinates',
        'preservation_fallback': preservation_fallback,
    }
