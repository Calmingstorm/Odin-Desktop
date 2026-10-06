"""Guest smoke logic runs against fake guest/session evidence, never a desktop."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "guest_smoke",
    ROOT / "scripts/qualification/lab/guest/smoke.py",
)
guest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guest)


def test_logind_requires_odq_active_graphical_session(monkeypatch):
    calls = []

    def command(*args):
        calls.append(args)
        if args[1] == "list-sessions":
            assert args[2:] == ("--no-legend", "--no-pager")
            return "1 1001 other seat0 tty1\n2 1000 odq seat0 tty2\n"
        return "Type=wayland\nActive=yes\nDesktop=GNOME\nState=active"

    monkeypatch.setattr(guest, "command", command)
    assert guest.session_info()["Type"] == "wayland"
    assert calls[1][2] == "2"
    monkeypatch.setattr(guest, "command", lambda *a: "")
    with pytest.raises(RuntimeError, match="No active odq"):
        guest.session_info()


def test_logind_rejects_malformed_other_or_inactive_sessions(monkeypatch):
    def command(*args):
        if args[1] == "list-sessions":
            return "bad\n1 1001 other seat0 tty1\n2 1000 odq seat0 tty2\n"
        assert args[2] == "2"
        return "Type=x11\nActive=no\nDesktop=Cinnamon\nState=online"

    monkeypatch.setattr(guest, "command", command)
    with pytest.raises(RuntimeError, match="No active odq"):
        guest.session_info()


def test_session_environment_skips_display_manager_incomplete_environment(tmp_path, monkeypatch):
    processes = tmp_path / "proc"
    processes.mkdir()
    base = {
        "DISPLAY": ":0",
        "XDG_SESSION_TYPE": "x11",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    }
    for pid, environment in (("1", base), ("2", {**base, "XDG_CURRENT_DESKTOP": "X-Cinnamon"})):
        process = processes / pid
        process.mkdir()
        (process / "environ").write_bytes(
            b"\0".join(f"{key}={value}".encode() for key, value in environment.items())
        )
    real_path = Path
    monkeypatch.setattr(
        guest, "Path", lambda path: processes if path == "/proc" else real_path(path)
    )
    result = guest.session_environment(processes.stat().st_uid, "x11")
    assert result["XDG_CURRENT_DESKTOP"] == "X-Cinnamon"
    assert result["DISPLAY"] == ":0"


@pytest.mark.parametrize(
    "desktop,session",
    [
        ("gnome", {"Type": "x11", "Desktop": "GNOME"}),
        ("gnome", {"Type": "wayland", "Desktop": "KDE"}),
    ],
)
def test_wrong_session_type_or_desktop_cannot_pass(monkeypatch, desktop, session):
    monkeypatch.setattr(guest, "command", lambda *a: "kvm")
    monkeypatch.setattr(guest.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1000))
    monkeypatch.setattr(guest, "session_info", lambda: session)
    monkeypatch.setattr(guest, "session_environment", lambda *a: {})
    with pytest.raises(RuntimeError):
        guest.smoke(desktop)


@pytest.mark.parametrize("shell_ready", [True, False])
def test_wayland_requires_real_shell_display_not_early_compositor(
    tmp_path, monkeypatch, shell_ready
):
    processes = tmp_path / "proc"
    processes.mkdir()
    base = {
        "WAYLAND_DISPLAY": "wayland-0",
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "GNOME",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    }
    candidates = (
        [base, {**base, "DISPLAY": ":0"}]
        if shell_ready
        else [base, {**base, "XDG_SESSION_TYPE": "x11", "DISPLAY": ":1"}]
    )
    for number, environment in enumerate(candidates, 1):
        process = processes / str(number)
        process.mkdir()
        (process / "environ").write_bytes(
            b"\0".join(f"{key}={value}".encode() for key, value in environment.items())
        )
    real_path = Path
    monkeypatch.setattr(
        guest, "Path", lambda path: processes if path == "/proc" else real_path(path)
    )
    if shell_ready:
        selected = guest.session_environment(processes.stat().st_uid, "wayland")
        assert selected["DISPLAY"] == ":0"
        assert selected["WAYLAND_DISPLAY"] == "wayland-0"
        assert selected["XDG_SESSION_TYPE"] == "wayland"
    else:
        with pytest.raises(RuntimeError, match="No graphical session environment"):
            guest.session_environment(processes.stat().st_uid, "wayland")


def test_smoke_cannot_execute_outside_vm(monkeypatch):
    monkeypatch.setattr(guest, "command", lambda *a: "none")
    with pytest.raises(RuntimeError, match="requires a VM"):
        guest.smoke("gnome")


@pytest.mark.parametrize(
    "capture_kind",
    [
        "good",
        "empty_desktop",
        "loopback",
        "uniform",
        "bad",
        "small",
        "listener",
    ],
)
def test_smoke_validates_capture_and_listeners(tmp_path, monkeypatch, capture_kind):
    actual_path = Path
    screenshot = tmp_path / "guest.png"
    monkeypatch.setattr(guest, "Path", lambda _: screenshot)
    monkeypatch.setattr(
        guest,
        "session_info",
        lambda: {
            "Type": "wayland",
            "Desktop": "" if capture_kind == "empty_desktop" else "GNOME",
        },
    )
    monkeypatch.setattr(
        guest,
        "session_environment",
        lambda *a: {
            "XDG_SESSION_TYPE": "wayland",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=guest-only",
            "XDG_CURRENT_DESKTOP": "GNOME",
        },
    )
    monkeypatch.setattr(guest.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1000))

    def command(*args):
        if args[0] == "systemd-detect-virt":
            return "kvm"
        if args[0] == "pgrep":
            if capture_kind == "empty_desktop" and "-x" in args:
                assert args[-1] == "gnome-shell"
            return "123"
        if capture_kind == "listener":
            return 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd"))'
        if capture_kind == "loopback":
            return "udp UNCONN 0 0 127.0.0.54:53 0.0.0.0:*\nudp UNCONN 0 0 [::1]:53 [::]:*"
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
    if capture_kind in ("good", "loopback", "empty_desktop"):
        proof = guest.smoke("gnome")
        assert proof["passed"] is True
        assert "not verified speech" in proof["limits"]
        assert "env" in calls[0] and "-i" in calls[0]
        assert calls[0][-2:] == ["/usr/local/lib/odq/capture", str(screenshot)]
        assert actual_path(screenshot).is_file()
    else:
        with pytest.raises((RuntimeError, OSError)):
            guest.smoke("gnome")
