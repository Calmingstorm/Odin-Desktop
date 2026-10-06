"""Offline guard behaviour only. Not native desktop qualification."""
import importlib.util
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_p33", ROOT / "scripts/qualification/lab/guest/native-p33-probe.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def environment():
    return {"XDG_RUNTIME_DIR": "/run/user/1001", "XDG_SESSION_TYPE": "x11", "DISPLAY": ":0",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1001/bus"}


def info(path):
    if str(path) == "/etc/odin-desktop-qualification":
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0)
    if str(path) in ("/run/user/1001/bus", "/tmp/.X11-unix/X0", "/run/user/1001/wayland-0"):
        return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=1001)
    return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1001)


@pytest.fixture
def guest():
    with patch.dict(os.environ, environment(), clear=True), \
            patch.object(MODULE.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=1001)), \
            patch.object(MODULE.os, "getuid", return_value=1001), \
            patch.object(Path, "stat", info), patch.object(Path, "lstat", info), \
            patch.object(Path, "read_text", return_value="odin-desktop-qualification-v1\n"), \
            patch.object(MODULE.socket, "gethostname", return_value="odq-cinnamon"), \
            patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
        yield


def test_valid_guest_guard_and_wayland(guest):
    assert MODULE.guard().pw_uid == 1001
    os.environ.update(XDG_SESSION_TYPE="wayland", WAYLAND_DISPLAY="wayland-0")
    assert MODULE.guard().pw_uid == 1001


@pytest.mark.parametrize("key,value", [
    ("DISPLAY", "host:0"), ("DBUS_SESSION_BUS_ADDRESS", "tcp:host=localhost,port=1234"),
    ("XDG_RUNTIME_DIR", "/tmp/host-runtime"), ("XDG_SESSION_TYPE", "tty"),
])
def test_foreign_session_environment_refused(guest, key, value):
    os.environ[key] = value
    with pytest.raises(RuntimeError):
        MODULE.guard()


def test_root_and_host_refused(guest):
    with patch.object(MODULE.os, "getuid", return_value=0), pytest.raises(RuntimeError):
        MODULE.guard()
    with patch.object(MODULE.socket, "gethostname", return_value="workstation"), pytest.raises(RuntimeError):
        MODULE.guard()
    with patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=1)), pytest.raises(RuntimeError):
        MODULE.guard()


def test_marker_contents_and_ownership_refused(guest):
    with patch.object(Path, "read_text", return_value="not-a-lab"), pytest.raises(RuntimeError):
        MODULE.guard()
    with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_uid=1001)), pytest.raises(RuntimeError):
        MODULE.guard()


def test_wayland_foreign_path_refused(guest):
    os.environ.update(XDG_SESSION_TYPE="wayland", WAYLAND_DISPLAY="/tmp/host-wayland")
    with pytest.raises(RuntimeError):
        MODULE.guard()


def session_module():
    spec = importlib.util.spec_from_file_location(
        "native_session", ROOT / "scripts/qualification/lab/guest/native-session.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_launcher_nonroot_and_nonvm_refuse():
    module = session_module()
    with patch.object(module.sys, "argv", ["native-session", "cinnamon"]), \
            patch.object(module.os, "geteuid", return_value=1001), pytest.raises(RuntimeError, match="guest root"):
        module.main()
    with patch.object(module.sys, "argv", ["native-session", "cinnamon"]), \
            patch.object(module.os, "geteuid", return_value=0), \
            patch.object(module.subprocess, "check_output", return_value="none\n"), \
            pytest.raises(RuntimeError, match="real lab VM"):
        module.main()


def test_session_launcher_wrong_guest_refuses_before_command():
    module = session_module()
    with patch.object(module.sys, "argv", ["native-session", "cinnamon", "--", "harmless"]), \
            patch.object(module.os, "geteuid", return_value=0), \
            patch.object(module.subprocess, "check_output", return_value="kvm\n"), \
            patch.object(Path, "read_text", return_value="workstation\n"), \
            patch.object(module.subprocess, "call") as called, \
            pytest.raises(RuntimeError, match="Guest name"):
        module.main()
    called.assert_not_called()
