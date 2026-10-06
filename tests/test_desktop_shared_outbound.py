"""Shared retained outbound owner, temporary profiles and injected HTTP only."""
from __future__ import annotations

import asyncio
import json
import os
import threading
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


class WorkerKeyring(TemporaryKeyring):
    """Real profile store adapter, but no native vault, prompt or network."""

    def __init__(self):
        super().__init__()
        self.loop_thread = threading.get_ident()
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def check(self, operation, name):
        assert threading.get_ident() != self.loop_thread
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        assert threading.current_thread().daemon
        self.calls.append((operation, name))
        self.entered.set()
        assert self.release.wait(5), "fixture worker was not released"

    def get_password(self, service, name):
        self.check("get", name)
        return super().get_password(service, name)

    def set_password(self, service, name, value):
        self.check("set", name)
        return super().set_password(service, name, value)

    def delete_password(self, service, name):
        self.check("clear", name)
        return super().delete_password(service, name)


async def wait_worker(backend):
    for _ in range(500):
        if backend.entered.is_set():
            return
        await asyncio.sleep(.001)
    pytest.fail("keyring worker did not enter while loop remained responsive")


async def test_shared_dispatcher_management_and_delivery_keyring_workers(graph):
    owner = graph.engine.deps.outbound_webhook_dispatcher
    backend = WorkerKeyring()
    graph.settings.secrets._backend = backend
    transport = Transport()
    owner._session = transport
    saved = await graph.management.invoke("webhooks.outbound.save", {
        "name": "worker", "url": "https://example.invalid/worker",
        "secret": "worker-fixture-signing", "events": ["all"],
    })
    assert saved["ok"], saved
    ident = saved["result"]["id"]
    listed = await graph.management.invoke("webhooks.outbound.list", {})
    assert listed["ok"] and listed["result"]["webhooks"][0]["has_secret"]
    assert (await owner.dispatch("health", {}))[0].success
    # Force fresh target hydration on each actual async path.
    graph.settings.config.outbound_webhooks.targets[0].name = "test-worker"
    tested = await graph.management.invoke("webhooks.outbound.test", {"id": ident})
    assert tested["ok"] and tested["result"]["success"], tested
    graph.settings.config.outbound_webhooks.targets[0].name = "send-worker"
    assert (await owner.send_test_event(ident)).success
    assert len(transport.requests) == 3
    for _, request in transport.requests:
        assert request["headers"]["X-Webhook-Signature"] == "sha256=" + sign_payload(
            request["data"], "worker-fixture-signing")
    changed = await graph.management.invoke("webhooks.outbound.save", {
        "id": ident, "secret": "changed-fixture-signing",
    })
    assert changed["ok"], changed
    deleted = await graph.management.invoke("webhooks.outbound.delete", {"id": ident})
    assert deleted["ok"], deleted
    assert {operation for operation, _ in backend.calls} == {"get", "set", "clear"}
    assert not backend.values
    assert graph.management.integrations.dispatcher is owner
    assert graph.engine.deps.turn_recorder._outbound_webhook_dispatcher is owner


@pytest.mark.parametrize("operation", ["dispatch", "test", "list"])
async def test_shared_live_config_keyring_wait_keeps_loop_responsive(graph, operation):
    owner = graph.engine.deps.outbound_webhook_dispatcher
    transport = Transport()
    owner._session = transport
    saved = await graph.management.invoke("webhooks.outbound.save", {
        "name": "existing", "url": "https://example.invalid/existing", "events": ["all"],
    })
    assert saved["ok"], saved
    ident = saved["result"]["id"]
    await owner.dispatch("health", {})
    previous = owner.get(ident)
    backend = WorkerKeyring()
    graph.settings.secrets._backend = backend
    graph.settings.config.outbound_webhooks.targets[0].url = "https://example.invalid/slow"
    backend.release.clear()
    if operation == "dispatch":
        pending = asyncio.create_task(owner.dispatch("health", {}))
    elif operation == "test":
        pending = asyncio.create_task(owner.send_test_event(ident))
    else:
        pending = asyncio.create_task(graph.management.invoke("webhooks.outbound.list", {}))
    try:
        await wait_worker(backend)
        # Tick while the native-style wait remains blocked, then change desired
        # config mid-qualification. No candidate may leak through early.
        await asyncio.sleep(.02)
        assert not pending.done() and owner.get(ident) is previous
        assert len(transport.requests) == 1
        graph.settings.save_changes([(("outbound_webhooks", "targets"), [
            graph.settings.config.outbound_webhooks.targets[0].model_dump()
            | {"url": "https://example.invalid/latest"}
        ])], method="webhooks.outbound.save")
    finally:
        backend.release.set()
    result = await asyncio.wait_for(pending, 2)
    if operation == "list":
        assert result["ok"], result
        assert result["result"]["webhooks"][0]["url"] == "https://example.invalid/latest"
        assert len(transport.requests) == 1
    else:
        assert (result[0] if operation == "dispatch" else result).success
        assert transport.requests[-1][0] == "https://example.invalid/latest"
    assert owner.get(ident).url == "https://example.invalid/latest"
    assert graph.management.integrations.dispatcher is owner


