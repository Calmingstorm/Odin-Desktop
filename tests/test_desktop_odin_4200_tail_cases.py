"""Odin 4.20.0 (PR #671) in Desktop: two frozen tail cases with Odin's exact edit.

Odin 4.20.0 offers no continuation cursor once a preview delivered every retained byte, so it
edited one statement in each of these frozen cases of tests/test_process_tail_correctness.py:
the cursor read from the preview becomes an assertion that there is none, plus an explicit
head cursor. Here each case is the runtime-D adapter's frozen case (the same setup hunks and
environment) with exactly that edit. The unedited cases are retired in
tests/desktop_adapters/step8_runtime_d.py.
"""
from __future__ import annotations

import ast
import copy
from types import ModuleType

import pytest

from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters import step8_runtime_d as runtime_d

STEM = "test_process_tail_correctness"
EDITED = (
    "test_partial_quota_records_loss_and_uses_complete_memory_tail",
    "test_remote_incomplete_spool_uses_complete_tail_or_withholds",
)
# Odin 4.20.0's edit, verbatim (its comment line is not part of the syntax tree).
FROZEN_STATEMENT = 'prefix = json.loads(await delivered(ex, info, cursor=meta["cursor"]))'
ODIN_4200_STATEMENTS = (
    'assert meta["truncated"] is False and meta["cursor"] is None\n'
    'prefix = json.loads(await delivered(ex, info, cursor=f"{info.generation}:0"))\n'
)


def _edit(function: ast.AsyncFunctionDef) -> int:
    """Replace the frozen statement with Odin's two; the number of replacements made."""
    target = ast.dump(ast.parse(FROZEN_STATEMENT).body[0])
    replacements = 0
    for node in ast.walk(function):
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if not isinstance(statements, list):
                continue
            for index, statement in enumerate(statements):
                if isinstance(statement, ast.stmt) and ast.dump(statement) == target:
                    new = copy.deepcopy(ast.parse(ODIN_4200_STATEMENTS).body)
                    for added in new:
                        ast.copy_location(added, statement)
                    statements[index:index + 1] = new
                    replacements += 1
                    break
    return replacements


def odin_4200_module():
    """The runtime-D frozen tail suite with Odin 4.20.0's edit in its two superseded cases."""
    _original, tree = runtime_d.transform(STEM)
    tree = copy.deepcopy(tree)
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.AsyncFunctionDef) and node.name in EDITED}
    if sorted(functions) != sorted(EDITED):
        raise ValueError("the superseded frozen cases are missing")
    for name, function in functions.items():
        if _edit(function) != 1:
            raise ValueError(f"Odin 4.20.0's edit must apply exactly once in {name}")
    ast.fix_missing_locations(tree)
    module = ModuleType(f"odin_4200_{STEM}")
    module.__dict__.update(KnowledgeCommandClient=runtime_d.KnowledgeCommandClient,
                           owner_id=runtime_d.owner_id)
    exec(compile(tree, f"tests/{STEM}.py", "exec"), module.__dict__)
    return module


_module = odin_4200_module()
no_background = _module.no_background  # the frozen suite's own autouse fixture


@pytest.fixture(autouse=True)
def _temporary_runtime_d_owner(tmp_path):
    with runtime_d.runtime_owner(tmp_path):
        yield


test_odin_4200_partial_quota_records_loss_and_uses_complete_memory_tail = getattr(
    _module, EDITED[0])
test_odin_4200_remote_incomplete_spool_uses_complete_tail_or_withholds = getattr(
    _module, EDITED[1])
for _case in (test_odin_4200_partial_quota_records_loss_and_uses_complete_memory_tail,
              test_odin_4200_remote_incomplete_spool_uses_complete_tail_or_withholds):
    _case.__module__ = __name__


def _simple_statements(function) -> list[str]:
    return [ast.dump(node) for node in ast.walk(function)
            if isinstance(node, ast.stmt) and not hasattr(node, "body")]


def test_only_the_reviewed_statement_differs_from_the_frozen_cases():
    _original, frozen = runtime_d.transform(STEM)
    target = ast.dump(ast.parse(FROZEN_STATEMENT).body[0])
    added = [ast.dump(statement) for statement in ast.parse(ODIN_4200_STATEMENTS).body]
    for name in EDITED:
        before = next(node for node in frozen.body
                      if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
        after = copy.deepcopy(before)
        assert _edit(after) == 1
        assert _simple_statements(before).count(target) == 1
        expected = []
        for dumped in _simple_statements(before):
            expected.extend(added if dumped == target else [dumped])
        assert _simple_statements(after) == expected
        assert "truncated" in getattr(_module, name).__code__.co_consts  # the edited code runs


def test_the_tail_retirements_are_exactly_the_reviewed_ones():
    from scripts.maintenance import phase2_suites as checker

    path, sha = f"tests/{STEM}.py", runtime_d.SUITES[STEM]
    rows = runtime_d.CORPUS_EXCLUSIONS[STEM]
    assert [row["case"] for row in rows] == list(EDITED)
    assert checker._case_retirements(checker.ROOT, path, sha, rows)
    widened = [*rows, dict(rows[0], case="test_partial_quota_records_loss_before_eof")]
    assert not checker._case_retirements(checker.ROOT, path, sha, widened)
    other_authority = [dict(row, reviewer=checker.ODIN_4192_REVIEWER) for row in rows]
    assert not checker._case_retirements(checker.ROOT, path, sha, other_authority)
    namespace = {"__name__": "odin_4200_tail_probe"}
    original, _tree, _module = runtime_d.load(namespace)[STEM]
    exported = sorted(key[len("test_process_tail_correctness_"):] for key in namespace
                      if key.startswith("test_process_tail_correctness_"))
    inherited = sorted({case for case, _, _ in corpus(original)["cases"]})
    assert set(EDITED) <= set(inherited)
    assert exported == sorted(case[5:] for case in inherited if case not in EDITED)
