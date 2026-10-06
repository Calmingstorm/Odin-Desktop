"""Exact frozen computer fixtures, with no manufactured foreground grant."""
# ruff: noqa: E501

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import tempfile
from types import ModuleType

from scripts.maintenance.fixture_corpus import (
    ROOT,
    corpus,
    digest,
    dump,
    frozen_source,
    nodes,
    register_module,
)
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths

RECORD = ROOT / "maintenance/step8-part4-computer-candidates.json"
MODULES = {}
PROOFS = {}
CORPUS_SELECTIONS = {
    'test_computer_lifecycle_review_r5': None,
    'test_computer_provisioning_r29': None,
    'test_computer_wayland_config_r8': None,
    'test_computer_identity_sequences_r21': None,
    'test_computer_sequence_injection_r21': None,
    'test_computer_admission_http_r8': None,
    'test_computer_product_status_r11': None,
    'test_computer_scope_readiness_r13': None,
    'test_computer_resources_r21': None,
    'test_round40_reviewer': None,
}
SUITES = {
    'test_computer_catalog': 'f69e52a4ac9043ff3a9f70cf0cbe8de1134c035a65b83c93aa8ed59bd6f5da7f',
    'test_computer_lifecycle_review_r5': '0ef699d85ce2777534041cf8a02f35d849a86d9fe9e5ba3fdaffbec49bfcd572',
    'test_computer_provisioning_r29': '7c87c683ff57c163749534fb114e869a8414ca3d679d9e6c75015a2e854ec92b',
    'test_computer_wayland_config_r8': '9805950ec34b39f95250034c1389c660e7e660a5443d3ffd44432ae25fe3218f',
    'test_computer_identity_sequences_r21': '3ce2e7d22070ce4c670b3ba58a8f17871b4fbfffd355273cd9a9dad62055ed7b',
    'test_computer_sequence_injection_r21': 'e8cf8cbdaf2d417110b59044585c92282ff17370c412387587b4a34b362eb05f',
    'test_computer_admission_http_r8': '628f4a155305880114e49a8f43654999da787dcac9f250af99b7bb4914431d94',
    'test_computer_product_status_r11': '550799804cd6fbb4c3334d2e5c3570971edf93bb1762d1215c88ea8f8f0f40bb',
    'test_computer_scope_readiness_r13': 'f3c4f80c1d8aafa864c1781355698f17cb03228f72b759cf1ee8430e996c646b',
    'test_computer_resources_r21': 'd4680ea395e2a6359f70be870df3cafe69bae6df064119daab10d41c6485fa00',
    'test_round40_reviewer': '93148dd08a347b3ac078ea19347c41a9a3b401694c3561eebd6b60bac4369c57',
}
CORPUS_EXCLUSIONS = {
    'test_computer_admission_http_r8': [
        {'case':'test_http_attached_has_no_application_allowlist','reviewer':'Claude, review of step 8 part 4','reason':'Removed Odin web UI HTTP GET /api/computer application-profile projection.','source_path':'tests/test_computer_admission_http_r8.py','source_sha256':'628f4a155305880114e49a8f43654999da787dcac9f250af99b7bb4914431d94'},
        {'case':'test_http_exposes_bounded_reason_and_remedy_with_actual_auth','reviewer':'Claude, review of step 8 part 4','reason':'Removed Odin web UI HTTP GET /api/computer bearer-authenticated admission projection.','source_path':'tests/test_computer_admission_http_r8.py','source_sha256':'628f4a155305880114e49a8f43654999da787dcac9f250af99b7bb4914431d94'}
    ],
    'test_computer_product_status_r11': [
        {'case':'test_attached_http_omits_invalid_provenance_and_unknown_capabilities','reviewer':'Claude, review of step 8 part 4','reason':'Removed Odin web UI HTTP GET /api/computer provenance projection.','source_path':'tests/test_computer_product_status_r11.py','source_sha256':'550799804cd6fbb4c3334d2e5c3570971edf93bb1762d1215c88ea8f8f0f40bb'},
        {'case':'test_attached_http_provenance_capabilities_and_public_null_app','reviewer':'Claude, review of step 8 part 4','reason':'Removed Odin web UI HTTP GET /api/computer attached status projection.','source_path':'tests/test_computer_product_status_r11.py','source_sha256':'550799804cd6fbb4c3334d2e5c3570971edf93bb1762d1215c88ea8f8f0f40bb'},
        {'case':'test_http_retains_isolated_fixed_launch_list_and_capability_fallback','reviewer':'Claude, review of step 8 part 4','reason':'Removed Odin web UI HTTP GET /api/computer isolated launch-list projection.','source_path':'tests/test_computer_product_status_r11.py','source_sha256':'550799804cd6fbb4c3334d2e5c3570971edf93bb1762d1215c88ea8f8f0f40bb'}
    ],
    'test_computer_scope_readiness_r13': [
        {'case':'test_http_retains_only_known_scope_failure_reasons','reviewer':'Claude, review of step 8 part 4','reason':'Removed Odin web UI HTTP GET /api/computer bearer-authenticated scope diagnostic projection.','source_path':'tests/test_computer_scope_readiness_r13.py','source_sha256':'f3c4f80c1d8aafa864c1781355698f17cb03228f72b759cf1ee8430e996c646b'}
    ]
}
_HOME = tempfile.TemporaryDirectory(prefix='step8-computer-owner-')
_AUTHORITY = OwnerAuthority(ProfilePaths.from_xdg(home=_HOME.name, environ={}))
_OWNER = _AUTHORITY.authenticate_local(peer_uid=os.geteuid())


