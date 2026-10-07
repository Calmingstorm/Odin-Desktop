"""Offline admission/evidence checks, never native platform qualification."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "native_qualification", ROOT / "scripts/qualification/computer.py")
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


def vm(name="odq-cinnamon", status="Running", marker="odin-desktop-qualification-v1"):
    return {"name": name, "status": status, "type": "virtual-machine",
            "config": {"user.odq.owner": marker}}


def test_exclusive_owned_vm_and_lane_lock():
    result = qualification.validate_lab([vm(), vm("odq-kde", "Stopped")], "x11", "p35 today")
    assert result == "odq-cinnamon"


@pytest.mark.parametrize("rows,owner", [
    ([vm()], "p36 today"), ([vm(marker="other")], "p35 today"),
    ([vm(), vm("odq-gnome")], "p35 today"), ([], "p35 today"),
    ([vm("odq-gnome")], "p35 today"), ([vm(status="Stopped")], "p35 today"),
    ([vm(status="Frozen"), vm("odq-gnome")], "p35 today"),
])
def test_wrong_owner_or_nonexclusive_guest_refuses(rows, owner):
    with pytest.raises(ValueError):
        qualification.validate_lab(rows, "x11", owner)


def test_receipts_and_headless_regressions_never_native_proof():
    rows = [{"case": "text", "passed": True, "evidence_kind": "receipt"}]
    assert qualification.classify(rows, []) == "blocked"
    rows[0]["evidence_kind"] = "receiver_platform"
    assert qualification.classify(rows, []) == "limited"
    assert qualification.classify(rows, ["unknown_release"]) == "limited"
    assert qualification.classify([], []) == "blocked"


def test_full_receiver_platform_corpus_required():
    names = ("target_capture text key stroke stale_observation stale_generation "
             "focus_geometry_modal pause cancel exit controller_loss guardian_loss "
             "retirement_recovery restart_quarantine helper_discovery abi_refusal").split()
    rows = [{"case": name, "passed": True, "evidence_kind": "receiver_platform"} for name in names]
    assert qualification.classify(rows, []) == "proven"
    assert qualification.classify(rows, ["missing_candidate_plugin"]) == "limited"
    rows[-1]["passed"] = False
    assert qualification.classify(rows, []) == "limited"


def test_hash_streams_artifact_bytes(tmp_path):
    import hashlib
    path = tmp_path / "candidate.deb"
    path.write_bytes(b"qualification artifact" * 100000)
    assert qualification.digest(path) == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("case,text", [("text", "P35safe"), ("key", "P35saf")])
def test_receiver_text_effect_not_receipt(case, text):
    assert not qualification.receiver_effect([{"status": "verified", "text": text}], case)
    assert qualification.receiver_effect([{"event": "text", "text": text}], case)
    assert not qualification.receiver_effect([{"event": "text", "text": "different"}], case)


def test_stroke_requires_release_after_motion():
    release = {"event": "button_up", "buttons": 0}
    motion = {"event": "stroke"}
    assert not qualification.receiver_effect([release, motion], "stroke")
    assert not qualification.receiver_effect([motion], "stroke")
    assert qualification.receiver_effect([motion, release], "stroke")


def test_receiver_unknown_case_is_not_default_pass():
    with pytest.raises(ValueError, match="unknown_receiver_case"):
        qualification.receiver_effect([], "unmeasured")
