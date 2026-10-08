"""Round F socket regression/security proofs inside test isolation only."""
import os
import socket
import stat
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from src.config.schema import Config, SSHPoolConfig
from src.desktop.paths import ProfilePaths
from src.desktop.provisioning import ensure_profile, fresh_config_document
from src.desktop.settings import SettingsService
from src.desktop.ssh_pool import SSHConnectionPool
from src.desktop.ssh_sockets import (
    OPENSSH_TEMP_SUFFIX_BYTES,
    REGISTRY_SOCKET_NAME,
    SOCKET_PATH_LIMIT,
    check_socket_path,
    effective_socket_directory,
    prepare_socket_directory,
    socket_directory,
)


@pytest.fixture
def runtime(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="r", dir="/tmp") as root:
        monkeypatch.setenv("XDG_RUNTIME_DIR", root)
        yield Path(root)


@pytest.mark.parametrize("profile", ["default", "x" * 64])
def test_fresh_long_home_bounded_and_real_socket_bind(runtime, profile):
    paths = ProfilePaths.from_xdg(profile, environ={}, home="/home/" + "long" * 60)
    directory = fresh_config_document(paths)["tools"]["ssh_pool"]["socket_dir"]
    assert directory == socket_directory(paths)
    assert directory.startswith(str(runtime) + "/odin-desktop/")
    final = directory + "/" + REGISTRY_SOCKET_NAME
    assert len(os.fsencode(final)) + OPENSSH_TEMP_SUFFIX_BYTES <= SOCKET_PATH_LIMIT
    prepare_socket_directory(directory)
    temporary = final + "." + "x" * 16
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(temporary)
    Path(temporary).unlink()
    for folder in (Path(directory), Path(directory).parent, Path(directory).parent.parent):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_saved_default_corrected_without_writing_yaml(runtime, tmp_path, monkeypatch):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    paths.create_private()
    from src.desktop.authority import OwnerAuthority

    authority = OwnerAuthority(paths)
    legacy = str(paths.cache_dir / "ssh-sockets")
    paths.config_file.write_text(yaml.safe_dump({"tools": {
        "ssh_key_path": str(tmp_path / "custom-key"),
        "ssh_pool": {"socket_dir": legacy},
    }}))
    paths.config_file.chmod(0o600)
    before = paths.config_file.read_bytes()
    from src.desktop import provisioning

    monkeypatch.setattr(provisioning, "_ensure_ssh_key", Mock())
    config = ensure_profile(paths, authority=authority)
    assert config.tools.ssh_pool.socket_dir == socket_directory(paths)
    settings = SettingsService(paths, Mock())
    assert settings.config.tools.ssh_pool.socket_dir == socket_directory(paths)
    desired, _ = settings._prepare(
        [(('tools', 'ssh_pool', 'socket_dir'), legacy)], 'settings.set'
    )
    assert desired.tools.ssh_pool.socket_dir == socket_directory(paths)
    assert paths.config_file.read_bytes() == before
    authority.release_runtime()
    aaron = ProfilePaths.from_xdg(environ={}, home="/home/calmingstorm")
    assert effective_socket_directory(
        "/home/calmingstorm/.cache/odin-desktop/default/ssh-sockets", aaron
    ) == socket_directory(aaron)


@pytest.mark.parametrize("value", ["/tmp/custom-ssh", "custom/sockets", "/custom/" + "x" * 90])
def test_custom_spelling_never_migrated(runtime, value):
    paths = ProfilePaths.from_xdg(environ={}, home="/home/calmingstorm")
    assert effective_socket_directory(value, paths) == value
    settings = SettingsService(paths, Mock(), config=Config.model_validate({
        "tools": {"ssh_pool": {"socket_dir": value}}
    }))
    assert settings.config.tools.ssh_pool.socket_dir == value


def test_schema_default_executor_adapter(runtime):
    assert SSHPoolConfig().socket_dir.startswith(str(runtime) + "/odin-desktop/")


@pytest.mark.parametrize("extra", [0, 1])
def test_guard_suffix_exact_limit(extra):
    path = "/" + "a" * (SOCKET_PATH_LIMIT - OPENSSH_TEMP_SUFFIX_BYTES - 1 + extra)
    if extra:
        with pytest.raises(ValueError, match="temporary suffix; maximum 107"):
            check_socket_path(path)
    else:
        check_socket_path(path)


def test_guard_bytes_not_characters():
    with pytest.raises(ValueError, match="too long"):
        check_socket_path("/" + "é" * 46)
    with pytest.raises(ValueError, match="invalid"):
        check_socket_path("/tmp/a\0b")