def desktop_owner_id():
    return _OWNER.owner_id


def desktop_authorize(context):
    return _AUTHORITY.accepts(_OWNER) and context.owner_id == _OWNER.owner_id


def _closure(tree, selected):
    """Keep exact declarations transitively referenced by selected definitions."""
    declarations = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            declarations[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for child in ast.walk(target):
                    if isinstance(child, ast.Name):
                        declarations[child.id] = node
    needed = set(selected)
    while True:
        referenced = {
            n.id for key in needed if key in declarations
            for n in ast.walk(declarations[key]) if isinstance(n, ast.Name)
        }
        expanded = needed | referenced
        if expanded == needed:
            break
        needed = expanded
    result = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            aliases = [a for a in node.names if (a.asname or a.name.split('.')[0]) in needed]
            if aliases or (isinstance(node, ast.ImportFrom) and node.module == '__future__'):
                retained = copy.deepcopy(node)
                retained.names = aliases or node.names
                result.append(retained)
        elif any(node is declarations.get(key) for key in needed):
            result.append(node)
    return result


def adapt(name, *, helper_symbols=None):
    records = json.loads(RECORD.read_text())
    path = f"tests/{name}.py"
    row = next((r for r in records['suites'] if r['path'] == path), None)
    if row is None and helper_symbols is None:
        raise ValueError('Unaudited computer suite')
    source = frozen_source(path)
    if name in SUITES and hashlib.sha256(source).hexdigest() != SUITES[name]:
        raise ValueError('Frozen inherited source hash changed')
    original = ast.parse(source, filename=path)
    tree = copy.deepcopy(original)
    changes = []

    class Setup(ast.NodeTransformer):
        def visit_Assert(self, node):
            return node

        def visit_FunctionDef(self, node):
            node.body = [self.visit(n) for n in node.body]
            return node

        def visit_AsyncFunctionDef(self, node):
            return self.visit_FunctionDef(node)

        def visit_ImportFrom(self, node):
            if not node.module or not node.module.startswith('tests.test_'):
                return node
            if node.module == 'tests.test_computer_contract_r1' and all(a.name == 'Stub' for a in node.names):
                return node
            before = copy.deepcopy(node)
            helper = node.module.rsplit('.', 1)[1]
            node.module = __name__
            node.names = [ast.alias(name=helper + '__' + a.name, asname=a.asname or a.name) for a in node.names]
            changes.append((before, copy.deepcopy(node)))
            return node

        def visit_Call(self, node):
            self.generic_visit(node)
            before = copy.deepcopy(node)
            if isinstance(node.func, ast.Name) and node.func.id == 'RequestContext':
                if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in {'owner', 'o', 'alice'}:
                    node.args[0] = ast.parse('desktop_owner_id()', mode='eval').body
                if not any(k.arg == 'surface' for k in node.keywords):
                    if len(node.args) != 4 or any(k.arg is None for k in node.keywords):
                        raise ValueError('Unexpected context fixture signature')
                    node.keywords.append(ast.keyword(arg='surface', value=ast.Constant('desktop')))
            if isinstance(node.func, ast.Name) and node.func.id == 'ComputerController':
                if len(node.args) >= 3 and isinstance(node.args[2], ast.Lambda) and isinstance(node.args[2].body, ast.Constant) and node.args[2].body.value is True:
                    node.args[2] = ast.Name(id='desktop_authorize', ctx=ast.Load())
            if isinstance(node.func, ast.Name) and node.func.id == 'Config':
                node.keywords = [k for k in node.keywords if k.arg != 'discord']
            if dump(before) != dump(node):
                changes.append((before, copy.deepcopy(node)))
            return node

    tree = Setup().visit(tree)
    if corpus(original) != corpus(tree):
        raise ValueError('Frozen assertion/signature/decorator/parameter corpus changed')
    reverse = copy.deepcopy(tree)
    for before, after in reversed(changes):
        matches = [n for _, n in nodes(reverse)
                   if getattr(n, 'lineno', None) == after.lineno and dump(n) == dump(after)]
        if len(matches) != 1:
            raise ValueError('Exact setup reverse hunk must match once')
        target = matches[0]

        class Reverse(ast.NodeTransformer):
            def visit(self, node):
                return copy.deepcopy(before) if node is target else super().visit(node)

        reverse = Reverse().visit(reverse)
    if dump(reverse) != dump(original):
        raise ValueError('Whole tree reverse replay differs')
    selected = helper_symbols if helper_symbols is not None else row['selected_symbols']
    if selected is None:
        selected = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and (n.name.startswith('test_') or n.name.startswith('Test'))]
    selected_tree = ast.Module(body=_closure(tree, selected), type_ignores=[])
    symbols = {id(n): s for s, n in nodes(original)}
    edits = []
    for before, after in changes:
        match = [n for _, n in nodes(original)
                 if getattr(n, 'lineno', None) == before.lineno and dump(n) == dump(before)]
        if len(match) != 1:
            raise ValueError('Exact setup source hunk must match once')
        edits.append({'line': before.lineno, 'symbol': symbols[id(match[0])],
                      'kind': 'expression' if isinstance(after, ast.expr) else 'statement',
                      'before_sha256': digest(dump(before).encode()),
                      'after_sha256': digest((dump(after) if isinstance(after, ast.expr) else json.dumps([dump(after)])).encode()),
                      'after_source': ast.unparse(after)})
    proof = {'path': path, 'source_sha256': digest(source),
             'original_ast_sha256': digest(dump(original).encode()),
             'adapted_ast_sha256': digest(dump(tree).encode()),
             'selected_ast_sha256': digest(dump(selected_tree).encode()),
             'corpus_sha256': digest(str(corpus(original)).encode()),
             'whole_tree_reverse_replay': True, 'transformations': edits,
             'selected_symbols': selected, 'helper_only': helper_symbols is not None}
    key = path if helper_symbols is None else path + ':' + ','.join(sorted(selected))
    PROOFS[key] = proof
    if row is not None and helper_symbols is None and row.get('proof_sha256'):
        if row['proof_sha256'] != digest(json.dumps(proof, sort_keys=True).encode()):
            raise ValueError('Computer selection/setup differs from pinned proof')
    return ast.fix_missing_locations(selected_tree)


