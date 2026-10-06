"""D19 live-source re-evaluation and evidence contract, not runtime proof."""

import pytest

from tests.test_desktop_d19_closure import gate, inventory, parsed


@pytest.mark.parametrize("source", [
    'value = "restored"',
    'def legacy():\n return "restored"\n return "fence complete"\n',
])
def test_pending_disappearance_requires_update_without_recorded_scan(tmp_path, source):
    rows = parsed()
    findings = gate.scan_source(source, "src/example.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="pending_restoration", owner="Odin",
                           pending_reference="PR #37 (6B)")
    data["rows"][0].pop("observations")
    errors = gate.validate(data, rows, findings, tmp_path)["errors"]
    assert any("pending string no longer has an active AST match" in e for e in errors)


def test_pending_multifragment_requires_each_diagnostic_to_remain_reachable(tmp_path):
    rows = parsed()
    rows[0]["strings"] = ["fence complete", "second fence"]
    findings = gate.scan_source('value = "fence complete"', "src/example.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="pending_restoration", owner="Odin",
                           pending_reference="PR #62 (skill delivery, lane 3)")
    assert any("pending string no longer" in e
               for e in gate.validate(data, rows, findings, tmp_path)["errors"])


def test_pending_other_module_same_text_does_not_mask_restoration(tmp_path):
    rows = parsed()
    findings = gate.scan_source('value = "fence complete"', "src/other.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="pending_restoration", owner="Odin",
                           pending_reference="PR #48 (media publication)")
    assert any("pending string no longer" in e
               for e in gate.validate(data, rows, findings, tmp_path)["errors"])


def test_pending_omnibus_caller_paths_are_explicit_and_individually_required(tmp_path):
    rows = parsed()
    rows[0]["strings"].append("operation name")
    findings = gate.scan_source('value = "fence complete"', "src/example.py")
    findings += gate.scan_source('value = "operation name"', "src/caller.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="pending_restoration", owner="unassigned",
                           pending_reference="unassigned",
                           pending_fragment_paths={"operation name": ["src/caller.py"]})
    assert not gate.validate(data, rows, findings, tmp_path)["errors"]
    # An unrelated identical operation name cannot hide its caller's removal.
    moved = findings[:1] + gate.scan_source('value = "operation name"', "src/other.py")
    data["rows"][0].pop("observations")
    assert any("pending string no longer" in e
               for e in gate.validate(data, rows, moved, tmp_path)["errors"])


@pytest.mark.parametrize("paths", [
    [], None, {"foreign fragment": ["src/caller.py"]}, {"fence complete": []},
    {"fence complete": [None]}, {"fence complete": ["/tmp/foreign.py"]},
    {"fence complete": ["src/../escape.py"]}, {"fence complete": ["src/document.md"]},
])
def test_pending_fragment_paths_reject_malformed_or_foreign_bindings(tmp_path, paths):
    rows = parsed()
    findings = gate.scan_source('value = "fence complete"', "src/example.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="pending_restoration", owner="Odin",
                           pending_reference="PR #37 (6B)", pending_fragment_paths=paths)
    assert any("invalid pending fragment source paths" in e
               for e in gate.validate(data, rows, findings, tmp_path)["errors"])


@pytest.mark.parametrize("reference,owner", [
    ("health/readiness lane", "Odin"), ("unassigned", "Odin"), ([], "Odin"),
])
def test_pending_rejects_imaginary_reference_or_owner(tmp_path, reference, owner):
    rows = parsed()
    findings = gate.scan_source('value = "fence complete"', "src/example.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="pending_restoration", owner=owner,
                           pending_reference=reference)
    assert gate.validate(data, rows, findings, tmp_path)["errors"]


def test_pending_can_be_explicitly_unassigned(tmp_path):
    rows = parsed()
    findings = gate.scan_source('value = "fence complete"', "src/example.py")
    data = inventory(rows, findings)
    data["rows"][0].update(status="pending_restoration", owner="unassigned",
                           pending_reference="unassigned")
    assert not gate.validate(data, rows, findings, tmp_path)["errors"]


def internal_inventory(tmp_path, rows, findings):
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests/test_guard.py").write_text(
        "def test_never_invoked():\n assert True\n", encoding="utf-8",
    )
    data = inventory(rows, findings)
    data["rows"][0].update(
        status="internal_unreachable_guard", reviewer="Claude",
        guard_proof="Fail-if-called spy around the legacy guard during composed requests.",
        evidence_tests=["tests/test_guard.py::test_never_invoked"],
        guard_targets=[{"path": "src/example.py", "selector": "legacy"}],
    )
    return data


def test_internal_guard_is_not_static_absence_or_wording_approval(tmp_path):
    rows = parsed()
    findings = gate.scan_source('def legacy():\n raise RuntimeError("fence complete")\n',
                                "src/example.py")
    data = internal_inventory(tmp_path, rows, findings)
    assert not gate.validate(data, rows, findings, tmp_path)["errors"]
    assert data["rows"][0]["status"] != "removed_by_restored_behaviour"


@pytest.mark.parametrize("field,value", [
    ("reviewer", "Aaron"), ("guard_proof", ""), ("evidence_tests", []),
    ("guard_targets", None), ("guard_targets", []), ("guard_targets", [None]),
    ("guard_targets", [{"path": [], "selector": "legacy"}]),
    ("guard_targets", [{"path": "src/other.py", "selector": "legacy"}]),
])
def test_internal_guard_requires_proof_and_current_source_identity(tmp_path, field, value):
    rows = parsed()
    findings = gate.scan_source('def legacy():\n return "fence complete"\n', "src/example.py")
    data = internal_inventory(tmp_path, rows, findings)
    data["rows"][0][field] = value
    assert gate.validate(data, rows, findings, tmp_path)["errors"]


@pytest.mark.parametrize("source", [
    'def legacy():\n return "restored"\n',
    'def legacy():\n return "fence complete"\n'
    'def admitted():\n return "fence complete"\n',
])
def test_internal_guard_disappearance_or_new_exposure_requires_new_proof(tmp_path, source):
    rows = parsed()
    findings = gate.scan_source(source, "src/example.py")
    data = internal_inventory(tmp_path, rows, findings)
    assert any("internal guard moved/disappeared" in e
               for e in gate.validate(data, rows, findings, tmp_path)["errors"])


@pytest.mark.parametrize("field", ["when_odin_sees_it", "odin_v4130_equivalent"])
def test_behavioural_proposal_requires_concrete_decision_context(tmp_path, field):
    data = inventory(parsed(), [])
    data["rows"][0].pop(field)
    assert any(field in e for e in gate.validate(data, parsed(), [], tmp_path)["errors"])
