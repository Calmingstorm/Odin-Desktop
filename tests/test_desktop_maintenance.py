"""Offline maintenance boundaries. No engine imports or live/native interaction."""
from __future__ import annotations

import copy
import importlib.util
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_inventory", REPO / "scripts/maintenance/inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

@pytest.fixture(scope="module")
def frozen():
    return inventory.baseline_blobs(REPO)

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    # Tiny deterministic fixture avoids importing or executing any baseline helper.
    blobs = {"src/shared.py": b"limit = 7\n", "tests/test_shared.py": b"assert 7 == 7\n"}
    manifest = {"entries": [{"path": p, "selected": True} for p in blobs]}
    safety = {"entries": [{"path": p, "sha256": inventory.digest(b)} for p, b in blobs.items()]}
    for path, data in blobs.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name, data in (("manifest.json", manifest), ("safety-manifest.json", safety), ("desktop-deltas.json", {"version": 1, "baseline": inventory.BASELINE, "entries": []}), ("ledger.json", {"version": 1, "baseline": inventory.BASELINE, "review_watermark": inventory.BASELINE, "entries": []})):
        inventory.write_json(tmp_path / "maintenance" / name, data)
    monkeypatch.setattr(inventory, "baseline_blobs", lambda root: blobs)
    monkeypatch.setattr(inventory, "manifests", lambda root, source: (manifest, safety))
    return tmp_path, blobs

def test_frozen_archive_and_copy_identity(frozen):
    assert len(frozen) == 1762
    assert inventory.digest((REPO / "maintenance/odin-v4.13.0.tar.gz").read_bytes()) == inventory.ARCHIVE_SHA256
    assert frozen["LICENSE"] == (REPO / "maintenance/UPSTREAM-LICENSE").read_bytes()

@pytest.mark.parametrize("path", ["src/llm/system_prompt.py", "src/discord/response_guards.py"])
def test_exact_approved_wording_protects_surroundings(frozen, path, tmp_path):
    before = frozen[path]
    approved = inventory.approved_wording(path, before)
    assert approved != before
    assert inventory.apply_byte_patch(before, inventory.byte_patch(before, approved)) == approved
    evidence = tmp_path / "tests/test_evidence.py"
    evidence.parent.mkdir()
    evidence.write_bytes(b"assert True\n")
    approval = tmp_path / "docs/design/prompt-changes.md"
    approval.parent.mkdir(parents=True)
    shutil.copyfile(REPO / "docs/design/prompt-changes.md", approval)
    entry = delta(path, before, approved)
    errors, pending, statuses = [], [], []
    inventory.validate_delta(tmp_path, entry, before, approved, errors, pending, statuses)
    assert not errors
    # Coherently updating the patch and hashes cannot expand approved wording.
    mutated = approved + b"# unapproved extra policy byte\n"
    errors.clear()
    inventory.validate_delta(tmp_path, delta(path, before, mutated), before, mutated, errors, [], [])
    assert any("surrounding" in e for e in errors)

def delta(path, before, after):
    return {"path": path, "before_sha256": inventory.digest(before), "after_sha256": inventory.digest(after),
            "patch": inventory.byte_patch(before, after), "reason": "test boundary", "contract": "exact bytes",
            "invariant": "no approval widening", "owner": "Odin", "reviewer": "pending Claude", "state": "pending",
            "tests": ["tests/test_evidence.py"], "approval": "pending", "evidence": "unit fixture"}

def test_shared_removed_added_and_budget_drift(sandbox):
    root, blobs = sandbox
    assert not inventory.report(root)["errors"]
    (root / "src/shared.py").write_bytes(b"limit = 8\n")
    assert any("Unexplained" in e for e in inventory.report(root)["errors"])
    (root / "src/shared.py").unlink()
    assert any("Missing" in e for e in inventory.report(root)["errors"])
    (root / "src/added.py").write_bytes(b"pass\n")
    assert any("addition" in e for e in inventory.report(root)["errors"])

def test_manifest_safety_and_upstream_watermark_tampering(sandbox):
    root, _ = sandbox
    inventory.write_json(root / "maintenance/safety-manifest.json", {"entries": []})
    assert any("safety-manifest" in e for e in inventory.report(root)["errors"])
    data = inventory.load_json(root / "maintenance/ledger.json")
    data["review_watermark"] = "not-the-baseline"
    inventory.write_json(root / "maintenance/ledger.json", data)
    assert any("watermark" in e for e in inventory.report(root)["errors"])

def test_frozen_selection_and_approved_docs_are_review_boundaries(frozen, tmp_path):
    for path in inventory.PINNED_DOCS:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / path, target)
    assert len(inventory.reuse_rows(tmp_path, frozen)) == 409
    approval = tmp_path / "docs/design/prompt-changes.md"
    approval.write_bytes(approval.read_bytes() + b"\ncoherent approval widening\n")
    with pytest.raises(ValueError, match="document changed"):
        inventory.reuse_rows(tmp_path, frozen)

