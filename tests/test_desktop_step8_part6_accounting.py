"""Behavioral fail-closed tests for the frozen exact case disposition tool."""
from __future__ import annotations

import copy

import pytest

from scripts.maintenance import phase2_part6 as accounting


def test_exact_population_and_final_named_blockers():
    errors, counts = accounting.validate()
    assert errors == []
    assert counts["functions"] == 83
    assert counts["expanded_cases"] == 108
    assert counts["runtime_pass_claim"] is False
    rows = [case for suite in accounting.build()["suites"] for case in suite["cases"]]
    assert all(case.get("blocker") and case.get("owner") for case in rows
               if case["disposition"] == "deferred")
    mismatch = next(case for case in rows if case["case"].endswith(
        "test_verify_shared_secret_accepts_matching_token"))
    assert mismatch["disposition"] == "deferred"
    assert "[REDACTED]" in mismatch["blocker"]


@pytest.mark.parametrize("mutation", ["lost", "duplicate", "hash", "case", "reason", "fake-pass",
                                      "approval", "substitution", "expanded", "callback-retired"])
def test_rejects_invented_identity_disposition_and_approval(mutation):
    data = copy.deepcopy(accounting.build())
    if mutation == "lost":
        data["suites"].pop()
    elif mutation == "duplicate":
        data["suites"][0]["cases"].append(data["suites"][0]["cases"][0])
    elif mutation == "hash":
        data["suites"][0]["inherited_sha256"] = "0" * 64
    elif mutation == "case":
        data["suites"][0]["cases"][0]["case"] = "invented"
    elif mutation == "reason":
        data["suites"][0]["cases"][0]["reason"] = ""
    elif mutation == "fake-pass":
        data["suites"][0]["whole_restore"] = True
    elif mutation == "approval":
        data["independent_review"] = "approved"
    elif mutation == "substitution":
        data["source_data_substitutions"] = ["secret"]
    elif mutation == "expanded":
        data["suites"][0]["cases"][0]["expanded_cases"] = 0
    else:
        callback = next(case for suite in data["suites"] for case in suite["cases"]
                        if case["case"] == (
                            "TestGitHubTriggerMatching.test_triggers_notified_on_push"))
        callback["disposition"] = "retired"
    assert accounting.validate(data=data)[0]


def test_retained_projection_is_exact_original_class_or_named_case_defer():
    import ast

    from scripts.maintenance.fixture_corpus import dump, frozen_source
    from tests.desktop_adapters.step8_part6 import DEFERRED, PROJECTED_AST

    for original, projected in PROJECTED_AST.items():
        path, cls = original.split("::")
        tree = ast.parse(frozen_source(path))
        original_class = next(node for node in tree.body
                              if isinstance(node, ast.ClassDef) and node.name == cls)
        original_class.body = [child for child in original_class.body
                               if f"{cls}.{getattr(child, 'name', '')}" not in DEFERRED]
        assert dump(original_class) == projected
