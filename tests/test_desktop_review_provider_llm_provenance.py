"""Whole inherited seals and fail-closed mixed-suite accounting for PR34."""

import ast
import copy

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump
from tests.desktop_adapters import review_provider_llm as adapter


def test_whole_frozen_corpus_counts_and_zero_reversible_hunks():
    original, adapted = adapter.source_tree(), adapter.adapted_tree()
    assert dump(original) == dump(adapted)
    assert corpus(original) == corpus(adapted)
    assert adapter.SETUP_HUNKS == ()
    record = adapter.inventory()
    assert (record["functions"], record["cases"], record["assertions"], record["classes"]) == (
        122,
        152,
        334,
        18,
    )
    assert len(record["case_inventory"]) == 122


def test_unsupported_cases_remain_whole_suite_blockers_not_skips_or_exclusions():
    record = adapter.inventory()
    names = {row["symbol"] for row in record["case_inventory"]}
    assert all(
        any(symbol == key or symbol.startswith(key + ".") for symbol in names)
        for key in adapter.MISSING_BEHAVIOR
    )
    assert adapter.RESTORATION_STATUS == "deferred"
    namespace = {"__name__": "blocked_llm_probe"}
    with pytest.raises(adapter.IncompleteDesktopSuiteError, match="step 5 completion PR"):
        adapter.load(namespace)
    assert namespace == {"__name__": "blocked_llm_probe"}


@pytest.mark.parametrize("mutation", ["assertion", "setup", "case_removal"])
def test_whole_tree_seal_rejects_assertion_setup_or_case_drift(mutation):
    original = adapter.source_tree()
    candidate = copy.deepcopy(original)
    if mutation == "assertion":
        next(
            node for node in ast.walk(candidate) if isinstance(node, ast.Assert)
        ).test = ast.Constant(True)
    elif mutation == "setup":
        candidate.body.append(ast.parse("carrier_manufactures_success = True").body[0])
    else:
        target = next(
            node
            for node in candidate.body
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test")
        )
        target.body = [
            node for node in target.body if not getattr(node, "name", "").startswith("test_")
        ]
    with pytest.raises(ValueError, match="no admitted"):
        adapter.verify_adaptation(original, candidate)


def test_unknown_verdict_projection_fails_closed():
    from src.desktop.management import MethodError

    with pytest.raises(KeyError):
        adapter.CommandResponse(error=MethodError("unknown_new_verdict", "not mapped"))
    with pytest.raises(TypeError):
        adapter.CommandResponse(error=ValueError("not a private verdict"))
