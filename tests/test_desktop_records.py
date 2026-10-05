"""Real audit and read-only turn observations, entirely under temporary roots."""
from __future__ import annotations

import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from src.audit.logger import AuditLogger
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.records import METHODS, READ_METHODS, RecordsService
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.health.checker import check_all
from src.turn_state.observer import read_turn_snapshot
from src.turn_state.store import TurnStateStore


@pytest.fixture
def paths(tmp_path):
    return ProfilePaths.from_xdg(home=tmp_path, environ={})


@pytest.fixture
async def audit(tmp_path):
    logger = AuditLogger(str(tmp_path / "audit" / "audit.jsonl"),
                         hmac_key="isolated-test-signing-key", classify_failures=False)
    for tool, host, error in (
        ("run_command", "alpha", None),
        ("run_command", "beta", "fixture failure"),
        ("http_probe", "alpha", None),
        ("run_command", "alpha", "fixture failure"),
    ):
        await logger.log_execution(
            user_id="test-owner", user_name="Fixture", channel_id="isolated",
            tool_name=tool, tool_input={"host": host, "password": "fixture-password"},
            approved=True, result_summary="test record", execution_time_ms=3, error=error,
        )
    return logger


async def test_default_lazy_profile_audit_and_unsigned_verification(paths):
    service = RecordsService(paths)
    assert not paths.data_dir.exists()
    assert await service.handle("audit.query", {}) == []
    assert service.audit.path == paths.data_dir / "audit.jsonl"
    assert not service.audit.path.exists()
    result = await service.handle("audit.verify", {})
    assert result["valid"] is False
    assert result["availability"] == "not_enabled"
    assert result["verified"] == 0
    assert "Signing not enabled" in result["error"]
    assert await service.handle("logs.search", {}) == {"entries": [], "count": 0}
    assert not paths.data_dir.exists()


@pytest.mark.parametrize("signed", [False, True])
async def test_settings_live_relocated_audit_reader(paths, tmp_path, signed):
    class MemoryKeyring:
        def __init__(self):
            self.values = {}

        def get_password(self, namespace, name):
            return self.values.get((namespace, name))

        def set_password(self, namespace, name, value):
            self.values[namespace, name] = value

        def delete_password(self, namespace, name):
            self.values.pop((namespace, name), None)

    paths.create_private()
    paths.config_file.write_text("{}\n")
    secrets = ProfileSecretStore(paths, backend=MemoryKeyring())
    key = "temporary-records-signing-key" if signed else ""
    secrets.set("audit.hmac_key", key)
    settings = SettingsService(paths, secrets)
    assert settings.hydrate_secrets()
    service = RecordsService(paths, settings=settings)
    writer = AuditLogger(str(paths.data_dir / "audit.jsonl"), hmac_key=key)
    await writer.log_event(event_type="fixture", action="original", detail="original record")
    assert (await service.handle("audit.query", {}))[0]["tool_name"] == "original"
    original_reader = service.audit
    original_bytes = writer.path.read_bytes()
    original_chain = writer._signer.prev_hmac if signed else None

    relocated = tmp_path / "relocated" / "history.jsonl"
    relocated_writer = AuditLogger(str(relocated), hmac_key=key)
    await relocated_writer.log_event(
        event_type="fixture", action="relocated", detail="relocated record")
    relocated_bytes = relocated.read_bytes()
    marker = relocated.with_name(relocated.name + ".repair-required")
    marker.write_text("temporary unsettled marker")
    saved = await settings.handle("settings.set", {
        "expected_revision": settings.revision,
        "changes": [{"path": "tools.audit_log_path", "value": str(relocated)}],
    })
    assert saved["fields"][0]["apply_mode"] == "restart"
    assert any(consumer["apply_mode"] == "live_read"
               for consumer in saved["fields"][0]["consumers"])
    assert settings.config.tools.audit_log_path == str(relocated)
    assert (await service.handle("audit.query", {}))[0]["tool_name"] == "relocated"
    assert service.audit is not original_reader
    assert service.audit.path == relocated
    assert (await service.handle("logs.search", {}))["entries"][0]["tool_name"] == "relocated"
    verified = await service.handle("audit.verify", {})
    assert verified["valid"] is signed
    assert verified["verified"] == (1 if signed else 0)
    assert writer.path == paths.data_dir / "audit.jsonl"
    assert writer.path.read_bytes() == original_bytes
    assert (writer._signer.prev_hmac if signed else None) == original_chain
    assert relocated.read_bytes() == relocated_bytes
    assert marker.read_text() == "temporary unsettled marker"

    missing = tmp_path / "never-created" / "nested" / "audit.jsonl"
    await settings.handle("settings.set", {
        "expected_revision": settings.revision,
        "changes": [{"path": "tools.audit_log_path", "value": str(missing)}],
    })
    assert await service.handle("audit.query", {}) == []
    assert await service.handle("logs.search", {}) == {"entries": [], "count": 0}
    await service.handle("audit.verify", {})
    assert not missing.parent.parent.exists()
    # Explicit injected audit seams are not rebound by settings changes.
    injected = RecordsService(paths, settings=settings, audit=writer)
    assert injected.audit is writer
    assert (await injected.handle("audit.query", {}))[0]["tool_name"] == "original"


