"""Fail-closed frozen byte, corpus, owner and result-carrier proofs."""

import copy
import hashlib
import uuid

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters import review_provider_hosts as adapter


def test_whole_frozen_corpus_and_reversible_seals():
    original = adapter.source_tree()
    adapted = adapter.adapted_tree()
    assert corpus(original) == corpus(adapted)
    assert len(corpus(adapted)["assertions"]) == 91
    assert hashlib.sha256(frozen_source(adapter.PATH)).hexdigest() == adapter.SOURCE_SHA256
    assert adapter.CORPUS_SELECTIONS == {"test_hosts_api": None}
    assert adapter.CORPUS_EXCLUSIONS == {}


def test_unknown_verdict_is_not_forged():
    with pytest.raises(KeyError):
        adapter.Response({"ok": False, "error": {"code": "unknown", "message": "x"}}, "hosts.list")


@pytest.mark.parametrize("field", ["before_sha256", "after_sha256", "after_source"])
def test_setup_hunk_tampering_fails_closed(monkeypatch, field):
    records = copy.deepcopy(adapter.hunk_records())
    records[0][field] = (
        "0" * 64 if field.endswith("sha256") else "from typing import Any as unrelated"
    )
    monkeypatch.setattr(adapter, "hunk_records", lambda: records)
    with pytest.raises(AssertionError):
        adapter.adapted_tree()


def test_verdict_projection_keeps_result_and_refusal_evidence():
    body = {
        "tested": False,
        "last_test": {"ok": False, "detail": "unverified"},
        "error": "unverified",
    }
    response = adapter.Response({"ok": True, "result": body}, "hosts.test")
    assert response.status == 424 and response.body is body
    refs = [{"kind": "schedule", "location": "daily"}]
    from src.desktop.hosts import HostReferenceConflictError

    conflict = adapter.Response(HostReferenceConflictError(refs).response(), "hosts.delete")
    assert conflict.status == 409
    assert conflict.body["pending_references"] is refs


def test_unmapped_carrier_fails_closed():
    with pytest.raises(ValueError):
        adapter.route("post", "/api/other", {})


def test_owner_is_canonical_current_profile(tmp_path):
    with adapter.owner_profile(tmp_path) as owner:
        assert str(uuid.UUID(owner.authority.owner_id)) == owner.authority.owner_id
        assert owner.manager.is_owner(owner.authority.owner_id)
        assert not owner.manager.is_owner("viewer")


@pytest.mark.asyncio
async def test_real_settings_publication(tmp_path):
    from tests.test_desktop_review_provider_hosts import _bot

    bot = _bot(tmp_path)
    with adapter.owner_profile(tmp_path):
        result = await bot.service.handle("hosts.set_enabled", {"alias": "alpha", "enabled": False})
    assert result["saved"]
    assert not bot.settings.config.tools.hosts["alpha"].enabled


@pytest.mark.asyncio
async def test_command_bound_to_real_owner_and_audit(tmp_path):
    from tests.test_desktop_review_provider_hosts import _bot

    bot = _bot(tmp_path)
    async with adapter.CommandClient(bot) as client:
        prepared = await client.post(
            "/api/hosts/candidates",
            json={"alias": "alpha", **bot.config.tools.hosts["alpha"].model_dump()},
        )
        assert prepared.status == 201
        assert client.management.methods["hosts.prepare"] is bot.service
        assert bot.audit.events[-1]["actor"] == client.owner.authority.owner_id
        assert client.owner.manager.is_owner(bot.audit.events[-1]["actor"])
        bot.denied = True
        refused = await client.get("/api/hosts")
        assert refused.status == 403
        assert refused.frame["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_audit_failure_cannot_reverse_saved_publication(tmp_path):
    from tests.test_desktop_review_provider_hosts import _bot

    bot = _bot(tmp_path)

    async def fail(**kwargs):
        raise OSError("disposable audit unavailable")

    bot.audit.log_event = fail
    with adapter.owner_profile(tmp_path):
        await bot.service.handle("hosts.set_enabled", {"alias": "alpha", "enabled": False})
        await bot.service._audit("update", "alpha")
    assert not bot.settings.config.tools.hosts["alpha"].enabled
    assert not bot.host_registry.get("alpha").enabled


async def test_host_audit_uses_executor_owner_or_configured_signed_path(tmp_path):
    from types import SimpleNamespace

    from src.audit.logger import AuditLogger
    from src.desktop.hosts import HostsService
    from tests.test_desktop_review_provider_hosts import _bot

    bot = _bot(tmp_path)
    existing = AuditLogger(str(tmp_path / "executor-audit.jsonl"), hmac_key="fixture-signing-key")
    service = HostsService(
        bot.settings, registry=bot.host_registry, executor=SimpleNamespace(audit=existing)
    )
    assert service.audit is existing
    bot.settings.config.tools.audit_log_path = str(tmp_path / "configured-audit.jsonl")
    bot.settings.config.audit.hmac_key = "fixture-signing-key"
    service = HostsService(bot.settings, registry=bot.host_registry)
    assert service.audit is None
    await service._audit("save", "fixture")
    assert service.audit.path == tmp_path / "configured-audit.jsonl"
    assert service.audit._signer is not None
