"""Executable loader safeguards, not restored original-case coverage."""
from __future__ import annotations

import ast
import copy

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump
from tests.desktop_adapters import step8_intake as candidate


@pytest.mark.parametrize("stem", tuple(candidate.SUITES))
def test_step8_intake_complete_frozen_ast(stem):
    original, adapted = candidate.prepare(stem)
    assert corpus(original) == corpus(adapted)
    assert dump(original) == dump(adapted)
    assert corpus(original)["cases"]


@pytest.mark.parametrize("stem", tuple(candidate.SUITES))
def test_step8_intake_blocked_loader_exports_nothing(stem):
    namespace = {"__name__": "blocked_intake_corpus"}
    before = dict(namespace)
    with pytest.raises(candidate.WholeSuiteBlockedError, match=".+"):
        candidate.load(namespace, stem)
    assert namespace == before


@pytest.mark.parametrize("stem", tuple(candidate.SUITES))
def test_step8_intake_rejects_source_hash_drift(stem, monkeypatch):
    source = candidate.frozen_source(f"tests/{stem}.py")
    monkeypatch.setattr(candidate, "frozen_source", lambda path: source + b"\n")
    with pytest.raises(ValueError, match="source hash"):
        candidate.prepare(stem)


@pytest.mark.parametrize("stem", tuple(candidate.SUITES))
def test_step8_intake_rejects_setup_drift(stem):
    original, _ = candidate.prepare(stem)
    changed = copy.deepcopy(original)
    changed.body.append(ast.parse("intake_setup_marker = 1").body[0])
    assert corpus(changed) == corpus(original)
    with pytest.raises(ValueError, match="setup AST"):
        candidate.prepare(stem, adapted=changed)


@pytest.mark.parametrize("kind", ["assertion", "signature", "decorator", "parameter"])
def test_step8_intake_rejects_case_contract_drift(kind):
    stem = "test_campaign_cli_coverage"
    original, _ = candidate.prepare(stem)
    changed = copy.deepcopy(original)
    test = next(n for n in changed.body if isinstance(n, ast.FunctionDef)
                and n.name.startswith("test_"))
    if kind == "assertion":
        next(n for n in ast.walk(test) if isinstance(n, ast.Assert)).test = ast.Constant(False)
    elif kind == "signature":
        test.args.args.append(ast.arg(arg="unapproved_fixture"))
    elif kind == "decorator":
        test.decorator_list.append(ast.Name(id="unapproved_marker", ctx=ast.Load()))
    else:
        test.decorator_list[0].args[1] = ast.List(elts=[ast.Constant(True)], ctx=ast.Load())
    with pytest.raises(ValueError, match="assertion/signature/decorator/parameter"):
        candidate.prepare(stem, adapted=changed)


def test_step8_intake_rejects_original_ast_drift():
    stem = "test_intake_pipeline"
    original, _ = candidate.prepare(stem)
    original.body.pop()
    with pytest.raises(ValueError, match="original AST"):
        candidate.prepare(stem, original=original)


def test_step8_intake_only_whole_suite_declarations():
    assert len(candidate.SUITES) == len(candidate.CORPUS_SELECTIONS) == 9
    assert all(v is None for v in candidate.CORPUS_SELECTIONS.values())
    assert candidate.CORPUS_EXCLUSIONS == candidate.SETUP_HUNKS == {}
    assert candidate.BLOCKERS.keys() == candidate.SUITES.keys()
    with pytest.raises(ValueError, match="Unassigned"):
        candidate.prepare("test_unassigned")
