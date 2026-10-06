"""Frozen loop fixture wiring over canonical admission, not route algorithms.

Only transport identities, runtime task scheduling and mock observations are
adapted here. Validation, locks, restart sequencing and history projection live
in WorkLoopOperations; admission uses the actual RequestService and LoopManager.
"""
from __future__ import annotations

import asyncio
import inspect
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from src.desktop.management import MethodError
from src.desktop.requests import LocalChannel
from src.desktop.work_loops import _LOOP_RESTART_LOCKS
from src.tools.autonomous_loop import LoopInfo, LoopManager

__all__ = ["configure", "request", "cleanup", "_LOOP_RESTART_LOCKS"]
_callback_channel = ContextVar("fixture_loop_callback_channel", default=None)


async def configure(client):
    client.loop_bridge_exited = False
    client.loop_bridge_closed = False
    client.loop_bridge_defer = False
    client.loop_bridge_workers = []
    client.loop_bridge_external = {}
    client.loop_bridge_destination = None
    manager = client.loops = LoopManager()
    client.service.loops = manager
    external_manager = client.bot.loop_manager
    fixtures = external_manager._loops
    if not isinstance(fixtures, dict) and isinstance(external_manager.stop_loop, AsyncMock):
        fixtures = {"L1": LoopInfo(id="L1", goal="harmless stop fixture", mode="notify",
            interval_seconds=60, stop_condition=None, max_iterations=50,
            channel_id="1", requester_id=client.owner.owner_id, requester_name="Owner")}
    if isinstance(fixtures, dict):
        for lid, info in fixtures.items():
            # Setup-only fixture mapping. Keep object identity for frozen checks.
            client.loop_bridge_external[lid] = str(info.channel_id)
            info.id, info.requester_id, info.channel_id = lid, client.owner.owner_id, client.cid
            info._task = None
            info._cancel_event = asyncio.Event()
            info._stop_requested = False
            manager._loops[lid] = info
            envelope = client.requests._register_background(
                "loop", "fixture:" + lid, "harmless frozen loop fixture", client.cid,
                client.owner.owner_id,
            )
            async with client.requests.background_execution(envelope, settle=False):
                client.service.register("loop", lid, envelope)

    async def resolve_destination(cid):
        external = client.loop_bridge_destination
        try:
            numeric = int(external)
        except (ValueError, TypeError):
            return None
        channel = client.bot.get_channel(numeric)
        if channel is None:
            return None
        identity = getattr(channel, "id", None)
        # An unconfigured MagicMock is the frozen send-shaped fixture, not an
        # asserted identity. Concrete identities must match the external target.
        if not isinstance(identity, Mock) and str(identity) != str(external):
            return None
        return LocalChannel(cid, "frozen fixture")

    client.service.resolve_destination = resolve_destination
    client.service.trajectory_saver = getattr(client.bot, "trajectory_saver", None)

    async def run_autonomous(prompt, message, previous, owner, *, cancel_event):
        client.requests.assert_bound_request(message)
        assert message.owner_id == owner == client.owner.owner_id
        assert message.conversation_id == client.cid
        # External legacy aliases are observation-only. Production already
        # selected the sealed native identity before reaching this boundary.
        return await client.bot.tool_loop.run_autonomous(
            prompt, _callback_channel.get(), previous, "web-api", cancel_event=cancel_event,
        )

    client.service.loop_runner = SimpleNamespace(run_autonomous=run_autonomous)
    native_start = manager.start_admitted_loop
    native_stop = manager.stop_loop
    # The frozen manager registry retains historical rows throughout one case.
    # Real cleanup is unrelated to the route contracts being carried here.
    manager.cleanup_finished = lambda: None

    def start_admitted_loop(**kwargs):
        native_callback = kwargs["iteration_callback"]

        async def callback(prompt, channel, previous, cancel_event):
            owner_token = client.permissions.set_request_owner(client.owner)
            channel_token = _callback_channel.set(channel)
            try:
                return await native_callback(prompt, channel, previous, cancel_event)
            finally:
                _callback_channel.reset(channel_token)
                client.permissions.reset_request_owner(owner_token)
                if client.loop_bridge_exited:
                    await cleanup(client, force=True)

        # Call the existing frozen observation Mock; it captures the actual
        # canonical callback and controls the fake runtime admission result.
        observed = external_manager.start_loop(**{
            key: value for key, value in kwargs.items() if key not in {
                "before_start", "execution", "publish", "on_settled", "iteration_callback"
            }
        }, iteration_callback=callback)
        if not isinstance(observed, str) or observed.startswith("Error"):
            return observed
        before_start = kwargs["before_start"]

        def admitted(info):
            del manager._loops[info.id]
            info.id = observed
            manager._loops[observed] = info
            before_start(info)
            client.loop_bridge_external[observed] = client.loop_bridge_destination

        def inert_worker(coroutine, *args, **kw):
            coroutine.close()  # Never execute the real autonomous runtime.
            future = asyncio.get_running_loop().create_future()
            client.loop_bridge_workers.append((observed, future))
            return future

        kwargs["before_start"], kwargs["iteration_callback"] = admitted, callback
        with patch("src.tools.autonomous_loop.asyncio.create_task", inert_worker):
            result = native_start(**kwargs)
        tool_loop = getattr(client.bot, "tool_loop", None)
        client.loop_bridge_defer = isinstance(getattr(tool_loop, "run_autonomous", None), AsyncMock)
        return observed if isinstance(result, str) and not result.startswith("Error") else result

    async def stop_loop(lid):
        # Real cancellation/settlement precedes the fixture's observation gate.
        await native_stop(lid)
        result = external_manager.stop_loop(lid)
        return await result if inspect.isawaitable(result) else result

    manager.start_admitted_loop = start_admitted_loop
    manager.stop_loop = stop_loop


