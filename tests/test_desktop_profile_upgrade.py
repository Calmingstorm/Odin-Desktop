"""Ordinary established Desktop upgrades, not import from a server installation."""
import json
from pathlib import Path

import pytest
import yaml

from src.config import migrations, schema
from src.desktop import profile as provisioning
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths


@pytest.fixture
def profile(tmp_path, monkeypatch):
    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    })
    OwnerAuthority(paths)
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: paths)
    monkeypatch.setattr(schema, "runtime_profile_paths", lambda: paths)
    monkeypatch.setattr(provisioning, "runtime_profile_paths", lambda: paths)
    schema.set_active_config_path(None)
    yield paths
    schema.set_active_config_path(None)


def test_ordered_upgrades_persist_once_and_preserve_operator_pins(profile):
    path = profile.config_file
    text = (
        "# owner comment\nopenai_codex:\n  context_compression:\n"
        "    max_context_chars: 750000 # historical ceiling\n"
        "image: {openai: {image_model: gpt-image-2, outer_model: gpt-5.5}}\n"
        "openai_compatible: {timeout: 120}\n"
    )
    path.write_text(text)
    cfg = schema.load_config()
    raw = yaml.safe_load(path.read_text())
    assert cfg.openai_codex.context_compression.max_context_chars is None
    assert cfg.image.openai.image_model == "gpt-image-2.5-flare"
    assert cfg.image.openai.outer_model == "gpt-6-astra"
    assert cfg.openai_compatible.request_timeout_seconds == 3600
    assert cfg.openai_compatible.stream_stall_timeout_seconds == 120
    assert raw["openai_codex"]["context_compression"]["max_context_chars"] is None
    assert "timeout" not in raw["openai_compatible"]
    assert "# owner comment" in path.read_text()
    assert "# historical ceiling" in path.read_text()
    markers = list((profile.data_dir / "config_migrations").glob("*.json"))
    assert len(markers) == 2
    assert all(json.loads(p.read_text())["state"] == "completed" for p in markers)
    path.write_text(text)
    later = schema.load_config()
    assert later.openai_codex.context_compression.max_context_chars == 750000
    assert later.image.openai.image_model == "gpt-image-2"
    assert schema.active_config_path() == path


def test_vacuous_completion_preserves_later_legacy_pin(profile):
    path = profile.config_file
    path.write_text("{}\n")
    schema.load_config()
    path.write_text("openai_codex: {context_compression: {max_context_chars: 750000}}\n")
    assert schema.load_config().openai_codex.context_compression.max_context_chars == 750000


def test_placeholders_are_not_shipped_literal_evidence(profile, monkeypatch):
    text = (
        "openai_codex: {context_compression: {max_context_chars: '${CEILING}'}}\n"
        "image: {openai: {image_model: '${IMAGE_MODEL}'}}\n"
        "openai_compatible: {timeout: '${STALL}'}\n"
    )
    monkeypatch.setenv("CEILING", "750000")
    monkeypatch.setenv("IMAGE_MODEL", "gpt-image-2")
    monkeypatch.setenv("STALL", "120")
    profile.config_file.write_text(text)
    cfg = schema.load_config()
    assert cfg.openai_codex.context_compression.max_context_chars == 750000
    assert cfg.image.openai.image_model == "gpt-image-2"
    saved = profile.config_file.read_text()
    assert "${CEILING}" in saved and "${IMAGE_MODEL}" in saved and "${STALL}" in saved
    assert "timeout:" not in saved.replace("stream_stall_timeout_seconds:", "")


@pytest.mark.parametrize("removed", ["discord", "permissions", "web", "unknown"])
def test_reject_obsolete_fields_before_any_migration_write(profile, removed):
    text = (f"{removed}: {{}}\n"
            "openai_codex: {context_compression: {max_context_chars: 750000}}\n")
    profile.config_file.write_text(text)
    before = sorted(p.relative_to(profile.data_dir) for p in profile.data_dir.rglob("*"))
    with pytest.raises(SystemExit, match="Config validation failed"):
        schema.load_config()
    assert profile.config_file.read_text() == text
    assert sorted(p.relative_to(profile.data_dir) for p in profile.data_dir.rglob("*")) == before
    assert schema.active_config_path() is None


