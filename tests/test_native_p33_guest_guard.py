"""Offline guard behaviour only. Not native desktop qualification."""

import importlib.util
import os
import socket
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
    with patch.object(MODULE.socket, "gethostname", return_value="workstation"), \
            pytest.raises(RuntimeError):
        MODULE.guard()
    with patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=1)), \
            pytest.raises(RuntimeError):
        MODULE.guard()


def test_marker_contents_and_ownership_refused(guest):
    with patch.object(Path, "read_text", return_value="not-a-lab"), pytest.raises(RuntimeError):
        MODULE.guard()
    with patch.object(Path, "lstat", return_value=SimpleNamespace(
            st_mode=stat.S_IFREG | 0o666, st_uid=1001)), pytest.raises(RuntimeError):
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
            patch.object(module.os, "geteuid", return_value=1001), \
            pytest.raises(RuntimeError, match="guest root"):
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


def test_capture_valid_existing_parent(tmp_path):
    root = tmp_path / "qualification"
    root.mkdir()
    nested = root / "screenshots"
    nested.mkdir()
    assert session_module().capture_target(str(nested / "new.png"), root) == nested / "new.png"


@pytest.mark.parametrize("escape", ["traversal", "parent-symlink", "leaf-symlink", "dangling"])
def test_capture_escape_refused(tmp_path, escape):
    root = tmp_path / "qualification"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if escape == "traversal":
        target = root / ".." / "outside" / "new.png"
    elif escape == "parent-symlink":
        (root / "link").symlink_to(outside, target_is_directory=True)
        target = root / "link" / "new.png"
    else:
        target = root / "new.png"
        destination = outside / "other.png"
        if escape == "leaf-symlink":
            destination.touch()
        target.symlink_to(destination)
    with pytest.raises(RuntimeError, match="Capture must stay"):
        session_module().capture_target(str(target), root)


def test_capture_missing_parent_and_symlink_root_refused(tmp_path):
    root = tmp_path / "qualification"
    root.mkdir()
    with pytest.raises(FileNotFoundError):
        session_module().capture_target(str(root / "missing" / "new.png"), root)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(RuntimeError, match="real directory"):
        session_module().capture_target(str(link / "new.png"), link)


@pytest.mark.parametrize("operation", sorted(MODULE.OPERATIONS))
def test_collector_allowlisted_request_real_peer(operation):
    # A real socketpair supplies kernel SO_PEERCRED, not a supplied request UID.
    client, server = socket.socketpair()
    with client, server:
        client.sendall((MODULE.json.dumps({"operation": operation}) + "\n").encode())
        dispatch = Mock(return_value={"observed": operation})
        result = MODULE.handle_request(server, os.getuid(), dispatch)
        assert result == {"ok": True, "result": {"observed": operation}}
        dispatch.assert_called_once_with({"operation": operation})


@pytest.mark.parametrize("payload", [
    b'{"operation":"command","cmd":"true"}\n',
    b'{"operation":"inspect"}\n{}\n',
    b"x" * (MODULE.MAX_REQUEST_BYTES + 1),
    b"[]\n", b"not-json\n",
])
def test_collector_invalid_frame_refuses_before_dispatch(payload):
    client, server = socket.socketpair()
    with client, server:
        client.sendall(payload)
        dispatch = Mock()
        assert MODULE.handle_request(server, os.getuid(), dispatch)["ok"] is False
        dispatch.assert_not_called()


def test_collector_foreign_uid_refused_before_read_or_dispatch():
    client, server = socket.socketpair()
    with client, server:
        dispatch = Mock()
        result = MODULE.handle_request(server, os.getuid() + 1, dispatch)
        assert result["ok"] is False and "Foreign" in result["error"]
        dispatch.assert_not_called()


def test_collector_slow_partial_frame_has_absolute_timeout():
    client, server = socket.socketpair()
    with client, server:
        client.sendall(b'{"operation":')
        with pytest.raises(TimeoutError):
            MODULE.read_request(server, os.getuid(), timeout=0.02)


def test_collector_total_deadline_not_reset_by_chunks():
    connection = Mock()
    connection.getsockopt.return_value = MODULE.struct.pack("3i", 123, 1001, 1001)
    connection.recv.return_value = b"{"
    with patch.object(MODULE.time, "monotonic", side_effect=[0, 1, 6]):
        with pytest.raises(TimeoutError, match="deadline"):
            MODULE.read_request(connection, 1001)
    assert connection.recv.call_count == 1
