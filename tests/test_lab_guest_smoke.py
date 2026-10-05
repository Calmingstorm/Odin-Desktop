"""Guest smoke logic runs against fake guest/session evidence, never a desktop."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "guest_smoke", ROOT / "scripts/qualification/lab/guest/smoke.py",
)
guest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guest)


def test_logind_requires_odq_active_graphical_session(monkeypatch):
    calls = []
    def command(*args):
        calls.append(args)
        if args[1] == "list-sessions":
            return json.dumps([{"user": "other", "session": "1"},
                               {"user": "odq", "session": "2"}])
        return "Type=wayland\nActive=yes\nDesktop=GNOME\nState=active"
    monkeypatch.setattr(guest, "command", command)
    assert guest.session_info()["Type"] == "wayland"
    assert calls[1][2] == "2"
    monkeypatch.setattr(guest, "command", lambda *a: "[]")
    with pytest.raises(RuntimeError, match="No active odq"):
        guest.session_info()


@pytest.mark.parametrize("desktop,session", [
    ("gnome", {"Type": "x11", "Desktop": "GNOME"}),
    ("gnome", {"Type": "wayland", "Desktop": "KDE"}),
])
def test_wrong_session_type_or_desktop_cannot_pass(monkeypatch, desktop, session):
    monkeypatch.setattr(guest, "command", lambda *a: "kvm")
    monkeypatch.setattr(guest.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1000))
    monkeypatch.setattr(guest, "session_info", lambda: session)
    with pytest.raises(RuntimeError):
        guest.smoke(desktop)


def test_smoke_cannot_execute_outside_vm(monkeypatch):
    monkeypatch.setattr(guest, "command", lambda *a: "none")
    with pytest.raises(RuntimeError, match="requires a VM"):
        guest.smoke("gnome")


@pytest.mark.parametrize("capture_kind", ["good", "uniform", "bad", "small", "listener"])
def test_smoke_validates_capture_and_listeners(tmp_path, monkeypatch, capture_kind):
    actual_path = Path
    screenshot = tmp_path / "guest.png"
    monkeypatch.setattr(guest, "Path", lambda _: screenshot)
    monkeypatch.setattr(guest, "session_info", lambda: {"Type": "wayland", "Desktop": "GNOME"})
    monkeypatch.setattr(guest, "session_environment", lambda *a: {
        "XDG_SESSION_TYPE": "wayland", "DBUS_SESSION_BUS_ADDRESS": "unix:path=guest-only",
    })
    monkeypatch.setattr(guest.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1000))
    def command(*args):
        if args[0] == "systemd-detect-virt":
            return "kvm"
        if args[0] == "pgrep":
            return "123"
        if capture_kind == "listener":
            return 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd"))'
        return "tcp LISTEN 0 128 127.0.0.1:631 0.0.0.0:*"
    monkeypatch.setattr(guest, "command", command)
    calls = []
    def capture(argv, **kwargs):
        calls.append(argv)
        if capture_kind == "bad":
            screenshot.write_bytes(b"not png")
        else:
            size = (50, 50) if capture_kind == "small" else (800, 600)
            image = Image.new("RGB", size)
            if capture_kind != "uniform":
                image.putpixel((1, 1), (255, 255, 255))
            image.save(screenshot)
        return SimpleNamespace(stdout="actual guest helper output")
    monkeypatch.setattr(guest.subprocess, "run", capture)
    if capture_kind == "good":
        proof = guest.smoke("gnome")
        assert proof["passed"] is True
        assert "not verified speech" in proof["limits"]
        assert "env" in calls[0] and "-i" in calls[0]
        assert calls[0][-2:] == ["/usr/local/lib/odq/capture", str(screenshot)]
        assert actual_path(screenshot).is_file()
    else:
        with pytest.raises((RuntimeError, OSError)):
            guest.smoke("gnome")
