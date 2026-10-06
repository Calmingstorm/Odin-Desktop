"""D17 file admission and real profile persistence, with no live configuration."""

import logging

import pytest
import yaml

from src.config.persistence import _patch_config_paths, submitted_leaves
from src.config.schema import (
    _KNOWN_REMOVED_TOP_LEVEL_CONFIG_KEYS,
    Config,
    load_config,
    set_active_config_path,
)
from src.desktop.authority import OwnerAuthority
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from tests.test_desktop_settings import MemoryKeyring


@pytest.fixture
def profile(tmp_path, monkeypatch):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    OwnerAuthority(paths)
    monkeypatch.setattr("src.config.schema.runtime_profile_paths", lambda: paths)
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: paths)
    yield paths
    set_active_config_path(None)


@pytest.mark.parametrize("unknown", ["sesions", "old_server_section"])
def test_profile_unknown_key_warns_and_starts(profile, caplog, unknown):
    profile.config_file.write_text(f"{unknown}: {{enabled: true}}\ntimezone: UTC\n")
    with caplog.at_level(logging.WARNING, logger="odin.config"):
        config = load_config()
    known = set(Config.model_fields)
    known.update(f.alias for f in Config.model_fields.values() if f.alias)
    expected = (
        f"Ignoring unknown config key(s): {unknown} — check for typos "
        f"(known top-level sections: {', '.join(sorted(known))})"
    )
    assert [r.getMessage() for r in caplog.records if "Ignoring unknown" in r.message] == [
        expected
    ]
    assert config.timezone == "UTC"
    assert unknown not in config.model_dump()
    assert config.model_extra is None
    # SettingsService also has a file-reading entry, independent of load_config.
    service = SettingsService(profile, None)
    assert unknown not in service.config.model_dump()


@pytest.mark.parametrize("bad", ["-1", "[1, 2]"])
def test_known_invalid_value_still_refuses(profile, bad):
    profile.config_file.write_text(
        f"sesions: {{}}\ntools: {{command_timeout_seconds: {bad}}}\n"
    )
    with pytest.raises(SystemExit, match="Config validation failed"):
        load_config()
    with pytest.raises(ValueError):
        SettingsService(profile, None)


@pytest.mark.parametrize("removed", sorted(_KNOWN_REMOVED_TOP_LEVEL_CONFIG_KEYS))
def test_removed_sections_still_refuse_before_migrations(profile, removed, caplog):
    raw = f"{removed}: {{enabled: true}}\n"
    profile.config_file.write_text(raw)
    before = sorted(p.relative_to(profile.data_dir) for p in profile.data_dir.rglob("*"))
    with pytest.raises(SystemExit, match="removed top-level"):
        load_config()
    assert profile.config_file.read_text() == raw
    assert sorted(p.relative_to(profile.data_dir) for p in profile.data_dir.rglob("*")) == before
    assert "Ignoring unknown config key" not in caplog.text


def test_settings_save_never_reintroduces_dropped_unknown_key(profile):
    profile.config_file.write_text("sesions: {}\ntimezone: UTC\n")
    config = load_config()
    service = SettingsService(
        profile, ProfileSecretStore(profile, backend=MemoryKeyring()), config=config
    )
    # Odin's leaf writer preserves existing unsubmitted YAML, including unknown
    # keys. It never emits them from a validated model or submitted_leaves.
    changes = submitted_leaves(
        {"new_typo": {}, "timezone": "America/New_York"},
        config.model_copy(update={"timezone": "America/New_York"}).model_dump(),
        Config,
    )
    assert changes == [(("timezone",), "America/New_York")]
    _patch_config_paths(changes, path=profile.config_file)
    assert yaml.safe_load(profile.config_file.read_text())["sesions"] == {}
    assert "new_typo" not in yaml.safe_load(profile.config_file.read_text())
    # Once removed from the document, a real settings save cannot add it back.
    profile.config_file.write_text("# operator removed typo\ntimezone: UTC\n")
    service.save_changes([(("timezone",), "America/New_York")])
    assert yaml.safe_load(profile.config_file.read_text()) == {"timezone": "America/New_York"}
    assert "sesions" not in service.config.model_dump()
    before = profile.config_file.read_text()
    with pytest.raises(MethodError):
        service.save_changes([(("new_typo",), {})])
    assert profile.config_file.read_text() == before
