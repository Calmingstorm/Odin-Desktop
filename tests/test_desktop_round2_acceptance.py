"""Static PR 2 B/C obligations. No engine imports, command inputs or endpoints."""
from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE2_SET_SHA256 = "a4bcf41b3ee1660c991df903cccbda1583497c2ec01cea6bb2be6425ba43888f"
GOVERNOR_SUITES = (
    "tests/test_risk_classifier.py",
    "tests/test_governor_policy_floor.py",
    "tests/test_governor_shape_fixtures.py",
    "tests/test_governor_shape_matrix.py",
)


def test_all_326_phase2_suites_are_frozen_and_required_in_both_exit_records():
    plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    paths = plan["phase2"]
    assert len(paths) == len(set(paths)) == 326
    assert set(paths) == {
        entry["path"] for entry in plan["entries"] if entry["classification"] == "phase2"
    }
    encoded = ("\n".join(sorted(paths)) + "\n").encode()
    assert hashlib.sha256(encoded).hexdigest() == PHASE2_SET_SHA256
    for document in ("docs/design/roadmap.md", "maintenance/test-plan.md"):
        text = (ROOT / document).read_text()
        assert "326 Phase-2-deferred suites" in text
        assert "never dropped" in text
        for required in (
            "tests/characterization/test_chat_tool_loop.py",
            "tests/test_recovery.py",
            "tests/test_tool_loop_helpers.py",
            "tests/test_codex_replay_boundaries.py",
            "tests/test_codex_replay_matrix.py",
        ):
            assert required in text, (document, required)
            assert required in paths


def test_governor_manual_gates_and_upstream_evidence_remain_explicit():
    plan = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    records = {entry["path"]: entry for entry in plan["entries"]}
    text = (ROOT / "docs/design/maintenance.md").read_text()
    for path in GOVERNOR_SUITES:
        assert path in plan["safety_manual_gated"]
        assert records[path]["classification"] == "safety_manual_gated"
        assert path in text
    assert "Porting a governor change requires its upstream CI evidence" in text
    assert "re-qualify only the pure classification cases" in text
    assert "36951324132" in text
    assert "cd7530906e9cfa10a0fa900247d7ce2a8bb33e25" in text


def test_governor_and_imports_keep_the_bytes_supported_by_upstream_ci():
    with tarfile.open(ROOT / "maintenance/odin-v4.13.0.tar.gz") as archive:
        for path in (
            "src/tools/risk_classifier.py",
            "src/tools/command_shapes.py",
            "src/tools/command_authority.py",
        ):
            stream = archive.extractfile(path)
            assert stream is not None
            assert (ROOT / path).read_bytes() == stream.read(), path
