"""Rootless focused probe guards: imports do not touch a session or AT-SPI."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/qualification/lab/guest/focused_probe.py"
spec = importlib.util.spec_from_file_location("focused_probe_test", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.parametrize("mode", ["suite", "", "seven", "electron;reboot"])
def test_focused_mode_rejects_before_guest_guard(mode, monkeypatch):
    monkeypatch.setattr(probe, "guard", lambda: pytest.fail("guest guard must not run"))
    with pytest.raises(ValueError, match="Only focused"):
        probe.run(mode)


def test_speech_is_only_native_debug_records():
    text = (
        "fake SPEECH OUTPUT: Probe message button\n"
        "01:02:03.123456 - SPEECH OUTPUT: 'actual text'\nother line\n"
    )
    assert probe.speech_records(text) == ["01:02:03.123456 - SPEECH OUTPUT: 'actual text'"]


def test_keyboard_guard_precedes_any_import_or_device(monkeypatch):
    def refused():
        raise RuntimeError("not actual guest")

    monkeypatch.setattr(probe, "guard", refused)
    with pytest.raises(RuntimeError, match="not actual guest"):
        probe.key("Tab")


def test_snapshot_guard_precedes_a11y_bus_import(monkeypatch):
    def refused():
        raise RuntimeError("not actual guest")

    monkeypatch.setattr(probe, "guard", refused)
    with pytest.raises(RuntimeError, match="not actual guest"):
        probe.snapshot()


def test_probe_launch_is_one_native_sandboxed_app_not_suite():
    source = SOURCE.with_name("focused_electron.cjs").read_text()
    assert source.count("_electron.launch(") == 1
    assert "chromiumSandbox: true" in source
    assert "--ozone-platform=${env.ODIN_ORCA_DESKTOP === 'cinnamon' ? 'x11' : 'wayland'}" in source
    assert "ELECTRON_ENABLE_LOGGING: '1'" in source
    assert "--no-sandbox" not in source
    assert "orca.spec" not in source


@pytest.mark.parametrize("mode", ["electron", "gtk-electron", "native-attach", "native-files"])
def test_modes_use_one_launch_and_keep_nonqualification_proof(mode, monkeypatch, tmp_path):
    monkeypatch.setenv("ODIN_ORCA_ROOT", str(tmp_path))
    monkeypatch.setenv("ODIN_ORCA_EVIDENCE", str(tmp_path))
    monkeypatch.setenv("ODIN_ORCA_LOG", str(tmp_path / "orca.log"))
    monkeypatch.setattr(probe, "guard", lambda: {"actual_guest": True})
    monkeypatch.setattr(probe, "measure_gtk", lambda *_: {"passed": True})
    calls = []

    def launch(argv, **kwargs):
        calls.append((argv, kwargs))
        assert argv == [str(tmp_path / "bin/node"), str(SOURCE.with_name("focused_electron.cjs"))]
        assert kwargs["cwd"] == tmp_path / "app"
        assert kwargs["timeout"] == (360 if mode == "native-files" else 150)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(probe.subprocess, "run", launch)
    assert probe.run(mode) == 0
    assert len(calls) == 1
    proof = json.loads((tmp_path / "probe-result.json").read_text())
    assert proof["kind"] == "focused-probes-not-qualification"
    assert proof["probe"] == mode
    assert proof["passed"] is True
    assert "tasks" not in proof


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_native_files_failure_retains_proof_without_relaunch(failure, monkeypatch, tmp_path):
    paths = {"ROOT": tmp_path, "EVIDENCE": tmp_path, "LOG": tmp_path / "orca.log"}
    for name, value in paths.items():
        monkeypatch.setenv(f"ODIN_ORCA_{name}", str(value))
    monkeypatch.setattr(probe, "guard", lambda: {"actual_guest": True})
    calls = []

    def launch(argv, **kwargs):
        calls.append(argv)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(probe.subprocess, "run", launch)
    assert probe.run("native-files") == 1
    assert len(calls) == 1
    proof = json.loads((tmp_path / "probe-result.json").read_text())
    assert proof["passed"] is False
    assert proof["probe"] == "native-files"
    assert proof["kind"] == "focused-probes-not-qualification"


@pytest.mark.parametrize("title", ["Attach files", "Save file"])
def test_dialog_snapshot_uses_existing_bound_native_helper(title, monkeypatch, tmp_path):
    monkeypatch.setenv("ODIN_ORCA_ROOT", str(tmp_path))
    calls = []
    monkeypatch.setattr(probe, "guard", lambda: calls.append("guard"))
    binding = SimpleNamespace(
        record={"peer": ":1.2", "path": "/measured/source"},
        revalidate=lambda name: calls.append(("revalidate", name)),
    )

    def active(name):
        calls.append(("active", name))
        return binding

    loader = SimpleNamespace(exec_module=lambda module: setattr(module, "active_dialog", active))
    monkeypatch.setattr(
        probe.importlib.util,
        "spec_from_file_location",
        lambda name, path: SimpleNamespace(loader=loader),
    )
    monkeypatch.setattr(probe.importlib.util, "module_from_spec", lambda _: SimpleNamespace())
    assert probe.dialog_snapshot(title) == binding.record
    assert calls == ["guard", ("active", title), ("revalidate", title)]


def test_dialog_snapshot_guard_precedes_helper_loading(monkeypatch):
    def refused():
        raise RuntimeError("not actual guest")

    monkeypatch.setattr(probe, "guard", refused)
    with pytest.raises(RuntimeError, match="not actual guest"):
        probe.dialog_snapshot("Save file")
