"""Canonical owner-bound loop operations for WorkService composition.

Inherit ``WorkLoopOperations`` and supply the existing WorkService dependencies.
Optional trusted composition hooks: ``resolve_destination(conversation_id)``
(sync or async, returns a canonical channel), ``loop_runner.run_autonomous``,
``trajectory_saver`` and ``publish_loop(message, text)``. None is a renderer
payload. The real RequestService seals admission; LoopManager owns execution,
budgets, cancellation and settlement. No transport aliases confer authority.
"""
from __future__ import annotations

import asyncio
import inspect
import time
import weakref
from collections.abc import Mapping
from contextlib import asynccontextmanager
from uuid import uuid4

from ..llm.secret_scrubber import scrub_output_secrets
from .management import MethodError
from .requests import LocalChannel

# Each holder AND waiter keeps its own strong local reference. Never explicitly
# pop on exit: a cancelled waiter must not split the remaining queue across locks.
_LOOP_RESTART_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def _get(item, key, default=None):
    return item.get(key, default) if isinstance(item, Mapping) else getattr(item, key, default)


def extract_loop_provenance(entry):
    """Observed response axes only, never configuration or requester defaults."""
    axes = {key: "unknown" for key in ("provider", "model", "reasoning_effort")}
    for iteration in entry.get("iterations", []):
        if isinstance(iteration, Mapping):
            for key in axes:
                value = iteration.get(key)
                if isinstance(value, str) and value:
                    axes[key] = value
    return axes


def project_loop_iteration(entry):
    # Deliberately exclude prompts/user_content and arbitrary stored metadata.
    result = {key: entry.get(key) for key in (
        "timestamp", "loop_iteration", "final_response", "tools_used",
        "duration_seconds", "error", "failure_class",
    ) if key in entry}
    result.update(extract_loop_provenance(entry))
    return result


