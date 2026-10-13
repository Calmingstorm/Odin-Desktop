"""macOS platform selection, profile layout, socket path and the darwin primitives."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from src.desktop.platform import current_platform, darwin
from src.desktop.platform.macos import SOCKET_PATH_LIMIT, macos_profile_paths, macos_socket_path


def test_darwin_selects_the_macos_platform():
    platform = current_platform()
    assert (platform.name, platform.computer_supported) == ("macos", False)
    assert type(platform.ipc).__name__ == "MacOSIpc"


def test_the_profile_lives_under_library(tmp_path):
    paths = macos_profile_paths("work", home=tmp_path)
    support = tmp_path / "Library" / "odin-desktop" / "work"
    assert paths.config_dir == support / "config"
    assert paths.data_dir == support / "data"
    assert paths.cache_dir == tmp_path / "Library" / "Caches" / "odin-desktop" / "work"
    assert paths.secrets_dir == paths.data_dir / "secrets"


@pytest.mark.parametrize("profile", ["", "-x", "a" * 65, "with space", "../up"])
def test_invalid_profiles_are_refused(tmp_path, profile):
    with pytest.raises(ValueError):
        macos_profile_paths(profile, home=tmp_path)


def test_a_relative_home_is_refused():
    with pytest.raises(ValueError):
        macos_profile_paths("default", home=Path("relative/home"))


def test_no_profile_path_has_whitespace(tmp_path):
    """OpenSSH splits -o UserKnownHostsFile values on whitespace: profile paths must have none."""
    paths = macos_profile_paths("default", home=tmp_path)
    for path in (paths.config_dir, paths.data_dir, paths.cache_dir, paths.secrets_dir):
        assert not any(character.isspace() for character in str(path)), path
    with pytest.raises(ValueError, match="whitespace"):
        macos_profile_paths("default", home=tmp_path / "with space")


def test_the_socket_lives_in_the_verified_private_temp_folder():
    root = darwin.user_temp_root()
    info = os.lstat(root)
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
    assert stat.S_IMODE(info.st_mode) == 0o700
    assert str(root).startswith("/private/")  # canonical, not the /var link
    path = macos_socket_path("default")
    assert path == root / "odin-desktop" / "default" / "core.sock"
    assert len(os.fsencode(path)) <= SOCKET_PATH_LIMIT


def test_an_overlong_socket_path_is_refused_not_shortened(tmp_path):
    with pytest.raises(ValueError, match="longer than macOS allows"):
        macos_socket_path("default", root=tmp_path / ("x" * 90))


def test_boot_identity_has_the_linux_shape():
    from src.desktop.resource_cleanup import current_boot_id

    value = current_boot_id()
    assert value is not None and re.fullmatch(r"[0-9a-f-]{36}", value)
    assert current_boot_id.darwin_target == "src.desktop.platform.darwin:current_boot_id"


def test_descriptor_usage_is_measured_not_unavailable():
    from src.health.checker import _process_descriptor_usage

    descriptors, soft_limit = _process_descriptor_usage()
    assert 0 < descriptors < soft_limit


def test_process_identity_is_readable_for_this_process():
    identity = darwin.process_identity(os.getpid())
    assert identity is not None and identity.pid == os.getpid() and identity.uniqueid > 0


def test_the_platform_members():
    from src.desktop.lifecycle import CoreLifetime
    from src.desktop.platform.macos_secrets import KeychainBackend
    from src.tools.workspace import resolve_workspace

    platform = current_platform()
    assert isinstance(platform.secret_backend(None), KeychainBackend)
    assert isinstance(platform.core_lifetime(), CoreLifetime)
    assert platform.ipc is platform.ipc  # one transport per platform object
    paths = platform.profile_paths("default", home=Path("/Users/someone"))
    assert paths.config_dir == Path(
        "/Users/someone/Library/odin-desktop/default/config")
    assert resolve_workspace.__name__ == "resolve_workspace"


def test_a_folder_that_is_not_private_is_refused_as_the_temp_root(monkeypatch, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    monkeypatch.setattr(darwin.os.path, "realpath", lambda value: str(shared))
    with pytest.raises(PermissionError, match="not private"):
        darwin.user_temp_root()


def test_the_peer_of_a_socket_pair_is_this_user():
    import socket

    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        assert darwin.peer_uid(left) == os.geteuid()
    finally:
        left.close()
        right.close()
    with pytest.raises(OSError):
        darwin.peer_uid(left)  # closed: the kernel's error, never a guessed UID


def test_a_gone_process_has_no_identity_and_a_missing_symbol_is_enosys(monkeypatch):
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert darwin.process_identity(child.pid) is None
    monkeypatch.setattr(darwin, "_signal_by_token", None)
    assert darwin.signal_identity(darwin.ProcessIdentity(1, 1, 1), 0) == darwin.errno.ENOSYS
