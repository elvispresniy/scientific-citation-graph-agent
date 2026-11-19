"""Native algorithm tests against full-sort mathematical reference, not old MT draws."""
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from graph_pilot.factory_step1 import Config
from graph_pilot.gumbel_step1 import candidate_key, export_candidates, invoke, run
from graph_pilot.store import Store


@pytest.fixture(scope='module')
def binary():
    path = Path(os.environ.get('GUMBEL_BINARY', Path(__file__).resolve().parents[2] /
                               'gumbel_topk/build/gumbel_topk')).resolve()
    if not path.is_file():
        if 'GUMBEL_BINARY' in os.environ:
            pytest.fail(f'GUMBEL_BINARY does not exist: {path}')
        pytest.skip('Build optional native tests first: make -C code/gumbel_topk')
    return path


def reference(rows, seed, k):
    mask = (1 << 64) - 1

    def mix(x):
        x = (x + 0x9e3779b97f4a7c15) & mask
        x = ((x ^ (x >> 30)) * 0xbf58476d1ce4e5b9) & mask
        x = ((x ^ (x >> 27)) * 0x94d049bb133111eb) & mask
        return x ^ (x >> 31)

    scores = []
    for key, weight in rows:
        u = ((mix(key ^ mix(seed)) >> 12) + .5) * 2**-52
        scores.append((key, math.log(weight) - math.log(-math.log(u))))
    return sorted(scores, key=lambda r: (-r[1], r[0]))[:k]


def test_benchmark_matrix_uses_separate_baselines(binary, tmp_path):
    script = Path(__file__).resolve().parents[2] / 'gumbel_topk/benchmark.py'
    output = tmp_path / 'matrix'
    subprocess.run([sys.executable, str(script), '--binary', str(binary),
                    '--output', str(output), '--sizes', '17', '31', '--k', '3', '40',
                    '--weight-pattern', 'uniform', 'skewed', '--threads', '1', '2',
                    '--repeat', '2', '--warmup', '1'], check=True, capture_output=True)
    report = json.loads((output / 'report.json').read_text())
    assert report['environment_label'] == 'local'
    assert report['input']['ks'] == [3, 40]
    assert len(report['results']) == 16
    assert len(list(output.glob('n*-p*.json'))) == 16
    baselines = {}
    for row in report['results']:
        case = row['n'], row['k'], row['weight_pattern']
        assert len(row['native']['timings']) == 2
        assert len(row['native']['selected']) == min(row['n'], row['k'])
        if row['threads'] == 1:
            baselines[case] = row
        baseline = baselines[case]
        assert row['native']['selected'] == baseline['native']['selected']
        assert row['speedup'] == pytest.approx(baseline['median_kernel_seconds'] / row['median_kernel_seconds'])
        weights = [(i, 1.0 if row['weight_pattern'] == 'uniform' else 10.0 ** (i % 7 - 3))
                   for i in range(row['n'])]
        assert [item['id'] for item in row['native']['selected']] == [
            item[0] for item in reference(weights, 42, row['k'])]