async def test_shared_save_serializes_with_blocked_target_qualification(graph):
    owner = graph.engine.deps.outbound_webhook_dispatcher
    transport = Transport()
    owner._session = transport
    backend = WorkerKeyring()
    graph.settings.secrets._backend = backend
    saved = await graph.management.invoke("webhooks.outbound.save", {
        "url": "https://example.invalid/old", "secret": "old-fixture-signing",
        "events": ["all"],
    })
    assert saved["ok"], saved
    ident = saved["result"]["id"]
    await owner.dispatch("health", {})
    original = owner.get(ident)
    graph.settings.config.outbound_webhooks.targets[0].name = "rehydrate"
    backend.entered.clear()
    backend.release.clear()
    delivery = asyncio.create_task(owner.dispatch("health", {}))
    mutation = None
    try:
        await wait_worker(backend)
        mutation = asyncio.create_task(graph.management.invoke("webhooks.outbound.save", {
            "id": ident, "url": "https://example.invalid/new",
            "secret": "new-fixture-signing",
        }))
        await asyncio.sleep(.02)
        assert not mutation.done() and not delivery.done()
        assert owner.get(ident) is original
    finally:
        backend.release.set()
    assert (await asyncio.wait_for(delivery, 2))[0].success
    assert (await asyncio.wait_for(mutation, 2))["ok"]
    assert (await owner.dispatch("health", {}))[0].success
    _, request = transport.requests[-1]
    assert transport.requests[-1][0] == "https://example.invalid/new"
    assert request["headers"]["X-Webhook-Signature"] == "sha256=" + sign_payload(
        request["data"], "new-fixture-signing")
    assert graph.management.integrations.dispatcher is owner


async def test_shared_cancelled_save_settles_before_waiting_delivery_adopts(graph):
    owner = graph.engine.deps.outbound_webhook_dispatcher
    transport = Transport()
    owner._session = transport

    class PausedWriteKeyring(WorkerKeyring):
        def __init__(self):
            super().__init__()
            self.pause_write = False
            self.write_entered = threading.Event()
            self.write_release = threading.Event()

        def set_password(self, service, name, value):
            if self.pause_write:
                self.write_entered.set()
                assert self.write_release.wait(5)
            return super().set_password(service, name, value)

    backend = PausedWriteKeyring()
    graph.settings.secrets._backend = backend
    saved = await graph.management.invoke("webhooks.outbound.save", {
        "url": "https://example.invalid/before", "secret": "before-fixture-signing",
        "events": ["all"],
    })
    assert saved["ok"], saved
    ident = saved["result"]["id"]
    await owner.dispatch("health", {})
    original = owner.get(ident)
    backend.pause_write = True
    service = graph.management.integrations
    mutation = asyncio.create_task(service.handle("webhooks.outbound.save", {
        "id": ident, "url": "https://example.invalid/after",
        "secret": "after-fixture-signing",
    }))
    delivery = None
    try:
        for _ in range(500):
            if backend.write_entered.is_set():
                break
            await asyncio.sleep(.001)
        assert backend.write_entered.is_set()
        mutation.cancel()
        delivery = asyncio.create_task(owner.dispatch("health", {}))
        await asyncio.sleep(.02)
        assert not mutation.done() and not delivery.done()
        assert service._lock.locked()
        assert owner.get(ident) is original
        assert len(transport.requests) == 1
    finally:
        backend.write_release.set()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert (await asyncio.wait_for(delivery, 2))[0].success
    assert transport.requests[-1][0] == "https://example.invalid/after"
    request = transport.requests[-1][1]
    assert request["headers"]["X-Webhook-Signature"] == "sha256=" + sign_payload(
        request["data"], "after-fixture-signing")
    assert graph.management.integrations.dispatcher is owner
