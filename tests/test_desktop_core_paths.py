"""Fresh profile defaults and bounded owned logging, with temporary paths only."""

import logging
import os
import stat
from pathlib import Path

import pytest

from src.desktop.paths import ProfilePaths, private_directory
from src.odin_log.logger import setup_logging
from src.planning.store import PlanStore
from src.runtime_paths import runtime_profile_paths
from src.scheduler.history import ScheduleHistory


def set_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("ODIN_DESKTOP_PROFILE", raising=False)
    for key, name in (("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                      ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(key, str(tmp_path / name))
    return ProfilePaths.from_xdg()


def test_default_plan_and_schedule_history_use_fresh_xdg_at_construction(monkeypatch, tmp_path):
    paths = set_xdg(monkeypatch, tmp_path)
    plans = PlanStore()
    history = ScheduleHistory()
    assert plans._path == paths.data_dir / "plans.json"
    assert history.path == paths.data_dir / "schedule_history.jsonl"
    assert not (tmp_path / "plans.json").exists()


def test_explicit_paths_remain_injected(tmp_path):
    assert PlanStore(str(tmp_path / "plans.json"))._path == tmp_path / "plans.json"
    assert ScheduleHistory(str(tmp_path / "history.jsonl")).path == tmp_path / "history.jsonl"


def test_selected_profile_is_used_by_default_stores(monkeypatch, tmp_path):
    set_xdg(monkeypatch, tmp_path)
    monkeypatch.setenv("ODIN_DESKTOP_PROFILE", "independent")
    paths = runtime_profile_paths()
    assert paths.profile_id == "independent"
    assert PlanStore()._path == paths.data_dir / "plans.json"
    assert ScheduleHistory().path == paths.data_dir / "schedule_history.jsonl"


def test_default_profile_directories_are_private(monkeypatch, tmp_path):
    paths = set_xdg(monkeypatch, tmp_path)
    PlanStore()
    ScheduleHistory()
    assert paths.data_dir.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("mode", [0o775, 0o755, 0o777, 0o1700])
def test_core_repairs_only_owned_namespace_directories(tmp_path, mode):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    ancestors = {}
    for profile in (paths.config_dir, paths.data_dir, paths.cache_dir):
        profile.mkdir(parents=True)
        profile.parent.chmod(mode)
        profile.chmod(mode)
        ancestor = profile.parent.parent
        ancestor.chmod(0o755)
        ancestors[ancestor] = ancestor.stat().st_mode
        if ancestor.name == "share":
            ancestor.parent.chmod(0o755)
            ancestors[ancestor.parent] = ancestor.parent.stat().st_mode
    paths.create_private()
    for profile in (paths.config_dir, paths.data_dir, paths.cache_dir):
        assert stat.S_IMODE(profile.stat().st_mode) == 0o700
        assert stat.S_IMODE(profile.parent.stat().st_mode) == 0o700
    assert all(path.stat().st_mode == mode for path, mode in ancestors.items())


@pytest.mark.parametrize("location", ["ancestor", "leaf", "invalid-profile", "secrets"])
@pytest.mark.parametrize("mode", [0o755, 0o775, 0o777, 0o1700])
def test_core_accepts_unrelated_directory_without_chmod(tmp_path, location, mode):
    if location == "ancestor":
        ancestor = tmp_path / "shared"
        ancestor.mkdir(mode=0o700)
        target = ancestor / "odin-desktop" / "default"
    elif location == "secrets":
        ancestor = tmp_path / "odin-desktop" / "default" / "secrets"
        ancestor.mkdir(parents=True, mode=0o700)
        ancestor.parent.chmod(0o700)
        ancestor.parent.parent.chmod(0o700)
        target = ancestor
    elif location == "invalid-profile":
        ancestor = tmp_path / "odin-desktop"
        ancestor.mkdir(mode=0o700)
        target = ancestor / "invalid.profile"
    else:
        ancestor = tmp_path / "custom"
        ancestor.mkdir(mode=0o700)
        target = ancestor
    ancestor.chmod(mode)
    private_directory(target)
    assert stat.S_IMODE(ancestor.stat().st_mode) == mode


@pytest.mark.parametrize("component", ["odin-desktop", "default"])
@pytest.mark.parametrize("owner", ["foreign", "root"])
def test_core_checks_namespace_owner_without_chmod_of_other_owners(
    tmp_path, monkeypatch, component, owner
):
    target = tmp_path / "odin-desktop" / "default"
    target.mkdir(parents=True)
    target.parent.chmod(0o700)
    foreign = target.parent if component == "odin-desktop" else target
    foreign.chmod(0o775)
    original = os.fstat
    inode = foreign.stat().st_ino

    def foreign_owner(fd):
        info = original(fd)
        if info.st_ino == inode:
            values = list(info)
            values[4] = 0 if owner == "root" else os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign_owner)
    if owner == "foreign":
        with pytest.raises(PermissionError, match="foreign"):
            private_directory(target)
    else:
        private_directory(target)
    assert stat.S_IMODE(foreign.stat().st_mode) == 0o775


@pytest.mark.parametrize("component", ["odin-desktop", "default"])
def test_core_follows_namespace_links_without_chmod_of_unrelated_target(tmp_path, component):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    outside.chmod(0o775)
    target = tmp_path / "odin-desktop" / "default"
    link = target.parent if component == "odin-desktop" else target
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    private_directory(target)
    assert target.is_dir()
    assert stat.S_IMODE(outside.stat().st_mode) == 0o775


def test_ssh_socket_parents_are_private_under_group_umask(tmp_path):
    from src.tools.ssh_pool import SSHConnectionPool

    ancestor = tmp_path / "cache"
    ancestor.mkdir(mode=0o755)
    before = ancestor.stat().st_mode
    directory = ancestor / "odin-desktop" / "default" / "ssh-sockets"
    previous = os.umask(0o002)
    try:
        pool = SSHConnectionPool(socket_dir=str(directory))
    finally:
        os.umask(previous)
    assert pool.socket_dir == str(directory)
    for path in (directory, directory.parent, directory.parent.parent):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert ancestor.stat().st_mode == before


def test_ssh_socket_parent_link_followed(tmp_path):
    from src.tools.ssh_pool import SSHConnectionPool

    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    link = tmp_path / "odin-desktop"
    link.symlink_to(outside, target_is_directory=True)
    directory = link / "default" / "ssh-sockets"
    pool = SSHConnectionPool(socket_dir=str(directory))
    assert pool.socket_dir == str(directory)
    assert (outside / "default" / "ssh-sockets").is_dir()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("relative", [False, True])
def test_configured_socket_directory_under_symlink_preserves_path_and_modes(
    tmp_path, monkeypatch, existing, relative
):
    from src.tools.ssh_pool import SSHConnectionPool

    parent = tmp_path / "disk"
    parent.mkdir()
    parent.chmod(0o775)
    link = tmp_path / "linked"
    link.symlink_to("disk", target_is_directory=True)
    directory = parent / "sockets"
    if existing:
        directory.mkdir()
        directory.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    spelling = "linked/sockets" if relative else str(link / "sockets")
    pool = SSHConnectionPool(socket_dir=spelling)
    assert pool.socket_dir == spelling
    assert pool.get_socket_path("lab", "operator") == f"{spelling}/operator@lab"
    assert stat.S_IMODE(directory.stat().st_mode) == (0o755 if existing else 0o700)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o775


@pytest.mark.parametrize("owner", ["foreign", "root"])
def test_directory_symlink_uses_target_owner_not_link_owner(tmp_path, monkeypatch, owner):
    target = tmp_path / "disk"
    target.mkdir()
    target.chmod(0o775)
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    original = os.fstat
    inode = target.stat().st_ino

    def target_owner(fd):
        info = original(fd)
        if info.st_ino == inode:
            values = list(info)
            values[4] = 0 if owner == "root" else os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", target_owner)
    if owner == "foreign":
        with pytest.raises(PermissionError, match="foreign") as refusal:
            private_directory(link / "private")
        assert refusal.value.filename == str(target)
        assert not (target / "private").exists()
    else:
        private_directory(link / "private")
        assert stat.S_IMODE((target / "private").stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o775


def test_private_directory_refuses_link_substitution_after_resolution(tmp_path, monkeypatch):
    from src.desktop import paths

    directory = tmp_path / "folder"
    directory.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o775)
    realpath = os.path.realpath

    def substitute_after_resolution(path):
        resolved = realpath(path)
        directory.rmdir()
        directory.symlink_to(outside, target_is_directory=True)
        return resolved

    monkeypatch.setattr(paths.os.path, "realpath", substitute_after_resolution)
    with pytest.raises(NotADirectoryError):
        private_directory(directory / "private")
    assert list(outside.iterdir()) == []
    assert stat.S_IMODE(outside.stat().st_mode) == 0o775


@pytest.mark.parametrize("mode", [0o755, 0o775, 0o777])
@pytest.mark.parametrize("namespace", [False, True])
def test_configured_existing_socket_directory_used_without_chmod(tmp_path, mode, namespace):
    from src.tools.ssh_pool import SSHConnectionPool

    directory = (tmp_path / "odin-desktop" / "default" if namespace
                 else tmp_path / "configured-sockets")
    directory.mkdir(parents=True)
    directory.chmod(mode)
    pool = SSHConnectionPool(socket_dir=str(directory))
    assert pool.socket_dir == str(directory)
    assert stat.S_IMODE(directory.stat().st_mode) == mode


def test_configured_new_socket_directory_under_writable_parent(tmp_path):
    from src.tools.ssh_pool import SSHConnectionPool

    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o775)
    directory = parent / "sockets"
    previous = os.umask(0o002)
    try:
        pool = SSHConnectionPool(socket_dir=str(directory))
    finally:
        os.umask(previous)
    assert pool.socket_dir == str(directory)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(parent.stat().st_mode) == 0o775