def load(name, symbols=None):
    if isinstance(name, dict):
        export(name)
        return None
    key = name, tuple(sorted(symbols)) if symbols is not None else None
    if key not in MODULES:
        tree = adapt(name, helper_symbols=symbols)
        module = ModuleType('desktop_step8_6a_' + name)
        module.__file__ = str(ROOT / f'tests/{name}.py')
        module.desktop_owner_id = desktop_owner_id
        module.desktop_authorize = desktop_authorize
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == __name__:
                groups = {}
                for alias in node.names:
                    helper, symbol = alias.name.split('__', 1)
                    groups.setdefault(helper, []).append(symbol)
                for helper, group in groups.items():
                    loaded = load(helper, group)
                    for symbol in group:
                        globals()[helper + '__' + symbol] = getattr(loaded, symbol)
        exec(compile(tree, module.__file__, 'exec'), module.__dict__)
        MODULES[key] = module
    return MODULES[key]


def __getattr__(name):
    if name.startswith('test_') and '__' in name:
        helper, symbol = name.split('__', 1)
        return getattr(load(helper, [symbol]), symbol)
    raise AttributeError(name)


def export(namespace):
    for row in json.loads(RECORD.read_text())['suites']:
        if row['selected_symbols'] == []:
            continue
        name = row['path'].rsplit('/', 1)[1][:-3]
        module = load(name)
        if name in CORPUS_SELECTIONS:
            for key, value in vars(module).items():
                if type(value).__name__ == 'FixtureFunctionDefinition':
                    namespace[key] = value
            register_module(namespace, module, prefix=name, full_class_name=True,
                            excluded=[item['case'] for item in CORPUS_EXCLUSIONS.get(name, ())])
            continue
        members = {'__module__': namespace['__name__']}
        for key, value in vars(module).items():
            if key.startswith('test_') or type(value).__name__ == 'FixtureFunctionDefinition':
                members[key] = staticmethod(value)
            elif isinstance(value, type) and key.startswith('Test'):
                namespace['Test_' + name + '_' + key] = value
        if len(members) > 1:
            namespace['Test_' + name] = type('Test_' + name, (), members)
