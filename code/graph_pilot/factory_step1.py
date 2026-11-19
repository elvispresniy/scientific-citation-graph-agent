"""Factory seed selection from a local snapshot; no network or text extraction."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import platform
import random
import sqlite3
import time

from .store import canonical_id


ALGORITHM_VERSION = 'factory-step1-uniform-sequential-v1'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest_rows(rows):
    digest = hashlib.sha256()
    for row in rows:
        digest.update((encoded(row) + '\n').encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class Config:
    snapshot_id: str
    K: int
    m: int
    D_max: int
    rng_seed: int
    weight_mode: str

    def __post_init__(self):
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id.strip():
            raise ValueError('snapshot_id must be a nonempty string')
        for name, minimum in [('K', 1), ('m', 1), ('D_max', 0)]:
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise ValueError(f'{name} must be an integer >= {minimum}')
        if type(self.rng_seed) is not int:
            raise ValueError('rng_seed must be an integer')
        if self.weight_mode != 'uniform':
            raise ValueError('Only weight_mode=uniform is implemented; all weights are 1')

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text()))


def is_canonical(pid):
    try:
        return canonical_id(pid) == pid
    except ValueError:
        return False


def analyze(connection, config):
    """Read a consistent SQLite transaction. All degrees are within nodes, not papers."""
    row = connection.execute("SELECT value FROM settings WHERE key='snapshot_id'").fetchone()
    snapshot = json.loads(row[0]) if row else None
    if snapshot != config.snapshot_id:
        raise ValueError(f'Snapshot mismatch: expected {config.snapshot_id!r}, got {snapshot!r}')
    rows = connection.execute('SELECT n.paper_id,p.metadata FROM nodes n '
                              'LEFT JOIN papers p ON p.id=n.paper_id ORDER BY n.paper_id').fetchall()
    node_ids = {pid for pid, _ in rows}
    # Invalid metadata prevents seed eligibility, but does not erase a graph node's edges.
    valid_ids = {pid for pid, meta in rows if meta is not None and is_canonical(pid)}
    readable = {r[0] for r in connection.execute(
        "SELECT DISTINCT s.paper_id FROM sources s JOIN nodes n ON n.paper_id=s.paper_id "
        "WHERE s.status='available'")} & valid_ids
    incoming = {pid: set() for pid in valid_ids}
    outgoing = {pid: set() for pid in valid_ids}
    ignored = Counter()
    for src, dst in connection.execute('SELECT src,dst FROM edges ORDER BY src,dst'):
        if src == dst:
            ignored['self_reference'] += 1
        elif src not in node_ids or dst not in node_ids:
            ignored['outside_snapshot'] += 1
        elif src not in valid_ids or dst not in valid_ids:
            ignored['invalid_endpoint'] += 1
        elif dst in outgoing[src]:
            ignored['duplicate'] += 1
        else:
            outgoing[src].add(dst)
            incoming[dst].add(src)

    candidates, reasons = [], Counter()
    for pid, raw_metadata in rows:
        failures = []
        if not is_canonical(pid):
            failures.append('invalid_id')
        metadata = {}
        if raw_metadata is None:
            failures.append('missing_metadata')
        else:
            try:
                metadata = json.loads(raw_metadata)
                if not isinstance(metadata, dict):
                    raise ValueError('Metadata must be an object')
            except (ValueError, TypeError):
                metadata = {}
                failures.append('invalid_metadata')
        has_text = pid in readable
        if not has_text:
            failures.append('text_unavailable')
        ins, outs = incoming.get(pid, set()), outgoing.get(pid, set())
        available_neighbors = len((ins | outs) & readable)
        if available_neighbors < config.m:
            failures.append('too_few_readable_neighbors')
        if len(ins) > config.D_max:
            failures.append('in_degree_above_max')
        reasons.update(failures)
        candidates.append({'paper_id': pid, 'title': metadata.get('title'),
                           'in_degree': len(ins), 'out_degree': len(outs),
                           'readable_neighbors': available_neighbors, 'text_available': has_text,
                           'usable': not any(r in failures for r in (
                               'invalid_id', 'missing_metadata', 'invalid_metadata', 'text_unavailable')),
                           'eligible': not failures, 'rejection_reasons': failures,
                           'venue': None, 'track': None, 'venue_evidence_status': 'not_enriched',
                           'weight': 1})

    fingerprints = {
        'nodes_sha256': digest_rows(sorted(node_ids)),
        'edges_sha256': digest_rows([src, dst] for src in sorted(outgoing) for dst in sorted(outgoing[src])),
        'readable_nodes_sha256': digest_rows(sorted(readable)),
        'metadata_sha256': digest_rows([pid, metadata] for pid, metadata in rows),
        'candidate_metrics_sha256': digest_rows(candidates),
    }
    return candidates, {
        'graph_nodes': len(node_ids), 'valid_graph_edges': sum(map(len, outgoing.values())),
        'readable_nodes': len(readable), 'eligible': sum(c['eligible'] for c in candidates),
        'eligible_zero_in_degree': sum(c['eligible'] and c['in_degree'] == 0 for c in candidates),
        'rejected': sum(not c['eligible'] for c in candidates),
        'rejection_reason_counts': dict(sorted(reasons.items())),
        'rejection_counts_overlap': True, 'ignored_edges': dict(sorted(ignored.items())),
    }, fingerprints


def select(candidates, config):
    """Sequential equal-weight draws without replacement, from sorted canonical IDs."""
    remaining = sorted((c for c in candidates if c['eligible']), key=lambda c: c['paper_id'])
    rng = random.Random(config.rng_seed)
    selected = []
    while remaining and len(selected) < config.K:
        selected.append({**remaining.pop(rng.randrange(len(remaining))), 'draw': len(selected) + 1})
    return selected


def run(database, config, output):
    started = time.monotonic()
    database, output = Path(database).resolve(), Path(output).resolve()
    # Reserve a fresh result directory: never overwrite a previous experiment.
    if output.exists():
        raise FileExistsError(f'Use a new output directory: {output}')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA cache_size=-16384')
        connection.execute('BEGIN')
        candidates, counts, fingerprints = analyze(connection, config)
    selected = select(candidates, config)
    selection_sha256 = digest_rows(c['paper_id'] for c in selected)
    report = {
        'purpose': 'factory step 1; local infrastructure validation, not a scientific benchmark',
        'algorithm_version': ALGORITHM_VERSION,
        'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'rng': {'implementation': 'random.Random / MT19937; sequential randrange then pop',
                'python_version': platform.python_version()},
        'config': asdict(config), 'snapshot_id': config.snapshot_id, 'database': str(database),
        'degree_scope': 'induced snapshot defined by nodes; valid unique edges only',
        'readability_scope': 'available status in source index; no text read during selection',
        'candidate_order': 'canonical paper_id ascending', 'counts': counts,
        'fingerprints': fingerprints, 'selected_ids_sha256': selection_sha256,
        'selected': selected, 'selected_count': len(selected),
        'stop_reason': 'K_reached' if len(selected) == config.K else 'candidate_pool_exhausted',
        'elapsed_seconds': round(time.monotonic() - started, 6),
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config.json').write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2) + '\n')
    (output / 'candidates.jsonl').write_text(''.join(encoded(c) + '\n' for c in candidates))
    (output / 'selected.jsonl').write_text(''.join(encoded(c) + '\n' for c in selected))
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report
