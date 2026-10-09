"""Desktop config strips transport authority but retains neutral controls."""
import pytest
from pydantic import ValidationError

from src.config.schema import Config, ToolHost, load_config, set_active_config_path
from src.config.workspace_paths import WORKSPACE_PROTECTED_CONFIG_PATH_NAMES
from src.desktop.ssh_sockets import socket_directory
from src.runtime_paths import runtime_profile_paths


@pytest.mark.parametrize("key", ["discord", "permissions", "web"])
def test_obsolete_top_level_config_rejected(key):
    with pytest.raises(ValidationError):
        Config.model_validate({key: {}})

def test_config_defaults_use_profile_and_explicit_hosts(tmp_path, monkeypatch):
    for key, suffix in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        monkeypatch.setenv(key, str(tmp_path / suffix))
    cfg = Config()
    assert not cfg.tools.hosts
    assert str(tmp_path) in cfg.context.directory
    assert str(tmp_path) in cfg.sessions.persist_directory
    assert str(tmp_path) in cfg.computer.storage_dir
    assert str(tmp_path) in cfg.tools.local_working_dir
    # SSH control sockets use the profile's short private runtime directory.
    assert cfg.tools.ssh_pool.socket_dir == socket_directory(runtime_profile_paths())
    assert "permissions.overrides_path" not in WORKSPACE_PROTECTED_CONFIG_PATH_NAMES
    assert "computer.storage_dir" in WORKSPACE_PROTECTED_CONFIG_PATH_NAMES
    assert "tools.ssh_key_path" in WORKSPACE_PROTECTED_CONFIG_PATH_NAMES

def test_host_trust_validation_preserved():
    assert ToolHost(address="example.invalid", trust_mode="pinned").trust_mode == "pinned"
    with pytest.raises(ValidationError):
        ToolHost(address="example.invalid", host_id="invalid")
    with pytest.raises(ValidationError):
        ToolHost(address="example.invalid", host_keys=["invalid\nmaterial"])

def test_config_load_read_only_no_implicit_migration(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("{}\n")
    before = path.read_bytes()
    cfg = load_config(path)
    assert isinstance(cfg, Config)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.yml"]
    set_active_config_path(None)

def test_environment_does_not_require_transport_token(tmp_path, monkeypatch):
    from src.config import OdinConfig
    value = OdinConfig.from_env(tmp_path / "absent-environment")
    assert not hasattr(value, "token")
    assert value.validate() == []

def test_initialization_does_not_import_recordless_install(tmp_path):
    from src.config.initialization import (
        InitializationMode,
        InitializationStore,
        InstallationBinding,
    )
    store = InitializationStore(
        tmp_path / "private" / "state.json",
        InstallationBinding("desktop-test", tmp_path / "config.yml"),
    )
    assert store.state(legacy_loopback_restricted=True).mode == InitializationMode.RECOVERY
    assert not store.path.exists()

def test_migrations_cannot_write_outside_desktop_profile(tmp_path):
    from src.config.migrations import MigrationCompletionError, apply_legacy_ceiling_migration
    path = tmp_path / "other.yml"
    path.write_text("{}\n")
    with pytest.raises(MigrationCompletionError):
        apply_legacy_ceiling_migration({}, path, "{}\n")
    assert path.read_text() == "{}\n"

def test_fresh_profile_explicit_model_intent_and_no_import(tmp_path, monkeypatch):
    from src.config.model_defaults import DEFAULT_MAIN_MODEL
    from src.desktop.paths import ProfilePaths
    from src.desktop.profile import provision_fresh_profile
    from src.desktop.provisioning import DESKTOP_AUXILIARY_MODEL
    for key, suffix in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        monkeypatch.setenv(key, str(tmp_path / suffix))
    paths = ProfilePaths.from_xdg()
    authority = provision_fresh_profile(paths)
    assert not authority.durability_degraded
    cfg = load_config(paths.config_file)
    assert cfg.openai_codex.model == DEFAULT_MAIN_MODEL
    assert cfg.llm_provider.model == DEFAULT_MAIN_MODEL
    # A new profile's auxiliary is Desktop's own choice (D20), written to its config.
    assert cfg.openai_codex.auxiliary.model == DESKTOP_AUXILIARY_MODEL
    assert paths.config_file.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        provision_fresh_profile(paths)
    set_active_config_path(None)
