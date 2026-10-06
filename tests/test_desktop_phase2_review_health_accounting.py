"""Offline guards for PR34 round-three health case accounting."""
import copy
import json
from pathlib import Path

import pytest

from scripts.maintenance import phase2_suites as checker
from scripts.maintenance import record_step8_part2_review as recorder

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "maintenance/step8-part2-review-health.json"


def test_exact_round3_case_metadata_and_counts():
    rows = {row["path"]: row for row in json.loads(RECORD.read_text())["entries"]}
    endpoints = rows["tests/test_health_endpoints.py"]
    startup = rows["tests/test_campaign_startup_health.py"]
    assert len(endpoints["case_retirements"]) == 22
    assert sum(item["reason"] == "multi-user tiers removed"
               for item in endpoints["case_retirements"]) == 4
    assert len(startup["restoration"]["case_retirements"]) == 1
    assert startup["case_counts"] == {"restored": 2, "retired": 2, "deferred": 0}
    assert checker._case_retirements(ROOT, endpoints["path"], endpoints["inherited_sha256"],
                                     endpoints["case_retirements"])
    assert checker._case_retirements(ROOT, startup["path"], startup["inherited_sha256"],
                                     startup["restoration"]["case_retirements"])


@pytest.mark.parametrize("tamper", ["reviewer", "reason", "source", "missing_case"])
def test_round3_case_authority_fails_closed(tamper):
    rows = {row["path"]: row for row in json.loads(RECORD.read_text())["entries"]}
    row = rows["tests/test_campaign_startup_health.py"]
    cases = copy.deepcopy(row["restoration"]["case_retirements"])
    if tamper == "reviewer":
        cases[0]["reviewer"] = "other authority"
    elif tamper == "reason":
        cases[0]["reason"] = "different reason"
    elif tamper == "source":
        cases[0]["source_sha256"] = "0" * 64
    else:
        cases.clear()
    assert not checker._case_retirements(ROOT, row["path"], row["inherited_sha256"], cases)


def test_recorder_preview_reports_expected_accounting_without_writing():
    _, report = recorder.build(ROOT, require_complete=False)
    assert (report["restored"], report["retired"], report["deferred"]) == (28, 42, 256)
    assert report["review34"]["adapt_decisions"] == {
        "deferred": 3, "restored": 9, "retired": 1}
    assert report["review34"]["restored_paths"]