def test_configured_relative_socket_directory_preserves_upstream_path(tmp_path, monkeypatch):
    from src.tools.ssh_pool import SSHConnectionPool

    working = tmp_path / "working"
    working.mkdir()
    tmp_path.chmod(0o775)
    monkeypatch.chdir(working)
    pool = SSHConnectionPool(socket_dir="../sockets")
    assert pool.socket_dir == "../sockets"
    assert pool.get_socket_path("lab", "operator") == "../sockets/operator@lab"
    assert stat.S_IMODE((tmp_path / "sockets").stat().st_mode) == 0o700
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o775


def test_default_socket_directory_created_private_under_group_umask(tmp_path, monkeypatch):
    from src.config.schema import SSHPoolConfig
    from src.desktop.ssh_pool import SSHConnectionPool
    from src.desktop.ssh_sockets import socket_directory

    paths = set_xdg(monkeypatch, tmp_path)
    tmp_path.chmod(0o775)
    previous = os.umask(0o002)
    try:
        pool = SSHConnectionPool(socket_dir=SSHPoolConfig().socket_dir)
    finally:
        os.umask(previous)
    assert pool.socket_dir == socket_directory(paths)
    for path in (Path(pool.socket_dir), Path(pool.socket_dir).parent,
                 Path(pool.socket_dir).parent.parent):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o775


