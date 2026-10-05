"""Named services exercised through the authenticated core transport."""
from __future__ import annotations

import hashlib
import os
import uuid

import pytest

from src.desktop.core import CoreService
from tests.test_desktop_core_lifecycle import connect, profile, receive, request


class TemporaryKeyring:
    def __init__(self):
        self.values = {}
        self.locked = False

    def get_password(self, service, name):
        if self.locked:
            raise RuntimeError("keyring locked")
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        if self.locked:
            raise RuntimeError("keyring locked")
        self.values[service, name] = value

    def delete_password(self, service, name):
        if self.locked:
            raise RuntimeError("keyring locked")
        self.values.pop((service, name), None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import aiohttp

    def refused_session(*args, **kwargs):
        raise AssertionError("Composed management tests must stub every network operation")

    monkeypatch.setattr(aiohttp, "ClientSession", refused_session)


@pytest.fixture
async def connected(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    backend = TemporaryKeyring()
    service = CoreService(paths, socket_path, token_file, secret_backend=backend)
    writer = None
    try:
        await service.start(read_fd)
        reader, writer, welcome = await connect(socket_path)
        yield service, reader, writer, backend, welcome
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await service.close()
        os.close(read_fd)
        os.close(write_fd)


async def test_schema_write_event_and_stale_binding_over_transport(connected):
    service, reader, writer, _, welcome = connected
    assert welcome["protocol"]["minor"] == 3  # older clients are accepted, minor is additive
    assert {"settings.schema", "secrets.set", "hosts.list", "memory.set"} <= set(
        welcome["capabilities"])
    schema = (await request(reader, writer, "settings.schema"))["result"]
    assert schema["image_models"]["image_model"]["status"] == "follow"
    params = {"expected_revision": schema["revision"],
              "changes": [{"path": "logging.level", "value": "DEBUG"}]}
    command_id = str(uuid.uuid4())
    first = await request(reader, writer, "settings.set", params, command_id)
    assert first["ok"], first
    assert await request(reader, writer, "settings.set", params, command_id) == first
    stale = await request(reader, writer, "settings.set", params)
    assert stale["error"]["code"] == "stale_binding"
    high = service.events.high
    await request(reader, writer, "events.subscribe", {"after": str(int(high) - 1)})
    event = await receive(reader)
    assert event["type"] == "settings.changed"
    assert event["payload"]["rev"] == first["result"]["revision"]
    assert event["payload"]["paths"] == ["logging.level"]


async def test_keyring_secret_and_memory_share_core_owners(connected):
    service, reader, writer, backend, _ = connected
    secret = "dummy-step5-credential"
    result = await request(reader, writer, "secrets.set", {
        "path": "email.smtp.password", "value": secret,
    })
    assert result["result"] == {"set": True}
    assert secret in backend.values.values()
    assert secret not in service.paths.config_file.read_text()
    row = service.store.connection.execute(
        "SELECT binding,response FROM command_receipts ORDER BY created_at DESC LIMIT 1",
    ).fetchone()
    assert secret not in str(tuple(row))
    schema = (await request(reader, writer, "settings.schema"))["result"]
    assert secret not in str(schema)
    saved = await request(reader, writer, "memory.set", {
        "scope": "global", "key": "step5", "value": "shared-store",
    })
    assert saved["ok"]
    assert service.management.executor._load_all_memory()["global"]["step5"] == "shared-store"
    backend.locked = True
    refused = await request(reader, writer, "secrets.set", {
        "path": "email.smtp.password", "value": "other-dummy",
    })
    assert not refused["ok"]


async def test_locked_keyring_list_returns_distinct_safe_error_over_transport(connected):
    service, reader, writer, backend, _ = connected
    backend.locked = True
    response = await request(reader, writer, "codex.accounts.list")
    assert not response["ok"]
    assert response["error"]["code"] == "keyring_unavailable"
    assert response["error"]["message"] == "The system keyring is locked or unavailable"
    assert response["error"]["disposition"] == "rejected"
    assert service.store.connection.execute(
        "SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 0
    backend.locked = False
    retry = await request(reader, writer, "codex.accounts.list")
    assert retry["ok"] and retry["result"] == {"configured": False, "accounts": []}


async def test_fresh_host_usage_and_health_are_real_reads(connected):
    service, reader, writer, _, _ = connected
    hosts = (await request(reader, writer, "hosts.list"))["result"]
    assert hosts["default_host"] == "localhost"
    usage = (await request(reader, writer, "usage.get"))["result"]
    assert usage["tokens"] == {"value": None, "kind": "unknown"}
    health = (await request(reader, writer, "health.get"))["result"]
    assert health["total"] > 0
    assert any(component["name"] == "open_files" for component in health["components"])
    assert service.store.connection.execute(
        "SELECT COUNT(*) FROM command_receipts").fetchone()[0] == 0


async def test_fresh_public_key_survives_real_core_restart(tmp_path):
    from src.tools.hosts.trust import fingerprint_public_key

    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    backend = TemporaryKeyring()
    original_public = None
    original_private = None
    try:
        for _ in range(2):
            core = CoreService(paths, socket_path, token_file, secret_backend=backend)
            writer = None
            try:
                await core.start(read_fd)
                reader, writer, _ = await connect(socket_path)
                response = await request(reader, writer, "hosts.public_key")
                assert response["ok"], response
                public = response["result"]
                assert public["public_key"].startswith("ssh-ed25519 ")
                assert public["fingerprint"] == fingerprint_public_key(public["public_key"])
                key = paths.secrets_dir / "id_ed25519"
                assert core.management.settings.config.tools.ssh_key_path == str(key)
                assert key.stat().st_mode & 0o777 == 0o600
                if original_public is None:
                    original_public, original_private = public, key.read_bytes()
                else:
                    assert public == original_public
                    assert key.read_bytes() == original_private
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await core.close()
    finally:
        os.close(read_fd)
        os.close(write_fd)


async def test_unknown_extras_do_not_become_event_paths_and_shell_applies(connected):
    service, reader, writer, _, _ = connected
    high = service.events.high
    result = await request(reader, writer, "runtime.reload", {
        "scope": "context", "changes": None,
    })
    assert result["ok"]
    assert service.events.high == high
    schema = (await request(reader, writer, "settings.schema"))["result"]
    changed = await request(reader, writer, "settings.set", {
        "expected_revision": schema["revision"],
        "changes": [{"path": "tools.command_shell", "value": "sh"}],
    })
    assert changed["ok"]
    assert service.management.executor._command_shell_mode() == "sh"
    result = await request(reader, writer, "runtime.reload", {
        "scope": "context", "changes": [{"path": "dummy-private-value"}],
    })
    assert result["ok"]
    assert "dummy-private-value" not in str(service.store.connection.execute(
        "SELECT frame FROM journal_events").fetchall())


async def test_binding_is_keyed_and_stable_for_profile_restart(connected):
    service, reader, writer, _, _ = connected
    params = {"path": "email.smtp.password", "value": "short-dummy"}
    identity = service.management.identity_params(params)
    assert "hmac_sha256" in identity
    from src.desktop.commands import canonical_json
    from src.desktop.management import _binding_key

    assert identity["hmac_sha256"] != hashlib.sha256(canonical_json(params).encode()).hexdigest()
    assert _binding_key(service.paths) == service.management._identity_key
    result = await request(reader, writer, "secrets.set", params)
    assert result["ok"]


async def test_real_core_restart_replays_secret_without_second_keyring_write(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    backend = TemporaryKeyring()
    writes = []
    original = backend.set_password

    def record_write(*args):
        writes.append(args)
        return original(*args)

    backend.set_password = record_write
    command_id = str(uuid.uuid4())
    params = {"path": "email.smtp.password", "value": "dummy-restart-value"}
    first_response = None
    try:
        for _ in range(2):
            core = CoreService(paths, socket_path, token_file, secret_backend=backend)
            writer = None
            try:
                await core.start(read_fd)
                reader, writer, _ = await connect(socket_path)
                response = await request(reader, writer, "secrets.set", params, command_id)
                assert response["ok"]
                if first_response is None:
                    first_response = response
                else:
                    assert response == first_response
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await core.close()
        assert len(writes) == 1
    finally:
        os.close(read_fd)
        os.close(write_fd)


async def test_config_reload_adopts_saved_live_values_atomically(connected):
    service, reader, writer, _, _ = connected
    from src.config.persistence import _patch_config_paths

    _patch_config_paths([(("tools", "command_shell"), "sh")], path=service.paths.config_file)
    assert service.management.executor._command_shell_mode() == "auto"
    response = await request(reader, writer, "runtime.reload", {"scope": "config"})
    assert response["ok"], response
    assert service.management.executor._command_shell_mode() == "sh"
    assert service.management.settings.config.tools.command_shell == "sh"


async def test_codex_login_publishes_and_last_remove_retires_real_provider(connected, monkeypatch):
    service, reader, writer, _, _ = connected
    import time

    class DeviceClient:
        async def request_device_code(self):
            return {"device_auth_id": "temporary-device", "user_code": "TEMP-CODE", "interval": 1}

        async def poll_device_auth_once(self, auth_id, code):
            return {"access_token": "dummy-access", "refresh_token": "dummy-refresh",
                    "account_id": "temporary-account", "email": "example@example.invalid",
                    "expires_at": time.time() + 1000}

    codex = service.management.codex
    codex.client = DeviceClient()
    async def compatible_probe(client):
        return None
    monkeypatch.setattr(service.management.providers, "_probe_aux", compatible_probe)
    begun = await request(reader, writer, "codex.login.begin")
    assert begun["ok"]
    codex._logins["temporary-device"].next_poll = 0
    response = await request(reader, writer, "codex.login.poll", {
        "device_auth_id": "temporary-device", "user_code": "TEMP-CODE",
    })
    assert response["ok"], response
    assert service.management.providers.codex_client is not None
    removed = await request(reader, writer, "codex.accounts.remove", {"index": 0})
    assert removed["ok"], removed
    assert service.management.providers.codex_client is None