async def test_audit_filters_raw_shape_and_nonmutating_reads(paths, audit):
    service = RecordsService(paths, audit=audit)
    before = audit.path.read_bytes()
    all_entries = await service.handle("audit.query", {})
    assert len(all_entries) == 4
    assert all_entries[0]["tool_input"]["host"] == "alpha"
    assert all_entries[0]["error"] == "fixture failure"
    assert all_entries[0]["tool_input"]["password"] == "[REDACTED]"
    assert "fixture-password" not in json.dumps(all_entries)
    filtered = await service.handle("audit.query", {
        "tool": "run_command", "host": "alpha", "user": "fixture",
        "q": "test record", "date": all_entries[0]["timestamp"][:10], "error_only": True,
    })
    assert filtered == [all_entries[0]]
    assert await service.handle("audit.query", {"date": "1900"}) == []
    assert await service.handle("audit.query", {"q": "no such entry"}) == []
    assert audit.path.read_bytes() == before


async def test_audit_path_callback_refreshes_without_creating_paths(paths, audit, tmp_path):
    current = audit.path
    service = RecordsService(paths, get_audit_path=lambda: current)
    assert len(await service.handle("audit.query", {})) == 4
    reader = service.audit
    current = tmp_path / "callback-missing" / "audit.jsonl"
    assert await service.handle("audit.query", {}) == []
    assert service.audit is not reader
    assert service.audit.path == current
    assert await service.handle("logs.search", {}) == {"entries": [], "count": 0}
    assert not current.parent.exists()


async def test_real_signed_verify_and_tampered_chain(paths, audit):
    service = RecordsService(paths, audit=audit)
    verified = await service.handle("audit.verify", {})
    assert verified["valid"] is True
    assert verified["verified"] == verified["total"] == 4
    assert verified["segments"][0]["status"] == "verified"
    # Only a disposable fixture is changed. The service must not repair it.
    content = audit.path.read_text().replace("test record", "altered record", 1)
    audit.path.write_text(content)
    result = await service.handle("audit.verify", {})
    assert result["valid"] is False
    assert result["first_bad"] is not None
    assert result["segments"][0]["status"] == "broken"
    assert audit.path.read_text() == content


async def test_logs_use_real_audit_derived_levels_and_time_filters(paths, audit):
    service = RecordsService(paths, audit=audit)
    raw = await audit.search(limit=10)
    result = await service.handle("logs.search", {
        "level": "error", "tool": "run_command", "q": "fixture failure",
        "start": raw[0]["timestamp"], "end": raw[0]["timestamp"],
    })
    assert result == {"entries": [raw[0]], "count": 1}
    info = await service.handle("logs.search", {"level": "info"})
    assert info["count"] == 2
    assert all(not entry["error"] for entry in info["entries"])
    assert (await service.handle("logs.search", {"end": "1900"}))["count"] == 0


