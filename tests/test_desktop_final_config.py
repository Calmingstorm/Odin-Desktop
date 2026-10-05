"""Final exact foundation cases and honest removed-surface boundaries."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.config.schema import Config, load_config, set_active_config_path
from src.tools.executor import EXECUTOR_HANDLERS
from src.tools.registry import PHASE1_EXECUTOR_TOOL_NAMES, get_tool_definitions
from tests.desktop_adapters.final_config import EVIDENCE, SELECTIONS, adapted_tree, export_cases
from tests.desktop_adapters.tools_cases import SkillManager, owner_fixture


@pytest.fixture(autouse=True)
def final_owner(tmp_path):
    with owner_fixture(tmp_path) as state:
        yield state
    set_active_config_path(None)


for _stem in SELECTIONS:
    export_cases(globals(), _stem)


@pytest.mark.parametrize("stem", list(SELECTIONS))
def test_final_full_corpus_freeze_before_projection(stem):
    original = ast.parse(frozen_source(f"tests/{stem}.py"))
    assert corpus(original) == corpus(adapted_tree(stem))
    assert EVIDENCE[f"tests/{stem}.py"]["full_assert_parameter_ast_preserved_before_projection"]


@pytest.mark.parametrize("removed", ["web", "discord", "permissions"])
def test_final_removed_schema_rejects_transport_and_tier_fields(removed, tmp_path):
    payload = {removed: {"port": 3002, "api_token": "inert-fixture", "tier": "admin"}}
    with pytest.raises(ValidationError) as error:
        Config.model_validate(payload)
    assert any(e["type"] == "extra_forbidden" and e["loc"] == (removed,)
               for e in error.value.errors())
    path = tmp_path / "rejected.yml"
    raw = json.dumps(payload)
    path.write_text(raw)
    with pytest.raises(SystemExit, match="unsupported top-level"):
        load_config(path)
    assert path.read_text() == raw


@pytest.mark.parametrize("row,port", [(12, 0), (13, 99999)])
def test_final_removed_web_invalid_parameter_row(row, port):
    assert row in (12, 13)
    with pytest.raises(ValidationError) as error:
        Config.model_validate({"web": {"port": port}})
    assert error.value.errors()[0]["loc"] == ("web",)
    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_final_valid_neutral_values_without_removed_web_field():
    from src.config.schema import RetryConfig, ToolsConfig
    assert RetryConfig(max_retries=3, base_delay=0.5).max_retries == 3
    assert ToolsConfig(command_timeout_seconds=30).command_timeout_seconds == 30
    assert "web" not in Config.model_fields


@pytest.mark.parametrize("section", [
    "grafana_alerts", "slack", "issue_tracker", "reaction_triggers", "message_triggers",
    "comfyui", "future_typoo",
])
def test_final_obsolete_loader_sections_fail_closed_without_rewrite(section, tmp_path):
    path = tmp_path / "obsolete.yml"
    raw = f"{section}: {{enabled: true}}\ntools: {{command_timeout_seconds: 123}}\n"
    path.write_text(raw)
    with pytest.raises(SystemExit, match="unsupported top-level"):
        load_config(path)
    assert path.read_text() == raw
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["obsolete.yml"]


def test_final_valid_config_environment_substitution_read_only(tmp_path, monkeypatch):
    path = tmp_path / "external.yml"
    raw = "timezone: ${ODIN_FINAL_TZ}\n"
    path.write_text(raw)
    monkeypatch.setenv("ODIN_FINAL_TZ", "America/New_York")
    assert load_config(path).timezone == "America/New_York"
    assert path.read_text() == raw
    assert not hasattr(Config(), "discord")


@pytest.mark.parametrize("legacy_guard_enabled", [False, True])
@pytest.mark.parametrize("legacy_grafana_enabled", [False, True])
def test_final_removed_settings_parameter_matrix_rejected(
    tmp_path, legacy_guard_enabled, legacy_grafana_enabled,
):
    import yaml
    payload = {
        "discord": {"token": "legacy"},
        "context": {"directory": "./legacy-context", "max_system_prompt_tokens": 12345},
        "openai_codex": {"enabled": True, "model": "gpt-5.6-terra", "max_tokens": 98765,
                         "reasoning_effort": "high"},
        "graceful_degradation": {"enabled": legacy_guard_enabled, "degraded_threshold": 7,
                                 "unavailable_threshold": 19},
        "grafana_alerts": {"enabled": legacy_grafana_enabled, "auto_remediate": True,
                           "cooldown_seconds": 612, "max_concurrent_remediations": 4},
    }
    path = tmp_path / "legacy.yml"
    raw = yaml.safe_dump(payload)
    path.write_text(raw)
    with pytest.raises(SystemExit, match="unsupported top-level"):
        load_config(path)
    assert path.read_text() == raw
    neutral = {k: v for k, v in payload.items() if k not in {"discord", "grafana_alerts"}}
    config = Config.model_validate(neutral, context={"startup": True})
    assert config.context.directory == "./legacy-context"
    assert config.graceful_degradation.degraded_threshold == 7
    assert config.graceful_degradation.unavailable_threshold == 19
    assert config.openai_codex.model == "gpt-5.6-terra"
    assert not hasattr(config.context, "max_system_prompt_tokens")
    assert not hasattr(config.openai_codex, "max_tokens")


def test_final_neutral_legacy_image_fields_retained_read_only(tmp_path):
    import yaml
    fields = {"enabled": True, "outer_model": "gpt-6-astra",
              "image_model": "gpt-image-2.5-flare", "request_timeout_seconds": 181,
              "connect_timeout_seconds": 31, "stream_stall_timeout_seconds": 121,
              "max_image_bytes": 16777215}
    path = tmp_path / "neutral-image.yml"
    raw = yaml.safe_dump({"image": {"backend": "auto", "openai": fields}})
    path.write_text(raw)
    config = load_config(path)
    assert config.image.openai.model_dump() == fields
    assert not hasattr(config.image, "backend")
    assert path.read_text() == raw


def test_final_legacy_host_inventory_needs_real_owner_not_policy(final_owner, tmp_path):
    from src.permissions.host_access import HostAccessManager
    from src.tools.executor import ToolExecutor
    from src.tools.hosts import HostRegistry
    path = tmp_path / "hosts.yml"
    raw = ("tools:\n  hosts:\n"
           "    alpha:\n      address: example.invalid\n      ssh_user: deploy\n      os: linux\n"
           "    beta:\n      address: localhost\n      ssh_user: root\n      os: linux\n")
    path.write_text(raw)
    config = load_config(path)
    registry = HostRegistry(config.tools.hosts, profile_paths=final_owner.paths)
    preference = final_owner.paths.config_dir / "host-preferences.json"
    access = HostAccessManager(preference, available_hosts_provider=registry.active_aliases,
                               permission_manager=final_owner.manager)
    assert registry.active_aliases() == ("alpha", "beta")
    assert access.get_allowed_hosts(final_owner.authority.owner_id) == ["alpha", "beta"]
    assert access.get_allowed_hosts("legacy-user") == []
    assert not preference.exists()
    executor = ToolExecutor(config.tools, host_registry=registry, host_access_manager=access,
                            permission_manager=final_owner.manager, profile_paths=final_owner.paths)
    executor.set_user_context(final_owner.authority.owner_id)
    try:
        assert executor._resolve_host("alpha") == ("example.invalid", "deploy", "linux")
    finally:
        executor.set_user_context(None)
    assert access.get_allowed_hosts("legacy-user") == []
    assert path.read_text() == raw


def test_final_fresh_profile_replaces_removed_server_template(final_owner, monkeypatch):
    from src.config.model_defaults import DEFAULT_AUXILIARY_MODEL, DEFAULT_MAIN_MODEL
    from src.desktop.profile import provision_fresh_profile
    # A removed repository-root server template is not silently recreated.
    assert not (Path(__file__).resolve().parents[1] / "config.yml").exists()
    monkeypatch.setattr("src.desktop.profile.runtime_profile_paths", lambda: final_owner.paths)
    monkeypatch.setattr("src.config.schema.runtime_profile_paths", lambda: final_owner.paths)
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: final_owner.paths)
    authority = provision_fresh_profile(final_owner.paths)
    assert not authority.durability_degraded
    config = load_config(final_owner.paths.config_file)
    assert config.openai_codex.model == DEFAULT_MAIN_MODEL
    assert config.openai_codex.auxiliary.model == DEFAULT_AUXILIARY_MODEL
    assert not hasattr(config, "discord")


def test_final_image_identity_aliases_and_distinct_owner_profiles(tmp_path, monkeypatch):
    import yaml

    from src.config.migrations import apply_image_defaults_migration
    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths

    profiles = [ProfilePaths.from_xdg(name, environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }) for name in ("one", "two")]
    raw = "image: {openai: {image_model: gpt-image-2}}\n"
    for profile in profiles:
        OwnerAuthority(profile)
        profile.config_file.write_text(raw)
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: profiles[0])
    apply_image_defaults_migration(yaml.safe_load(raw), profiles[0].config_file, raw)
    profiles[0].config_file.write_text(raw)
    for name in ("alias-one", "alias-two"):
        alias = tmp_path / name
        alias.symlink_to(profiles[0].config_file)
        apply_image_defaults_migration(yaml.safe_load(raw), alias, raw)
        assert alias.is_symlink()
        assert alias.read_text() == raw
    monkeypatch.setattr("src.runtime_paths.runtime_profile_paths", lambda: profiles[1])
    apply_image_defaults_migration(yaml.safe_load(raw), profiles[1].config_file, raw)
    assert profiles[1].config_file.read_text() != raw
    assert profiles[0].config_file.read_text() == raw


def _module(name):
    return (f'SKILL_DEFINITION = {{"name": "{name}", "description": "demo", '
            '"input_schema": {"type": "object", "properties": {}}}\n'
            'async def execute(inp, context):\n    return "ok"\n')


def test_final_real_skill_snapshots_loaded_disabled_error(final_owner):
    from unittest.mock import MagicMock
    directory = final_owner.paths.data_dir / "skills"
    directory.mkdir(mode=0o700)
    for name in ("enabled", "disabled"):
        (directory / f"{name}.py").write_text(_module(name))
    (directory / "broken.py").write_text("invalid syntax here\n")
    manager = SkillManager(str(directory), MagicMock())
    manager.disable_skill("disabled")
    reloaded = SkillManager(str(directory), MagicMock())
    assert {s["name"]: s["status"] for s in reloaded.list_skills()} == {
        "enabled": "loaded", "disabled": "disabled", "broken": "error"}
    assert not reloaded.has_skill("broken")
    assert {d["name"] for d in reloaded.get_tool_definitions()} == {"enabled"}


def test_final_real_skill_rejected_edits_do_not_add_error_rows(final_owner):
    from unittest.mock import MagicMock
    manager = SkillManager(str(final_owner.paths.data_dir / "skills"), MagicMock())
    manager.create_skill("good", _module("good"))
    manager.create_skill("bad", "invalid syntax here")
    manager.edit_skill("good", "invalid syntax here")
    assert [s["name"] for s in manager.list_skills()] == ["good"]
    assert manager.list_skills()[0]["status"] == "loaded"


@pytest.mark.parametrize("failure", ["read", "spec", "execute"])
def test_final_real_skill_failed_load_snapshot_no_source(final_owner, monkeypatch, failure):
    from unittest.mock import MagicMock

    import src.tools.skill_manager as module
    directory = final_owner.paths.data_dir / "skills"
    directory.mkdir(mode=0o700)
    path = directory / "broken.py"
    path.write_text(_module("broken").split("async def", 1)[0])
    if failure == "read":
        original = Path.read_text
        def read(file, *args, **kwargs):
            if file == path:
                raise PermissionError("sensitive internal detail")
            return original(file, *args, **kwargs)
        monkeypatch.setattr(Path, "read_text", read)
    elif failure == "spec":
        monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *args: None)
    manager = SkillManager(str(directory), MagicMock())
    snapshot = manager.list_skills()
    assert snapshot[0]["status"] == "error"
    assert "sensitive internal detail" not in json.dumps(snapshot)
    assert not manager.has_skill("broken")


@pytest.mark.parametrize("executed", [False, True])
def test_final_real_agent_snapshot_preserves_requested_and_executed_provenance(executed):
    from src.agents.manager import AgentInfo, AgentManager
    manager = AgentManager()
    for name, effort in [("gpt-6.1-sol", "high"), ("gpt-6-luna", "medium")]:
        info = AgentInfo(name, name, "test", "channel", "owner", "Owner",
                         model_override=name, reasoning_effort_override=effort)
        if executed:
            info.has_executed = True
            info.last_provider = "codex"
            info.last_model = name
            info.last_reasoning_effort = effort
        manager._agents[name] = info
    rows = manager.list("channel")
    assert len(rows) == 2
    for row in rows:
        assert row["has_executed"] is executed
        assert row["last_model"] == (row["model_override"] if executed else "")
        assert row["last_reasoning_effort"] == (
            row["reasoning_effort_override"] if executed else None)


def test_final_executed_agent_missing_provenance_stays_unknown():
    from src.agents.manager import AgentInfo, AgentManager
    manager = AgentManager()
    info = AgentInfo("unknown", "unknown", "test", "channel", "owner", "Owner",
                     model_override="gpt-6.1-sol", reasoning_effort_override="high",
                     has_executed=True)
    manager._agents[info.id] = info
    row = manager.list("channel")[0]
    assert row["has_executed"]
    assert row["last_model"] == ""
    assert row["last_reasoning_effort"] is None
    assert row["model_override"] == "gpt-6.1-sol"


@pytest.mark.parametrize("name", ["list_skills", "enable_skill", "disable_skill", "list_agents"])
def test_final_phase2_listing_dispatch_and_publication_withheld(name):
    assert name not in EXECUTOR_HANDLERS
    assert name not in PHASE1_EXECUTOR_TOOL_NAMES
    assert name not in {t["name"] for t in get_tool_definitions(readiness={name: True})}
    from src.discord import wiring
    with pytest.raises(RuntimeError, match="Phase 2"):
        wiring.build_components()
