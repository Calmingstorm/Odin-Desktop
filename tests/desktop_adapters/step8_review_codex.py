"""Whole frozen replay matrix, with only the documentation import adapted.

This is not a readiness publication or a synthetic historical catalog. The
unchanged catalog assertion refuses restoration when desktop schemas differ.
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
CORPUS_SELECTIONS = {"test_codex_replay_matrix": None}
CORPUS_EXCLUSIONS = {}


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


def verify(original, adapted):
    """Independently reverse the only allowed hunk over the complete AST."""
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
    """Machine-readable complete corpus and catalog mismatch, never authority."""
    inherited = corpus(original)
    expected = set(module.BUILTIN_INPUTS)
    documentation = {tool["name"] for tool in module.get_tool_definitions()}
    cases = module.CASES
    return {
        "path": PATH,
        "source_sha256": SOURCE_SHA256,
        "original_ast_sha256": digest(dump(original).encode()),
        "adapted_ast_sha256": digest(dump(tree).encode()),
        "corpus_sha256": digest(json.dumps(inherited, sort_keys=True).encode()),
        "assertions_sha256": digest(json.dumps(inherited["assertions"]).encode()),
        "static_test_definitions": len(inherited["cases"]),
        "static_assertions": len(inherited["assertions"]),
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
