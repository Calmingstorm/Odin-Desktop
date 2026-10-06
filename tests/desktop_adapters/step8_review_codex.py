"""Frozen replay restoration approved by Claude, review of #35, round 2.

Only the documentation import and five retired/one added builtin rows change.
The catalog equality assertion and every other assertion remain unchanged.
No tool handler, live endpoint, desktop input or owner admission is involved.
"""
# ruff: noqa: E501
from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module

PATH = "tests/test_codex_replay_matrix.py"
SOURCE_SHA256 = "eed93185f30efd619bafbfb1fd0f2d7bcac1eda96879b50214cfc1f8f5585256"
BEFORE_SHA256 = "42e493c48ee7f8eadebcd6df64c7d0ee3371ea61bbd739a85869855d7f404126"
AFTER_SHA256 = "d4c875dc0b31819aaca8ed6cb0f5fec4fc99df5b984b5b28d4c5154649a8cf6b"
AFTER_SOURCE = (
    "from src.tools.registry import "
    "get_documentation_tool_definitions as get_tool_definitions"
)
SETUP_HUNKS = ((22, 0, BEFORE_SHA256, AFTER_SHA256, AFTER_SOURCE),)
REVIEW_AUTHORITY = "Claude, review of #35, round 2"
REMOVED = frozenset({"purge_messages", "set_permission", "read_channel", "add_reaction", "create_poll"})
NEW_INPUT = {"limit": 10}
MATRIX_BEFORE_SHA256 = "96af24f8e2b4f7d499fa0c8c7f0b8fa77600552871bc1109b85169e8ae736c43"
MATRIX_AFTER_SHA256 = "d30aab0dda7d38794e57b66636795ab8e58b59f1af0510b94a7578db3372e203"
CORPUS_SELECTIONS = {"test_codex_replay_matrix": None}
CORPUS_EXCLUSIONS = {}
PARAMETER_RETIREMENTS = {
    "test_codex_replay_matrix": {
        "test_emitted_replayed_matrix": [
            "builtin-add_reaction", "builtin-create_poll", "builtin-purge_messages",
            "builtin-read_channel", "builtin-set_permission",
        ],
    },
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _paths(node, path=()):
    yield path, node
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, ast.AST):
                    yield from _paths(child, (*path, field, index))
        elif isinstance(value, ast.AST):
            yield from _paths(value, (*path, field))


def _put(tree, path, replacement):
    target = tree
    for part in path[:-1]:
        target = target[part] if isinstance(part, int) else getattr(target, part)
    if isinstance(path[-1], int):
        target[path[-1]] = replacement
    else:
        setattr(target, path[-1], replacement)


def _matrix(tree, expected_hash):
    matches = [(p, n) for p, n in _paths(tree)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "BUILTIN_INPUTS" for t in n.targets)]
    if len(matches) != 1 or digest(dump(matches[0][1]).encode()) != expected_hash:
        raise ValueError("Codex exact approved input matrix hash mismatch")
    return matches[0]


def _desktop_matrix(original):
    _, before = _matrix(original, MATRIX_BEFORE_SHA256)
    after = copy.deepcopy(before)
    pairs = [(k, v) for k, v in zip(after.value.keys, after.value.values, strict=True)
             if ast.literal_eval(k) not in REMOVED]
    after.value.keys = [k for k, _ in pairs] + [ast.Constant("read_conversation")]
    after.value.values = [v for _, v in pairs] + [ast.parse(repr(NEW_INPUT), mode="eval").body]
    if digest(dump(after).encode()) != MATRIX_AFTER_SHA256:
        raise ValueError("Codex exact approved input matrix hash mismatch")
    return after


def verify(original, adapted):
    """Reverse both exact approved deltas, protecting every other source node."""
    if corpus(original) != corpus(adapted):
        raise ValueError("Codex assertion/signature/decorator/parameter corpus drift")
    matches = [(p, n) for p, n in _paths(original)
               if getattr(n, "lineno", None) == 22
               and getattr(n, "col_offset", None) == 0
               and digest(dump(n).encode()) == BEFORE_SHA256]
    if len(matches) != 1:
        raise ValueError("Codex original setup hunk must match exactly once")
    path, before = matches[0]
    matches = [(p, n) for p, n in _paths(adapted)
               if p == path and digest(dump(n).encode()) == AFTER_SHA256]
    if len(matches) != 1:
        raise ValueError("Codex adapted setup hunk hash mismatch")
    restored = copy.deepcopy(adapted)
    _put(restored, path, copy.deepcopy(before))
    matrix_path, matrix_before = _matrix(original, MATRIX_BEFORE_SHA256)
    adapted_path, matrix_after = _matrix(adapted, MATRIX_AFTER_SHA256)
    if adapted_path != matrix_path or dump(matrix_after) != dump(_desktop_matrix(original)):
        raise ValueError("Codex exact approved input matrix hash mismatch")
    _put(restored, matrix_path, copy.deepcopy(matrix_before))
    if dump(restored) != dump(original):
        raise ValueError("Codex complete AST reverse replay failed")
    return True


