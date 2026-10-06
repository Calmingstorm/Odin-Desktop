"""Closure aggregation and report behavior on disposable input only."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/maintenance/phase2_closure.py"
SPEC = importlib.util.spec_from_file_location("phase2_closure", PATH)
closure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(closure)


def check(mapping=None, wording=None, *, parity=True, errors=None):
    return closure.summarize(
        {"entries": []} if mapping is None else mapping, {"errors": errors or []},
        {"rows": []} if wording is None else wording, {"errors": []},
        {"valid": parity, "errors": []})


def test_final_dispositions_are_not_relabelled_as_passes():
    result = check({"entries": [{"path": "tests/a.py", "status": "restored"},
                                 {"path": "tests/b.py", "status": "retired"}]})
    assert result["ready"]
    assert result["suites"] == {"total": 2, "statuses": {"restored": 1, "retired": 1},
                                "without_final_disposition": 0}


@pytest.mark.parametrize("status", ["deferred", "pending-review", "passing", None])
def test_unfinished_suite_status_and_reason_remain_blockers(status):
    result = check({"entries": [{"path": "tests/a.py", "status": status,
                                  "blocked_on": "Awaiting exact case disposition"}]})
    assert not result["ready"]
    assert result["suites"]["without_final_disposition"] == 1
    assert result["blockers"][0]["reason"] == "Awaiting exact case disposition"


@pytest.mark.parametrize("status", ["pending_restoration", "proposed_mechanical",
                                    "proposed_behavioural", "approved", None])
def test_d19_proposals_and_unspecified_approval_do_not_close_rows(status):
    result = check(wording={"rows": [{"id": "D19-001", "status": status}]})
    assert not result["ready"]
    assert result["D19"]["open"] == 1


def test_missing_bridge_file_remains_distinct_from_zero_open_rows():
    result = closure.summarize({"entries": []}, {"errors": []}, None,
                               {"errors": []}, {"valid": True, "errors": []})
    assert result["D19"] == {"inventory": "missing", "rows": 0, "open": 0}
    assert not result["ready"]
    assert result["blockers"][0]["kind"] == "D19_inventory"


def test_byte_validation_error_blocks_even_final_rows():
    result = check(errors=["Inherited source hash changed"])
    assert not result["ready"]
    assert result["errors"] == ["suites: Inherited source hash changed"]
    assert result["blockers"][0]["kind"] == "integrity"


def test_missing_or_stale_parity_blocks_closure():
    result = check(parity=False)
    assert not result["ready"]
    assert result["blockers"][0]["kind"] == "parity"


def test_report_mode_returns_zero_with_missing_temporary_inputs(tmp_path, capsys):
    assert closure.main(["report", "--root", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["ready"]
    assert result["D19"]["inventory"] == "missing"
    assert result["blocker_counts"]["parity"] == 1
    assert result["errors"]


def test_detailed_report_preserves_every_row(tmp_path, monkeypatch, capsys):
    expected = check({"entries": [{"path": "tests/a.py", "status": "deferred"}]})
    monkeypatch.setattr(closure, "report", lambda root: expected)
    assert closure.main(["report", "--root", str(tmp_path), "--details"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["blockers"][0]["id"] == "tests/a.py"


def test_duplicate_input_keys_are_not_last_write_wins(tmp_path):
    data = tmp_path / "bad.json"
    data.write_text('{"status":"deferred","status":"restored"}')
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        closure._json(data)


def test_enforcement_is_not_part_of_this_change():
    with pytest.raises(SystemExit) as exc:
        closure.main(["enforce"])
    assert exc.value.code == 2


@pytest.mark.parametrize("status", [{"fake": "restored"}, ["restored"]])
def test_malformed_unhashable_status_is_open_not_a_report_crash(status):
    result = check({"entries": [{"path": "tests/a.py", "status": status}]},
                   {"rows": [{"id": "D19-001", "status": status}]})
    assert not result["ready"]
    assert result["suites"]["without_final_disposition"] == 1
    assert result["D19"]["open"] == 1


def test_report_runs_each_checker_against_temporary_data(tmp_path, monkeypatch):
    from types import SimpleNamespace

    (tmp_path / "maintenance").mkdir()
    (tmp_path / closure.SUITES).write_text(json.dumps({"entries": [
        {"path": "tests/a.py", "status": "restored"}]}))
    (tmp_path / closure.D19).write_text(json.dumps({"rows": [
        {"id": "D19-001", "status": "removed_by_restored_behaviour"}]}))
    seen = []

    def suite_check(root):
        seen.append(("suites", root))
        return [], {}

    def source(root):
        seen.append(("D19", root))
        return ["exact source row"], ["source scan"]

    def validate(wording, rows, findings, root):
        assert wording["rows"][0]["id"] == "D19-001"
        assert rows == ["exact source row"] and findings == ["source scan"]
        return {"errors": ["restoration source drift"]}

    def parity(root):
        seen.append(("parity", root))
        return {"valid": True, "errors": []}

    tools = {"phase2_suites": SimpleNamespace(_evaluate=suite_check),
             "d19": SimpleNamespace(load_source=source, validate=validate),
             "fresh_profile_parity": SimpleNamespace(check=parity)}
    monkeypatch.setattr(closure, "_tool", tools.__getitem__)
    result = closure.report(tmp_path)
    assert seen == [("suites", tmp_path), ("D19", tmp_path), ("parity", tmp_path)]
    assert result["D19"]["open"] == 0
    assert result["suites"]["without_final_disposition"] == 0
    assert not result["ready"]  # final labels cannot override stale source evidence
    assert result["errors"] == ["D19: restoration source drift"]
