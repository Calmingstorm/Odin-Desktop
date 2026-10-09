"""Durable projections of real work owners, and a ControlService backend.

This module never spawns a replacement or infers privilege from a destination.
Admission registers a manager generation before yielding to its execution task.
The composition root routes *all* mutation through ControlService; ``apply`` is
its authenticated backend, not an IPC endpoint. A signal is not settlement.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping
from pathlib import Path

from ..llm.secret_scrubber import scrub_output_secrets
from ..web.api._agent_display import agent_display_policy
from .commands import canonical_json, response_error

WORK_COLUMNS = {"kind", "id", "manager_generation", "record"}
KINDS = frozenset({"agent", "task", "workflow", "loop", "process", "schedule"})
TERMINAL = frozenset({"completed", "failed", "timeout", "killed", "cancelled",
                      "stopped", "error"})


def _get(item, key, default=None):
    return item.get(key, default) if isinstance(item, Mapping) else getattr(item, key, default)


class WorkService:
    """Compose retained managers without copying their budget/control algorithms.

    ``requests`` is the real RequestService. ``controls`` is attached after
    construction to break the composition cycle. Schema owners must register
    WORK_COLUMNS as ``desktop_work`` before reopening a profile journal.
    """

    def __init__(self, store, events, *, authority, permissions, requests,
                 conversations, agents=None, tasks=None, loops=None, processes=None,
                 scheduler=None, display_config=None, controls=None):
        self.store, self.events = store, events
        self.authority, self.permissions = authority, permissions
        self.requests, self.conversations = requests, conversations
        self.agents, self.tasks, self.loops = agents, tasks, loops
        self.processes, self.scheduler = processes, scheduler
        self.display_config, self.controls = display_config, controls
        self.authorize_process = None
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._watched: set[asyncio.Task] = set()
        with store.transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_work (
                kind TEXT NOT NULL,id TEXT NOT NULL,manager_generation TEXT NOT NULL,
                record TEXT NOT NULL,PRIMARY KEY(kind,id,manager_generation))""")

    def _items(self, kind):
        if kind == "agent":
            return getattr(self.agents, "_agents", {})
        if kind in {"task", "workflow"}:
            return self.tasks if self.tasks is not None else {}
        if kind == "loop":
            return getattr(self.loops, "_loops", {})
        if kind == "process":
            return {str(k): v for k, v in getattr(self.processes, "_processes", {}).items()}
        if kind == "schedule":
            return {str(s["id"]): s for s in self.scheduler.list_all()} if self.scheduler else {}
        return {}

    def _generation(self, kind, item):
        if kind == "schedule":
            return str(_get(item, "_generation", _get(item, "created_at", "")))
        if kind == "process":
            return str(_get(item, "generation", ""))
        # These retained managers create a new metadata object at each admission.
        # Their creation time is immutable; iterations are NOT new work generations.
        return str(_get(item, "created_at", ""))

    def _owner_destination(self, kind, item):
        return (_get(item, "owner_id") if kind == "process" else _get(item, "requester_id"),
                _get(item, "origin_channel") if kind == "process" else
                _get(item, "conversation_id") if kind in {"task", "workflow"} else
                _get(item, "channel_id"))

    def register(self, kind: str, manager_id, message, *, parent_message=None) -> dict:
        """Admission-only hook. No caller-supplied owner or execution generation."""
        if parent_message is None:
            self.requests.assert_bound_request(message)
        else:
            self.requests.assert_bound_request(parent_message)
            self.requests.assert_preserved_request(message)
            if (message.owner_id, message.conversation_id) != (
                    parent_message.owner_id, parent_message.conversation_id):
                raise PermissionError("Background work cannot change its admission binding")
        if kind not in KINDS:
            raise ValueError("Unknown work kind")
        manager_id = str(manager_id)
        item = self._items(kind).get(manager_id)
        if item is None:
            raise ValueError("Manager work does not exist")
        owner, destination = self._owner_destination(kind, item)
        if (owner, destination) != (message.owner_id, message.conversation_id):
            raise PermissionError("Manager ownership differs from admitted request")
        self.conversations.get(destination)
        generation = self._generation(kind, item)
        if not generation:
            raise ValueError("Manager has no immutable generation")
        record = {"kind": kind, "id": str(uuid.uuid4()), "manager_id": manager_id,
                  "manager_generation": generation,
                  "run_id": message.request_id, "request_id": message.request_id,
                  "generation": message.generation, "owner_id": owner,
                  "conversation_id": destination, "started_at": _get(item, "created_at",
                      _get(item, "start_time")), "state": "admitted", "actions": [],
                  "settlement": {"state": "pending", "resource_release": "unproven"},
                  "detail": {}}
        with self.store.transaction() as connection:
            prior = connection.execute("SELECT record FROM desktop_work WHERE kind=? AND id=? "
                                       "AND manager_generation=?",
                                       (kind, manager_id, generation)).fetchone()
            if prior:
                old = json.loads(prior[0])
                for key in ("run_id", "generation", "owner_id", "conversation_id"):
                    if old[key] != record[key]:
                        raise ValueError("Work generation already has another binding")
                return old
            connection.execute("INSERT INTO desktop_work VALUES (?,?,?,?)",
                               (kind, manager_id, generation, canonical_json(record)))
        self._watch(item)
        return self.refresh(record)

    def register_schedule(self, schedule: dict, *, current=None) -> dict:
        """Trusted scheduler-definition import, not renderer admission.

        Scheduled execution owns a separate ``run_binding``. A definition's
        immutable run ID is for its control identity, never a runnable request.
        ``current`` is a scheduler snapshot by ID that the caller already holds.
        """
        sid = str(schedule["id"])
        current = self._items("schedule") if current is None else current
        actual = current.get(sid)
        if actual is None or actual != schedule:
            raise ValueError("Schedule is not the manager's current definition")
        owner, destination = self._owner_destination("schedule", actual)
        if owner != self.authority.owner_id or not self.permissions.is_owner(owner):
            raise PermissionError("Schedule has no authenticated owner")
        self.conversations.get(destination)
        gen = self._generation("schedule", actual)
        if not gen:
            raise ValueError("Schedule has no immutable generation")
        with self.store.transaction() as connection:
            prior = connection.execute("SELECT record FROM desktop_work WHERE kind='schedule' "
                                       "AND id=? AND manager_generation=?", (sid, gen)).fetchone()
            if prior:
                record = json.loads(prior[0])
                if (record["owner_id"], record["conversation_id"]) != (owner, destination):
                    raise ValueError("Schedule generation destination changed")
                return self.refresh(record, current)
            record = {"kind": "schedule", "id": str(uuid.uuid4()), "manager_id": sid,
                      "manager_generation": gen,
                      "run_id": str(uuid.uuid4()), "request_id": None, "generation": 1,
                      "owner_id": owner, "conversation_id": destination,
                      "started_at": actual.get("created_at"), "state": "admitted",
                      "detail": {}, "actions": [], "settlement": {"state": "pending"}}
            connection.execute("INSERT INTO desktop_work VALUES ('schedule',?,?,?)",
                               (sid, gen, canonical_json(record)))
        return self.refresh(record, current)

    def sync_schedules(self) -> None:
        """Bring Work up to date with the scheduler after any change to its definitions.

        Odin can create, pause or delete a schedule from chat, which changes the
        scheduler without any Work call, so the core runs this after each scheduler
        publication. Owner definitions Work hasn't seen are imported, and every
        schedule record is refreshed, so a paused or deleted one shows at once. A
        definition that can't be imported now (its conversation is gone, its owner
        changed) stays out, as with any other import. One scheduler snapshot serves
        the whole pass, and each record is refreshed once.
        """
        if self.scheduler is None:
            return
        current = self._items("schedule")
        refreshed = set()
        for schedule in current.values():
            if schedule.get("requester_id") != self.authority.owner_id:
                continue
            try:
                record = self.register_schedule(schedule, current=current)
            except (PermissionError, ValueError):
                continue
            refreshed.add((record["manager_id"], record["manager_generation"]))
        with self.store.transaction() as connection:
            records = [json.loads(row[0]) for row in connection.execute(
                "SELECT record FROM desktop_work WHERE kind='schedule' "
                "ORDER BY id,manager_generation")]
        for record in records:
            if (record["manager_id"], record["manager_generation"]) not in refreshed:
                self.refresh(record, current)

    def _watch(self, item):
        task = _get(item, "_task", _get(item, "_asyncio_task", _get(item, "_exit_task")))
        # A finished task needs no watch: this refresh already projects its end. Its
        # done-callback would run at once and refresh again, which re-watched it: a
        # finished agent, task, loop or process kept the core busy forever.
        if task is not None and not task.done() and task not in self._watched:
            self._watched.add(task)
            def settled(done):
                self._watched.discard(done)
                # Storage failure leaves the previously durable pending state.
                # The next list/reconciliation reads actual managers again.
                try:
                    self.refresh_all()
                except Exception:
                    pass
            task.add_done_callback(settled)

    def _same(self, record, item):
        return (item is not None and self._generation(record["kind"], item) ==
                record["manager_generation"] and self._owner_destination(record["kind"], item) ==
                (record["owner_id"], record["conversation_id"]))

    def _project(self, record, item):
        kind = record["kind"]
        state = _get(item, "status", "unknown")
        task = _get(item, "_task", _get(item, "_asyncio_task"))
        pending = task is not None and not task.done()
        detail = {}
        actions = []
        settlement = {"state": "pending", "resource_release": "unproven"}
        if kind == "agent":
            detail = {key: _get(item, key) for key in (
                "parent_id", "root_id", "depth", "children_ids", "max_children", "max_depth",
                "max_iterations", "iteration_count", "max_lifetime", "iteration_timeout",
                "inbox_sequence", "last_consumed_sequence", "inbox_events")}
            # Keep the retained truthful per-axis provenance policy intact.
            detail.update(agent_display_policy(item, self.display_config))
            active_children = [a for aid in self.agents.get_descendants(record["manager_id"])
                               if (a := self._items("agent").get(aid)) is not None
                               and (_get(a, "status") not in TERMINAL or
                                    (_get(a, "_task") is not None and not a._task.done()))]
            detail["unsettled_descendants"] = [_get(a, "id") for a in active_children]
            if state not in TERMINAL or active_children:
                actions = ["cancel"]
            if state not in TERMINAL:
                actions.append("steer")
            pending = pending or bool(active_children)
        elif kind in {"task", "workflow"}:
            detail = {"current_step": item.current_step, "steps": len(item.steps),
                      "results": len(item.results), "progress": item.progress_text}
            if state == "running":
                actions = ["cancel"]
        elif kind == "loop":
            detail = {key: _get(item, key) for key in ("mode", "interval_seconds",
                      "max_iterations", "iteration_count", "stop_condition")}
            if state == "running":
                actions = ["stop"]
        elif kind == "process":
            detail = {key: _get(item, key) for key in ("host", "exit_code", "containment",
                      "transport_unknown", "session_confirmed_empty", "termination_reason")}
            if not _get(item, "restored", False) and (
                    state == "running" or not item.session_confirmed_empty):
                actions = ["stop"]
            settlement = {"state": "settled" if item.session_confirmed_empty else "unknown",
                          "resource_release": "confirmed" if item.session_confirmed_empty else
                          "unproven", "scope": item.containment}
        elif kind == "schedule":
            state = "paused" if item.get("paused") else "scheduled"
            detail = {key: item.get(key) for key in ("next_run", "last_run", "last_error",
                      "run_binding", "last_run_binding", "settlement", "inert_reason")}
            detail["revision"] = item.get("_revision", 0)
            # CAS-capable scheduler adapters alone can offer mutations. Never
            # advertise a race-prone legacy mutation as qualified.
            if getattr(self.scheduler, "desktop_control", None) is not None:
                actions = ["cancel", "resume" if item.get("paused") else "pause", "run_now"]
            settlement = {"state": "definition", "last_run": item.get("settlement")}
        if kind not in {"process", "schedule"} and state in TERMINAL and not pending:
            settlement = {"state": "settled", "resource_release": "manager_task_finished",
                          "remote_effects": "not_undone"}
        result = dict(record, state=state, detail=detail, actions=actions,
                      title=scrub_output_secrets(str(_get(item, "label",
                                _get(item, "description", _get(item, "goal",
                                _get(item, "command", record["id"]))))))[:1000],
                      settlement=settlement)
        return result

    def refresh(self, record, items=None):
        """``items``: the record kind's manager items by ID, when the caller holds them."""
        item = (self._items(record["kind"]) if items is None else items).get(record["manager_id"])
        if self._same(record, item):
            result = self._project(record, item)
            self._watch(item)
        else:
            result = dict(record, actions=[])
            if record["kind"] == "schedule":
                # Schedule records end only below; an ended or unconcluded one keeps its state.
                if item is None and self.scheduler is not None and record["state"] in {
                        "scheduled", "paused", "running"}:
                    result = self._ended_schedule_projection(record, result)
            elif record["settlement"]["state"] not in {"settled", "definition"}:
                result.update(state="interrupted", settlement={"state": "unknown",
                              "resource_release": "unproven"})
        if result != record:
            with self.store.transaction() as connection:
                connection.execute("UPDATE desktop_work SET record=? WHERE kind=? AND id=? "
                                   "AND manager_generation=?",
                                   (canonical_json(result), record["kind"],
                                   record["manager_id"], record["manager_generation"]))
                self.events.append("work.updated",
                                   {"kind": result["kind"], "id": result["id"]}, result)
        return json.loads(canonical_json(result))

    def _ended_schedule_projection(self, record, result):
        """A schedule its scheduler no longer holds: a one-time schedule after its run, or a
        deleted one. Deleting a definition doesn't end a run already executing; only the
        latest run's own recorded result settles it."""
        in_flight = getattr(self.scheduler, "_in_flight", None)
        if not isinstance(in_flight, (set, frozenset)):
            return result  # Running state can't be known; conclude nothing.
        removed = self._removed_definition(record)
        if removed is not None:
            # The scheduler's record of the definition as it removed it names its latest
            # run, including one whose start never reached Work.
            result = dict(result, detail=dict(result.get("detail") or {},
                          run_binding=removed["run_binding"],
                          last_run_binding=removed["last_run_binding"]))
        last_run = record["settlement"].get("last_run")
        if record["manager_id"] in in_flight:
            return dict(result, state="running",
                        settlement={"state": "pending", "last_run": last_run})
        ended = self._ended_schedule_state(record["manager_id"], removed)
        return dict(result, state=ended, settlement={
            "state": "unknown" if ended == "unknown" else "settled", "last_run": last_run})

    def _removed_definition(self, record):
        """The scheduler's complete removal record for this generation, or None."""
        lookup = getattr(self.scheduler, "removed_definition", None)
        removed = lookup(record["manager_id"]) if callable(lookup) else None
        if (not isinstance(removed, dict)
                or removed.get("generation") != record["manager_generation"]):
            return None
        return removed

    def _ended_schedule_state(self, schedule_id, removed):
        """The result of the definition's latest run, from that run's own history entry.

        The scheduler's removal record names the latest run the definition had
        (`run_binding`, else `last_run_binding`). Only a history entry with that run ID
        settles it: completed, failed or unknown. A run that left no entry (cancelled,
        history unavailable, the core stopped) is unknown, never settled from an older
        run. Only a record whose two bindings are explicitly null says the definition
        never ran: cancelled. Without a complete removal record (removed by an older
        version, pruned or damaged) the latest run can't be named, so the ending is
        unknown: Work's own binding may predate a run it never heard start. So is a latest
        run that belongs to an earlier generation of the definition.
        """
        if removed is None:
            return "unknown"
        latest = (removed["run_binding"] if removed["run_binding"] is not None
                  else removed["last_run_binding"])
        if latest is None:
            return "cancelled"
        if latest.get("generation") != removed["generation"]:
            return "unknown"
        path = getattr(getattr(self.scheduler, "history", None), "path", None)
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines() if path else []
        except (OSError, UnicodeError, TypeError):
            lines = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (type(entry) is dict and entry.get("schedule_id") == schedule_id
                    and type(entry.get("run_binding")) is dict
                    and entry["run_binding"].get("run_id") == latest["run_id"]):
                return {"success": "completed", "failure": "failed"}.get(entry.get("status"),
                                                                         "unknown")
        return "unknown"

    def refresh_all(self):
        with self.store.transaction() as connection:
            records = [json.loads(row[0]) for row in connection.execute(
                "SELECT record FROM desktop_work ORDER BY kind,id,manager_generation")]
        items = {}  # one read of each kind's manager per pass: the scheduler's is a full copy
        for record in records:
            if record["kind"] not in items:
                items[record["kind"]] = self._items(record["kind"])
        return [self.refresh(record, items[record["kind"]]) for record in records]

    def list(self, params=None) -> dict:
        params = params or {}
        if not self.permissions.is_owner(self.authority.owner_id):
            return response_error("unauthorized", "Current profile owner authority required")
        if params.get("kind") is not None and params["kind"] not in KINDS:
            return response_error("bad_request", "Unknown work kind")
        items = self.refresh_all()
        return {"items": [r for r in items if r["owner_id"] == self.authority.owner_id
                          and (not params.get("kind") or r["kind"] == params["kind"])
                          and (not params.get("conversation_id") or
                               r["conversation_id"] == params["conversation_id"])]}

    def resolve(self, kind: str, id: str) -> dict | None:
        """Resolve the protocol's immutable list ID, never a recycled PID/manager ID."""
        if kind not in KINDS or type(id) is not str:
            return None
        with self.store.transaction() as connection:
            rows = connection.execute("SELECT record FROM desktop_work WHERE kind=?",
                                      (kind,)).fetchall()
        record = next((r for row in rows if (r := json.loads(row[0]))["id"] == id), None)
        return self.refresh(record) if record else None

    def binding(self, params):
        """Exact work binding for ControlService reservation and duplicate checks."""
        required = ("kind", "id", "manager_generation", "run_id", "conversation_id")
        if (any(type(params.get(k)) is not str or not params[k] for k in required)
                or type(params.get("generation")) is not int):
            return None
        with self.store.transaction() as connection:
            rows = connection.execute("SELECT record FROM desktop_work WHERE kind=? "
                                      "AND manager_generation=?", (params["kind"],
                                      params["manager_generation"])).fetchall()
        record = next((r for row in rows if (r := json.loads(row[0]))["id"] == params["id"]),
                      None)
        if record and all(record[k] == params[k] for k in required + ("generation",)):
            return record
        return None

    async def control_native(self, message, kind, manager_id, action, *, text=None):
        """Native controls share ControlService command journal, never bypass it."""
        self.requests.assert_bound_request(message)
        # Work belongs to the profile owner, not the conversation issuing this
        # control. Resolve globally, then journal the target's original binding.
        listing = self.list({"kind": kind})
        records = [r for r in listing.get("items", []) if r["manager_id"] == str(manager_id)
                   and r["owner_id"] == message.owner_id and action in r["actions"]]
        if len(records) != 1 or self.controls is None:
            return "Error: bound work control is not available."
        record = records[0]
        params = {k: record[k] for k in ("kind", "id", "manager_generation", "run_id",
                  "generation", "conversation_id")}
        params.update(control_command_id=str(uuid.uuid4()), action=action)
        if text is not None:
            params["text"] = text
        if kind == "schedule":
            params["revision"] = record["detail"]["revision"]
        return await self.controls.dispatch("work.control", params)

    async def apply(self, params, *, owner_context) -> dict:
        """ControlService-only backend. Reservation MUST commit before calling.

        A thrown exception may follow a dispatched signal; ControlService leaves
        that reservation unknown and never retries it. This backend does not
        mint cached receipts or authorize a renderer's claimed owner.
        """
        if (not self.authority.accepts(owner_context) or
                not self.permissions.is_owner(owner_context.owner_id)):
            return response_error("unauthorized", "Authenticated profile owner required")
        record = self.binding(params)
        if record is None or record["owner_id"] != owner_context.owner_id:
            return {"disposition": "not_available", "reason": "stale_target"}
        key = (record["kind"], record["manager_id"])
        async with self._locks.setdefault(key, asyncio.Lock()):
            if (not self.authority.accepts(owner_context) or
                    not self.permissions.is_owner(owner_context.owner_id)):
                return response_error("unauthorized", "Authenticated profile owner required")
            current = self.refresh(record)
            action = params.get("action")
            if action not in current["actions"]:
                return {"disposition": "not_available", "reason": "action_unavailable"}
            item = self._items(record["kind"]).get(record["manager_id"])
            if not self._same(record, item):
                return {"disposition": "not_available", "reason": "stale_target"}
            kind, manager_id = record["kind"], record["manager_id"]
            if kind == "agent":
                if action == "steer":
                    text = params.get("text")
                    if type(text) is not str or not text:
                        return response_error("bad_request", "Expected a parent correction")
                    result = self.agents.send(manager_id, text)
                    receipt = {"disposition": "queued", "consumed": False,
                               "sequence": item.inbox_sequence, "detail": result}
                else:
                    self.agents.kill(manager_id)  # preserves cascade/lineage ownership
                    receipt = {"disposition": "requested"}
            elif kind in {"task", "workflow"}:
                await item.request_cancel()
                receipt = {"disposition": "requested"}
            elif kind == "loop":
                await self.loops.stop_loop(manager_id)
                receipt = {"disposition": "requested"}
            elif kind == "process":
                if self.authorize_process is None or not self.authorize_process(item):
                    return response_error("unauthorized", "Current process scope is not authorized")
                await self.processes.kill(int(manager_id), authorized=lambda info:
                    self._same(record, info) and self.authority.accepts(owner_context) and
                    self.permissions.is_owner(record["owner_id"]) and
                    self.authorize_process(info))
                receipt = {"disposition": "requested"}
            else:
                if params.get("revision") != current["detail"]["revision"]:
                    return {"disposition": "not_available", "reason": "stale_revision"}
                receipt = await self.scheduler.desktop_control(manager_id, action,
                    expected_binding={"generation": record["manager_generation"],
                                      "revision": params["revision"],
                                      "owner_id": record["owner_id"],
                                      "conversation_id": record["conversation_id"]})
                # The retained scheduler returns its own domain response, not
                # a control receipt. Completion of run_now includes its actual
                # history status; a skipped run was never dispatched.
                if type(receipt) is bool:
                    receipt = {"disposition": "done" if receipt else "not_available"}
                elif "disposition" not in receipt:
                    receipt = {"disposition": "not_available" if
                        receipt.get("status") == "skipped" else "done", "schedule": receipt}
            updated = self.refresh(current)
            if (receipt["disposition"] == "requested" and
                    updated["settlement"]["state"] == "settled"):
                receipt["disposition"] = "done"
            return dict(receipt, settlement=updated["settlement"], run_id=record["run_id"],
                        generation=record["generation"],
                        manager_generation=record["manager_generation"])
