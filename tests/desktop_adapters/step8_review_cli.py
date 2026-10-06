"""Exact CLI replay candidate; HTTP case retirements need explicit review.

Review #35 group B authorizes building the prompt client, not retiring its cases.
Every original assertion is frozen here; excluded HTTP-only tests are proposals,
and this candidate must not be counted as a restored whole suite yet.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from scripts.maintenance.fixture_corpus import register_module as _register_module

SOURCE_PATH = "tests/test_campaign_cli_coverage.py"
SOURCE_SHA256 = "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"
CORPUS_SELECTIONS = {"test_campaign_cli_coverage": None}
CORPUS_EXCLUSIONS = {"test_campaign_cli_coverage": [
    {"case": "test_piped_prompt_and_environment_build_real_authenticated_request",
     "reviewer": "Pending explicit CLI case-level approval",
     "reason": "Retired case: HTTP URL/header/request-data construction; "
               "desktop prompt uses authenticated local IPC.",
     "source_path": "tests/test_campaign_cli_coverage.py",
     "source_sha256": "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"},
    {"case": "test_transport_failure_is_nonzero_even_in_json_mode",
     "reviewer": "Pending explicit CLI case-level approval",
     "reason": "Retired case: HTTP transport error handling; "
               "desktop prompt uses authenticated local IPC.",
     "source_path": "tests/test_campaign_cli_coverage.py",
     "source_sha256": "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"},
]}
SETUP_HUNKS = [
    (19, 4, "b4f4214a88955ad6c5c1e0a0676005a5a1315a13bb1fc0e4e46f2ed891dd1b1f",
     "monkeypatch.setattr(cli.local_client.LocalClient, 'connect', transport)"),
    (70, 4, "650953cd53bc04a1878232f1c8766f9de6e889aed0c47cbd944db257068e3c98",
     "monkeypatch.setattr(cli.local_client.LocalClient, 'connect', network)"),
]


def _paths(node, path=()):
    yield path, node
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, ast.AST):
                    yield from _paths(child, (*path, field, index))
        elif isinstance(value, ast.AST):
            yield from _paths(value, (*path, field))


def _put(tree, path, value):
    target = tree
    for part in path[:-1]:
        target = target[part] if isinstance(part, int) else getattr(target, part)
    if isinstance(path[-1], int):
        target[path[-1]] = value
    else:
        setattr(target, path[-1], value)


def adapt(source, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("CLI frozen bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    rules = SETUP_HUNKS if hunks is None else hunks
    if len({(r[0], r[1], r[2]) for r in rules}) != len(rules):
        raise ValueError("CLI duplicate setup hunk")
    if rules != SETUP_HUNKS:
        raise ValueError("CLI exact admitted setup allowlist changed")
    replay = []
    for line, column, digest, replacement in rules:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and hashlib.sha256(dump(n).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("CLI setup must match exactly once")
        path, node = matches[0]
        _put(tree, path, ast.copy_location(ast.parse(replacement).body[0], node))
        replay.append((path, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("CLI assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for path, node in replay:
        _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("CLI complete AST reverse replay failed")
    return original, tree


def register_module(namespace, module, *, prefix, excluded):
    """Export every original case except the exact proposed HTTP-only pins.

    The executed original module and complete verified AST remain intact. Only
    pytest export is projected, using the unchanged shared discovery rebasing.
    """
    expected = [item["case"] for item in
                CORPUS_EXCLUSIONS.get("test_campaign_cli_coverage", ())]
    if excluded != expected or len(set(excluded)) != len(excluded):
        raise ValueError("CLI exact proposed retirement projection changed")
    exported = ModuleType(module.__name__ + "_export")
    exported.__dict__.update({name: value for name, value in vars(module).items()
                              if name not in excluded})
    _register_module(namespace, exported, prefix=prefix)


def load(namespace):
    stem = "test_campaign_cli_coverage"
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_review_cli")
    module.__file__ = SOURCE_PATH
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    register_module(namespace, module, prefix="step8_review_cli",
                    excluded=[item["case"] for item in CORPUS_EXCLUSIONS.get(stem, ())])
    return original, tree