def test_external_supplied_config_is_runtime_only(profile, tmp_path):
    path = tmp_path / "external.yml"
    text = (
        "openai_codex: {context_compression: {max_context_chars: 750000}}\n"
        "image: {openai: {image_model: gpt-image-2}}\n"
        "openai_compatible: {timeout: 120}\n"
    )
    path.write_text(text)
    cfg = schema.load_config(path)
    assert cfg.openai_codex.context_compression.max_context_chars == 750000
    assert cfg.image.openai.image_model == "gpt-image-2"
    assert cfg.openai_compatible.stream_stall_timeout_seconds == 120
    assert path.read_text() == text
    assert not (profile.data_dir / "config_migrations").exists()
    assert not list(tmp_path.glob("*.json"))


def test_alias_to_selected_config_is_same_identity(profile, tmp_path):
    path = profile.config_file
    path.write_text("image: {openai: {image_model: gpt-image-2}}\n")
    alias = tmp_path / "launch.yml"
    alias.symlink_to(path)
    cfg = schema.load_config(alias)
    assert cfg.image.openai.image_model == "gpt-image-2.5-flare"
    assert alias.is_symlink()
    assert schema.active_config_path() == path
    assert schema.active_config_launch_path() == alias
    assert (migrations.image_defaults_marker_path(alias)
            == migrations.image_defaults_marker_path(path))


def test_selected_config_cannot_symlink_to_other_installation(profile, tmp_path):
    target = tmp_path / "foreign.yml"
    target.write_text("image: {openai: {image_model: gpt-image-2}}\n")
    profile.config_file.symlink_to(target)
    with pytest.raises(SystemExit, match="Configuration migration failed"):
        schema.load_config()
    assert target.read_text() == "image: {openai: {image_model: gpt-image-2}}\n"
    assert not (profile.data_dir / "config_migrations").exists()


@pytest.mark.parametrize("identity", ["missing", "corrupt", "foreign", "public"])
def test_owner_identity_must_be_established_before_upgrade(profile, identity):
    profile.config_file.write_text("image: {openai: {image_model: gpt-image-2}}\n")
    if identity == "missing":
        profile.identity_file.unlink()
    elif identity == "corrupt":
        profile.identity_file.write_text("{broken")
    elif identity == "foreign":
        record = json.loads(profile.identity_file.read_text())
        record["profile_id"] = "other"
        profile.identity_file.write_text(json.dumps(record))
    else:
        profile.identity_file.chmod(0o644)
    with pytest.raises(SystemExit, match="Configuration migration failed"):
        schema.load_config()
    assert "gpt-image-2}" in profile.config_file.read_text()
    assert not (profile.data_dir / "config_migrations").exists()


def test_invalid_marker_failure_is_not_reported_as_success(profile):
    profile.config_file.write_text("{}\n")
    marker = migrations.ceiling_marker_path(profile.config_file)
    marker.parent.mkdir()
    marker.write_text("{broken")
    with pytest.raises(SystemExit, match="Configuration migration failed"):
        schema.load_config()
    assert marker.read_text() == "{broken"
    assert schema.active_config_path() is None


def test_timeout_persistence_only_after_schema_validation(profile):
    text = "agents: {max_concurrent_agents: -1}\nopenai_compatible: {timeout: 120}\n"
    profile.config_file.write_text(text)
    with pytest.raises(SystemExit, match="Config validation failed"):
        schema.load_config()
    assert profile.config_file.read_text() == text


def test_loader_reconciles_concurrent_save_between_upgrade_steps(profile, monkeypatch):
    profile.config_file.write_text("image: {openai: {image_model: custom}}\n")
    def concurrent_save(data, path, original):
        Path(path).write_text("image: {openai: {image_model: newer}}\n")
    monkeypatch.setattr(migrations, "apply_legacy_ceiling_migration", concurrent_save)
    assert schema.load_config().image.openai.image_model == "newer"


def test_fresh_provision_materializes_intent_without_server_import(profile, tmp_path):
    from src.desktop.profile import provision_fresh_profile
    foreign = tmp_path / "server"
    foreign.mkdir()
    (foreign / "config.yml").write_text("discord: {token: fixture}\n")
    (foreign / "context_ceiling_migration.json").write_text("{broken")
    owner = provision_fresh_profile(profile)
    before = profile.config_file.read_text()
    cfg = schema.load_config()
    assert not owner.durability_degraded
    assert cfg.openai_codex.model
    assert profile.config_file.read_text() == before
    assert (foreign / "context_ceiling_migration.json").read_text() == "{broken"
    assert all(p.is_relative_to(profile.data_dir) for p in (
        migrations.ceiling_marker_path(profile.config_file),
        migrations.image_defaults_marker_path(profile.config_file),
    ))
