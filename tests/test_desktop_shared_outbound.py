"""Shared retained outbound owner, temporary profiles and injected HTTP only."""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from src.config.schema import Config, OutboundWebhookTarget
from src.desktop.core import CoreService, profile_config
from src.desktop.integrations import IntegrationsService, ProfileOutboundWebhookDispatcher
from src.desktop.management import ManagementService, MethodError
from src.notifications.outbound_webhooks import OutboundWebhookDispatcher, sign_payload
from tests.test_desktop_core_lifecycle import profile
from tests.test_desktop_engine_services import Provider
from tests.test_desktop_management_core import TemporaryKeyring


class Response:
    status = 204
    headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class Transport:
    def __init__(self):
        self.closed = False
        self.closes = 0
        self.requests = []
        self.sent = asyncio.Event()

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        self.sent.set()
        return Response()

    async def close(self):
        self.closes += 1
        self.closed = True


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import aiohttp

    def refuse(*_, **__):
        raise AssertionError("Every outbound transport must be injected")

    monkeypatch.setattr(aiohttp, "ClientSession", refuse)


@pytest.fixture
async def graph(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    config = profile_config(paths)
    config.openai_codex.enabled = False
    config.browser.enabled = False
    config.learning.enabled = False
    config.outbound_webhooks.enabled = True
    config.outbound_webhooks.rate_limit_seconds = 0
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, config_provider=lambda _: config,
                       secret_backend=TemporaryKeyring())
    try:
        await core.start(read_fd)
        yield core
    finally:
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


async def test_actual_graph_shares_retained_owner_and_management_adoption(graph):
    core = graph
    owner = core.engine.deps.outbound_webhook_dispatcher
    assert isinstance(owner, OutboundWebhookDispatcher)
    assert owner is core.management.integrations.dispatcher
    assert owner is core.engine.deps.turn_recorder._outbound_webhook_dispatcher
    assert owner is core.engine.runner._turn_recorder._outbound_webhook_dispatcher
    assert owner._session is None
    transport = Transport()
    owner._session = transport
    saved = await core.management.invoke("webhooks.outbound.save", {
        "name": "shared", "url": "https://example.invalid/first", "events": ["all"],
        "secret": "isolated-test-signing-value",
    })
    assert saved["ok"], saved
    ident = saved["result"]["id"]
    assert owner.get(ident).url == "https://example.invalid/first"
    assert not transport.requests
    assert "isolated-test-signing-value" not in core.paths.config_file.read_text()
    await core.engine.deps.turn_recorder._emit_lifecycle_event("loop.stuck", {"iteration": 1})
    await asyncio.wait_for(transport.sent.wait(), 2)
    await asyncio.sleep(0)
    assert json.loads(transport.requests[0][1]["data"])["event_type"] == "loop.stuck"
    delivered = transport.requests[0][1]
    assert delivered["headers"]["X-Webhook-Signature"] == "sha256=" + sign_payload(
        delivered["data"], "isolated-test-signing-value")
    changed = await core.management.invoke("webhooks.outbound.save", {
        "id": ident, "url": "https://example.invalid/second", "enabled": False,
    })
    assert changed["ok"], changed
    assert await owner.dispatch("loop.stuck", {}) == []
    changed = await core.management.invoke("webhooks.outbound.save", {
        "id": ident, "enabled": True,
    })
    assert changed["ok"], changed
    assert (await owner.dispatch("loop.stuck", {}))[0].success
    assert transport.requests[-1][0] == "https://example.invalid/second"
    listed = await core.management.invoke("webhooks.outbound.list", {})
    assert listed["result"]["stats"]["total_delivered"] == 2
    deleted = await core.management.invoke("webhooks.outbound.delete", {"id": ident})
    assert deleted["ok"], deleted
    assert await owner.dispatch("loop.stuck", {}) == []
    await core.management.close()
    assert transport.closes == 0
    await core.engine.close()
    await core.engine.close()
    assert transport.closes == 1
    assert await owner.dispatch("loop.stuck", {}) == []


