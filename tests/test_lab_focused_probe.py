"""Rootless focused probe guards: imports do not touch a session or AT-SPI."""

import importlib.util
from pathlib import Path

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
