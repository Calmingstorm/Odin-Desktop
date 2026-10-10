"""Windows platform members: selection, profile layout, locks, DPAPI secrets, boot ID, workspace."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.desktop.platform import current_platform, locks, win32
from src.desktop.platform.windows import WindowsPlatform, windows_profile_paths
from src.desktop.platform.windows_files import dacl_is_private, held, private_directory


def test_windows_is_selected_and_its_2a_transport_fails_closed():
    platform = current_platform()
    assert isinstance(platform, WindowsPlatform) and platform.name == "windows"
    assert platform.computer_supported is False
    with pytest.raises(NotImplementedError, match="phase 2b"):
        platform.ipc  # noqa: B018 - the property itself refuses
    with pytest.raises(NotImplementedError, match="phase 2b"):
        platform.core_lifetime()


def test_profile_lives_under_local_appdata(tmp_path):
    paths = windows_profile_paths("work", environ={"LOCALAPPDATA": str(tmp_path)})
    root = tmp_path / "odin-desktop" / "work"
    assert (paths.config_dir, paths.data_dir, paths.cache_dir, paths.secrets_dir) == (
        root / "config", root / "data", root / "cache", root / "data" / "secrets")
    home = windows_profile_paths("work", environ={}, home=tmp_path)
    assert home.config_dir == tmp_path / "AppData" / "Local" / "odin-desktop" / "work" / "config"


@pytest.mark.parametrize(
    "value", ["relative\\path", "\\\\server\\share", "C:relative", "C:\\a\\..\\b"])
def test_local_appdata_must_be_an_absolute_local_path(value):
    with pytest.raises(ValueError):
        windows_profile_paths("work", environ={"LOCALAPPDATA": value})


def test_profile_folders_are_created_private(tmp_path):
    paths = windows_profile_paths("work", environ={"LOCALAPPDATA": str(tmp_path)})
    paths.create_private()
    for folder in (paths.config_dir, paths.data_dir, paths.cache_dir, paths.secrets_dir):
        with held(folder) as chain:
            assert dacl_is_private(win32.object_security(chain.handle))


def test_lock_excludes_a_second_holder_and_a_second_process(tmp_path):
    path = tmp_path / "profile.lock"
    first = open(path, "a+b")  # noqa: SIM115 - held by the test
    second = open(path, "a+b")  # noqa: SIM115
    try:
        locks.lock_exclusive(first)
        with pytest.raises(BlockingIOError):
            locks.lock_exclusive(second, blocking=False)
        script = ("import sys\nfrom src.desktop.platform import locks\n"
                  "f = open(sys.argv[1], 'a+b')\n"
                  "try:\n    locks.lock_exclusive(f, blocking=False)\nexcept BlockingIOError:\n"
                  "    sys.exit(3)\n")
        held_elsewhere = subprocess.run([sys.executable, "-c", script, str(path)],
                                        cwd=Path(__file__).resolve().parents[2], timeout=60)
        assert held_elsewhere.returncode == 3
        locks.unlock(first)
        locks.lock_exclusive(second, blocking=False)
        locks.unlock(second)
    finally:
        first.close()
        second.close()


def test_a_lock_never_blocks_the_files_own_data(tmp_path):
    path = tmp_path / "state.lock"
    path.write_bytes(b"data")
    holder = open(path, "r+b")  # noqa: SIM115
    try:
        locks.lock_exclusive(holder)
        assert path.read_bytes() == b"data"
        path.write_bytes(b"more")
    finally:
        holder.close()


def _store(tmp_path, profile="work"):
    from src.desktop.secrets import ProfileSecretStore

    paths = windows_profile_paths(profile, environ={"LOCALAPPDATA": str(tmp_path)})
    paths.create_private()
    return ProfileSecretStore(paths)


def test_dpapi_round_trip_delete_and_unlock(tmp_path):
    store = _store(tmp_path)
    assert store.get("codex_accounts") is None
    secret = "x" * 9000  # larger than Credential Manager's 2,560-byte cap
    assert store.set("codex_accounts", secret) is True
    assert store.get("codex_accounts") == secret
    assert store.delete("codex_accounts") is True
    assert store.delete("codex_accounts") is True
    assert store.get("codex_accounts") is None
    assert store._adapter().unlock() is True
    files = list((tmp_path / "odin-desktop" / "work" / "data" / "secrets" / "dpapi").iterdir())
    assert files == []


def test_two_profiles_keep_separate_secrets_and_refuse_each_others_ciphertext(tmp_path):
    from src.desktop.secrets import SecretStoreError

    first, second = _store(tmp_path, "one"), _store(tmp_path, "two")
    first.set("codex_accounts", "first")
    second.set("codex_accounts", "second")
    assert (first.get("codex_accounts"), second.get("codex_accounts")) == ("first", "second")
    one = tmp_path / "odin-desktop" / "one" / "data" / "secrets" / "dpapi"
    two = tmp_path / "odin-desktop" / "two" / "data" / "secrets" / "dpapi"
    [source] = list(one.iterdir())
    [target] = list(two.iterdir())
    target.write_bytes(source.read_bytes())  # another profile's ciphertext under this name
    with pytest.raises(SecretStoreError):
        second.get("codex_accounts")


def test_a_corrupt_credential_file_refuses(tmp_path):
    from src.desktop.secrets import SecretStoreError

    store = _store(tmp_path)
    store.set("codex_accounts", "value")
    [path] = list((tmp_path / "odin-desktop" / "work" / "data" / "secrets" / "dpapi").iterdir())
    path.write_bytes(b"not a dpapi blob")
    with pytest.raises(SecretStoreError):
        store.get("codex_accounts")


def test_boot_identifier_is_a_stable_uuid():
    first, second = win32.boot_identifier(), win32.boot_identifier()
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", first)


def _resolve(path, **kwargs):
    return current_platform().resolve_workspace(str(path), **kwargs)


def test_workspace_is_created_private_and_revalidated(tmp_path):
    private_directory(tmp_path / "odin-desktop" / "work" / "data")
    workspace = tmp_path / "odin-desktop" / "work" / "data" / "workspace"
    assert _resolve(workspace) == workspace.resolve()
    with held(workspace) as chain:
        assert dacl_is_private(win32.object_security(chain.handle))
    assert _resolve(workspace) == workspace.resolve()


@pytest.mark.parametrize("value", ["relative", "C:relative"])
def test_workspace_must_be_absolute(value):
    from src.tools.workspace import WorkspaceError

    with pytest.raises(WorkspaceError, match="absolute"):
        _resolve(value)


def test_workspace_refuses_a_junction(tmp_path):
    import _winapi

    from src.tools.workspace import WorkspaceError

    target = tmp_path / "target"
    target.mkdir()
    _winapi.CreateJunction(str(target), str(tmp_path / "workspace"))
    with pytest.raises(WorkspaceError, match="symlink"):
        _resolve(tmp_path / "workspace")


def test_workspace_overlap_is_refused_before_creation_including_case_aliases(tmp_path):
    from src.tools.workspace import WorkspaceError

    data = tmp_path / "Data"
    data.mkdir()
    inside = tmp_path / "data" / "workspace"
    with pytest.raises(WorkspaceError, match="overlap"):
        _resolve(inside, protected_roots=[str(data).upper()])
    assert not inside.exists()


def test_workspace_open_to_others_is_refused(tmp_path, sddl):
    from src.tools.workspace import WorkspaceError

    workspace = tmp_path / "shared"
    workspace.mkdir()
    sddl(workspace, "D:P(A;OICI;FA;;;WD)(A;OICI;FA;;;OW)", directory=True)
    with pytest.raises(WorkspaceError, match="private"):
        _resolve(workspace)


def test_the_engine_entry_modules_import_on_windows():
    import importlib

    for name in ("src.__main__", "src.cli", "src.desktop.core", "src.desktop.services",
                 "src.desktop.package_state", "src.desktop.package_ownership"):
        importlib.import_module(name)
