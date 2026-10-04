"""Collection metadata is evidence of identity, never evidence of execution."""
import json

import pytest

from scripts.maintenance.refresh_case_collection import refresh


def test_refresh_preserves_uncollected_gaps_and_original_parameters(tmp_path):
    (tmp_path / "maintenance").mkdir()
    (tmp_path / ".test-state").mkdir()
    rows = [{"original": "tests/test_case.py::test_matrix[a]",
             "disposition": "unmapped-neutral-blocker", "blocks_phase1": True},
            {"original": "tests/test_case.py::test_matrix[b]",
             "disposition": "unmapped-neutral-blocker", "blocks_phase1": True}]
    accounting = {"historical_failures": rows, "foundation_suites": [],
                  "status": "pending-review-not-accepted"}
    (tmp_path / "maintenance/case-accounting.json").write_text(json.dumps(accounting))
    (tmp_path / ".test-state/qualification-result.json").write_text(
        json.dumps({"failed_groups": []}))
    (tmp_path / ".test-state/qualification-collected.json").write_text(json.dumps({"cases": [
        {"original": rows[0]["original"], "executable": "tests/test_adapter.py::test_matrix[a]"}
    ]}))
    result = refresh(tmp_path)
    assert result["historical_failures"][0]["disposition"] == "executable"
    assert result["historical_failures"][1]["blocks_phase1"]
    assert result["historical_failure_blockers"] == [rows[1]["original"]]
    assert result["status"] == "pending-review-not-accepted"
    assert [case["original"] for case in result["historical_failures"]] == [
        case["original"] for case in rows]
    (tmp_path / ".test-state/qualification-result.json").write_text(
        json.dumps({"failed_groups": [{"name": "failed", "exit_code": 1}]}))
    with pytest.raises(ValueError, match="Failed collection"):
        refresh(tmp_path)