def test_named_case_evidence_digest_cannot_silently_change(sandbox):
    root, blobs = sandbox
    evidence = root / "tests/test_evidence.py"
    evidence.write_bytes(b"assert True\n")
    entry = delta("src/shared.py", blobs["src/shared.py"], b"limit = 8\n")
    entry["test_sha256"] = {"tests/test_evidence.py": inventory.digest(evidence.read_bytes())}
    evidence.write_bytes(b"assert False\n")
    errors = []
    inventory.validate_delta(root, entry, blobs["src/shared.py"], b"limit = 8\n", errors, [], [])
    assert any("evidence test digest" in e for e in errors)

def test_safety_selection_cannot_be_deleted_through_override_json(frozen, tmp_path):
    for path in inventory.PINNED_DOCS:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / path, target)
    plan = {"entries": [{"path": p, "reason": "retained fixture", "classification": "retained_support"} for p in frozen if p.startswith("tests/")]}
    inventory.write_json(tmp_path / "maintenance/test-plan.json", plan)
    inventory.write_json(tmp_path / "maintenance/selection-overrides.json", {"version": 1, "baseline": inventory.BASELINE, "entries": [{"path": "src/discord/response_guards.py", "upstream_sha256": inventory.digest(frozen["src/discord/response_guards.py"]), "reason": "forged approval"}]})
    with pytest.raises(ValueError, match="Invalid/duplicate selection"):
        inventory.manifests(tmp_path, frozen)

def test_upstream_corpus_cannot_be_coherently_ledgered(sandbox):
    root, blobs = sandbox
    path = "tests/test_shared.py"
    altered = b"assert 8 == 8\n"
    (root / path).write_bytes(altered)
    (root / "tests/test_evidence.py").write_bytes(b"assert True\n")
    data = inventory.load_json(root / "maintenance/desktop-deltas.json")
    data["entries"] = [delta(path, blobs[path], altered)]
    inventory.write_json(root / "maintenance/desktop-deltas.json", data)
    assert any("test corpus" in e for e in inventory.report(root)["errors"])

def test_inconsistent_delta_self_review_and_duplicate_path(sandbox):
    root, blobs = sandbox
    evidence = root / "tests/test_evidence.py"
    evidence.write_bytes(b"assert True\n")
    entry = delta("src/shared.py", blobs["src/shared.py"], b"limit = 8\n")
    bad = copy.deepcopy(entry)
    bad["after_sha256"] = "0" * 64
    errors = []
    inventory.validate_delta(root, bad, blobs["src/shared.py"], b"limit = 8\n", errors, [], [])
    assert any("inconsistency" in e for e in errors)
    entry.update(state="reviewed", reviewer="Odin", approval="approved")
    errors = []
    inventory.validate_delta(root, entry, blobs["src/shared.py"], b"limit = 8\n", errors, [], [])
    assert any("independent" in e for e in errors)
    inventory.write_json(root / "maintenance/desktop-deltas.json", {"version": 1, "baseline": inventory.BASELINE, "entries": [entry, entry]})
    with pytest.raises(ValueError, match="Duplicate"):
        inventory.ledger(root)

def test_archive_tamper_fails_without_trusting_manifest_hash(tmp_path):
    (tmp_path / "maintenance").mkdir()
    (tmp_path / "maintenance/odin-v4.13.0.tar.gz").write_bytes(b"not frozen")
    with pytest.raises(ValueError, match="archive digest"):
        inventory.baseline_blobs(tmp_path)

def test_byte_patch_rejects_anchor_and_offset_tampering():
    patch = inventory.byte_patch(b"abc\n", b"def\n")
    patch[0]["start"] = 1
    with pytest.raises(ValueError, match="original bytes"):
        inventory.apply_byte_patch(b"abc\n", patch)
    patch[0]["end"] = 99
    with pytest.raises(ValueError, match="out-of-bounds"):
        inventory.apply_byte_patch(b"abc\n", patch)

def test_review_gate_is_not_fake_success(sandbox):
    root, _ = sandbox
    result = inventory.report(root, require_review=True)
    assert result["gate"] == "fail"
    assert any("review pending" in e for e in result["errors"])

def test_offline_source_and_evidence_symlink_substitution_fails(sandbox):
    root, blobs = sandbox
    source = root / "src/shared.py"
    source.unlink()
    source.symlink_to(root / "tests/test_shared.py")
    assert any("unsafe selected" in e for e in inventory.report(root)["errors"])
    assert not inventory.regular_file(root, "src/shared.py")
    (root / "src/unowned").symlink_to(root / "tests", target_is_directory=True)
    assert any("Unsafe symlink" in e for e in inventory.report(root)["errors"])
