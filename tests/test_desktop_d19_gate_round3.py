"""Validate recorded decisions and the specific composed #69 restoration."""

import pytest

from tests.test_desktop_d19_closure import gate, inventory, parsed


@pytest.mark.parametrize("field,value", [
    ("reviewer", "Claude"), ("approval_date", None), ("approval_date", ""),
    ("approval_date", "2026-02-30"), ("approval_date", "20261006"),
    ("approval_date", []), ("when_odin_sees_it", ""), ("odin_v4130_equivalent", ""),
])
def test_approved_behavioural_requires_aaron_date_and_context(tmp_path, field, value):
    rows = parsed()
    data = inventory(rows, [])
    data["rows"][0].update(status="approved_behavioural", reviewer="Aaron",
                           approval_date="2026-10-06")
    assert not gate.validate(data, rows, [], tmp_path)["errors"]
    data["rows"][0][field] = value
    assert gate.validate(data, rows, [], tmp_path)["errors"]


def health_inventory(tmp_path):
    rows = parsed()
    rows[0].update(id="D19-049", source_path="src/health/checker.py")
    findings = gate.scan_source('def check_delivery():\n return "fence complete"\n',
                                "src/health/checker.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="removed_by_restored_behaviour",
                           restoration_kind="composed_delivery_health",
                           evidence_tests=[gate.HEALTH_RESTORATION_TEST])
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_desktop_health_delivery.py").write_text(
        "def test_health_delivery_ready_after_startup_and_real_guarded_turn():\n pass\n")
    return rows, findings, data


def test_health_restoration_allows_only_its_legitimate_retained_diagnostics(tmp_path):
    rows, findings, data = health_inventory(tmp_path)
    assert not gate.validate(data, rows, findings, tmp_path)["errors"]
    other = gate.scan_source('def other():\n return "fence complete"\n', "src/other.py")
    data["rows"][0].pop("observations")
    assert gate.validate(data, rows, findings + other, tmp_path)["errors"]
    assert gate.validate(data, rows, [], tmp_path)["errors"]


@pytest.mark.parametrize("field,value", [
    ("status", "pending_restoration"), ("status", "approved_behavioural"),
    ("restoration_kind", None), ("evidence_tests", []),
    ("evidence_tests", ["tests/test_desktop_health_delivery.py::test_missing"]),
])
def test_health_row_requires_exact_restoration_and_guarded_turn_test(tmp_path, field, value):
    rows, findings, data = health_inventory(tmp_path)
    data["rows"][0][field] = value
    assert any("exact guarded-turn evidence" in error for error in
               gate.validate(data, rows, findings, tmp_path)["errors"])


def test_health_exception_cannot_waive_another_removed_row(tmp_path):
    rows, findings, data = health_inventory(tmp_path)
    rows[0]["id"] = data["rows"][0]["id"] = "D19-001"
    assert any("present active" in error for error in
               gate.validate(data, rows, findings, tmp_path)["errors"])


def test_d17_followup_is_a_real_pending_reference(tmp_path):
    rows = parsed()
    findings = gate.scan_source('value = "fence complete"', "src/example.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="pending_restoration",
                           owner="D17 restoration (next bridge task)",
                           pending_reference="D17 restoration (next bridge task)")
    assert not gate.validate(data, rows, findings, tmp_path)["errors"]
