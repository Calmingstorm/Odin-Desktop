"""Actual Codex matrix restoration: Claude, review of #35, round 2.

All retained assertions execute through real strict compilation, SSE and replay.
Five removed-by-design builtin rows retire at case level; read_conversation joins.
"""
from __future__ import annotations

import ast
import copy
import json

import pytest

from tests.desktop_adapters import step8_review_codex as candidate

FROZEN, ORIGINAL, ADAPTED = candidate.load(globals())


def test_whole_source_corpus_and_reverse_replay_are_pinned():
    assert candidate.verify(ORIGINAL, ADAPTED)
    record = candidate.evidence(FROZEN, ORIGINAL, ADAPTED)
    assert record["corpus_equal"]
    assert record["complete_reverse_replay"]
    assert record["static_test_definitions"] == 3
    assert record["static_assertions"] == 22
    assert candidate.CORPUS_SELECTIONS == {"test_codex_replay_matrix": None}
    assert candidate.CORPUS_EXCLUSIONS == {}
    assert candidate.PARAMETER_RETIREMENTS == {"test_codex_replay_matrix": {
        "test_emitted_replayed_matrix": ["builtin-" + name for name in sorted(candidate.REMOVED)],
    }}
    assert record["original_matrix_cases"] == 147
    assert record["matrix_cases"] == 143
    assert record["retained_original_executions"] == 287
    assert record["retired_original_executions"] == 10
    assert record["added_executions"] == 2
    assert record["builtin_fixture_count"] == record["documentation_catalog_count"] == 63
    assert record["missing_from_documentation"] == record["missing_from_frozen_inputs"] == []
    assert record["missing_schema_case_labels"] == []
    print("CODEX_CANDIDATE_EVIDENCE", json.dumps(record, sort_keys=True))


def test_changed_frozen_bytes_are_rejected():
    from scripts.maintenance.fixture_corpus import frozen_source

    with pytest.raises(ValueError, match="frozen source bytes changed"):
        candidate.adapt(frozen_source(candidate.PATH) + b"\n")


@pytest.mark.parametrize("hunks", [(), candidate.SETUP_HUNKS * 2, (
    (22, 0, candidate.BEFORE_SHA256, candidate.AFTER_SHA256,
     "from src.tools.registry import get_tool_definitions"),
)])
def test_missing_duplicate_or_wrong_hunks_are_rejected(hunks):
    with pytest.raises(ValueError, match="exact admitted allowlist"):
        candidate.adapt(hunks=hunks)


@pytest.mark.parametrize("kind", ["assertion", "signature", "decorator", "parameter"])
def test_original_assertion_signature_decorator_parameter_mutations_are_rejected(kind):
    tree = copy.deepcopy(ADAPTED)
    tests = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
             and n.name == "test_emitted_replayed_matrix"]
    assert len(tests) == 1
    test = tests[0]
    if kind == "assertion":
        next(n for n in ast.walk(test) if isinstance(n, ast.Assert)).test = ast.Constant(True)
    elif kind == "signature":
        test.args.args[0].arg = "different_adapter"
    elif kind == "decorator":
        test.decorator_list.pop()
    else:
        test.decorator_list[1].args[1] = ast.List(elts=[ast.Constant("chat")], ctx=ast.Load())
    with pytest.raises(ValueError, match="corpus drift"):
        candidate.verify(ORIGINAL, tree)


def test_noncorpus_matrix_constructor_change_is_rejected_by_whole_reverse_replay():
    tree = copy.deepcopy(ADAPTED)
    inputs = next(n for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "BUILTIN_INPUTS"
                          for t in n.targets))
    inputs.value.keys.pop()
    inputs.value.values.pop()
    with pytest.raises(ValueError, match="exact approved input matrix hash mismatch"):
        candidate.verify(ORIGINAL, tree)


def test_changed_adapted_import_hash_is_rejected():
    tree = copy.deepcopy(ADAPTED)
    node = next(n for n in tree.body if isinstance(n, ast.ImportFrom)
                and n.module == "src.tools.registry")
    node.names[0].name = "get_tool_definitions"
    with pytest.raises(ValueError, match="adapted setup hunk hash mismatch"):
        candidate.verify(ORIGINAL, tree)


@pytest.mark.parametrize("kind", ["retained-value", "new-value", "restored-retired", "extra-row"])
def test_only_reviewed_case_level_matrix_dispositions_are_allowed(kind):
    tree = copy.deepcopy(ADAPTED)
    _, inputs = candidate._matrix(tree, candidate.MATRIX_AFTER_SHA256)
    if kind == "retained-value":
        inputs.value.values[0] = ast.Dict(keys=[], values=[])
    elif kind == "new-value":
        inputs.value.values[-1] = ast.parse('{"limit": 11}', mode="eval").body
    else:
        key = "read_channel" if kind == "restored-retired" else "invented"
        inputs.value.keys.append(ast.Constant(key))
        inputs.value.values.append(ast.Dict(keys=[], values=[]))
    with pytest.raises(ValueError, match="exact approved input matrix hash mismatch"):
        candidate.verify(ORIGINAL, tree)


@pytest.mark.parametrize("name", sorted(candidate.REMOVED))
def test_retired_rows_absent_and_new_real_input_present(name):
    assert name not in FROZEN.BUILTIN_INPUTS
    assert not any(c.name == name for c in FROZEN.CASES)
    new = next(c for c in FROZEN.CASES if c.label == "builtin-read_conversation")
    assert new.name == "read_conversation"
    assert new.supplied == new.expected == {"limit": 10}
    assert not new.error and new.literal is None


def test_equality_assertion_cannot_be_weakened():
    tree = copy.deepcopy(ADAPTED)
    test = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "test_matrix_covers_real_served_catalog_and_computer_operations")
    test.body[0].test.ops = [ast.LtE()]
    with pytest.raises(ValueError, match="corpus drift"):
        candidate.verify(ORIGINAL, tree)


def test_unapproved_helper_change_is_rejected_by_complete_reverse_replay():
    tree = copy.deepcopy(ADAPTED)
    helper = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_encoded_inputs")
    helper.body[-1].value = ast.Dict(keys=[], values=[])
    with pytest.raises(ValueError, match="complete AST reverse replay failed"):
        candidate.verify(ORIGINAL, tree)
