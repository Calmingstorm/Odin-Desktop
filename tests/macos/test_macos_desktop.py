"""SSH control-socket paths on macOS: the 103-byte bound and the /private/tmp fallback."""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import uuid
from pathlib import Path

import pytest

from src.desktop import ssh_sockets
from src.desktop.platform import macos_desktop
from src.desktop.platform.macos import macos_profile_paths


@pytest.fixture
def profile(tmp_path):
    name = f"t{uuid.uuid4().hex[:10]}"
    yield macos_profile_paths(name, home=tmp_path)
    shutil.rmtree(macos_desktop._fallback_root() / name, ignore_errors=True)


def test_the_routes_reach_the_macos_variants():
    target = "src.desktop.platform.macos_desktop:"
    assert ssh_sockets.check_socket_path.darwin_target == target + "check_socket_path"
    assert ssh_sockets.socket_directory.darwin_target == target + "socket_directory"
    assert ssh_sockets.prepare_socket_directory.darwin_target == target + "prepare_socket_directory"


def test_the_bound_keeps_room_for_the_openssh_suffix():
    base = "/private/tmp/" + "x" * (103 - 17 - len("/private/tmp/"))
    ssh_sockets.check_socket_path(base)  # exactly at the bound
    with pytest.raises(ValueError, match="maximum 103"):
        ssh_sockets.check_socket_path(base + "x")
    with pytest.raises(ValueError):
        ssh_sockets.check_socket_path("/private/tmp/a\0b")


def test_the_default_falls_back_to_private_tmp_and_is_created_private(profile, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    provisioned = str(profile.cache_dir / "ssh-sockets")
    assert not ssh_sockets._fits(provisioned)  # Library/Caches is too long for a socket
    chosen = ssh_sockets.effective_socket_directory(provisioned, profile)
    expected = macos_desktop._fallback_root() / profile.profile_id / "ssh"
    assert chosen == str(expected)
    ssh_sockets.prepare_socket_directory(chosen)
    for path in (expected, expected.parent, expected.parent.parent):
        info = os.lstat(path)
        assert info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700
    ssh_sockets.prepare_socket_directory(chosen)  # idempotent


def test_a_long_profile_uses_the_compact_namespace(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    paths = macos_profile_paths("p" * 60, home=tmp_path)
    chosen = Path(macos_desktop.socket_directory(paths))
    assert chosen.parent.name.startswith("p-") and len(chosen.parent.name) == 14


def test_a_private_xdg_runtime_root_is_preferred(tmp_path, monkeypatch):
    # Short names: the runtime root's socket path must fit the 103-byte bound itself.
    runtime = Path(tempfile.mkdtemp(prefix="o", dir="/private/tmp"))  # mode 0700
    profile = macos_profile_paths("x" + uuid.uuid4().hex[:3], home=tmp_path)
    try:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        chosen = macos_desktop.socket_directory(profile)
        assert chosen == str(runtime / "odin-desktop" / profile.profile_id / "ssh")
        macos_desktop.prepare_socket_directory(chosen)
        assert stat.S_IMODE(os.lstat(chosen).st_mode) == 0o700
        runtime.chmod(0o755)  # no longer private: refused, never repaired
        with pytest.raises(PermissionError, match="Unsafe Desktop SSH XDG runtime root"):
            macos_desktop.prepare_socket_directory(chosen)
    finally:
        runtime.chmod(0o700)
        shutil.rmtree(runtime, ignore_errors=True)


def test_a_planted_fallback_namespace_is_refused(profile, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    root = macos_desktop._fallback_root()
    root.mkdir(mode=0o700, exist_ok=True)
    planted = root / profile.profile_id
    planted.mkdir(mode=0o755)  # not this user's exact 0700
    with pytest.raises(PermissionError, match="Unsafe Desktop SSH runtime directory"):
        macos_desktop.prepare_socket_directory(str(planted / "ssh"))
    assert stat.S_IMODE(os.lstat(planted).st_mode) == 0o755  # never chmodded


def test_a_custom_directory_keeps_pool_policy(tmp_path):
    custom = tmp_path / "custom" / "ssh"
    macos_desktop.prepare_socket_directory(str(custom))
    assert not custom.exists()  # neither managed root: nothing created here


def test_no_bounded_directory_is_an_error(profile, monkeypatch):
    monkeypatch.setattr(ssh_sockets, "_fits", lambda candidate: False)
    with pytest.raises(ValueError, match="No bounded Desktop SSH runtime directory"):
        macos_desktop.socket_directory(profile)