async def test_live_config_replacement_adopts_targets_without_replacing_owner(graph):
    owner = graph.engine.deps.outbound_webhook_dispatcher
    transport = Transport()
    owner._session = transport
    rows = [OutboundWebhookTarget(
        id="live", name="live", url="https://example.invalid/live", events=["health"])]
    previous_config = graph.settings.config
    graph.settings.save_changes([(("outbound_webhooks", "targets"),
                                  [row.model_dump() for row in rows])],
                                method="webhooks.outbound.save")
    desired = graph.settings.config
    assert desired is not previous_config
    assert (await owner.dispatch("health", {}))[0].success
    assert owner.get("live").url == "https://example.invalid/live"
    desired.outbound_webhooks.targets[0].enabled = False
    assert await owner.dispatch("health", {}) == []
    desired.outbound_webhooks.targets[0].enabled = True
    desired.outbound_webhooks.enabled = False
    assert await owner.dispatch("health", {}) == []
    assert len(transport.requests) == 1
    assert graph.management.integrations.dispatcher is owner


async def test_injected_runtime_dispatcher_is_shared_and_engine_closes_once(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    owner = OutboundWebhookDispatcher()
    transport = Transport()
    owner._session = transport
    provider = Provider([])
    config = profile_config(paths)
    config.openai_codex.enabled = False
    config.browser.enabled = False
    core = CoreService(paths, socket_path, token_file, config_provider=lambda _: config,
        runtime_provider=lambda *_: SimpleNamespace(outbound_webhook_dispatcher=owner,
                                                    compatible_client=provider),
        secret_backend=TemporaryKeyring())
    try:
        await core.start(read_fd)
        assert core.engine.deps.outbound_webhook_dispatcher is owner
        assert core.management.integrations.dispatcher is owner
        assert core.engine.deps.turn_recorder._outbound_webhook_dispatcher is owner
        await core.management.close()
        assert transport.closes == 0
    finally:
        await core.close()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
    assert transport.closes == 1


async def test_management_only_composition_owns_close(graph):
    standalone = SimpleNamespace(paths=graph.paths, authority=graph.authority,
                                 permissions=graph.permissions, settings=graph.settings)
    manager = ManagementService.compose(standalone)
    owner = manager.integrations.dispatcher
    assert isinstance(owner, ProfileOutboundWebhookDispatcher)
    assert owner._session is None
    transport = Transport()
    owner._session = transport
    await manager.close()
    await manager.close()
    assert transport.closes == 1


async def test_constructor_is_inert_and_close_cancels_delivery():
    config = Config()
    config.outbound_webhooks.enabled = True
    config.outbound_webhooks.targets = [OutboundWebhookTarget(
        id="close", name="close", url="https://example.invalid/close")]

    class Secrets:
        calls = 0

        def get(self, _):
            self.calls += 1
            return None

    secrets = Secrets()
    owner = ProfileOutboundWebhookDispatcher(lambda: config, secrets=secrets)
    assert owner._session is None and not owner._webhooks
    assert secrets.calls == 0
    entered = asyncio.Event()

    class BlockingResponse(Response):
        async def __aenter__(self):
            entered.set()
            await asyncio.Event().wait()

    class BlockingTransport(Transport):
        def post(self, *_args, **_kwargs):
            return BlockingResponse()

    transport = BlockingTransport()
    owner._session = transport
    pending = asyncio.create_task(owner.dispatch("health", {}))
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.wait_for(owner.close(), 2)
    assert pending.cancelled()
    assert transport.closes == 1
    assert not owner._deliveries and not owner._in_flight
    await owner.dispatch_fire_and_forget("health", {})
    await asyncio.sleep(0)
    assert owner._session is None
    borrowed = IntegrationsService(SimpleNamespace(config=config), dispatcher=owner)
    with pytest.raises(MethodError, match="closed"):
        await borrowed.handle("webhooks.outbound.list", {})


async def test_locked_keyring_refuses_new_rows_without_partial_adoption(graph):
    owner = graph.engine.deps.outbound_webhook_dispatcher
    transport = Transport()
    owner._session = transport
    saved = await graph.management.invoke("webhooks.outbound.save", {
        "name": "existing", "url": "https://example.invalid/existing", "events": ["all"],
    })
    assert saved["ok"], saved
    ident = saved["result"]["id"]
    await owner.dispatch("health", {})
    original = owner.get(ident)
    graph.settings.config.outbound_webhooks.targets.append(OutboundWebhookTarget(
        id="new", name="new", url="https://example.invalid/new"))
    graph.settings.secrets._backend.locked = True
    with pytest.raises(MethodError, match="keyring is unavailable"):
        await owner.dispatch("health", {})
    assert owner.get(ident) is original
    assert owner.get("new") is None
    assert len(transport.requests) == 1
