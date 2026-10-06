"""Task-authorized case exclusions remain exact, immutable and fail closed."""
from __future__ import annotations

import ast
import hashlib
import json
from types import ModuleType

import pytest

from scripts.maintenance import phase2_suites as checker
from scripts.maintenance.fixture_corpus import register_module


def test_register_exact_retired_cases_keeps_other_functions_and_class_methods():
    module = ModuleType("frozen_fixture")
    exec(compile(
        "def test_retired(): pass\ndef test_kept(): pass\n"
        "class TestFrozen:\n    def test_retired(self): pass\n"
        "    def test_kept(self): pass\n", "fixture", "exec"), module.__dict__)
    namespace = {"__name__": "qualified_fixture"}
    register_module(namespace, module, prefix="frozen",
                    excluded=["test_retired", "TestFrozen.test_retired"])
    assert "test_frozen_retired" not in namespace
    assert "test_frozen_kept" in namespace
    assert hasattr(namespace["Test_frozen_Frozen"], "test_kept")
    assert not hasattr(namespace["Test_frozen_Frozen"], "test_retired")


def fixture_record(tmp_path, monkeypatch):
    path = "tests/test_fixture.py"
    source = b"def test_retired():\n    assert True\ndef test_kept():\n    assert True\n"
    target = tmp_path / path
    target.parent.mkdir()
    target.write_bytes(source)
    sha = hashlib.sha256(source).hexdigest()
    rows = [{"case": "test_retired", "reviewer": checker.PART4_REVIEWER,
             "reason": "Removed Odin web UI listener", "source_path": path,
             "source_sha256": sha}]
    monkeypatch.setattr(checker, "_part4_dispositions", lambda root: {
        path: {"inherited_sha256": sha, "retired_cases": rows},
    })
    return path, sha, rows


def test_case_retirement_requires_exact_task_record_and_frozen_case(tmp_path, monkeypatch):
    path, sha, rows = fixture_record(tmp_path, monkeypatch)
    assert checker._case_retirements(tmp_path, path, sha, rows)
    changed = [dict(rows[0], case="test_kept")]
    assert not checker._case_retirements(tmp_path, path, sha, changed)
    assert not checker._case_retirements(tmp_path, path, "0" * 64, rows)
    (tmp_path / path).write_text("def test_retired(): pass\n")
    assert not checker._case_retirements(tmp_path, path, sha, rows)


@pytest.mark.parametrize("mutation", ["hash", "reviewer", "case", "reason", "extra"])
def test_case_retirement_rejects_coherent_invalid_case_metadata(tmp_path, monkeypatch, mutation):
    path, sha, rows = fixture_record(tmp_path, monkeypatch)
    if mutation == "hash":
        rows[0]["source_sha256"] = "0" * 64
    elif mutation == "reviewer":
        rows[0]["reviewer"] = "Odin"
    elif mutation == "case":
        rows[0]["case"] = "test_missing"
    elif mutation == "reason":
        rows[0]["reason"] = " "
    else:
        rows[0]["selected"] = True
    assert not checker._case_retirements(tmp_path, path, sha, rows)


def test_part4_disposition_artifact_is_independently_byte_pinned(tmp_path, monkeypatch):
    target = tmp_path / checker.PART4_PATH
    target.parent.mkdir()
    data = json.dumps({"reviewer": checker.PART4_REVIEWER, "dispositions": []}).encode()
    target.write_bytes(data)
    monkeypatch.setattr(checker, "PART4_SHA256", hashlib.sha256(data).hexdigest())
    assert checker._part4_dispositions(tmp_path) == {}
    target.write_bytes(data + b" ")
    with pytest.raises(ValueError, match="hash changed"):
        checker._part4_dispositions(tmp_path)


def test_part4_group_admission_is_not_generic_selector_waiver():
    assert set(checker.PART4_GROUPS) == {
        "phase2-step6a-tools-restored-corpus", "phase2-step6a-computer-restored-corpus",
        "phase2-step6a-hyprland-restored-corpus", "phase2-step6a-campaigns-restored-corpus",
    }
    for files in checker.PART4_GROUPS.values():
        assert files and all(path.startswith("tests/test_desktop_step8_6a_") for path in files)


def test_register_does_not_change_inherited_assertion_code():
    tree = ast.parse("def test_kept():\n    assert 2 + 2 == 4\n")
    module = ModuleType("frozen")
    exec(compile(tree, "fixture", "exec"), module.__dict__)
    code = module.test_kept.__code__
    namespace = {"__name__": "qualified"}
    register_module(namespace, module, prefix="frozen", excluded=[])
    assert namespace["test_frozen_kept"].__code__ is code