async def test_explicit_logs_override_does_not_read_audit(paths, audit, tmp_path):
    logs = AuditLogger(str(tmp_path / "separate" / "audit.jsonl"))
    await logs.log_event(event_type="fixture", action="separate", detail="separate record")
    result = await RecordsService(paths, audit=audit, logs=logs).handle("logs.search", {})
    assert result["count"] == 1
    assert result["entries"][0]["tool_name"] == "separate"


@pytest.mark.parametrize("method, default, maximum", [
    ("audit.query", 50, 200), ("logs.search", 100, 500),
])
async def test_route_limits_default_fallback_and_clamp(paths, method, default, maximum):
    class Backend:
        async def search(self, **kwargs):
            self.limit = kwargs["limit"]
            return [{"tool_name": str(i)} for i in range(600)]

        search_logs = search

    backend = Backend()
    service = RecordsService(paths, audit=backend)
    for value, expected in [(None, default), ("invalid", default), (0, 1), (-3, 1),
                            (100000, maximum), ("7", 7)]:
        result = await service.handle(method, {"limit": value})
        assert backend.limit == expected
        assert len(result["entries"] if isinstance(result, dict) else result) == expected


async def test_scrub_legacy_audit_and_bound_injected_diagnostics(paths, tmp_path):
    logger = AuditLogger(str(tmp_path / "legacy" / "audit.jsonl"))
    logger.path.write_text(json.dumps({
        "timestamp": "2026-10-05", "tool_name": "fixture",
        "tool_input": {"apiKey": "legacy-secret", "command": "harmless text"},
        "result_summary": "Bearer legacy-credential",
    }) + "\n")
    result = await RecordsService(paths, audit=logger).handle("audit.query", {})
    assert result[0]["tool_input"]["apiKey"] == "[REDACTED]"
    assert result[0]["tool_input"]["command"].startswith("<shell command:")
    assert "legacy-credential" not in json.dumps(result)
    payload = {"detail": "Bearer " + "a" * 8000, "long": "b" * 8000,
               "components": [{"token": "fixture-private"}] * 800}
    health = await RecordsService(paths, health=lambda: payload).handle("health.get", {})
    assert health["detail"] == "[REDACTED]"
    assert len(health["long"]) <= 4000
    assert len(health["components"]) == 500
    assert "fixture-private" not in json.dumps(health)
    assert len(payload["components"]) == 800
    assert payload["components"][0]["token"] == "fixture-private"


@pytest.mark.parametrize("callable_checker", [False, True])
async def test_real_health_checker_injection(paths, callable_checker):
    runtime = SimpleNamespace()
    expected = check_all(runtime)
    backend = (lambda: check_all(runtime)) if callable_checker else runtime
    actual = await RecordsService(paths, health=backend).handle("health.get", {})
    assert actual["components"] == expected["components"]
    for key in ("overall", "healthy_count", "degraded_count", "down_count", "total",
                "unconfigured_count", "unavailable_count"):
        assert actual[key] == expected[key]
    assert actual["total"] > 0
    assert actual["checked_at"]


async def test_missing_health_and_unavailable_managers_are_honest(paths):
    service = RecordsService(paths, audit=object(), logs=object())
    for method in ("health.get", "audit.query", "audit.verify", "logs.search"):
        with pytest.raises(MethodError) as error:
            await service.handle(method, {})
        assert error.value.code == "capability_unavailable"
        assert error.value.disposition == "rejected"

    def failed_health():
        raise RuntimeError("token=fixture-secret")

    with pytest.raises(MethodError) as error:
        await RecordsService(paths, health=failed_health).handle("health.get", {})
    assert error.value.code == "unavailable"
    assert "fixture-secret" not in error.value.message


