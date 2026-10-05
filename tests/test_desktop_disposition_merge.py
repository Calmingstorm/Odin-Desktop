"""Triage cannot erase gaps using missing selectors or rewritten original hashes."""
import copy

import pytest

from scripts.maintenance.merge_case_dispositions import merge


def fixture():
    case = {"original": "tests/test_old.py::test_case", "source_sha256": "original",
            "disposition": "unmapped-neutral-blocker", "blocks_phase1": True}
    accounting = {"historical_failures": [case], "foundation_suites": [],
                  "status": "pending-review-not-accepted"}
    proposal = {**case, "disposition": "removed-surface-replacement", "executable": [],
                "replacement_cases": ["tests/test_new.py::test_boundary"],
                "reason": "Exact removed transport contract; negative owner boundary checked."}
    collected = [{"executable": "tests/test_new.py::test_boundary"}]
    return accounting, proposal, collected


def test_merge_requires_actual_collection_and_original_digest():
    accounting, proposal, collected = fixture()
    original = copy.deepcopy(accounting)
    result = merge(accounting, collected, [("maintenance/triage.json", {"cases": [proposal]})])
    assert accounting == original
    assert not result["historical_failure_blockers"]
    assert result["status"] == "pending-review-not-accepted"
    for change, message in (({"source_sha256": "rewritten"}, "digest"),
                            ({"replacement_cases": ["tests/test_missing.py::test_x"]},
                             "Uncollected"),
                            ({"replacement_cases": []}, "require"),
                            ({"original": "tests/test_unknown.py::test_x"}, "Unknown")):
        with pytest.raises(ValueError, match=message):
            merge(accounting, collected, [("maintenance/triage.json", {"cases": [
                {**proposal, **change}]} )])


def test_deferred_boundary_is_not_implemented_parity_and_duplicate_refuses():
    accounting, proposal, collected = fixture()
    proposal["disposition"] = "phase2-admission-wiring"
    result = merge(accounting, collected, [("maintenance/triage.json", {"cases": [proposal]})])
    assert result["historical_failure_blockers"] == [proposal["original"]]
    with pytest.raises(ValueError, match="Duplicate"):
        merge(accounting, collected, [("maintenance/triage.json", {"cases": [proposal, proposal]})])


def test_explicit_maintenance_script_delta_is_checked_not_orphaned():
    import inspect

    from scripts.maintenance.inventory import report

    source = inspect.getsource(report)
    assert 'path.startswith("scripts/maintenance/") and path not in deltas' in source


def test_executable_original_can_have_explicit_collected_supplement():
    accounting, proposal, collected = fixture()
    proposal["disposition"] = "executable"
    proposal["executable"] = ["tests/test_adapter.py::test_original"]
    collected.append({"executable": proposal["executable"][0]})
    result = merge(accounting, collected, [("maintenance/triage.json", {"cases": [proposal]})])
    row = result["historical_failures"][0]
    assert row["executable"] == proposal["executable"]
    assert row["replacement_cases"] == proposal["replacement_cases"]
