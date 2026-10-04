"""The suite launcher is tested as a command plan, never as nested real sudo."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "desktop_isolated_runner", ROOT / "scripts/run-phase1-tests.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_namespaces_and_cleans_ambient_environment(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", ["runner", "tests/test_neutral.py"])
    monkeypatch.setenv("USER", "testowner")
    monkeypatch.setenv("DISPLAY", ":active-display")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "active-session")
    monkeypatch.setenv("DISCORD_TOKEN", "fixture-only-not-a-credential")
    captured = []
    monkeypatch.setattr(
        runner.subprocess, "call", lambda cmd, **kwargs: captured.append((cmd, kwargs)) or 0
    )
    assert runner.main() == 0
    command, options = captured[0]
    assert command[:8] == [
        "sudo", "-n", "unshare", "--mount", "--pid", "--fork", "--mount-proc", "--kill-child"
    ]
    assert command[8:15] == [
        "sudo", "-n", "-u", "testowner", "env", "-i",
        f"PATH={tmp_path / '.venv/bin'}:/usr/bin:/bin",
    ]
    assert options == {"cwd": tmp_path}
    assert not any(
        arg.startswith((
            "DISPLAY=", "DBUS_SESSION_BUS_ADDRESS=", "XDG_RUNTIME_DIR=", "DISCORD_TOKEN="
        ))
        for arg in command
    )
    assert f"HOME={tmp_path / '.test-state/home'}" in command
    assert f"XDG_DATA_HOME={tmp_path / '.test-state/data'}" in command
    assert command[-1] == "tests/test_neutral.py"
    assert "import subprocess,sys; raise SystemExit(subprocess.call(sys.argv[1:]))" in command
    assert "--timeout=90" in command
    assert "--timeout-method=signal" in command


def test_runner_refuses_an_empty_unclassified_selection(tmp_path, monkeypatch):
    import pytest

    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", ["runner"])
    (tmp_path / "maintenance").mkdir()
    (tmp_path / "maintenance/test-plan.json").write_text('{"safe_pass_now": []}')
    monkeypatch.setattr(
        runner.subprocess, "call", lambda *args, **kwargs: pytest.fail("must not execute")
    )
    with pytest.raises(SystemExit, match="unclassified"):
        runner.main()
