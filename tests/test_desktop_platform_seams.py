"""The Desktop engine's operating-system seams keep Linux exactly as it was."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.desktop import platform as desktop_platform
from src.desktop.paths import ProfilePaths
from src.desktop.platform import current_platform, locks
from src.desktop.platform.linux import LinuxPlatform

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh_platform():
    current_platform.cache_clear()
    yield
    current_platform.cache_clear()


def test_linux_is_chosen_once(fresh_platform):
    first = current_platform()
    assert isinstance(first, LinuxPlatform) and first.name == "linux"
    assert current_platform() is first


@pytest.mark.parametrize("system", ["win32", "darwin"])
def test_other_systems_are_refused_as_before(fresh_platform, monkeypatch, tmp_path, system):
    monkeypatch.setattr(desktop_platform.sys, "platform", system)
    with pytest.raises(NotImplementedError, match="desktop provisioning is Linux-only"):
        current_platform()
    with pytest.raises(NotImplementedError, match="desktop provisioning is Linux-only"):
        ProfilePaths.from_app("default", token_file=tmp_path / "config/ipc.token",
                              data_dir=tmp_path / "data")


def test_linux_profile_paths_are_the_xdg_paths(fresh_platform, monkeypatch, tmp_path):
    environ = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_DATA_HOME": str(tmp_path / "share")}
    assert (LinuxPlatform().profile_paths("work", environ=environ, home=tmp_path)
            == ProfilePaths.from_xdg("work", environ=environ, home=tmp_path))
    app = ProfilePaths.from_app("work", token_file=tmp_path / "app/ipc.token",
                                data_dir=tmp_path / "app-data", environ=environ, home=tmp_path)
    assert app.cache_dir == ProfilePaths.from_xdg("work", environ=environ, home=tmp_path).cache_dir

    from src.runtime_paths import runtime_profile_paths

    for key in ("ODIN_DESKTOP_DATA_DIR", "ODIN_DESKTOP_TOKEN_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ODIN_DESKTOP_PROFILE", "work")
    assert runtime_profile_paths() == ProfilePaths.from_xdg("work")


def test_locks_exclude_a_second_holder(tmp_path):
    path = tmp_path / ".lock"
    first = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    second = os.open(path, os.O_RDWR)
    try:
        locks.lock_exclusive(first)
        with pytest.raises(BlockingIOError):
            locks.lock_exclusive(second, blocking=False)
        locks.unlock(first)
        locks.lock_exclusive(second, blocking=False)
        with path.open("a+b") as stream, pytest.raises(BlockingIOError):
            locks.lock_exclusive(stream, blocking=False)
    finally:
        os.close(first)
        os.close(second)


def test_locks_refuse_on_a_system_without_fcntl(monkeypatch):
    monkeypatch.setattr(locks, "fcntl", None)
    with pytest.raises(NotImplementedError):
        locks.lock_exclusive(0)
    with pytest.raises(NotImplementedError):
        locks.unlock(0)


def test_profile_modules_load_without_fcntl():
    """These modules no longer need fcntl just to load, so they can load on Windows later."""
    script = (
        "import sys; sys.modules['fcntl'] = None\n"
        "import src.config.environment, src.config.initialization\n"
        "import src.desktop.authority, src.runtime.pdf_resources\n"
        "from src.desktop.platform import locks\n"
        "try:\n    locks.lock_exclusive(0)\nexcept NotImplementedError:\n    print('refused')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "refused"


def test_the_keyring_backend_comes_from_the_platform(monkeypatch, tmp_path):
    """The store still builds its default backend lazily, and a backend that can't start
    is still reported as an unavailable keyring."""
    from src.desktop import secrets

    class Backend:
        pass

    monkeypatch.setattr(secrets, "_SecretServiceBackend", Backend)
    assert isinstance(LinuxPlatform().secret_backend(), Backend)
    store = secrets.ProfileSecretStore(ProfilePaths.from_xdg("work", environ={}, home=tmp_path))
    assert isinstance(store._adapter(), Backend)

    def unavailable():
        raise RuntimeError("no session bus")

    monkeypatch.setattr(secrets, "_SecretServiceBackend", unavailable)
    broken = secrets.ProfileSecretStore(ProfilePaths.from_xdg("work", environ={}, home=tmp_path))
    with pytest.raises(secrets.SecretStoreError, match="Profile keyring is unavailable"):
        broken._adapter()


def test_the_core_lifetime_is_the_existing_class():
    from src.desktop.lifecycle import CoreLifetime

    lifetime = LinuxPlatform().core_lifetime()
    assert type(lifetime) is CoreLifetime and lifetime.admitting


async def test_local_shells_come_from_the_platform_at_call_time(monkeypatch):
    """Shell choice and the supervised launch are today's functions, looked up when called,
    so tests and callers that replace them still reach every local command."""
    from src.tools import command_shell, local_supervisor

    platform = LinuxPlatform()
    assert platform.resolve_local_shell("sh") == command_shell.resolve_local_shell("sh")
    monkeypatch.setattr(command_shell, "resolve_local_shell",
                        lambda mode: command_shell.ShellChoice("fixture", f"/fixture/{mode}"))
    fixture = command_shell.ShellChoice("fixture", "/fixture/auto")
    assert platform.resolve_local_shell("auto") == fixture

    seen = []

    async def launch(command, **options):
        seen.append((command, options))
        return "supervised"

    monkeypatch.setattr(local_supervisor, "create_supervised_shell", launch)
    launched = await platform.create_local_shell("true", cwd="/tmp", start_new_session=True)
    assert launched == "supervised"
    assert seen == [("true", {"cwd": "/tmp", "start_new_session": True})]
