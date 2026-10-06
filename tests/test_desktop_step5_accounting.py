"""Enrollment preserves whole original populations, hashes and prior gates."""
import json
from pathlib import Path

import pytest

from scripts.maintenance import phase2_suites
from scripts.maintenance.record_step5_completion import GROUP, RESTORATIONS, enroll

ROOT = Path(__file__).resolve().parents[1]


def test_all_completion_adapters_have_exact_whole_corpus_static_proof():
    mapping = json.loads((ROOT / "maintenance/phase2-suite-map.json").read_text())
    hashes = {row["path"]: row["inherited_sha256"] for row in mapping["entries"]}
    for selector, names in RESTORATIONS.items():
        for name in names:
            path = f"tests/test_{name}.py"
            assert phase2_suites._full_adapter(ROOT, selector, path, hashes[path]), path
    assert sum(map(len, RESTORATIONS.values())) == 21


@pytest.fixture
def accounting_copy(tmp_path):
    directory = tmp_path / "maintenance"
    directory.mkdir()
    for name in ("phase2-suite-map.json", "test-plan.json", "qualification-plan.json"):
        (directory / name).write_bytes((ROOT / "maintenance" / name).read_bytes())
    return tmp_path


def test_enrollment_is_idempotent_and_preserves_previous_gates(accounting_copy, monkeypatch):
    root = accounting_copy
    before = json.loads((root / "maintenance/qualification-plan.json").read_text())
    original = json.loads((root / "maintenance/test-plan.json").read_text())
    hashes = {row["path"]: row["sha256"] for row in original["entries"]}
    monkeypatch.setattr(phase2_suites, "_full_adapter", lambda *args: True)
    assert enroll(root) == 21
    once = {path: path.read_bytes() for path in (root / "maintenance").iterdir()}
    assert enroll(root) == 21
    assert once == {path: path.read_bytes() for path in once}
    after = json.loads((root / "maintenance/qualification-plan.json").read_text())
    for old, new in zip(before["groups"], after["groups"]):
        assert old["name"] == new["name"]
        assert set(old["files"]) <= set(new["files"])
        if old["name"] != GROUP:
            assert old == new
    plan = json.loads((root / "maintenance/test-plan.json").read_text())
    assert hashes == {row["path"]: row["sha256"] for row in plan["entries"]}
    assert len(plan["phase2"] + plan["phase2_restored"] + plan["phase2_retired"]) == 326


def test_missing_whole_adapter_proof_cannot_promote_a_suite(accounting_copy, monkeypatch):
    before = {path: path.read_bytes() for path in (accounting_copy / "maintenance").iterdir()}
    monkeypatch.setattr(phase2_suites, "_full_adapter", lambda *args: False)
    with pytest.raises(ValueError, match="Whole pinned step-five adapter required"):
        enroll(accounting_copy)
    assert before == {path: path.read_bytes() for path in before}
