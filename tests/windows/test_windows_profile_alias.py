"""A profile reached through an aliased folder starts again after its first run (Windows).

LOCALAPPDATA can name the profile through an alias: an 8.3 short name (GitHub's runner TEMP is
C:\\Users\\RUNNER~1\\...) or a junction. The first run creates the config without loading it, so
only a later start reaches the selected-profile check, which must compare real locations.
"""
from __future__ import annotations

import ctypes
from pathlib import Path

import _winapi
import pytest


def short_path(path: Path) -> str:
    size = ctypes.windll.kernel32.GetShortPathNameW(str(path), None, 0)
    if not size:
        raise ctypes.WinError()
    buffer = ctypes.create_unicode_buffer(size)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, size):
        raise ctypes.WinError()
    return buffer.value


@pytest.fixture(params=["junction", "short-name"])
def aliased_local(request, tmp_path) -> Path:
    real = tmp_path / "a-long-folder-name"
    real.mkdir()
    if request.param == "junction":
        alias = tmp_path / "alias"
        _winapi.CreateJunction(str(real), str(alias))
        return alias
    short = short_path(real)
    if short.lower() == str(real).lower():
        pytest.skip("8.3 names are off on this volume")
    return Path(short)


def test_a_profile_through_an_alias_loads_on_its_second_start(aliased_local, monkeypatch):
    from src.desktop.authority import OwnerAuthority
    from src.desktop.platform.windows import windows_profile_paths
    from src.desktop.provisioning import ensure_profile

    paths = windows_profile_paths("default", environ={"LOCALAPPDATA": str(aliased_local)})
    # Selected as the app selects it, so loading runs the selected-profile check.
    monkeypatch.setenv("LOCALAPPDATA", str(aliased_local))
    monkeypatch.setenv("ODIN_DESKTOP_PROFILE", paths.profile_id)
    monkeypatch.setenv("ODIN_DESKTOP_TOKEN_FILE", str(paths.config_dir / "ipc.token"))
    monkeypatch.setenv("ODIN_DESKTOP_DATA_DIR", str(paths.data_dir))
    authority = OwnerAuthority(paths)
    try:
        first = ensure_profile(paths, authority=authority)  # creates the config
        again = ensure_profile(paths, authority=authority)  # loads it
    finally:
        authority.release_runtime()
    assert again.tools == first.tools
