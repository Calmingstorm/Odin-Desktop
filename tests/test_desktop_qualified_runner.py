"""Qualification plans cannot fall back to an unisolated or empty suite."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def runner():
    spec = importlib.util.spec_from_file_location(
        "qualified_runner", ROOT / "scripts/run-qualified-tests.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qualified_groups_use_namespace_launcher_and_preserve_failure(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "maintenance").mkdir()
    (tmp_path / ".test-state").mkdir()
    plan = {"groups": [{"name": "neutral", "files": ["tests/test_neutral.py"],
                        "reason": "reviewed neutral cases", "exclude_expression": "old_surface"}]}
    (tmp_path / "maintenance/qualification-plan.json").write_text(json.dumps(plan))
    captured = []
    monkeypatch.setattr(module.subprocess, "call", lambda args, **kw: captured.append(args) or 1)
    assert module.main() == 1
    assert captured[0][1] == str(tmp_path / "scripts/run-phase1-tests.py")
    assert captured[0][2:6] == ["tests/test_neutral.py", "--tb=short", "-k", "not (old_surface)"]
    result = json.loads((tmp_path / ".test-state/qualification-result.json").read_text())
    assert result["failed_groups"] == [{"name": "neutral", "exit_code": 1}]


def test_empty_qualification_is_not_success(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "maintenance").mkdir()
    (tmp_path / "maintenance/qualification-plan.json").write_text('{"groups": []}')
    with pytest.raises(SystemExit, match="No classified"):
        module.main()
