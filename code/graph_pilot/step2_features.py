"""Offline, full-frontier T/G/M ranking. No model client or inference API."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from statistics import median
import unicodedata

from .probe_modules import fulltext_preserve
from .store import canonical_id


VERSION = 'step2-tgm-v1'
ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / 'research' / 'terminology-pilot'


class Step2Error(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(encoded(value) + b'\n')
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


class LocalGraph:
    """Internal read-only snapshot reader; public graph API stays unchanged."""

    def __init__(self, database):
        self.path = Path(database).resolve()
        self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA query_only=ON')

    def close(self):
        self.db.close()

    def identity(self):
        h = hashlib.sha256()
        for query in ('SELECT paper_id FROM nodes ORDER BY paper_id',
                      'SELECT src,dst,evidence FROM edges ORDER BY src,dst'):
            for row in self.db.execute(query):
                h.update(encoded(list(row)) + b'\n')
        row = self.db.execute("SELECT value FROM settings WHERE key='snapshot_id'").fetchone()
        snapshot = json.loads(row[0]) if row else None
        return {'snapshot_id': snapshot, 'graph_sha256': h.hexdigest()}

    def ids(self):
        return [r[0] for r in self.db.execute('SELECT paper_id FROM nodes ORDER BY paper_id')]

    def degrees(self):
        return dict(self.db.execute('SELECT dst,count(DISTINCT src) FROM edges GROUP BY dst'))

    def connections(self, pid):
        return [dict(r) for r in self.db.execute(
            'SELECT src,dst,evidence FROM edges WHERE src=? OR dst=? ORDER BY src,dst', (pid, pid))]

    def paper(self, pid):
        """Read existing extracted sources, never repair/write the source database."""
        row = self.db.execute('SELECT metadata FROM papers WHERE id=?', (pid,)).fetchone()
        if row is None:
            raise Step2Error('Unknown paper ID')
        meta = json.loads(row[0])
        sources = self.db.execute(
            "SELECT * FROM sources WHERE paper_id=? AND status NOT IN ('failed','missing','absent') "
            'ORDER BY kind,path', (pid,)).fetchall()
        for source in sources:
            locator = json.loads(source['locator'])
            kind = source['kind']
            path = Path(source['path'])
            if not path.is_file():
                continue
            if kind == 'unarxive_doc':
                from .unarxive import render_text
                with gzip.open(path, 'rt') as stream:
                    doc = json.load(stream)
                if not any(isinstance(p.get('text'), str) and p['text'].strip() for p in doc.get('body_text', [])):
                    raise Step2Error('No structured main body; an abstract alone is not a fulltext')
                if canonical_id(doc['paper_id']) != pid:
                    raise Step2Error('Source paper ID mismatch')
                if locator.get('source_hash') and doc.get('_source_hash') != locator['source_hash']:
                    raise Step2Error('Source document hash mismatch')
                text, fmt = render_text(doc), 'unarxive_structured_text'
                view = 'structured_body_without_bibliography'
            elif kind == 'body_bundle':
                with gzip.open(path, 'rt') as stream:
                    text = json.load(stream)['body_no_references']
                fmt, view = 'plain_text_without_bibliography', 'body_without_bibliography'
            elif kind == 'plain_text':
                text = path.read_text()
                fmt, view = 'plain_text', 'fulltext_bibliography_unverified'
            elif source['cache_path'] and Path(source['cache_path']).is_file():
                with gzip.open(source['cache_path'], 'rt') as stream:
                    text = json.load(stream)['text']
                fmt, view = 'merged_latex', 'cleaned_fulltext_bibliography_unverified'
            else:
                continue
            if not isinstance(text, str) or not text.strip():
                continue
            payload = {'arxiv_id': pid.removeprefix('arxiv:'), 'title': meta.get('title'),
                       'text': text, 'text_format': fmt,
                       'merged_latex': text if fmt == 'merged_latex' else None,
                       'provenance': {'source_path': str(path), 'locator': locator}}
            prepared = fulltext_preserve(payload, pid)
            # The cleaned text is complete; the duplicate raw body is not needed in RAM/artifacts.
            prepared.pop('source_text')
            prepared['index_text_view'] = view
            return prepared
        raise Step2Error('No existing extracted source; source database was not modified')


class Lexicon:
    """Frozen benchmark tokens + unambiguous WordNet noun normalization."""

    def __init__(self, legacy_root=LEGACY):
        import nltk
        from nltk.corpus import wordnet
        root = Path(legacy_root)
        spec = read_json(root / 'metric-config.v1.json')
        stop_path = root / 'stopwords.v1.json'
        wn_path = root / 'fulltext-cache/nltk_data/corpora/wordnet.zip'
        if digest(encoded(read_json(stop_path))) != spec['stoplist_sha256']:
            raise Step2Error('Frozen stoplist hash mismatch')
        if digest(wn_path.read_bytes()) != spec['wordnet_zip_sha256']:
            raise Step2Error('Frozen WordNet hash mismatch')
        nltk.data.path.insert(0, str(root / 'fulltext-cache/nltk_data'))
        self.wordnet = wordnet
        self.wordnet.ensure_loaded()
        stop = read_json(stop_path)
        self.stop = set(stop['words'])
        self.boiler = set(stop['query_boilerplate_words'])
        self.identity = {'normalizer': 'english-alphanumeric-unique-wordnet-noun-v1',
                         'stoplist_sha256': spec['stoplist_sha256'],
                         'wordnet_zip_sha256': spec['wordnet_zip_sha256'],
                         'nltk_version': nltk.__version__,
                         'reference_implementation_sha256': digest((root / 'measure_terms.py').read_bytes())}

    def words(self, text, query=False):
        text = unicodedata.normalize('NFKC', text).replace('\u00ad', '')
        text = re.sub(r'(?<=[A-Za-z])-\s*\n\s*(?=[a-z])', '', text).replace('’', "'")
        words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?", text.lower())
        words = [re.sub(r"'s$", '', w) for w in words]
        return [w for w in words if w not in self.stop and (not query or w not in self.boiler)]

    @lru_cache(maxsize=300000)
    def lemma(self, word):
        forms = self.wordnet._morphy(word, self.wordnet.NOUN) if word.isalpha() else []
        return forms[0] if len(forms) == 1 else word

    def vocabulary(self, text):
        return sorted({self.lemma(w) for w in self.words(text)})

    def gap(self, terms, candidate_vocabulary):
        words = sorted({w for t in terms for w in self.words(t['term'], query=True)})
        if not words:
            return {'G': None, 'status': 'empty_author_vocabulary', 'words': [], 'found': [], 'missing': []}
        found = [w for w in words if self.lemma(w) in candidate_vocabulary]
        return {'G': 1 - len(found) / len(words), 'status': 'ok', 'words': words,
                'found': found, 'missing': sorted(set(words) - set(found)),
                'denominator': len(words), 'numerator': len(found)}


@dataclass(frozen=True)
class IndexConfig:
    n_components: int = 128
    max_features: int = 40000
    min_df: int = 2
    random_state: int = 42

    def __post_init__(self):
        for name in ('n_components', 'max_features', 'min_df'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise Step2Error(f'{name} must be a positive integer')
        if type(self.random_state) is not int or self.random_state < 0:
            raise Step2Error('random_state must be a nonnegative integer')


def build_index(graph, output, config, lexicon, progress=None):
    import joblib
    import numpy as np
    import sklearn
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'papers').mkdir()
    identity = graph.identity()
    rows, unavailable = [], {}

    def corpus():
        for pid in graph.ids():
            try:
                paper = graph.paper(pid)
            except (Step2Error, OSError, LookupError, ValueError) as exc:
                unavailable[pid] = type(exc).__name__ + ': ' + str(exc)
                continue
            ref = 'papers/' + digest(pid.encode()) + '.json.gz'
            item = {'paper': paper, 'vocabulary': lexicon.vocabulary(paper['text'])}
            raw = gzip.compress(encoded(item), mtime=0)
            (output / ref).write_bytes(raw)
            rows.append({'paper_id': pid, 'artifact': ref, 'sha256': digest(raw),
                         'text_sha256': paper['text_sha256'], 'index_text_view': paper['index_text_view']})
            if progress and len(rows) % 250 == 0:
                progress({'phase': 'texts_and_tfidf', 'indexed': len(rows), 'unavailable': len(unavailable)})
            yield paper['text']

    vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2),
                                sublinear_tf=True, max_features=config.max_features,
                                min_df=config.min_df, dtype=np.float32)
    matrix = vectorizer.fit_transform(corpus())
    components = min(config.n_components, matrix.shape[0] - 1, matrix.shape[1] - 1)
    if components < 1:
        raise Step2Error('At least two usable documents and two features are required for LSA')
    if progress:
        progress({'phase': 'svd', 'documents': matrix.shape[0], 'features': matrix.shape[1], 'components': components})
    svd = TruncatedSVD(n_components=components, random_state=config.random_state)
    vectors = normalize(svd.fit_transform(matrix)).astype(np.float32)
    joblib.dump((vectorizer, svd), output / 'transform.joblib')
    np.save(output / 'vectors.npy', vectors, allow_pickle=False)
    if graph.identity() != identity:
        raise Step2Error('Graph changed while building the index')
    manifest = {'version': VERSION, 'graph': identity, 'config': asdict(config),
                'implementation_sha256': digest(Path(__file__).read_bytes()),
                'effective_components': components, 'normalization': lexicon.identity,
                'sklearn_version': sklearn.__version__, 'numpy_version': np.__version__,
                'rows': rows, 'unavailable': unavailable,
                'files': {name: digest((output / name).read_bytes())
                          for name in ('transform.joblib', 'vectors.npy')}}
    write_json(output / 'manifest.json', manifest)
    return manifest


def validate_card(card, *, allow_empty=False):
    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())
    if not isinstance(card, dict) or set(card) != {'aspects', 'missing_or_unclear'}:
        raise Step2Error('Invalid card keys')
    if not isinstance(card['aspects'], list) or (not card['aspects'] and not allow_empty):
        raise Step2Error('Card must contain at least one substantive aspect')
    if not isinstance(card['missing_or_unclear'], list) or not all(nonempty(x) for x in card['missing_or_unclear']):
        raise Step2Error('Invalid card limitations')
    if not card['aspects'] and not card['missing_or_unclear']:
        raise Step2Error('Unavailable card must explain the extraction limitation')
    keys = {'problem', 'mechanism_or_approach', 'author_terms', 'conventional_terms',
            'findings', 'conditions_and_limits'}
    for aspect in card['aspects']:
        if not isinstance(aspect, dict) or set(aspect) != keys:
            raise Step2Error('Invalid aspect keys')
        descriptions = [aspect[k] for k in ('problem', 'mechanism_or_approach')]
        if (not all(v is None or nonempty(v) for v in descriptions)
                or not any(nonempty(v) for v in descriptions)):
            raise Step2Error('Empty aspect description')
        for name in ('author_terms', 'conventional_terms'):
            if not isinstance(aspect[name], list):
                raise Step2Error('Terms must be arrays')
            for term in aspect[name]:
                if (not isinstance(term, dict) or set(term) != {'term', 'meaning'}
                        or not nonempty(term['term'])
                        or not (term['meaning'] is None or nonempty(term['meaning']))):
                    raise Step2Error('Terms must contain term and meaning')
        if not isinstance(aspect['findings'], list):
            raise Step2Error('Invalid findings')
        for finding in aspect['findings']:
            if (not isinstance(finding, dict) or set(finding) != {'statement', 'status'}
                    or not nonempty(finding['statement']) or finding['status'] not in
                    ('reported_result', 'authors_interpretation', 'authors_hypothesis')):
                raise Step2Error('Invalid finding')
        if not isinstance(aspect['conditions_and_limits'], list) or not all(nonempty(x) for x in aspect['conditions_and_limits']):
            raise Step2Error('Invalid conditions')
    return card


def validate_cards(cards):
    if not isinstance(cards, list) or not cards:
        raise Step2Error('Supply a nonempty array of initial cards')
    seen = set()
    for record in cards:
        if not isinstance(record, dict) or set(record) != {'paper_id', 'card'}:
            raise Step2Error('Expected paper_id/card records')
        pid = canonical_id(record['paper_id'])
        if pid != record['paper_id'] or pid in seen:
            raise Step2Error('Duplicate or noncanonical initial paper ID')
        seen.add(pid)
        validate_card(record['card'])
    return cards


class TopicIndex:
    def __init__(self, directory, lexicon, *, compatibility=None):
        import joblib
        import numpy as np
        import sklearn
        self.directory = Path(directory).resolve()
        manifest_path = self.directory / 'manifest.json'
        self.manifest_hash = digest(manifest_path.read_bytes())
        self.manifest = read_json(manifest_path)
        if self.manifest['version'] != VERSION or self.manifest['normalization'] != lexicon.identity:
            raise Step2Error('Index or lexical implementation differs; rebuild the index')
        self.compatibility = None
        if compatibility is not None:
            from .step2_index_compat import verify_index_compatibility
            self.compatibility = verify_index_compatibility(self.directory, compatibility)
        elif self.manifest['implementation_sha256'] != digest(Path(__file__).read_bytes()):
            raise Step2Error('Index or lexical implementation differs; rebuild or explicitly verify compatibility')
        if self.manifest['sklearn_version'] != sklearn.__version__:
            raise Step2Error('Index sklearn version differs; rebuild the index')
        for name, expected in self.manifest['files'].items():
            if digest((self.directory / name).read_bytes()) != expected:
                raise Step2Error('Index artifact hash mismatch')
        # Only load locally built, trusted artifacts (joblib uses pickle).
        self.vectorizer, self.svd = joblib.load(self.directory / 'transform.joblib')
        self.vectors = np.load(self.directory / 'vectors.npy', mmap_mode='r', allow_pickle=False)
        self.rows = {r['paper_id']: (i, r) for i, r in enumerate(self.manifest['rows'])}
        if self.vectors.shape[0] != len(self.rows):
            raise Step2Error('Index row count mismatch')

    def item(self, pid):
        record = self.rows[pid][1]
        data = (self.directory / record['artifact']).read_bytes()
        if digest(data) != record['sha256']:
            raise Step2Error('Paper cache hash mismatch')
        item = json.loads(gzip.decompress(data))
        if item['paper']['paper_id'] != pid:
            raise Step2Error('Cached paper identity mismatch')
        return item

    def aspects(self, cards):
        import numpy as np
        from sklearn.preprocessing import normalize
        records, texts = [], []
        for record in sorted(cards, key=lambda r: r['paper_id']):
            for number, aspect in enumerate(record['card']['aspects']):
                records.append({'paper_id': record['paper_id'], 'aspect_index': number, 'aspect': aspect})
                parts = [aspect['problem'], aspect['mechanism_or_approach']] + [
                    t[k] for t in aspect['conventional_terms'] for k in ('term', 'meaning')]
                texts.append(' '.join(part for part in parts if part is not None))
        raw = self.vectorizer.transform(texts)
        vectors = normalize(self.svd.transform(raw)).astype(np.float32)
        return records, vectors


def frontier(graph, cards, rejected, unavailable, index):
    from .step2_sources import source_availability
    accepted = {r['paper_id'] for r in cards}
    blocked = accepted | set(rejected) | set(unavailable)
    result = {}
    for pid in sorted(accepted):
        for edge in graph.connections(pid):
            other = edge['dst'] if edge['src'] == pid else edge['src']
            if other in blocked:
                continue
            if other not in index.rows:
                unavailable[other] = 'not_in_readable_index'
                continue
            availability = source_availability(index, other)
            if availability['status'] == 'unavailable':
                unavailable[other] = availability['reason']
                continue
            connection = {'src': edge['src'], 'dst': edge['dst'],
                          'evidence': json.loads(edge['evidence'])}
            result.setdefault(other, {})[(edge['src'], edge['dst'])] = connection
    return {pid: list(connections.values()) for pid, connections in sorted(result.items())}


def rank_candidates(index, lexicon, cards, candidates, degrees, *, gap_weight=0.5, rng_seed=42):
    import numpy as np
    if type(gap_weight) not in (int, float) or not math.isfinite(gap_weight) or not 0 <= gap_weight <= 1:
        raise Step2Error('Invalid gap weight')
    validate_cards(cards)
    aspects, aspect_vectors = index.aspects(cards)
    represented_aspects = bool(np.any(np.linalg.norm(aspect_vectors, axis=1) > 0))
    ids = sorted(candidates)
    if not ids:
        return {'profiles': [], 'selected_id': None, 'selection_method': 'empty_frontier'}
    m = median(degrees.get(pid, 0) for pid in ids)
    profiles = []
    # Chunked comparison covers every ID; never preselect top-k or sample neighbors.
    for offset in range(0, len(ids), 256):
        batch = ids[offset:offset + 256]
        vectors = np.asarray(index.vectors[[index.rows[pid][0] for pid in batch]])
        similarities = np.clip(vectors @ aspect_vectors.T, 0, 1)
        for i, pid in enumerate(batch):
            best = int(similarities[i].argmax())
            t = float(similarities[i, best])
            defined = bool(np.linalg.norm(vectors[i]) > 0 and represented_aspects)
            d = degrees.get(pid, 0)
            middle = 1 / (1 + abs(d - m) / max(1, m))
            aspect = aspects[best] if defined and t > 0 else None
            gap = {'G': None, 'status': 'no_representable_matching_aspect'}
            if aspect:
                vocabulary = set(index.item(pid)['vocabulary'])
                gap = lexicon.gap(aspect['aspect']['author_terms'], vocabulary)
            g = gap['G']
            score = None
            if defined:
                if t == 0:
                    score = 0.0  # G stays unknown; a zero T factor determines S for any bounded G.
                elif gap_weight == 0:
                    score = t * middle
                elif g is not None:
                    score = t * (gap_weight * g + (1 - gap_weight) * middle)
            profiles.append({'paper_id': pid, 'T': t if defined else None, 'G': g, 'M': middle,
                             'd': d, 'median': m, 'S': score, 'gap': gap,
                             'matched_aspect': {k: aspect[k] for k in ('paper_id', 'aspect_index')} if aspect else None,
                             'status': 'scored' if score is not None else 'unknown',
                             'connections': candidates[pid]})
    tie = lambda p: digest(f"{rng_seed}|{p['paper_id']}".encode())
    scored = [p for p in profiles if p['S'] is not None]
    selected = min(scored, key=lambda p: (-p['S'], tie(p))) if scored else min(profiles, key=tie)
    return {'profiles': profiles, 'selected_id': selected['paper_id'],
            'selection_method': 'max_score' if scored else 'unknown_seeded_fallback',
            'memory_sha256': digest(encoded(cards)), 'gap_weight': gap_weight,
            'rng_seed': rng_seed, 'frontier_count': len(ids), 'median': m}