def adapt(source=None, *, hunks=SETUP_HUNKS):
    source = frozen_source(PATH) if source is None else source
    if digest(source) != SOURCE_SHA256:
        raise ValueError("Codex frozen source bytes changed")
    if hunks != SETUP_HUNKS:
        raise ValueError("Codex setup hunks differ from exact admitted allowlist")
    original = ast.parse(source, filename=PATH)
    tree = copy.deepcopy(original)
    for line, column, before_hash, after_hash, replacement in hunks:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and digest(dump(n).encode()) == before_hash]
        if len(matches) != 1:
            raise ValueError("Codex setup hunk must match exactly once")
        path, before = matches[0]
        after = ast.parse(replacement).body[0]
        if digest(dump(after).encode()) != after_hash:
            raise ValueError("Codex replacement hunk hash mismatch")
        _put(tree, path, ast.copy_location(after, before))
    matrix_path, matrix_before = _matrix(original, MATRIX_BEFORE_SHA256)
    _put(tree, matrix_path, ast.copy_location(_desktop_matrix(original), matrix_before))
    ast.fix_missing_locations(tree)
    verify(original, tree)
    return original, tree


def load(namespace):
    original, tree = adapt()
    module = ModuleType("step8_review_codex_frozen_test_codex_replay_matrix")
    module.__file__ = PATH
    # dataclass's lookup requires its defining module to exist in sys.modules.
    sys.modules[module.__name__] = module
    try:
        exec(compile(tree, PATH, "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(module.__name__, None)
        raise
    module.adapter.__module__ = namespace["__name__"]
    namespace["adapter"] = module.adapter
    register_module(namespace, module, prefix="test_codex_replay_matrix")
    return module, original, tree


def evidence(module, original, tree):
    """Exact case/parameter dispositions and preserved assertions, not qualification."""
    inherited = corpus(original)
    expected = set(module.BUILTIN_INPUTS)
    documentation = {tool["name"] for tool in module.get_tool_definitions()}
    cases = module.CASES
    _, original_matrix = _matrix(original, MATRIX_BEFORE_SHA256)
    original_inputs = eval(compile(ast.Expression(original_matrix.value), PATH, "eval"), module.__dict__)
    original_cases = [module._case("builtin-" + name, name, expected)
                      for name, expected in original_inputs.items()]
    original_cases.extend(c for c in cases if not c.label.startswith("builtin-"))
    dispositions = []
    for case in original_cases:
        retired = case.name in REMOVED
        dispositions.append({
            "label": case.label, "tool": case.name,
            "disposition": "retired" if retired else "retained",
            "reason": "removed-by-design Desktop tool" if retired else "unchanged case and assertions",
            "supplied": case.supplied, "expected": case.expected,
            "error": case.error, "literal": case.literal,
            "parameters": [{"path": path, "disposition": "retired" if retired else "retained"}
                           for path in ("chat", "agent")],
        })
    dispositions.append({
        "label": "builtin-read_conversation", "tool": "read_conversation", "disposition": "added",
        "reason": "real Desktop documentation-catalog input; strict normalization and exact SSE/history replay",
        "supplied": NEW_INPUT, "expected": NEW_INPUT, "error": False, "literal": None,
        "parameters": [{"path": path, "disposition": "added"} for path in ("chat", "agent")],
    })
    return {
        "path": PATH,
        "source_sha256": SOURCE_SHA256,
        "original_ast_sha256": digest(dump(original).encode()),
        "adapted_ast_sha256": digest(dump(tree).encode()),
        "corpus_sha256": digest(json.dumps(inherited, sort_keys=True).encode()),
        "assertions_sha256": digest(json.dumps(inherited["assertions"]).encode()),
        "static_test_definitions": len(inherited["cases"]),
        "static_assertions": len(inherited["assertions"]),
        "review_authority": REVIEW_AUTHORITY,
        "original_matrix_cases": len(original_cases),
        "original_executions": 2 * len(original_cases) + 3,
        "retained_original_executions": 2 * (len(original_cases) - len(REMOVED)) + 3,
        "retired_original_executions": 2 * len(REMOVED),
        "added_executions": 2,
        "documentation_catalog_names": sorted(documentation),
        "case_dispositions": dispositions,
        "non_matrix_parameter_dispositions": [
            {"test": "test_matrix_covers_real_served_catalog_and_computer_operations", "disposition": "retained"},
            *[{"test": "test_multi_call_order_and_duplicate_stream_events", "path": path,
               "disposition": "retained"} for path in ("chat", "agent")],
        ],
        "approved_matrix_delta": {
            "before_sha256": MATRIX_BEFORE_SHA256, "after_sha256": MATRIX_AFTER_SHA256,
            "retired_labels": ["builtin-" + name for name in sorted(REMOVED)],
            "added_label": "builtin-read_conversation", "added_input": NEW_INPUT,
            "equality_assertion_changed": False,
            "contract": "unchanged equality assertion compares 63 fixture names to real Desktop documentation catalog",
        },
        "matrix_cases": len(cases),
        "matrix_executions": 2 * len(cases),
        "multi_call_executions": 2,
        "catalog_guard_executions": 1,
        "builtin_fixture_count": len(expected),
        "documentation_catalog_count": len(documentation),
        "missing_from_documentation": sorted(expected - documentation),
        "missing_from_frozen_inputs": sorted(documentation - expected),
        "missing_schema_case_labels": [case.label for case in cases
                                       if case.name in expected - documentation],
        "case_labels_sha256": digest(json.dumps([c.label for c in cases]).encode()),
        "corpus_equal": corpus(tree) == inherited,
        "complete_reverse_replay": verify(original, tree),
        "setup_hunks": [{
            "symbol": "<module>", "line": rule[0], "column": rule[1],
            "operation": "documentation_catalog_import",
            "before_sha256": rule[2], "after_sha256": rule[3],
            "after_source": rule[4], "kind": "statement",
        } for rule in SETUP_HUNKS],
    }