@pytest.mark.parametrize("method, params, code", [
    ("unsupported", {}, "method_not_found"),
    ("health.get", [], "bad_request"),
    ("logs.search", {"level": "debug"}, "bad_request"),
    ("audit.query", {"tool": 42}, "bad_request"),
    ("logs.search", {"q": []}, "bad_request"),
])
async def test_method_errors(paths, method, params, code):
    with pytest.raises(MethodError) as error:
        await RecordsService(paths).handle(method, params)
    assert error.value.code == code
    assert error.value.disposition == "rejected"
    assert not paths.data_dir.exists()


@pytest.fixture
def turn_db(paths):
    path = paths.data_dir / "turn_state" / "turns.sqlite3"
    store = TurnStateStore(path)
    assert store.available
    store.close()
    now = time.time()
    with sqlite3.connect(path) as connection:
        for i, status in enumerate(("ACTIVE", "SUSPENDED", "COMPLETED")):
            connection.execute(
                "INSERT INTO turns (source,channel_id,message_id,turn_generation,status,"
                "last_progress_at,created_at,schema_version,lease_token,payload) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("desktop", "fixture", str(i), "generation", status, now, now, 1,
                 "fixture-private-lease", json.dumps({"password": "fixture-private-payload"})),
            )
    return path


async def test_turn_snapshot_real_reader_never_sweeps_or_opens_writer(paths, turn_db, monkeypatch):
    def writer_forbidden(*args, **kwargs):
        raise AssertionError("writer construction forbidden")

    monkeypatch.setattr(TurnStateStore, "__init__", writer_forbidden)
    before = turn_db.read_bytes()
    result = await RecordsService(paths).handle("turn_state.list", {})
    assert result["availability"] == "available"
    assert result["limit"] == 100
    assert result["data"] == read_turn_snapshot(str(turn_db), 100)
    assert result["data"]["counts"]["active"] == 1
    assert result["data"]["counts"]["suspended"] == 1
    assert result["data"]["truncated"] is False
    assert {turn["status"] for turn in result["data"]["turns"]} == {"ACTIVE", "SUSPENDED"}
    assert "fixture-private" not in json.dumps(result)
    assert turn_db.read_bytes() == before
    with sqlite3.connect(turn_db) as connection:
        state = connection.execute(
            "SELECT status FROM turns WHERE message_id='0'").fetchone()[0]
        assert state == "ACTIVE"


async def test_turn_injected_path_and_limits(paths, turn_db):
    other = ProfilePaths.from_xdg(home=paths.config_dir / "other-home", environ={})
    backend = SimpleNamespace(db_path=turn_db)
    service = RecordsService(other, turn_state=backend)
    for value, expected in [(None, 100), ("bad", 100), (0, 1), (300, 200), ("1", 1)]:
        result = await service.handle("turn_state.list", {"limit": value})
        assert result["availability"] == "available"
        assert result["limit"] == expected
        assert len(result["data"]["turns"]) == min(2, expected)
    assert not other.data_dir.exists()


async def test_turn_absence_and_read_errors_return_empty_envelopes(paths):
    absent = await RecordsService(paths).handle("turn_state.list", {})
    assert absent["availability"] == "not_enabled"
    assert absent["data"] == {}
    assert not paths.data_dir.exists()
    missing = paths.data_dir / "missing.sqlite3"
    result = await RecordsService(paths, turn_state=SimpleNamespace(db_path=missing)).handle(
        "turn_state.list", {})
    assert result["availability"] == "unavailable"
    assert result["data"] == {}
    assert not missing.exists()
    corrupt = paths.data_dir / "turn_state" / "turns.sqlite3"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("fixture non-database")
    result = await RecordsService(paths).handle("turn_state.list", {})
    assert result["availability"] == "unavailable"
    assert result["data"] == {}
    assert corrupt.read_text() == "fixture non-database"


def test_all_methods_are_read_only():
    assert METHODS == READ_METHODS == RecordsService.READ_METHODS == {
        "audit.query", "audit.verify", "health.get", "logs.search", "turn_state.list",
    }
