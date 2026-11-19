"""Prepare random seed-neighbor pairs from indexes, without reading full texts."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import random
import sqlite3

from .factory_step1 import digest_rows
from .store import canonical_id


VERSION = 'factory-step1.5-uniform-neighbors-v1'


def sample(database, seed_report, *, budget, rng_seed, seed_count):
    if type(budget) is not int or budget < 1 or type(seed_count) is not int or seed_count < 1:
        raise ValueError('budget and seed_count must be positive integers')
    if type(rng_seed) is not int:
        raise ValueError('rng_seed must be an integer')
    source = Path(seed_report).read_bytes()
    report = json.loads(source)
    seeds = report['selected'][:seed_count]
    if len({s['paper_id'] for s in seeds}) != len(seeds):
        raise ValueError('Duplicate seeds in input')
    result = {'purpose': 'Prompt development pairs; no scientific decisions or LLM calls',
              'version': VERSION, 'python_version': platform.python_version(),
              'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'source_seed_report': str(Path(seed_report).resolve()),
              'source_seed_report_sha256': hashlib.sha256(source).hexdigest(),
              'snapshot_id': report['snapshot_id'],
              'config': {'neighbors_per_seed': budget, 'rng_seed': rng_seed, 'seed_count': seed_count,
                         'seed_order': 'prefix of step-1 draw order',
                         'pool': 'unique readable In(seed) union Out(seed), excluding self',
                         'sampling': 'uniform without replacement; no directional quotas',
                         'rng': 'random.Random seeded by SHA256(version, snapshot, rng_seed, seed_id)'},
              'seeds': [], 'pairs': []}
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        row = connection.execute("SELECT value FROM settings WHERE key='snapshot_id'").fetchone()
        if not row or json.loads(row[0]) != report['snapshot_id']:
            raise ValueError('Snapshot mismatch with step-1 seed report')
        for seed in seeds:
            pid = seed['paper_id']
            if canonical_id(pid) != pid:
                raise ValueError('Noncanonical seed ID')
            row = connection.execute(
                "SELECT p.metadata FROM papers p JOIN nodes n ON n.paper_id=p.id WHERE p.id=? "
                "AND EXISTS(SELECT 1 FROM sources s WHERE s.paper_id=p.id AND s.status='available')", (pid,)).fetchone()
            if row is None:
                raise ValueError('Seed absent from snapshot or without indexed available text')
            seed_metadata = json.loads(row[0])
            pool = []
            for neighbor_id, metadata, references, citations in connection.execute(
                "SELECT p.id,p.metadata,EXISTS(SELECT 1 FROM edges WHERE src=? AND dst=p.id),"
                "EXISTS(SELECT 1 FROM edges WHERE dst=? AND src=p.id) "
                "FROM papers p JOIN nodes n ON n.paper_id=p.id WHERE p.id<>? "
                "AND p.id IN (SELECT dst FROM edges WHERE src=? UNION SELECT src FROM edges WHERE dst=?) "
                "AND EXISTS(SELECT 1 FROM sources s WHERE s.paper_id=p.id AND s.status='available') ORDER BY p.id",
                (pid, pid, pid, pid, pid)):
                try:
                    if canonical_id(neighbor_id) != neighbor_id:
                        continue
                except ValueError:
                    continue
                pool.append({'paper_id': neighbor_id, 'title': json.loads(metadata).get('title'),
                             'directions': [d for d, exists in [('references', references), ('citations', citations)] if exists]})
            material = json.dumps([VERSION, report['snapshot_id'], rng_seed, pid], separators=(',', ':')).encode()
            remaining, selected = pool.copy(), []
            rng = random.Random(int.from_bytes(hashlib.sha256(material).digest(), 'big'))
            while remaining and len(selected) < budget:
                selected.append(remaining.pop(rng.randrange(len(remaining))))
            result['seeds'].append({'paper_id': pid, 'title': seed_metadata.get('title'),
                                    'available_neighbor_count': len(pool), 'pool_sha256': digest_rows(pool),
                                    'selected_neighbors': selected})
            for neighbor in selected:
                result['pairs'].append({'seed_id': pid, 'seed_title': seed_metadata.get('title'),
                                        'neighbor_id': neighbor['paper_id'], 'neighbor_title': neighbor['title'],
                                        'directions': neighbor['directions']})
    result['pair_count'] = len(result['pairs'])
    result['pairs_sha256'] = digest_rows(result['pairs'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--seed-report', type=Path, required=True)
    parser.add_argument('--neighbors', type=int, required=True)
    parser.add_argument('--seed-count', type=int, required=True)
    parser.add_argument('--rng-seed', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output file')
    try:
        result = sample(args.db, args.seed_report, budget=args.neighbors,
                        rng_seed=args.rng_seed, seed_count=args.seed_count)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
