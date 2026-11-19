"""Explicit, exact-source compatibility evidence for an existing local index.

This checks a trusted saved snapshot, not arbitrary program equivalence. Changing
query-card representation or ranking need not refit frozen document transforms.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

from .step2_features import Step2Error, digest, read_json, write_json


SCHEMA = 'step2-index-compatibility-v1'
SOURCE = 'code/graph_pilot/step2_features.py'
DEPENDENCIES = ('probe_modules.py', 'unarxive.py', 'latex_to_text.py', 'store.py')
RUNTIME_FUNCTIONS = {'validate_card', 'validate_cards', 'frontier', 'rank_candidates'}


def _scope(source):
    """Keep every module-level node except an explicit runtime-only allowlist.

    TopicIndex.item and its numerical artifact loading stay protected. Its
    validation preamble may change to check this evidence; aspects() constructs
    new query strings, rather than the document vectors saved in the index.
    """
    tree = ast.parse(source)
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in RUNTIME_FUNCTIONS:
            continue
        if isinstance(node, ast.ClassDef) and node.name == 'TopicIndex':
            node = copy.deepcopy(node)
            methods = []
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name == 'aspects':
                    continue
                if isinstance(method, ast.FunctionDef) and method.name == '__init__':
                    # Keep imports and the exact load/shape/identity block after
                    # the compatibility/version/hash validation preamble.
                    start = next((i for i, stmt in enumerate(method.body)
                                  if isinstance(stmt, ast.Assign)
                                  and any(isinstance(target, ast.Tuple)
                                          and [ast.unparse(x) for x in target.elts] ==
                                          ['self.vectorizer', 'self.svd']
                                          for target in stmt.targets)), None)
                    if start is None:
                        raise Step2Error('Cannot identify protected index artifact loading')
                    method.args = ast.arguments(posonlyargs=[], args=[], vararg=None,
                                                kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[])
                    method.body = [n for n in method.body[:start]
                                   if isinstance(n, (ast.Import, ast.ImportFrom))] + method.body[start:]
                methods.append(method)
            node.body = methods
        nodes.append(node)
    return ast.dump(ast.Module(body=nodes, type_ignores=[]), include_attributes=False)


def _evidence(index_dir, baseline_source, snapshot_manifest):
    import numpy as np
    import sklearn

    directory = Path(index_dir).resolve()
    baseline_path, snapshot_path = Path(baseline_source).resolve(), Path(snapshot_manifest).resolve()
    source_path = Path(__file__).with_name('step2_features.py')
    baseline, current = baseline_path.read_bytes(), source_path.read_bytes()
    manifest_path = directory / 'manifest.json'
    manifest = read_json(manifest_path)
    snapshot = read_json(snapshot_path)
    archived = {record['path']: record['sha256'] for record in snapshot['archived_files']}
    manifest_hash = digest(manifest_path.read_bytes())
    root = source_path.resolve().parents[2]
    reference = manifest_path.relative_to(root).as_posix() if manifest_path.is_relative_to(root) else None
    snapshot_index_hash = archived.get(reference)
    if snapshot_index_hash is not None and snapshot_index_hash != manifest_hash:
        raise Step2Error('Index manifest differs from the saved snapshot reference')
    if digest(baseline) != manifest['implementation_sha256'] or archived.get(SOURCE) != digest(baseline):
        raise Step2Error('Baseline source does not match the index and saved snapshot')
    old_scope, new_scope = _scope(baseline), _scope(current)
    if old_scope != new_scope:
        raise Step2Error('Protected index/normalizer AST differs; rebuild the index')
    dependencies = {}
    for name in DEPENDENCIES:
        path = source_path.with_name(name)
        expected = archived.get('code/graph_pilot/' + name)
        if expected is None or digest(path.read_bytes()) != expected:
            raise Step2Error('Index preparation dependency differs from saved snapshot: ' + name)
        dependencies[name] = expected
    if manifest['numpy_version'] != np.__version__ or manifest['sklearn_version'] != sklearn.__version__:
        raise Step2Error('Index numerical runtime differs; rebuild the index')
    if any(digest((directory / name).read_bytes()) != expected
           for name, expected in manifest['files'].items()):
        raise Step2Error('Index artifact hash mismatch')
    return {'schema': SCHEMA,
            'index_manifest_sha256': manifest_hash,
            'snapshot_index_manifest_sha256': snapshot_index_hash,
            'baseline_source': str(baseline_path), 'baseline_source_sha256': digest(baseline),
            'current_source_sha256': digest(current),
            'snapshot_manifest': str(snapshot_path), 'snapshot_manifest_sha256': digest(snapshot_path.read_bytes()),
            'protected_ast_sha256': digest(old_scope.encode()),
            'preparation_dependencies_sha256': dependencies,
            'verifier_sha256': digest(Path(__file__).read_bytes()),
            'index_files': manifest['files'],
            'numpy_version': np.__version__, 'sklearn_version': sklearn.__version__,
            'allowed_changes': sorted(RUNTIME_FUNCTIONS) +
                               ['TopicIndex.aspects', 'TopicIndex.__init__ validation preamble']}


def create_index_compatibility(index_dir, baseline_source, snapshot_manifest, output):
    """Write new evidence outside the index; never edit an index or its manifest."""
    directory, output = Path(index_dir).resolve(), Path(output).resolve()
    if output.is_relative_to(directory) or output.exists():
        raise Step2Error('Compatibility evidence must be a new file outside the frozen index')
    evidence = _evidence(directory, baseline_source, snapshot_manifest)
    write_json(output, evidence)
    return evidence


def verify_index_compatibility(index_dir, compatibility):
    """Recheck every premise, including the exact current/baseline source pair."""
    path = Path(compatibility).resolve()
    report = read_json(path)
    if report.get('schema') != SCHEMA:
        raise Step2Error('Unsupported index compatibility evidence')
    expected = _evidence(index_dir, report['baseline_source'], report['snapshot_manifest'])
    if report != expected:
        raise Step2Error('Index compatibility evidence does not match the exact current sources/index')
    return {'report_sha256': digest(path.read_bytes()), 'evidence': report}
