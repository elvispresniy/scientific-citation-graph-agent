from dataclasses import replace
import hashlib
import json
import sqlite3

import pytest

from graph_pilot.factory_step1 import Config, analyze, run, select
from graph_pilot.store import Store


def config(**changes):
    return replace(Config('test-snapshot', 20, 2, 2, 42, 'uniform'), **changes)


@pytest.fixture
def snapshot(tmp_path):
    store = Store(tmp_path / 'graph.sqlite')
    store.setting('snapshot_id', 'test-snapshot')
    ids = {name: f'arxiv:1901.{i:05d}' for i, name in enumerate('ABCZHDEFQO', 1)}
    for name, pid in ids.items():
        store.upsert(pid, {'title': name})
        if name != 'O':
            store.add_node(pid, 0)
        # Nonexistent paths prove that selection uses the availability index only.
        store.source(pid, 'fixture', tmp_path / (name + '.missing'), {},
                     'unchecked' if name == 'F' else 'failed' if name in 'DE' else 'available')
    ids['Q'] = 'invalid-id'
    store.db.execute('INSERT INTO papers VALUES (?,?)', ('invalid-id', '{}'))
    store.db.execute('INSERT INTO nodes(paper_id,depth) VALUES (?,0)', ('invalid-id',))
    pairs = [('A', 'B'), ('B', 'A'), ('A', 'C'), ('A', 'D'), ('E', 'A'),
             ('Z', 'B'), ('Z', 'C'), ('B', 'H'), ('C', 'H'), ('Z', 'H'),
             ('A', 'A'), ('O', 'A'), ('Q', 'A')]
    for src, dst in pairs:
        store.db.execute('INSERT INTO edges VALUES (?,?,0,?)', (ids[src], ids[dst], '{}'))
    store.close()
    return store.path, ids


def metrics(database, cfg):
    with sqlite3.connect(database) as connection:
        candidates, counts, fingerprints = analyze(connection, cfg)
    return {c['paper_id']: c for c in candidates}, counts, fingerprints


def test_degree_scope_readability_and_boundaries(snapshot):
    database, ids = snapshot
    rows, counts, _ = metrics(database, config())
    a = rows[ids['A']]
    # Reciprocal B counts once, D/E unreadable, outside O and invalid Q ignored.
    assert (a['in_degree'], a['out_degree'], a['readable_neighbors']) == (2, 3, 2)
    assert a['eligible'] and a['usable']
    assert rows[ids['Z']]['in_degree'] == 0 and rows[ids['Z']]['eligible']
    assert rows[ids['H']]['in_degree'] == 3
    assert rows[ids['H']]['rejection_reasons'] == ['in_degree_above_max']
    assert not rows[ids['F']]['text_available']
    assert not rows[ids['D']]['usable']
    assert 'invalid_id' in rows[ids['Q']]['rejection_reasons']
    assert ids['O'] not in rows
    assert counts['ignored_edges'] == {'invalid_endpoint': 1, 'outside_snapshot': 1, 'self_reference': 1}
    assert not metrics(database, config(m=3))[0][ids['A']]['eligible']
    assert not metrics(database, config(D_max=1))[0][ids['A']]['eligible']
    # The hub is retained as a readable neighbor despite being ineligible as a seed.
    assert rows[ids['Z']]['readable_neighbors'] == 3


def test_selection_known_sequence_no_replacement_and_empty_pool():
    candidates = [{'paper_id': str(i), 'eligible': True} for i in range(5)]
    candidates.append({'paper_id': 'excluded', 'eligible': False})
    selected = select(list(reversed(candidates)), config(K=3))
    assert [c['paper_id'] for c in selected] == ['0', '1', '4']
    assert [c['draw'] for c in selected] == [1, 2, 3]
    assert len(select(candidates, config(K=20))) == 5
    assert select([{'paper_id': 'x', 'eligible': False}], config()) == []
    assert select(candidates, config(rng_seed=43)) != select(candidates, config())


def test_reproducible_artifacts_readonly_and_pool_exhaustion(snapshot, tmp_path):
    database, _ = snapshot
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    first = run(database, config(), tmp_path / 'first')
    second = run(database, config(), tmp_path / 'second')
    assert first['selected'] == second['selected']
    assert first['fingerprints'] == second['fingerprints']
    assert first['selected_ids_sha256'] == second['selected_ids_sha256']
    assert first['stop_reason'] == 'candidate_pool_exhausted'
    assert first['selected_count'] == first['counts']['eligible']
    assert all(c['weight'] == 1 for c in first['selected'])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    saved = json.loads((tmp_path / 'first/report.json').read_text())
    assert saved['config'] == json.loads((tmp_path / 'first/config.json').read_text())
    with pytest.raises(FileExistsError):
        run(database, config(), tmp_path / 'first')
    empty = run(database, config(m=100), tmp_path / 'empty')
    assert empty['selected_count'] == 0 and empty['counts']['eligible'] == 0
    assert empty['config']['m'] == 100


def test_snapshot_mismatch_and_input_fingerprint(snapshot, tmp_path):
    database, ids = snapshot
    with pytest.raises(ValueError, match='Snapshot mismatch'):
        run(database, config(snapshot_id='other'), tmp_path / 'wrong')
    assert not (tmp_path / 'wrong').exists()
    _, _, before = metrics(database, config())
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sources SET status='failed' WHERE paper_id=?", (ids['C'],))
    _, _, after = metrics(database, config())
    assert before['readable_nodes_sha256'] != after['readable_nodes_sha256']
    assert before['candidate_metrics_sha256'] != after['candidate_metrics_sha256']


@pytest.mark.parametrize('changes', [{'K': 0}, {'m': 0}, {'D_max': -1}, {'m': 1.5},
                                      {'rng_seed': True}, {'weight_mode': 'venue'}, {'snapshot_id': ''}])
def test_configuration_validation(changes):
    with pytest.raises(ValueError):
        config(**changes)
