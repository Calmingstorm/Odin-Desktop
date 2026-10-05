"""Outbound management uses temporary config/keyring and stubbed HTTP only."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from src.config.schema import Config, OutboundWebhookTarget
from src.desktop.integrations import (
    IntegrationsService,
    _runtime_id,
    _secret_name,
    _url_secret_name,
)
from src.desktop.management import MethodError
from src.notifications.outbound_webhooks import OutboundWebhookDispatcher, sign_payload


class TemporaryKeyring:
    def __init__(self):
        self.values = {}
        self.fail = False

    def get(self, key):
        if self.fail:
            raise RuntimeError("locked keyring")
        return self.values.get(key)

    def set(self, key, value):
        if self.fail:
            raise RuntimeError("locked keyring")
        self.values[key] = value

    def clear(self, key):
        if self.fail:
            raise RuntimeError("locked keyring")
        self.values.pop(key, None)


class Settings:
    def __init__(self, tmp_path):
        self.config = Config()
        self.revision = 0
        self.secrets = TemporaryKeyring()
        self.path = tmp_path / "config.json"
        self.fail = False
        self.calls = []

    def save_changes(self, changes, *, method="settings.set", expected_revision=None):
        if self.fail:
            raise RuntimeError("private persistence error containing sensitive material")
        assert method.startswith("webhooks.outbound.")
        if expected_revision is not None and expected_revision != self.revision:
            raise MethodError("conflict", "settings revision changed")
        self.calls.append(deepcopy(changes))
        for path, rows in changes:
            assert path == ("outbound_webhooks", "targets")
            assert all(not row["secret"] for row in rows)
            self.config.outbound_webhooks.targets = [OutboundWebhookTarget(**row) for row in rows]
        self.path.write_text(json.dumps(self.config.model_dump()))
        self.revision += 1


@pytest.fixture
def service(tmp_path):
    return IntegrationsService(Settings(tmp_path))


async def create(service, **fields):
    return await service.handle("webhooks.outbound.save", {
        "name": "status", "url": "https://example.invalid/hook", **fields,
    })


async def test_crud_persists_real_rows_and_keyring_only_secret(service):
    target = await create(service, secret="temporary-signing-value", events=["health"])
    assert target["has_secret"] is True
    assert "secret" not in target
    assert "temporary-signing-value" not in service.settings.path.read_text()
    assert service.settings.secrets.get(_secret_name(target["id"])) == "temporary-signing-value"
    listed = await service.handle("webhooks.outbound.list", {})
    assert listed["webhooks"] == [target]
    assert listed["webhook_count"] == 1
    updated = await service.handle("webhooks.outbound.save", {
        "id": target["id"], "name": "renamed", "enabled": False,
    })
    assert updated["name"] == "renamed" and updated["has_secret"]
    # Config-restart reconstructs the retained owner from real rows and keyring.
    restored = IntegrationsService(service.settings)
    assert (await restored.handle("webhooks.outbound.list", {}))["webhooks"] == [updated]
    cleared = await service.handle("webhooks.outbound.save", {"id": target["id"], "secret": ""})
    assert cleared["has_secret"] is False
    deleted = await service.handle("webhooks.outbound.delete", {"id": target["id"]})
    assert deleted == {"status": "deleted", "webhook_id": target["id"]}
    assert service.settings.config.outbound_webhooks.targets == []
    assert service.settings.secrets.values == {}


@pytest.mark.parametrize("fields", [
    {"url": "file:///safe"}, {"url": "http://169.254.169.254/"},
    {"url": "http://metadata.google.internal/"}, {"url": ""},
    {"events": ["unknown"]}, {"events": ["all", "health"]}, {"events": "health"},
    {"enabled": 1}, {"scrub_secrets": "yes"}, {"verify_ssl": None},
    {"secret": 123}, {"secret": "s" * 257}, {"name": "n" * 101},
])
async def test_source_validation_rejects_without_mutation(service, fields):
    with pytest.raises(MethodError) as error:
        await create(service, **fields)
    assert error.value.code == "bad_request"
    assert not service.settings.calls
    assert not service.settings.secrets.values
    assert service.dispatcher.list_webhooks() == []


async def test_private_destinations_and_put_limits_match_upstream(service):
    row = await create(service, url="http://127.0.0.1:8123/hook")
    updated = await service.handle("webhooks.outbound.save", {
        "id": row["id"], "name": "n" * 128, "enabled": None,
    })
    assert updated["name"] == "n" * 128
    assert updated["enabled"] is True


async def test_persistence_failure_keeps_runtime_and_restores_vault(service):
    row = await create(service, secret="original")
    before = service.dispatcher.get_status()
    service.settings.fail = True
    with pytest.raises(MethodError, match="could not save"):
        await service.handle("webhooks.outbound.save", {"id": row["id"], "secret": "replacement"})
    assert service.dispatcher.get_status() == before
    assert service.settings.secrets.get(_secret_name(row["id"])) == "original"


async def test_failed_owner_apply_rolls_back_durable_config_runtime_and_vault(service, monkeypatch):
    row = await create(service, secret="original")
    before_rows = service.settings.config.outbound_webhooks.targets

    def fail_after_adoption(dispatcher, targets):
        # The save must precede any owner effect, even one failing after effect.
        assert service.settings.config.outbound_webhooks.targets[0].name == "changed"
        dispatcher._webhooks = targets
        raise RuntimeError("owner rejected adoption")

    monkeypatch.setattr(service, "_apply_targets", fail_after_adoption)
    with pytest.raises(MethodError, match="could not save"):
        await service.handle("webhooks.outbound.save", {
            "id": row["id"], "name": "changed", "secret": "replacement",
        })
    assert service.settings.config.outbound_webhooks.targets == before_rows
    assert service.dispatcher.get(row["id"]).name == "status"
    assert service.settings.secrets.get(_secret_name(row["id"])) == "original"
    saved = json.loads(service.settings.path.read_text())["outbound_webhooks"]["targets"]
    assert saved[0]["name"] == "status"


async def test_locked_keyring_and_stale_revision_do_not_claim_success(service):
    service.settings.secrets.fail = True
    with pytest.raises(MethodError, match="could not save"):
        await create(service, secret="key")
    assert not service.settings.calls
    service.settings.secrets.fail = False
    with pytest.raises(MethodError) as error:
        await create(service, secret="key", expected_revision=100)
    assert error.value.code == "stale_binding"
    assert not service.settings.secrets.values


async def test_idless_duplicate_url_reindex_preserves_rows_keys_and_rejected_config(service):
    settings = service.settings
    settings.config.outbound_webhooks.targets = [
        OutboundWebhookTarget(name="first", url="http://127.0.0.1/hook"),
        OutboundWebhookTarget(name="second", url="http://127.0.0.1/hook"),
        OutboundWebhookTarget(name="invalid", url="file:///safe"),
    ]
    ids = [
        _runtime_id(row, index)
        for index, row in enumerate(settings.config.outbound_webhooks.targets)
    ]
    settings.secrets.set(_secret_name(ids[1]), "second-key")
    await service.handle("webhooks.outbound.delete", {"id": ids[0]})
    rows = settings.config.outbound_webhooks.targets
    assert [row.name for row in rows] == ["second", "invalid"]
    assert rows[0].id == ""
    second = service.dispatcher.get(_runtime_id(rows[0], 0))
    assert second.name == "second" and second.secret == "second-key"
    restored = IntegrationsService(settings)
    assert (await restored.handle("webhooks.outbound.list", {}))["webhooks"][0]["has_secret"]


async def test_idless_url_edit_writes_explicit_id(service):
    row = OutboundWebhookTarget(name="legacy", url="http://127.0.0.1/old")
    service.settings.config.outbound_webhooks.targets = [row]
    ident = _runtime_id(row, 0)
    updated = await service.handle("webhooks.outbound.save", {"id": ident, "url": "http://127.0.0.1/new"})
    assert updated["id"] == ident
    assert service.settings.config.outbound_webhooks.targets[0].id == ident


async def test_plaintext_config_signing_secret_never_adopted(service):
    service.settings.config.outbound_webhooks.targets = [
        OutboundWebhookTarget(url="https://example.invalid/hook", secret="legacy-plaintext"),
    ]
    with pytest.raises(MethodError, match="keyring storage"):
        await service.handle("webhooks.outbound.list", {})
    assert service.dispatcher is None


class Response:
    headers = {}

    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class HTTPSession:
    closed = False

    def __init__(self, status):
        self.status = status
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return Response(self.status)


@pytest.mark.parametrize("status, success", [(204, True), (400, False)])
async def test_delivery_is_retained_dispatcher_with_stubbed_http_only(service, status, success):
    target = await create(service, secret="test-signing-key")
    session = HTTPSession(status)
    service.dispatcher._session = session
    result = await service.handle("webhooks.outbound.test", {"id": target["id"]})
    assert result["success"] is success
    assert result["status_code"] == status
    assert result["event_type"] == "test"
    url, request = session.requests[0]
    assert url == "https://example.invalid/hook"
    expected = "sha256=" + sign_payload(request["data"], "test-signing-key")
    assert request["headers"]["X-Webhook-Signature"] == expected
    assert service.dispatcher.stats.total_dispatched == 1
    assert service.dispatcher.stats.total_delivered == int(success)


async def test_missing_ids_do_not_send_or_change_config(service):
    for method in ("save", "delete", "test"):
        with pytest.raises(MethodError) as error:
            await service.handle(f"webhooks.outbound.{method}", {"id": "missing"})
        assert error.value.code == "not_found"
    assert not service.settings.calls


async def test_email_state_never_exposes_passwords_or_delivers(service):
    service.settings.config.email.smtp.password = "smtp-private"
    service.settings.config.email.imap.password = "imap-private"
    row = await service.handle("integrations.email.get", {})
    assert row["enabled"] is False
    assert "password" not in row["smtp"] and "password" not in row["imap"]
    assert service.dispatcher is None
    assert not service.settings.calls


async def test_injected_dispatcher_retains_actual_statistics_and_targets(service):
    dispatcher = OutboundWebhookDispatcher(rate_limit_seconds=7)
    dispatcher.stats.total_failed = 8
    injected = IntegrationsService(service.settings, dispatcher=dispatcher)
    result = await injected.handle("webhooks.outbound.list", {})
    assert result["stats"]["total_failed"] == 8
    assert result["rate_limit_seconds"] == 7


async def test_keyring_false_is_not_acknowledged(service, monkeypatch):
    monkeypatch.setattr(service.settings.secrets, "set", lambda *args: False)
    with pytest.raises(MethodError, match="could not save"):
        await create(service, secret="temporary-key")
    assert not service.settings.calls
    assert not service.dispatcher.list_webhooks()


async def test_owner_false_rejects_and_restores(service, monkeypatch):
    monkeypatch.setattr(service, "_apply_targets", lambda *args: False)
    with pytest.raises(MethodError, match="could not save"):
        await create(service, secret="temporary-key")
    assert not service.settings.config.outbound_webhooks.targets
    assert not service.settings.secrets.values
    assert not service.dispatcher.list_webhooks()


async def test_rollback_failure_reports_unknown_not_success(service, monkeypatch):
    def fail_and_break_rollback(*args):
        service.settings.fail = True
        raise RuntimeError("owner failed")

    monkeypatch.setattr(service, "_apply_targets", fail_and_break_rollback)
    with pytest.raises(MethodError, match="rollback failed") as error:
        await create(service, secret="temporary-key")
    assert error.value.disposition == "outcome_unknown"
    assert not service.dispatcher.list_webhooks()


async def test_dispatcher_limit_is_preserved(service):
    dispatcher = OutboundWebhookDispatcher()
    for index in range(50):
        dispatcher.register(name=str(index), url="http://127.0.0.1/hook")
    service.dispatcher = dispatcher
    with pytest.raises(MethodError) as error:
        await create(service)
    assert error.value.code == "bad_request"
    assert len(dispatcher.list_webhooks()) == 50
    assert not service.settings.calls


async def test_url_auth_is_keyring_only_without_stricter_source_rejection(service):
    row = await create(service, name="", url="https://user:temporary-password@example.invalid/hook")
    assert "temporary-password" not in json.dumps(row)
    saved_url = service.settings.config.outbound_webhooks.targets[0].url
    assert saved_url == "https://example.invalid/hook"
    assert "temporary-password" not in service.settings.path.read_text()
    assert service.settings.secrets.get(_url_secret_name(row["id"])) is not None
    restored = IntegrationsService(service.settings)
    await restored.handle("webhooks.outbound.list", {})
    assert restored.dispatcher.get(row["id"]).url.startswith("https://user:temporary-password@")
    await restored.handle("webhooks.outbound.delete", {"id": row["id"]})
    assert service.settings.secrets.values == {}


async def test_real_settings_and_profile_keyring_adapter_roundtrip(tmp_path):
    from src.config.persistence import _load_document
    from src.desktop.paths import ProfilePaths
    from src.desktop.secrets import ProfileSecretStore
    from src.desktop.settings import SettingsService

    class Backend:
        def __init__(self):
            self.values = {}

        def get_password(self, namespace, key):
            return self.values.get((namespace, key))

        def set_password(self, namespace, key, value):
            self.values[namespace, key] = value

        def delete_password(self, namespace, key):
            self.values.pop((namespace, key), None)

    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    paths.create_private()
    paths.config_file.write_text("{}")
    backend = Backend()
    secrets = ProfileSecretStore(paths, backend=backend)
    settings = SettingsService(paths, secrets, config=Config())
    service = IntegrationsService(settings)
    row = await create(service, secret="temporary-credential")
    assert "temporary-credential" not in paths.config_file.read_text()
    assert backend.values
    document, _ = _load_document(paths.config_file)
    assert document.get("outbound_webhooks", {}).get("targets"), paths.config_file.read_text()
    fresh_settings = SettingsService(paths, secrets)
    restored = IntegrationsService(fresh_settings)
    listed = await restored.handle("webhooks.outbound.list", {})
    assert listed["webhooks"][0]["id"] == row["id"]
    assert listed["webhooks"][0]["has_secret"] is True
    await restored.handle("webhooks.outbound.delete", {"id": row["id"]})
    assert not backend.values
