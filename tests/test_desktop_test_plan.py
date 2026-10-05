"""Static audit artifact invariants, no inherited test/source execution."""
import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_869_frozen_paths_accounted_once():
    plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    with tarfile.open(ROOT / "maintenance/odin-v4.13.0.tar.gz") as archive:
        originals = {m.name: archive.extractfile(m).read() for m in archive.getmembers()
                     if m.isfile() and m.name.startswith("tests/")}
    entries = plan["entries"]
    assert len(entries) == len({e["path"] for e in entries}) == 869
    assert {e["path"] for e in entries} == set(originals)
    for entry in entries:
        assert entry["reason"]
        assert entry["sha256"] == hashlib.sha256(originals[entry["path"]]).hexdigest()


def test_disjoint_classifications_and_guard_safety_selection():
    plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    selected = set()
    for kind in ("safe_pass_now", "phase2", "excluded", "safety_manual_gated",
                 "retained_adaptation_gated", "retained_support"):
        expected = {e["path"] for e in plan["entries"] if e["classification"] == kind}
        assert set(plan[kind]) == expected
        assert not (selected & expected)
        selected.update(expected)
        assert plan["counts"][kind] == len(expected)
    assert len(selected) == 869
    assert "tests/test_response_guards.py" in plan["safe_pass_now"]
    assert "tests/test_round41_hedging_regression.py" in plan["safe_pass_now"]
    assert "tests/test_turn_checkpoint_codec.py" in plan["safe_pass_now"]
    for filename in ("test_risk_classifier.py", "test_command_shell_policy.py",
                     "test_governor_policy_floor.py", "test_campaign_a_validation.py",
                     "test_computer_dispatch_native_r19.py",
                     "test_hyprland_input_loss_campaign.py"):
        assert "tests/" + filename in plan["safety_manual_gated"]


def test_retained_inherited_bytes_and_import_evidence():
    plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    for entry in plan["entries"]:
        if entry["classification"] != "excluded":
            assert (
                hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
            ), entry["path"]
        if "import_closure_id" in entry:
            closure = plan["import_closures"][entry["import_closure_id"]]
            assert all(p.startswith("src/") for p in closure)
            assert set(entry["direct_source_imports"]).issubset(closure)
            assert entry["path"] in entry["test_import_closure"]
