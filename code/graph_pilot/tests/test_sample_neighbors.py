import hashlib
import json

import pytest

from graph_pilot.sample_neighbors import sample
from graph_pilot.store import Store


@pytest.fixture
def snapshot(tmp_path):
    store = Store(tmp_path / 'graph.sqlite')
    store.setting('snapshot_id', 'test')
    ids = [f'arxiv:1901.{i:05d}' for i in range(1, 7)]
    for i, pid in enumerate(ids):
        store.upsert(pid, {'title': str(i)})
        if i != 5:
            store.add_node(pid, 0)
        store.source(pid, 'fixture', tmp_path / str(i), {}, 'unchecked' if i == 4 else 'available')
    for a, b in [(0, 1), (1, 0), (2, 0), (0, 3), (0, 4), (5, 0), (0, 0)]:
        store.db.execute('INSERT INTO edges VALUES (?,?,0,?)', (ids[a], ids[b], '{}'))
    store.close()
    report = tmp_path / 'seeds.json'
    report.write_text(json.dumps({'snapshot_id': 'test', 'selected': [{'paper_id': ids[0]}, {'paper_id': ids[1]}]}))
    return store.path, report, ids


def test_pool_dedup_scope_and_small_pool(snapshot):
    db, report, ids = snapshot
    result = sample(db, report, budget=20, rng_seed=42, seed_count=1)
    assert result['pair_count'] == 3
    neighbors = {r['paper_id']: r for r in result['seeds'][0]['selected_neighbors']}
    assert set(neighbors) == set(ids[1:4])
    assert neighbors[ids[1]]['directions'] == ['references', 'citations']
    assert neighbors[ids[2]]['directions'] == ['citations']
    assert neighbors[ids[3]]['directions'] == ['references']


def test_stable_per_seed_without_text_reads_or_database_writes(snapshot):
    db, report, ids = snapshot
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    one = sample(db, report, budget=2, rng_seed=42, seed_count=1)
    again = sample(db, report, budget=2, rng_seed=42, seed_count=1)
    both = sample(db, report, budget=2, rng_seed=42, seed_count=2)
    assert one == again
    assert one['seeds'][0] == both['seeds'][0]
    assert len({r['neighbor_id'] for r in one['pairs']}) == 2
    assert all(r['seed_id'] == ids[0] for r in one['pairs'])
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_snapshot_mismatch(snapshot):
    db, report, _ = snapshot
    report.write_text(json.dumps({'snapshot_id': 'other', 'selected': []}))
    with pytest.raises(ValueError, match='Snapshot mismatch'):
        sample(db, report, budget=2, rng_seed=42, seed_count=1)
