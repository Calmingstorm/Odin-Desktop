"""Batch-B boundary probes, not partial exports of blocked inherited suites.

The complete native knowledge suite runs directly at its original path. These
tests establish why an unchanged HTTP-status assertion cannot be exported as a
Desktop result without inventing transport semantics. Only disposable profiles,
an in-memory keyring and authenticated local IPC are used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.maintenance.fixture_corpus import corpus, digest, frozen_source
from src.audit.logger import AuditLogger
from src.config.schema import Config, OutboundWebhooksConfig, OutboundWebhookTarget
from src.desktop.core import CoreService
from src.desktop.integrations import IntegrationsService
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from tests.test_desktop_core_lifecycle import connect, profile, request


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


@pytest.fixture(autouse=True)
def refuse_external_http(monkeypatch):
    import aiohttp

    def forbidden(*args, **kwargs):
        raise AssertionError("Batch-B probes must not initiate network requests")

    monkeypatch.setattr(aiohttp, "ClientSession", forbidden)


@pytest.fixture
async def local_core(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, secret_backend=MemoryKeyring())
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, welcome = await connect(socket_path)
        assert welcome["t"] == "welcome"
        assert core.authority.owner_id
        yield core, reader, writer
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


def test_native_knowledge_original_has_no_setup_adaptation():
    import ast

    original = frozen_source("tests/test_native_knowledge.py")
    assert digest(original) == "418046d5ffe538ac586ccc89fa17b2430347fca1838c3dcbb5b404e556c25bac"
    inherited = corpus(ast.parse(original))
    assert len(inherited["cases"]) == 26
    assert len(inherited["assertions"]) == 33


def test_all_batch_b_retained_bytes_match_frozen_archive_and_review_map():
    root = Path(__file__).resolve().parents[1]
    mapping = json.loads((root / "maintenance/phase2-suite-map.json").read_text())
    owned = sorted((row for row in mapping["entries"] if row["step"] == 5),
                   key=lambda row: row["path"])[1::4]
    assert len(owned) == 21
    for row in owned:
        # frozen_source checks the archive hash, unique regular member, retained
        # byte identity and no symlink ancestors before parsing or execution.
        assert digest(frozen_source(row["path"])) == row["inherited_sha256"]


@pytest.mark.parametrize("scenario, valid, availability", [
    ("valid", True, "available"),
    ("tampered", False, "available"),
    ("rotated_tampered", False, "available"),
    ("no_signing", False, "not_enabled"),
    ("unsigned_prefix", True, "available"),
    ("empty_signed", True, "available"),
])
async def test_real_audit_ipc_reports_integrity_without_invented_conflict(
    local_core, scenario, valid, availability,
):
    core, reader, writer = local_core
    key = "isolated-batch-b-signing-key" if scenario != "no_signing" else ""
    if key:
        saved = await request(reader, writer, "secrets.set", {
            "path": "audit.hmac_key", "value": key,
        })
        assert saved["ok"], saved
    path = core.paths.data_dir / "audit.jsonl"
    if scenario == "unsigned_prefix":
        path.write_text("".join(json.dumps({"legacy": i}) + "\n" for i in range(3)))
    audit = AuditLogger(str(path), hmac_key=key,
                        max_bytes=1 if scenario == "rotated_tampered" else 1_000_000,
                        max_files=2)
    await audit.initialize_chain()
    if scenario != "empty_signed":
        for i in range(2 if scenario == "rotated_tampered" else 1):
            await audit.log_event(event_type="fixture", action=f"act{i}",
                                  actor="temporary-owner", detail="intact")
    tampered = None
    if scenario in {"tampered", "rotated_tampered"}:
        tampered = path.with_name("audit.jsonl.1") if scenario == "rotated_tampered" else path
        lines = tampered.read_text().splitlines(keepends=True)
        entry = json.loads(lines[0])
        entry["detail"] = "changed only in disposable fixture"
        lines[0] = json.dumps(entry) + "\n"
        tampered.write_text("".join(lines))
    before = {item: item.read_bytes() for item in path.parent.glob("audit.jsonl*")}
    receipt_count = core.store.connection.execute(
        "SELECT COUNT(*) FROM command_receipts").fetchone()[0]
    response = await request(reader, writer, "audit.verify")
    # Invalid integrity is a successful read of an invalid report, not an
    # integrity-conflict MethodError. Returning synthetic 409 would hide this.
    assert response["ok"] is True
    assert "error" not in response
    report = response["result"]
    assert report["valid"] is valid
    assert report["availability"] == availability
    if scenario == "rotated_tampered":
        assert report["first_bad_file"] == "audit.jsonl.1"
    if scenario == "unsigned_prefix":
        assert report["unsigned_prefix"] == 3
        assert report["verified"] == 1
    if not valid:
        assert report["error"]
    assert {item: item.read_bytes() for item in before} == before
    assert core.store.connection.execute(
        "SELECT COUNT(*) FROM command_receipts").fetchone()[0] == receipt_count


def isolated_integrations(tmp_path, *, config=None):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n")
    secrets = ProfileSecretStore(paths, backend=MemoryKeyring())
    settings = SettingsService(paths, secrets, config=config)
    return IntegrationsService(settings)


async def test_webhook_file_desired_state_is_not_the_in_memory_rejected_row(tmp_path):
    config = Config(outbound_webhooks=OutboundWebhooksConfig(enabled=True, targets=[
        OutboundWebhookTarget(id="bad", name="typo", url="http://169.254.169.254/"),
        OutboundWebhookTarget(id="good", name="valid", url="https://good.example.test/hook"),
    ]))
    service = isolated_integrations(tmp_path, config=config)
    # Match the inherited test: saved desired state differs from rejected boot
    # state. The original HTTP route preserves the saved URL, not the boot URL.
    service.settings.paths.config_file.write_text(
        "outbound_webhooks:\n  enabled: true\n  targets:\n"
        "    - id: bad\n      name: typo\n      url: https://example.test/hook\n"
        "    - id: good\n      name: valid\n      url: https://good.example.test/hook\n")
    try:
        result = await service.handle("webhooks.outbound.save", {"id": "good", "name": "renamed"})
        assert result["name"] == "renamed"
        import yaml

        saved = yaml.safe_load(service.settings.paths.config_file.read_text())
        rows = saved["outbound_webhooks"]["targets"]
        assert rows[0]["id"] == "bad"
        assert rows[0]["url"] == "http://169.254.169.254/"
        assert service.dispatcher.get("bad") is None
    finally:
        await service.dispatcher.close()


async def test_webhook_persistence_refusal_is_real_method_error_not_http_503(tmp_path, monkeypatch):
    service = isolated_integrations(tmp_path)

    def failed_persistence(*args, **kwargs):
        raise OSError("disposable persistence refusal")

    monkeypatch.setattr("src.desktop.settings._patch_config_paths", failed_persistence)
    try:
        with pytest.raises(MethodError) as refused:
            await service.handle("webhooks.outbound.save", {
                "name": "not saved", "url": "https://example.test/hook",
                "secret": "batch-b-dummy-only",
            })
        assert refused.value.code == "internal_error"
        assert refused.value.disposition == "rejected"
        assert "batch-b-dummy-only" not in refused.value.message
        assert service.dispatcher.list_webhooks() == []
        assert service.settings.config.outbound_webhooks.targets == []
        assert service.settings.secrets._backend.values == {}
    finally:
        await service.dispatcher.close()