def test_custom_guard_before_directory_creation(runtime, tmp_path):
    directory = str(tmp_path / ("custom" * 20))
    with pytest.raises(ValueError, match="Choose a shorter tools.ssh_pool.socket_dir"):
        SSHConnectionPool(socket_dir=directory)
    assert not Path(directory).exists()


def test_relative_guard_absolute_runtime_path(runtime, tmp_path, monkeypatch):
    working = tmp_path / ("long" * 20)
    working.mkdir()
    monkeypatch.chdir(working)
    with pytest.raises(ValueError, match="too long"):
        SSHConnectionPool(socket_dir="s")
    assert not (working / "s").exists()


def test_short_relative_symlink_modes_preserved(runtime, monkeypatch):
    target = runtime / "t"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    (runtime / "l").symlink_to(target)
    monkeypatch.chdir(runtime)
    pool = SSHConnectionPool(socket_dir="l")
    assert pool.socket_dir == "l"
    assert pool.get_socket_path("lab", "me") == "l/me@lab"
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    with pytest.raises(ValueError, match="too long"):
        pool.get_socket_path("x" * 100, "me")


@pytest.mark.parametrize("kind", ["absent", "relative", "missing", "public", "symlink", "long"])
def test_unusable_xdg_private_fallback(runtime, monkeypatch, kind):
    if kind == "absent":
        monkeypatch.delenv("XDG_RUNTIME_DIR")
    elif kind == "relative":
        monkeypatch.setenv("XDG_RUNTIME_DIR", "relative")
    elif kind == "missing":
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime / "missing"))
    elif kind == "public":
        runtime.chmod(0o755)
    elif kind == "symlink":
        link = runtime / "link"
        link.symlink_to(runtime)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(link))
    else:
        long = runtime / ("x" * 90)
        long.mkdir(mode=0o700)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(long))
    paths = ProfilePaths.from_xdg(environ={}, home="/home/calmingstorm")
    value = socket_directory(paths)
    assert value == f"/tmp/odin-desktop-{os.geteuid()}/default/ssh"
    pool = SSHConnectionPool(socket_dir=value)
    assert pool.socket_dir == value
    for folder in (Path(value), Path(value).parent, Path(value).parent.parent):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700


@pytest.mark.parametrize("component", ["odin-desktop", "default", "ssh"])
@pytest.mark.parametrize("kind", ["symlink", "public", "foreign", "root"])
def test_planted_namespace_rejected_no_chmod(runtime, monkeypatch, component, kind):
    directory = runtime / "odin-desktop" / "default" / "ssh"
    target = {"odin-desktop": directory.parent.parent,
              "default": directory.parent, "ssh": directory}[component]
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    outside = runtime / "outside"
    outside.mkdir(mode=0o700)
    if kind == "symlink":
        target.symlink_to(outside)
    else:
        target.mkdir(mode=0o700)
        if kind == "public":
            target.chmod(0o755)
        else:
            real = os.fstat
            inode = target.stat().st_ino

            def owner(fd):
                info = real(fd)
                if info.st_ino == inode:
                    values = list(info)
                    values[4] = 0 if kind == "root" else os.geteuid() + 1
                    return os.stat_result(values)
                return info

            monkeypatch.setattr(os, "fstat", owner)
    before = target.stat().st_mode
    with pytest.raises(OSError):
        prepare_socket_directory(str(directory))
    assert target.stat().st_mode == before
    assert list(outside.iterdir()) == []


def test_xdg_owner_late_mode_change_refused(runtime, monkeypatch):
    paths = ProfilePaths.from_xdg(environ={}, home="/home/calmingstorm")
    directory = socket_directory(paths)
    runtime.chmod(0o755)
    with pytest.raises(PermissionError, match="XDG runtime root"):
        prepare_socket_directory(directory)
    runtime.chmod(0o700)
    real = os.fstat
    inode = runtime.stat().st_ino

    def foreign(fd):
        info = real(fd)
        if info.st_ino == inode:
            values = list(info)
            values[4] = os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign)
    assert socket_directory(paths).startswith(f"/tmp/odin-desktop-{os.geteuid()}/")


def test_fallback_planted_uid_namespace_not_followed(runtime, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    namespace = Path(f"/tmp/odin-desktop-{os.geteuid()}")
    backup = namespace.with_name(namespace.name + "-saved")
    if namespace.exists():
        namespace.rename(backup)
    namespace.symlink_to(runtime)
    try:
        with pytest.raises(OSError):
            prepare_socket_directory(str(namespace / "default" / "ssh"))
        assert list(runtime.iterdir()) == []
    finally:
        namespace.unlink()
        if backup.exists():
            backup.rename(namespace)
