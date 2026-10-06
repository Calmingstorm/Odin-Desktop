"""Consumed case-level accounting, without importing inherited test modules."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.maintenance import phase2_part5 as checker

ROOT = Path(__file__).resolve().parents[1]


def manifest():
    return checker.load_manifest(ROOT)


def test_real_case_record_is_complete_and_not_a_runtime_pass_claim():
    errors, report = checker.validate(ROOT)
    assert errors == []
    assert report["suites"] == 16
    assert report["definitions"] > 100
    assert report["runtime_pass_claim"] is False
    assert report["independent_review"] == "pending"


@pytest.mark.parametrize("mutation", [
    "missing_suite", "duplicate_suite", "missing_case", "duplicate_case",
    "unknown_case", "changed_hash", "unknown_status", "empty_reason",
    "missing_owner", "missing_blocker", "retirement_citation",
    "retirement_category", "retirement_pass_claim", "restoration_no_selector",
    "restoration_no_counterpart", "restoration_unsafe_selector",
    "restoration_no_mode", "boolean_schema",
])
def test_case_record_mutations_fail_closed(mutation):
    data = copy.deepcopy(manifest())
    all_cases = [case for suite in data["suites"] for case in suite["cases"]]
    retired = next(case for case in all_cases if case["disposition"] == "retired")
    restored = next(case for case in all_cases if case["disposition"] == "restored")
    deferred = next(case for case in all_cases if case["disposition"] in {"deferred", "proposed"})
    if mutation == "missing_suite":
        data["suites"].pop()
    elif mutation == "duplicate_suite":
        data["suites"].append(copy.deepcopy(data["suites"][0]))
    elif mutation == "missing_case":
        data["suites"][0]["cases"].pop()
    elif mutation == "duplicate_case":
        data["suites"][0]["cases"].append(copy.deepcopy(data["suites"][0]["cases"][0]))
    elif mutation == "unknown_case":
        all_cases[0]["case"] = "test_invented"
    elif mutation == "changed_hash":
        data["suites"][0]["inherited_sha256"] = "0" * 64
    elif mutation == "unknown_status":
        all_cases[0]["disposition"] = "passed"
    elif mutation == "empty_reason":
        all_cases[0]["reason"] = " "
    elif mutation == "missing_owner":
        deferred.pop("owner", None)
    elif mutation == "missing_blocker":
        deferred.pop("blocker", None)
    elif mutation == "retirement_citation":
        retired["citation"] = "self-approved"
    elif mutation == "retirement_category":
        retired["category"] = "neutral-engine"
    elif mutation == "retirement_pass_claim":
        retired["selectors"] = ["tests/test_desktop_step8_part5_accounting.py"]
    elif mutation == "restoration_no_selector":
        restored["selectors"] = []
    elif mutation == "restoration_no_counterpart":
        restored.pop("counterpart", None)
    elif mutation == "restoration_unsafe_selector":
        restored["selectors"] = ["../outside.py"]
    elif mutation == "restoration_no_mode":
        restored.pop("mode", None)
    elif mutation == "boolean_schema":
        data["schema_version"] = True
    errors, _ = checker.validate(ROOT, data)
    assert errors