async def request(client, verb, path, json=None):
    verb = verb.lower()
    parsed = urlsplit(path)
    parts = parsed.path.strip("/").split("/")
    try:
        if verb == "get":
            if len(parts) == 2:
                listing = client.service.list({"kind": "loop"})
                return [record["detail"] for record in listing.get("items", [])], 200
            limit = parse_qs(parsed.query).get("limit", [25])[0]
            return await client.service.loop_detail(parts[2], limit=limit,
                owner_context=client.owner), 200
        # One actual owner-bound execution identity per incoming fixture call.
        parent = client.requests._register_background(
            "task", uuid4().hex, "harmless frozen loop command", client.cid,
            client.owner.owner_id,
        )
        async with client.requests.background_execution(parent):
            if verb == "post" and len(parts) == 2:
                params = dict(json or {})
                # Transport rename only. Production owns all config validation.
                external = params.pop("channel_id", None)
                client.loop_bridge_destination = external
                params["conversation_id"] = client.cid if external else None
                result = await client.service.start_loop(params, message=parent,
                    owner_context=client.owner)
                return result, 201
            lid = parts[2]
            client.loop_bridge_destination = client.loop_bridge_external.get(lid)
            if verb == "post" and parts[-1] == "restart":
                return await client.service.restart_loop(lid, message=parent,
                    owner_context=client.owner), 201
            if verb == "delete":
                value = await client.service.control_native(parent, "loop", lid, "stop")
                # The frozen stop/missing mock is a runtime result observation;
                # native control remains the actual durable owner path.
                if isinstance(value, str) and value.startswith("Error"):
                    return {"error": "Loop not found"}, 404
                if isinstance(value, dict) and value.get("result", {}).get(
                        "disposition") == "not_available":
                    return {"error": "Loop not found"}, 404
                return {"result": value}, 200
        return {"error": "unsupported fixture method"}, 400
    except MethodError as error:
        status = {"not_found": 404, "unauthorized": 403,
                  "capability_unavailable": 503, "busy": 409}.get(error.code, 400)
        return {"error": error.message}, status


async def cleanup(client, *, force=False):
    client.loop_bridge_exited = True
    if client.loop_bridge_closed or (client.loop_bridge_defer and not force):
        return
    client.loop_bridge_closed = True
    owner_token = client.permissions.set_request_owner(client.owner)
    try:
        for lid, future in client.loop_bridge_workers:
            item = client.loops._loops.get(lid)
            if item is not None:
                item.status = "stopped"
            if not future.done():
                future.cancel()
        await asyncio.sleep(0)  # Native on_settled and WorkService watches run.
        # No runtime worker was run; the fixture's parent tasks already settled.
        client.requests._closed = True
    finally:
        client.permissions.reset_request_owner(owner_token)
        client.store.close()
        client.permissions.reset_request_owner(client.owner_token)
        client.authority.release_runtime()
        client.temp.cleanup()
