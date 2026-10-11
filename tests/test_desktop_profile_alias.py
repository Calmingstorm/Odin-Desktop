"""A profile reached through an aliased folder starts again after its first run.

The app names the profile by the paths it was given (XDG or HOME on Linux, LOCALAPPDATA on
Windows), and a folder above the profile can be an alias: a symlinked home (Fedora Atomic's
/home -> /var/home), a symlinked ~/.config, or on Windows an 8.3 short name or a junction. The
selected-profile check compared the config path, resolved, with the profile's slot, unresolved,
so every launch after the first exited: "configuration is outside the selected desktop profile".
"""
from __future__ import annotations

import pytest

from src.config.migrations import MigrationCompletionError, _require_desktop_config
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from src.desktop.provisioning import ensure_profile


@pytest.fixture
def aliased(tmp_path, monkeypatch):
    """A selected profile whose home is a symlink to the real folder."""
    real = tmp_path / "var-home"
    real.mkdir(mode=0o700)
    home = tmp_path / "home"
    home.symlink_to(real, target_is_directory=True)
    paths = ProfilePaths.from_xdg("aliased", environ={}, home=home)
    monkeypatch.setenv("HOME", str(home))
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ODIN_DESKTOP_PROFILE", paths.profile_id)
    monkeypatch.setenv("ODIN_DESKTOP_TOKEN_FILE", str(paths.config_dir / "ipc.token"))
    monkeypatch.setenv("ODIN_DESKTOP_DATA_DIR", str(paths.data_dir))
    authority = OwnerAuthority(paths)
    try:
        yield paths, authority
    finally:
        authority.release_runtime()


def test_a_profile_under_a_symlinked_home_loads_on_its_second_start(aliased):
    paths, authority = aliased
    first = ensure_profile(paths, authority=authority)  # creates the config
    again = ensure_profile(paths, authority=authority)  # loads it: the selected-profile check runs
    assert again.tools == first.tools


def test_the_config_slot_itself_as_a_symlink_is_still_refused(aliased, tmp_path):
    paths, authority = aliased
    ensure_profile(paths, authority=authority)
    elsewhere = tmp_path / "another-installation.yml"
    elsewhere.write_bytes(paths.config_file.read_bytes())
    paths.config_file.unlink()
    paths.config_file.symlink_to(elsewhere)
    with pytest.raises(MigrationCompletionError, match="outside the selected desktop profile"):
        _require_desktop_config(paths.config_file)


def test_an_alias_naming_the_selected_config_is_accepted(aliased, tmp_path):
    paths, authority = aliased
    ensure_profile(paths, authority=authority)
    alias = tmp_path / "alias.yml"
    alias.symlink_to(paths.config_file)
    _require_desktop_config(alias)
    _require_desktop_config(paths.config_file.resolve())


def test_a_config_outside_the_selected_profile_is_refused(aliased, tmp_path):
    paths, authority = aliased
    ensure_profile(paths, authority=authority)
    other = tmp_path / "config.yml"
    other.write_bytes(paths.config_file.read_bytes())
    with pytest.raises(MigrationCompletionError, match="outside the selected desktop profile"):
        _require_desktop_config(other)