@pytest.mark.parametrize("location", ["ancestor", "leaf"])
@pytest.mark.parametrize("owner", ["foreign", "root"])
def test_configured_socket_directory_checks_foreign_nonroot_owner(
    tmp_path, monkeypatch, location, owner
):
    from src.tools.ssh_pool import SSHConnectionPool

    directory = tmp_path / "shared" / "sockets"
    directory.mkdir(parents=True)
    foreign = directory.parent if location == "ancestor" else directory
    inode = foreign.stat().st_ino
    original = os.fstat

    def foreign_owner(fd):
        info = original(fd)
        if info.st_ino == inode:
            values = list(info)
            values[4] = 0 if owner == "root" else os.geteuid() + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", foreign_owner)
    if owner == "foreign":
        with pytest.raises(PermissionError, match="foreign") as refusal:
            SSHConnectionPool(socket_dir=str(directory))
        assert refusal.value.filename == str(foreign)
    else:
        SSHConnectionPool(socket_dir=str(directory))


def test_logging_reinitialization_retires_only_owned_handlers(monkeypatch, tmp_path):
    paths = set_xdg(monkeypatch, tmp_path)
    root = logging.getLogger("odin")
    previous = list(root.handlers)
    root.handlers.clear()
    foreign = logging.NullHandler()
    root.addHandler(foreign)
    try:
        setup_logging()
        first = [h for h in root.handlers if getattr(h, "_odin_core_owned", False)]
        setup_logging()
        second = [h for h in root.handlers if getattr(h, "_odin_core_owned", False)]
        assert foreign in root.handlers
        assert len(second) == 2
        assert not any(h in root.handlers for h in first)
        files = [h for h in second if hasattr(h, "baseFilename")]
        assert len(files) == 1
        assert Path(files[0].baseFilename) == paths.data_dir / "logs" / "odin.log"
        assert files[0].maxBytes * (files[0].backupCount + 1) == 50 * 1024 * 1024
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if handler is not foreign:
                handler.close()
        root.handlers.extend(previous)
