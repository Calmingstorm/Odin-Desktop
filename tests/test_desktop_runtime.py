"""Runtime facts come from real owners, never a saved setting's optimism."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.audit.logger import AuditLogger
from src.context.loader import ContextLoader
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.runtime import RuntimeService
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.llm.codex_quota import CodexQuotaTracker
from src.usage.rollup import UsageRollup


def make_service(tmp_path, **owners):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    core = SimpleNamespace(
        phase="ready", authority=SimpleNamespace(runtime_id="isolated-core"),
        paths=paths, capabilities=RuntimeService.METHODS,
        limits={"chunk_bytes": 262144, "attachment_bytes": 16777216,
                "attachments_per_turn": 8},
    )
    config = SimpleNamespace(llm_provider=SimpleNamespace(active_provider="codex"))
    settings = SimpleNamespace(config=config)
    return RuntimeService(core, settings, **owners)


@pytest.mark.asyncio
async def test_absent_engine_status_is_not_saved_model_readiness(tmp_path):
    service = make_service(tmp_path)
    # Prove the observer never recurses through the composition entry point.
    service.core.status = lambda: pytest.fail("recursive core.status call")
    status = await service.handle("status.get", {})
    assert status["phase"] == "ready"  # Transport readiness is separate from inference.
    assert status["model"] == {"main": None, "effort": None, "provider": None}
    assert all(row["health"] == "unavailable" for row in status["providers"])
    assert status["core_instance_id"] == "isolated-core"
    assert set(status["capabilities"]) == service.METHODS
    assert status["limits"]["attachment_bytes"] == 16777216
    assert "not configured" in status["summary"]


@pytest.mark.asyncio
async def test_status_tracks_gateway_serving_identity_changes(tmp_path):
    identity = SimpleNamespace(model="first", provider="codex", reasoning_effort="high")
    gateway = SimpleNamespace(capture_serving_identity=lambda: identity,
                              codex_client=None, ollama_client=None, compatible_client=None)
    service = make_service(tmp_path, llm=gateway)
    assert service.status()["model"]["main"] == "first"
    identity.model = "second"
    assert service.status()["model"]["main"] == "second"


def test_provider_guard_failure_is_unknown_not_live(tmp_path):
    def failed(*args):
        raise RuntimeError("fixture guard failure")
    gateway = SimpleNamespace(
        capture_serving_identity=lambda: None, codex_client=SimpleNamespace(auth=None),
        subsystem_guard=SimpleNamespace(is_usable=failed),
    )
    service = make_service(tmp_path, llm=gateway)
    providers = {item["name"]: item["health"] for item in service.status()["providers"]}
    assert providers["codex"] == "unknown"


@pytest.mark.asyncio
async def test_usage_absence_unknown_and_does_not_create_rollup(tmp_path):
    service = make_service(tmp_path)
    result = await service.handle("usage.get", {})
    assert result["period"] == "7d"
    assert result["tokens"] == {"value": None, "kind": "unknown"}
    assert result["context"] == {
        "used": {"value": None, "kind": "unknown"},
        "budget": {"value": None, "kind": "unknown"},
    }
    assert result["quota"] == []
    assert "history unavailable" in result["summary"]
    assert not service.core.paths.data_dir.exists()


def make_rollup(service):
    data = service.core.paths.data_dir
    return UsageRollup(str(data / "usage"), trajectory_directory=str(data / "trajectories"),
                       agent_trajectory_directory=str(data / "trajectories" / "agents"),
                       audit=AuditLogger(str(data / "audit.jsonl")))


def record(iteration, message="m1"):
    return {"source": "desktop", "channel_id": "c1", "message_id": message,
            "timestamp": datetime.now(UTC).isoformat(), "iterations": [iteration],
            "iteration_count": 1, "total_duration_ms": 10, "is_error": False}


@pytest.mark.asyncio
async def test_real_rollup_read_only_default_measured_estimated_unknown(tmp_path):
    service = make_service(tmp_path)
    rollup = make_rollup(service)
    await rollup.observe_trajectory(record({"iteration": 1, "server_input_tokens": 17,
                                          "input_token_provenance": "provider_reported",
                                          "server_output_tokens": 3,
                                          "output_token_provenance": "provider_reported"}), "turn")
    rollup._set_backfill_state(True)
    before = rollup.db_path.read_bytes()
    # Lazy default uses the real rollup observer against the profile database.
    result = await service.handle("usage.get", {"period": "all"})
    assert result["tokens"] == {"value": 20, "kind": "measured"}
    assert rollup.db_path.read_bytes() == before
    await rollup.observe_trajectory(record({"iteration": 1, "input_tokens": 11,
                                          "output_tokens": 2}, "m2"), "turn")
    result = await service.handle("usage.get", {"period": "all"})
    assert result["tokens"] == {"value": 33, "kind": "estimated"}
    await rollup.observe_trajectory(record({"iteration": 1}, "m3"), "turn")
    result = await service.handle("usage.get", {"period": "all"})
    assert result["tokens"] == {"value": None, "kind": "unknown"}


@pytest.mark.asyncio
async def test_corrupt_profile_rollup_is_unknown_not_fabricated(tmp_path):
    service = make_service(tmp_path)
    directory = service.core.paths.data_dir / "usage"
    directory.mkdir(parents=True)
    path = directory / "usage.sqlite3"
    path.write_bytes(b"not a sqlite database")
    result = await service.handle("usage.get", {})
    assert result["tokens"]["kind"] == "unknown"
    assert path.read_bytes() == b"not a sqlite database"


@pytest.mark.asyncio
async def test_context_snapshot_requires_explicit_provenance(tmp_path):
    context = SimpleNamespace(usage_snapshot=lambda: {
        "used": {"value": 100, "kind": "estimated"},
        "budget": {"value": 10000, "kind": "measured"},
    })
    result = await make_service(tmp_path, context=context).handle("usage.get", {})
    assert result["context"] == context.usage_snapshot()
    context.usage_snapshot = lambda: {
        "used": {"value": 5}, "budget": {"value": float("nan"), "kind": "measured"},
    }
    result = await make_service(tmp_path, context=context).handle("usage.get", {})
    assert all(item["kind"] == "unknown" for item in result["context"].values())


@pytest.mark.asyncio
async def test_real_quota_tracker_current_first_and_labels_scrubbed(tmp_path):
    tracker = CodexQuotaTracker(clock=lambda: 1000.0)
    tracker.record_headers("other", {"x-codex-primary-used-percent": "30",
                                     "x-codex-primary-window-minutes": "300"})
    tracker.record_headers("current", {"x-codex-primary-used-percent": "12",
                                       "x-codex-primary-window-minutes": "300",
                                       "x-codex-primary-reset-after-seconds": "30"})
    auth = SimpleNamespace(quota_view=lambda: tracker.view(
        current_key="current", known_keys=["other", "current"]),
                           describe_accounts=lambda: [{"key": "current", "label": "Primary"},
                                                     {"key": "other",
                                                      "label": "password=fixture-value"}])
    result = await make_service(tmp_path, quota=auth).handle("usage.get", {})
    assert result["quota"][0]["account"] == "Primary"
    assert result["quota"][0]["used_percent"] == {"value": 12.0, "kind": "measured"}
    assert result["quota"][0]["resets_at"] == 1030.0
    assert result["quota"][1]["used_percent"]["kind"] == "unknown"
    assert "fixture-value" not in json.dumps(result)
    assert "Other accounts" in result["summary"]


@pytest.mark.asyncio
async def test_real_context_reload_report_and_effect(tmp_path):
    directory = tmp_path / "context"
    directory.mkdir()
    (directory / "notes.md").write_text("A temporary context note.")
    context = ContextLoader(str(directory))
    service = make_service(tmp_path, context=context)
    calls = []
    service.prompt_builder = SimpleNamespace(
        invalidate=lambda: calls.append("prompt.invalidate"),
        rebuild_default=lambda: calls.append("prompt.rebuild"),
    )
    service.tool_catalog = SimpleNamespace(invalidate=lambda: calls.append("catalog.invalidate"))
    result = await service.handle("runtime.reload", {"scope": "context"})
    assert result["disposition"] == "reloaded"
    assert "notes.md" in result["summary"]
    assert "temporary context note" in context.context
    assert calls == ["prompt.invalidate", "catalog.invalidate", "prompt.rebuild"]


@pytest.mark.asyncio
async def test_profile_configured_context_is_lazy_not_boot_loaded(tmp_path):
    service = make_service(tmp_path)
    directory = tmp_path / "configured-context"
    directory.mkdir()
    (directory / "note.md").write_text("Isolated configured context")
    service.settings.config.context = SimpleNamespace(directory=str(directory))
    runtime = RuntimeService(service.core, service.settings)
    assert runtime.context.context == ""
    result = await runtime.handle("runtime.reload", {"scope": "context"})
    assert "note.md" in result["summary"]
    assert "Isolated configured context" in runtime.context.context


@pytest.mark.asyncio
async def test_config_reload_calls_owner_and_applies_observed_result(tmp_path):
    service = make_service(tmp_path)
    async def reload():
        service.settings.config.llm_provider.active_provider = "ollama"
        return {"summary": "Config reloaded; restart-only fields remain pending."}
    service.settings.reload = reload
    result = await service.handle("runtime.reload", {"scope": "config"})
    assert service.config.llm_provider.active_provider == "ollama"
    assert "restart-only" in result["summary"]


@pytest.mark.asyncio
async def test_real_settings_reload_unchanged_and_missing_atomic_owner(tmp_path):
    class TemporaryKeyring:
        def get_password(self, namespace, name):
            return None

    service = make_service(tmp_path)
    paths = service.core.paths
    paths.create_private()
    paths.config_file.write_text("personality:\n  custom_name: Initial\n")
    secrets = ProfileSecretStore(paths, backend=TemporaryKeyring())
    service.settings = SettingsService(paths, secrets)
    result = await service.handle("runtime.reload", {"scope": "config"})
    assert result == {"disposition": "reloaded", "summary": "Reloaded config."}
    paths.config_file.write_text("personality:\n  custom_name: Changed\n")
    with pytest.raises(MethodError) as error:
        await service.handle("runtime.reload", {"scope": "config"})
    assert error.value.code == "capability_unavailable"
    assert service.settings.config.personality.custom_name == "Initial"


@pytest.mark.asyncio
async def test_reload_absent_owner_not_fake_success(tmp_path):
    service = make_service(tmp_path)
    for scope in ("skills", "context", "config"):
        with pytest.raises(MethodError) as caught:
            await service.handle("runtime.reload", {"scope": scope})
        assert caught.value.code == "capability_unavailable"
    assert "runtime.shutdown" not in service.METHODS


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params", [("usage.get", {"period": "bad"}),
                                         ("usage.get", {"period": None}),
                                         ("runtime.reload", {"scope": []}),
                                         ("status.get", [])])
async def test_bad_parameters_are_protocol_refusals(tmp_path, method, params):
    with pytest.raises(MethodError) as caught:
        await make_service(tmp_path).handle(method, params)
    assert caught.value.code == "bad_request"


@pytest.mark.asyncio
async def test_provider_switch_without_owner_does_not_persist(tmp_path):
    with pytest.raises(MethodError) as caught:
        await make_service(tmp_path).switch_provider(
            "ollama", persist=lambda: pytest.fail("saved"), model_ref="test")
    assert caught.value.code == "capability_unavailable"


@pytest.mark.asyncio
async def test_provider_switch_delegates_persistence_to_actual_owner(tmp_path):
    calls = []
    def persist():
        calls.append("saved")
    async def switch(provider, *, persist, model_ref):
        calls.append((provider, model_ref))
        persist()
        return {"provider": provider, "model": model_ref}
    runtime = make_service(tmp_path, llm=SimpleNamespace(switch_provider=switch))
    result = await runtime.switch_provider("ollama", persist=persist, model_ref="fixture-model")
    assert result == {"provider": "ollama", "model": "fixture-model"}
    assert calls == [("ollama", "fixture-model"), "saved"]