def test_benchmark_rejects_cluster_label_outside_slurm(binary, tmp_path):
    script = Path(__file__).resolve().parents[2] / 'gumbel_topk/benchmark.py'
    environment = dict(os.environ)
    environment.pop('SLURM_JOB_ID', None)
    output = tmp_path / 'not-a-cluster-run'
    result = subprocess.run([sys.executable, str(script), '--binary', str(binary),
                             '--output', str(output), '--environment-label', 'lomonosov2'],
                            env=environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'inside a SLURM job' in result.stderr
    assert not output.exists()


@pytest.mark.parametrize('k', [0, 1, 20, 1000])
def test_native_matches_full_sort_and_thread_counts(binary, tmp_path, k):
    rows = [(i * 7919, 10.0 ** (i % 9 - 4)) for i in range(257)]
    rows += [((1 << 64) - 1, 1e-300), ((1 << 64) - 2, 1e300)]
    rows += [((1 << 64) - 3, 5e-324)]
    data = tmp_path / 'rows.tsv'
    data.write_text(''.join(f'{key}\t{weight:.17g}\n' for key, weight in rows))
    expected = reference(rows, 42, k)
    first = None
    for threads in [1, 2, 4, 8]:
        result = invoke(binary, data, k=k, seed=42, threads=threads, repeat=2)
        assert result['threads_used'] == threads
        selected = result['selected']
        assert [r['id'] for r in selected] == [r[0] for r in expected]
        assert [r['score'] for r in selected] == pytest.approx([r[1] for r in expected], abs=1e-12)
        if first is None:
            first = selected
        assert selected == first
        for timing in result['timings']:
            assert timing['total_seconds'] == pytest.approx(timing['local_seconds'] + timing['merge_seconds'])
    data.write_text(''.join(f'{key}\t{weight:.17g}\n' for key, weight in reversed(rows)))
    assert invoke(binary, data, k=k, seed=42, threads=4)['selected'] == first


def test_empty_pool_and_more_threads_than_rows(binary, tmp_path):
    data = tmp_path / 'empty.tsv'
    data.write_text('')
    assert invoke(binary, data, k=20, seed=0, threads=4)['selected'] == []
    data.write_text('1\t1\n2\t5\n')
    result = invoke(binary, data, k=20, seed=-1, threads=8)
    assert {r['id'] for r in result['selected']} == {1, 2}
    assert result['seed'] == (1 << 64) - 1


@pytest.mark.parametrize('text', ['1\t0\n', '1\t-1\n', '1\tnan\n', '1\tinf\n',
                                 '1\t1\n1\t2\n', '-1\t1\n', '1\t1\textra\n'])
def test_reject_invalid_native_input(binary, tmp_path, text):
    data = tmp_path / 'bad.tsv'
    data.write_text(text)
    with pytest.raises(ValueError, match='Native sampler failed'):
        invoke(binary, data, k=1, seed=42, threads=1)


def test_weighted_first_draw_not_uniform(binary, tmp_path):
    data = tmp_path / 'weighted.tsv'
    data.write_text('1\t1\n2\t9\n')
    # Fixed seeds; broad tolerance detects accidentally ignoring weights, not tiny PRNG biases.
    heavy = sum(invoke(binary, data, k=1, seed=seed, threads=1)['selected'][0]['id'] == 2
                for seed in range(200))
    assert 155 <= heavy <= 198


def test_adapter_preserves_eligibility_readonly_and_artifacts(binary, tmp_path):
    database = tmp_path / 'graph.sqlite'
    store = Store(database)
    store.setting('snapshot_id', 'native-fixture')
    ids = [f'arxiv:1901.{i:05d}' for i in range(1, 7)]
    for pid in ids:
        store.upsert(pid, {'title': pid})
        store.add_node(pid, 0)
        store.source(pid, 'fixture', tmp_path / 'not-read.txt', {}, 'available')
    for i in range(5):
        store.db.execute('INSERT INTO edges VALUES (?,?,0,?)', (ids[i], ids[i+1], '{}'))
    store.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    config = Config('native-fixture', 3, 1, 50, 42, 'uniform')
    one = run(database, config, tmp_path / 'one', binary=binary)
    many = run(database, config, tmp_path / 'many', binary=binary, threads=4)
    assert one['selected'] == many['selected']
    assert one['fingerprints'] == many['fingerprints']
    assert one['counts']['eligible'] == 6
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert json.loads((tmp_path / 'many/report.json').read_text())['native']['threads_used'] == 4
    with pytest.raises(FileExistsError):
        run(database, config, tmp_path / 'one', binary=binary)
    empty = run(database, replace(config, m=100), tmp_path / 'none', binary=binary, threads=4)
    assert empty['selected'] == []
    assert empty['stop_reason'] == 'candidate_pool_exhausted'


def test_export_keys_and_collisions(tmp_path, monkeypatch):
    rows = [{'paper_id': 'a', 'eligible': True, 'weight': 1},
            {'paper_id': 'b', 'eligible': False, 'weight': 0}]
    assert candidate_key('a') == int.from_bytes(hashlib.sha256(b'a').digest()[:8], 'little')
    mapping, checksum = export_candidates(rows, tmp_path / 'good.tsv')
    assert len(mapping) == 1
    assert checksum == hashlib.sha256((tmp_path / 'good.tsv').read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        export_candidates([{**rows[0], 'weight': float('nan')}], tmp_path / 'bad.tsv')
    monkeypatch.setattr('graph_pilot.gumbel_step1.candidate_key', lambda _: 0)
    with pytest.raises(ValueError, match='collision'):
        export_candidates([rows[0], {**rows[0], 'paper_id': 'c'}], tmp_path / 'collision.tsv')


def test_serial_build_rejects_parallel_request(tmp_path):
    serial = Path(__file__).resolve().parents[2] / 'gumbel_topk/build/gumbel_topk_serial'
    if not serial.exists():
        pytest.skip('Optional serial-only binary not built')
    result = subprocess.run([str(serial), '--synthetic', '10', '--threads', '2'], capture_output=True, text=True)
    assert result.returncode != 0 and 'no OpenMP' in result.stderr