class WorkLoopOperations:
    """Mixin: canonical IDs and sealed messages, not legacy route authority.

    ``start_loop`` takes ``conversation_id`` plus goal/config. ``restart_loop``
    and ``loop_detail`` take an admitted manager ID; the matching durable work
    generation must still exist. Mutation requires a currently bound message.
    Optional owner_context is additionally checked, not used to mint a request.
    Domain failures raise MethodError for the command/fixture response adapter.
    """

    def _loop_owner(self, *, message=None, owner_context=None):
        owner = self.authority.owner_id
        if not self.permissions.is_owner(owner):
            raise MethodError("unauthorized", "Authenticated profile owner required")
        if owner_context is not None and (not self.authority.accepts(owner_context)
                or owner_context.owner_id != owner):
            raise MethodError("unauthorized", "Authenticated profile owner required")
        if message is not None:
            self.requests.assert_bound_request(message)
            if message.owner_id != owner:
                raise MethodError("unauthorized", "Foreign request owner")
            if self.requests._closed:
                raise MethodError("busy", "The core is quiescing")
        elif owner_context is None:
            raise MethodError("unauthorized", "An authenticated owner context is required")
        return owner

    def _loop_config(self, params):
        if not isinstance(params, Mapping):
            raise MethodError("bad_request", "loop configuration is invalid")
        goal = params.get("goal")
        interval = params.get("interval_seconds", 60)
        mode = params.get("mode", "notify")
        condition = params.get("stop_condition")
        iterations = params.get("max_iterations", 50)
        if (type(goal) is not str or not goal.strip() or len(goal) > 2000
                or type(interval) is not int or interval < 10
                or mode not in ("notify", "act", "silent")
                or type(iterations) is not int or not 1 <= iterations <= 1000
                or (condition is not None and (type(condition) is not str
                    or len(condition) > 2000))):
            raise MethodError("bad_request", "loop configuration is invalid")
        return {"goal": goal, "interval_seconds": interval, "mode": mode,
                "stop_condition": condition, "max_iterations": iterations}

    async def _loop_destination(self, cid):
        if type(cid) is not str or not cid:
            raise MethodError("bad_request", "conversation_id is required")
        try:
            self.conversations.get(cid)
        except (KeyError, ValueError):
            raise MethodError("not_found", "Loop destination not found") from None
        resolver = getattr(self, "resolve_destination", None)
        channel = resolver(cid) if resolver is not None else LocalChannel(cid, cid)
        if inspect.isawaitable(channel):
            channel = await channel
        if channel is None or str(getattr(channel, "id", "")) != cid:
            raise MethodError("not_found", "Loop destination not found")
        return channel

    def _loop_target(self, loop_id, owner, *, message=None):
        if type(loop_id) is not str or not loop_id:
            raise MethodError("not_found", "Loop not found")
        item = self._items("loop").get(loop_id)
        if item is None or _get(item, "requester_id") != owner:
            raise MethodError("not_found", "Loop not found")
        cid = _get(item, "channel_id")
        if message is not None and message.conversation_id != cid:
            raise MethodError("not_found", "Loop not found")
        records = self.list({"kind": "loop", "conversation_id": cid}).get("items", [])
        record = next((r for r in records if r["manager_id"] == loop_id
                       and r["owner_id"] == owner and self._same(r, item)), None)
        if record is None:
            raise MethodError("not_found", "Loop admission not found")
        return item, record

    def _loop_runtime(self):
        runner = getattr(self, "loop_runner", None)
        if runner is None:
            runner = getattr(self.requests.engine, "runner", None)
        if (self.loops is None or not callable(getattr(self.loops, "start_admitted_loop", None))
                or not callable(getattr(runner, "run_autonomous", None))):
            raise MethodError("capability_unavailable", "Admitted loop runtime unavailable")
        return runner

    def _start_bound_loop(self, config, channel, message, runner):
        admitted = {}

        def before_start(info):
            # No worker is queued until both durable request and work binding
            # commit. A failed WorkService admission is never runnable.
            background = self.requests.register_background(
                message, "loop", uuid4().hex, config["goal"]
            )
            try:
                self.register("loop", info.id, background, parent_message=message)
            except BaseException:
                self.requests.settle_background(background, "failed")
                raise
            admitted["message"] = background

        @asynccontextmanager
        async def execution(info):
            async with self.requests.background_execution(admitted["message"], settle=False):
                yield

        async def publish(info, text):
            background = admitted["message"]
            self.requests.assert_bound_request(background)
            publisher = getattr(self, "publish_loop", None)
            if publisher is not None:
                await publisher(background, text)
            elif self.requests.delivery is not None:
                await self.requests.delivery.send(background.channel, text)
            else:
                raise MethodError("capability_unavailable", "Loop delivery unavailable")

        def settled(info):
            outcome = "completed" if info.status == "completed" else (
                "cancelled" if info.status == "stopped" else "failed"
            )
            self.requests.settle_background(admitted["message"], outcome)
            self.refresh_all()

        async def run_iteration(prompt, prev_context, cancel_event):
            background = admitted["message"]
            iteration = self.requests.register_background(
                background, "loop_iteration", uuid4().hex, prompt
            )
            async with self.requests.background_execution(iteration):
                return await runner.run_autonomous(
                    prompt, iteration, prev_context, iteration.owner_id,
                    cancel_event=cancel_event,
                )

        async def iteration_callback(prompt, channel, prev_context, cancel_event):
            # The manager channel argument is transport data, not admission.
            # Always derive the destination from the sealed background request.
            background = admitted["message"]
            try:
                current = self.requests.current_bound_request()
            except PermissionError:
                current = None
            if current is background:
                return await run_iteration(prompt, prev_context, cancel_event)
            # Instrumentation may invoke a captured callback without running a
            # worker. It still needs native admission; no test-authority branch.
            async with self.requests.background_execution(background, settle=False):
                return await run_iteration(prompt, prev_context, cancel_event)

        result = self.loops.start_admitted_loop(
            **config, channel=channel, requester_id=message.owner_id,
            requester_name=message.owner_name, iteration_callback=iteration_callback,
            before_start=before_start, execution=execution, publish=publish,
            on_settled=settled,
        )
        if type(result) is not str or result.startswith("Error"):
            raise MethodError("bad_request", scrub_output_secrets(str(result)))
        return result

    async def start_loop(self, params, *, message, owner_context=None):
        if message is None:
            raise MethodError("unauthorized", "An admitted request is required")
        self._loop_owner(message=message, owner_context=owner_context)
        config = self._loop_config(params)
        cid = params.get("conversation_id")
        if cid != message.conversation_id:
            raise MethodError("bad_request", "Loop destination differs from admitted request")
        channel = await self._loop_destination(cid)
        self._loop_owner(message=message, owner_context=owner_context)
        return {"loop_id": self._start_bound_loop(config, channel, message, self._loop_runtime())}

    async def restart_loop(self, loop_id, *, message, owner_context=None):
        if message is None:
            raise MethodError("unauthorized", "An admitted request is required")
        owner = self._loop_owner(message=message, owner_context=owner_context)
        if type(loop_id) is not str or not loop_id:
            raise MethodError("not_found", "Loop not found")
        lock = _LOOP_RESTART_LOCKS.get(loop_id)
        if lock is None:
            lock = asyncio.Lock()
            _LOOP_RESTART_LOCKS[loop_id] = lock
        async with lock:
            self._loop_owner(message=message, owner_context=owner_context)
            item, record = self._loop_target(loop_id, owner, message=message)
            config = self._loop_config({key: _get(item, key) for key in (
                "goal", "interval_seconds", "mode", "stop_condition", "max_iterations"
            )})
            channel = await self._loop_destination(record["conversation_id"])
            self._loop_owner(message=message, owner_context=owner_context)
            if not self._same(record, self._items("loop").get(loop_id)):
                raise MethodError("not_found", "Loop binding changed")
            runner = self._loop_runtime()  # Validate before destructive stop.
            if _get(item, "status") == "running":
                await self.loops.stop_loop(loop_id)
                self._loop_owner(message=message, owner_context=owner_context)
            # Logical self-stop can ACK before the owned manager task settles.
            task = _get(item, "_task")
            if task is not None and not task.done():
                raise MethodError("busy", "Loop stop has not settled")
            new_id = self._start_bound_loop(config, channel, message, runner)
            return {"old_id": loop_id, "new_id": new_id}

    async def loop_detail(self, loop_id, *, limit=25, owner_context=None, message=None):
        owner = self._loop_owner(message=message, owner_context=owner_context)
        item, record = self._loop_target(loop_id, owner, message=message)
        try:
            limit = min(max(int(limit), 1), 500)
        except (ValueError, TypeError, OverflowError):
            limit = 25
        result = dict(record.get("detail", {}))
        result.update(id=loop_id, goal=_get(item, "goal"), status=_get(item, "status"),
                      last_trigger_age_seconds=max(0, time.monotonic() -
                          (_get(item, "last_trigger", 0) or 0)),
                      context_history=list(_get(item, "_iteration_history", [])),
                      iterations=[], history_available=False, history_truncated=False,
                      history_limit=limit)
        saver = getattr(self, "trajectory_saver", None)
        if saver is not None:
            try:
                entries = await saver.find_by_loop_id(loop_id, limit=limit + 1)
                result["iterations"] = [project_loop_iteration(entry) for entry in entries[:limit]]
                result["history_available"] = True
                result["history_truncated"] = len(entries) > limit
            except Exception:
                # Preserve the live projection; unavailable storage is not empty
                # available history. Cancellation intentionally propagates.
                pass
        self._loop_owner(message=message, owner_context=owner_context)
        return _scrub_projection(result)


def _scrub_projection(value):
    if isinstance(value, str):
        return scrub_output_secrets(value)
    if isinstance(value, dict):
        return {key: _scrub_projection(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_projection(item) for item in value]
    return value
