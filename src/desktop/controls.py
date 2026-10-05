"""Request-bound controls over Odin's existing cancellation and resume owners.

The control identity is deliberately independent of the transport envelope ID.
A pending receipt is an unknown outcome, never permission to repeat input after
a crash. Steering's admission receipt and its later mailbox receipt are distinct.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime

from ..discord.channel_state import STEER_MESSAGE_MAX_CHARS, STEER_MESSAGES_PER_TURN
from ..discord.turn_resume import TurnResumeManager
from ..turn_state.store import TurnKey
from .commands import JournalStorageError, canonical_json, response_error

CONTROL_COLUMNS = {
    "control_command_id", "binding", "conversation_id", "request_id", "generation",
    "kind", "disposition", "sequence", "response", "created_at",
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ControlService:
    """Service seam; request execution remains exclusively RequestService's job.

    ``requests`` exposes binding/get_request and async launch_resume(row, turn).
    ``resume_manager`` is the real TurnResumeManager with its profile TurnStateStore,
    fresh catalog/config/permissions and trusted original-message fetch adapter.
    No simplified checkpoint decoder or fallback fresh submission exists here.
    """

    def __init__(self, store, events, requests, channel_state, *, authority, permissions,
                 resume_manager: TurnResumeManager | None = None,
                 on_changed: Callable[[], None] | None = None) -> None:
        self.store = store
        self.events = events
        self.requests = requests
        self.channel_state = channel_state
        self.authority = authority
        self.permissions = permissions
        self.resume_manager = resume_manager
        self.on_changed = on_changed
        self.work = None
        self._locks: dict[str, asyncio.Lock] = {}
        with store.transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_controls (
                control_command_id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                conversation_id TEXT NOT NULL, request_id TEXT NOT NULL,
                generation INTEGER NOT NULL, kind TEXT NOT NULL,
                disposition TEXT NOT NULL, sequence INTEGER, response TEXT,
                created_at REAL NOT NULL)""")

    async def dispatch(self, method: str, params: dict, *, on_notice=None) -> dict:
        if method == "work.control":
            return await self._work_control(params)
        if method not in {"control.stop", "control.steer", "control.resume"}:
            return response_error("not_found", "Unknown control method")
        if (type(params) is not dict
                or any(type(params.get(key)) is not str or not params[key]
                       for key in ("control_command_id", "conversation_id", "request_id"))
                or type(params.get("generation")) is not int or params["generation"] < 1):
            return response_error("bad_request", "Expected a request-bound control")
        command_id = params["control_command_id"]
        # No caller-supplied owner identity. Revocation wins over cached receipts.
        if not self.permissions.is_owner(self.authority.owner_id):
            return response_error("unauthorized", "Current profile owner authority is required")
        normalized = {key: params[key] for key in (
            "control_command_id", "conversation_id", "request_id", "generation")}
        if method == "control.steer":
            normalized["text"] = params.get("text")
        try:
            binding = canonical_json([self.store.profile_id, method, normalized])
            async with self._locks.setdefault(command_id, asyncio.Lock()):
                cached = self._reserve(method, normalized, binding)
                if cached is not None:
                    return cached
                if method == "control.resume":
                    answer = await self._resume(normalized, on_notice=on_notice)
                    self._finish(command_id, answer)
                else:
                    answer = self._stop_or_steer(method, normalized)
                    self._finish(command_id, answer)
                self._changed()
                return answer
        except (JournalStorageError, sqlite3.Error, OSError):
            return response_error("storage_unavailable", "Durable control storage is unavailable",
                                  "outcome_unknown")
        except Exception:
            # Leave the reservation pending. An external action may already have
            # happened, so even a fresh transport envelope cannot retry it.
            return response_error("internal", "Control outcome is unknown", "outcome_unknown")

    async def _work_control(self, params):
        """Use the same durable control boundary for real manager controls.

        The app names the immutable id it read. Persist the resolved run and
        generation before any manager action. A replay returns that old receipt,
        never resolves a successor using the same manager-visible identifier.
        """
        if (type(params) is not dict or any(type(params.get(key)) is not str or not params[key]
                for key in ("control_command_id", "kind", "id", "action"))):
            return response_error("bad_request", "Expected a work-bound control")
        if not self.permissions.is_owner(self.authority.owner_id):
            return response_error("unauthorized", "Current profile owner authority is required")
        command_id = params["control_command_id"]
        binding = canonical_json([self.store.profile_id, "work.control", params])
        try:
            async with self._locks.setdefault(command_id, asyncio.Lock()):
                with self.store.transaction() as db:
                    old = db.execute("SELECT * FROM desktop_controls WHERE control_command_id=?",
                                     (command_id,)).fetchone()
                    if old is not None:
                        if old["binding"] != binding:
                            return response_error("id_conflict",
                                                  "Control ID has a different binding")
                        if old["response"] is None:
                            return response_error("internal", "Control outcome is unknown",
                                                  "outcome_unknown")
                        return json.loads(old["response"])
                if self.work is None:
                    return response_error("capability_unavailable", "Work controls are unavailable")
                records = self.work.list({"kind": params["kind"]}).get("items", [])
                records = [item for item in records if item["id"] == params["id"]]
                if len(records) != 1:
                    return {"ok": True, "result": {"disposition": "not_available"}}
                record = records[0]
                normalized = {key: record[key] for key in (
                    "kind", "id", "manager_generation", "run_id", "generation", "conversation_id")}
                normalized.update(control_command_id=command_id, action=params["action"])
                for key in normalized:
                    if key in params and params[key] != normalized[key]:
                        return {"ok": True, "result": {"disposition": "not_available"}}
                if "text" in params:
                    normalized["text"] = params["text"]
                if record["kind"] == "schedule":
                    normalized["revision"] = record["detail"]["revision"]
                    if "revision" in params and params["revision"] != normalized["revision"]:
                        return {"ok": True, "result": {"disposition": "not_available"}}
                self._reserve("work.control", dict(normalized,
                    request_id=record.get("request_id") or record["run_id"]), binding)
                owner = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
                result = await self.work.apply(normalized, owner_context=owner)
                answer = result if "ok" in result else {"ok": True, "result": result}
                self._finish(command_id, answer)
                self._changed()
                return answer
        except (JournalStorageError, sqlite3.Error, OSError):
            return response_error("storage_unavailable", "Durable control storage is unavailable",
                                  "outcome_unknown")
        except Exception:
            return response_error("internal", "Control outcome is unknown", "outcome_unknown")

    def _reserve(self, method: str, params: dict, binding: str) -> dict | None:
        with self.store.transaction() as connection:
            row = connection.execute("SELECT * FROM desktop_controls WHERE control_command_id=?",
                                     (params["control_command_id"],)).fetchone()
            if row is not None:
                if row["binding"] != binding:
                    return response_error("id_conflict", "Control ID has a different binding")
                if row["response"] is None:
                    return response_error("internal", "Control outcome is unknown",
                                          "outcome_unknown")
                return json.loads(row["response"])
            connection.execute("""INSERT INTO desktop_controls
                (control_command_id,binding,conversation_id,request_id,generation,kind,
                 disposition,created_at) VALUES (?,?,?,?,?,?,'pending',?)""",
                               (params["control_command_id"], binding, params["conversation_id"],
                                params["request_id"], params["generation"],
                                method.split(".")[1], time.time()))
        return None

    def _finish(self, command_id: str, answer: dict) -> None:
        with self.store.transaction() as connection:
            connection.execute("UPDATE desktop_controls SET response=? WHERE control_command_id=?",
                               (canonical_json(answer), command_id))

    def _receipt(self, params: dict, disposition: str, sequence: int | None = None,
                 *, emit: bool = True) -> None:
        with self.store.transaction() as connection:
            connection.execute("""UPDATE desktop_controls SET disposition=?,sequence=?
                WHERE control_command_id=? AND request_id=? AND generation=?""",
                               (disposition, sequence, params["control_command_id"],
                                params["request_id"], params["generation"]))
            row = connection.execute("SELECT kind FROM desktop_controls WHERE control_command_id=?",
                                     (params["control_command_id"],)).fetchone()
            if emit and row and row["kind"] in {"stop", "steer"}:
                payload = {key: params[key] for key in (
                    "conversation_id", "request_id", "generation", "control_command_id")}
                payload.update(kind=row["kind"], disposition=disposition)
                self.events.append("control.receipt",
                                   {"kind": "control", "id": params["control_command_id"]}, payload)

    def _target(self, params: dict) -> dict | None:
        row = self.requests.binding(params["conversation_id"], params["request_id"],
                                    params["generation"])
        return row if row and row.get("owner") == self.authority.owner_id else None

    def _stop_or_steer(self, method: str, params: dict) -> dict:
        if method == "control.stop":
            return self._stop(params)
        # All binding and owner checks plus mailbox input are synchronous. No
        # successor can acquire the channel between the checks and delivery.
        with self.store.transaction():
            row = self._target(params)
            if row is None:
                self._receipt(params, "stale_binding")
                return {"ok": True, "result": {"disposition": "stale_binding"}}
            cid, rid = params["conversation_id"], params["request_id"]
            text = params.get("text")
            if type(text) is not str or not text.strip():
                self._receipt(params, "closed", emit=False)
                return response_error("bad_request", "Expected a nonempty steering message")
            # The app's fixture contracts the transport payload to 4000 chars.
            # Preserve full text in durable identity binding, while passing
            # only the bounded directive to Odin's unchanged mailbox primitive.
            text = text[:STEER_MESSAGE_MAX_CHARS]
            if (row["state"] != "running"
                    or self.channel_state.active_requests.get(cid) != rid):
                self._receipt(params, "closed")
                return {"ok": True, "result": {"disposition": "closed"}}
            inbox = self.channel_state._steer_inboxes.get((cid, rid))
            if (inbox is None or not inbox.accepting
                    or inbox.requester_id != self.authority.owner_id
                    or self.channel_state.is_cancelled(cid)
                    or inbox.inbox_sequence >= STEER_MESSAGES_PER_TURN):
                self._receipt(params, "closed")
                return {"ok": True, "result": {"disposition": "closed"}}
            # Reserve the existing mailbox's next sequence, with no await or
            # secondary counter. Persist admission before process-local input.
            sequence = inbox.inbox_sequence + 1
            self._receipt(params, "queued", sequence)
        async def settled(sequence: int, outcome: str) -> None:
            self.settle_steer(params["control_command_id"], rid, params["generation"],
                              sequence, outcome)
        result = self.channel_state.request_steer(
            cid, text, user_id=self.authority.owner_id, notifier=settled)
        if result != f"Message queued (sequence {sequence}; not yet consumed).":
            raise RuntimeError("Steering owner changed after durable admission")
        return {"ok": True, "result": {"disposition": "queued", "sequence": sequence}}

    def _stop(self, params: dict) -> dict:
        cid, rid = params["conversation_id"], params["request_id"]
        with self.store.transaction() as connection:
            row = self._target(params)
            if row is None:
                self._receipt(params, "stale_binding")
                return {"ok": True, "result": {"disposition": "stale_binding"}}
            if row["state"] == "queued":
                connection.execute("""UPDATE desktop_requests SET state='cancelled',ended_at=?
                    WHERE request_id=? AND generation=? AND state='queued'""",
                                   (_now(), rid, params["generation"]))
                self._receipt(params, "confirmed")
                self.events.append("request.cancelled", {"kind": "request", "id": rid},
                                   {"conversation_id": cid, "request_id": rid,
                                    "generation": params["generation"], "unknown_effects": 0})
                return {"ok": True, "result": {"disposition": "requested"}}
            if (row["state"] not in {"running", "stop_requested"}
                    or self.channel_state.active_requests.get(cid) != rid):
                self._receipt(params, "not_running", emit=False)
                return {"ok": True, "result": {"disposition": "not_running"}}
            connection.execute("UPDATE desktop_requests SET state='stop_requested' "
                               "WHERE request_id=? AND generation=?",
                               (rid, params["generation"]))
            self._receipt(params, "requested")
        # Commit the receipt/event before cancellation input. No await allows
        # a successor to replace the binding between admission and delivery.
        owned = self.channel_state.request_stop(cid)
        if owned is None or owned[0] != rid:
            raise RuntimeError("Cancellation owner changed after durable admission")
        owned[1].add_done_callback(lambda waiter: self._stop_settled(params, waiter))
        return {"ok": True, "result": {"disposition": "requested"}}

    def _stop_settled(self, params: dict, waiter: asyncio.Future) -> None:
        if waiter.cancelled() or waiter.exception() is not None:
            return
        if not getattr(waiter.result(), "confirmed", False):
            return
        # Existing stop confirmation means its own turn durably settled. It
        # cannot confirm a newer generation's control even when rid is reused.
        try:
            with self.store.transaction() as connection:
                row = connection.execute("SELECT disposition FROM desktop_controls "
                                         "WHERE control_command_id=? AND generation=?",
                                         (params["control_command_id"],
                                          params["generation"])).fetchone()
                if row and row[0] == "requested":
                    self._receipt(params, "confirmed")
            self._changed()
        except (JournalStorageError, sqlite3.Error, OSError):
            pass  # No false receipt when persistence failed.

    def settle_steer(self, command_id: str, request_id: str, generation: int,
                     sequence: int, outcome: str) -> bool:
        if outcome not in {"consumed", "closed"}:
            raise ValueError("Expected a mailbox settlement")
        with self.store.transaction() as connection:
            row = connection.execute("""SELECT * FROM desktop_controls WHERE control_command_id=?
                AND request_id=? AND generation=? AND sequence=? AND disposition='queued'""",
                                     (command_id, request_id, generation, sequence)).fetchone()
            if row is None:
                return False
            self._receipt(dict(row), outcome, sequence)
        self._changed()
        return True

    async def _resume(self, params: dict, *, on_notice=None) -> dict:
        def reject(reason, notice=None):
            answer = self._reject_resume(params, reason)
            if on_notice is not None:
                on_notice(notice or (
                    f"I couldn't resume the preserved work: {reason}. "
                    "Ask again from scratch if you still need it."))
            return answer

        cid = params["conversation_id"]
        async with self.channel_state.lock_for(cid):
            if getattr(self.requests, "_closed", False):
                return reject("quiescing")
            row = self._target(params)
            if row is None:
                existing = self.requests.get_request(params["request_id"])
                if (existing and existing["conversation_id"] == cid
                        and existing.get("owner") != self.authority.owner_id):
                    return reject("stale_binding",
                        "There is preserved work in this channel, but only the person "
                        "who started it can resume it.")
                return reject("stale_binding")
            if row["state"] not in {"interrupted", "suspended"}:
                return reject("not_resumable")
            if self._busy(cid):
                return reject("busy")
            manager = self.resume_manager
            if manager is None:
                return reject("resume_unavailable")
            key = TurnKey("conversation", cid, params["request_id"])
            preserved = await asyncio.to_thread(manager._store.load_resumable_sync, key)
            if preserved is None:
                return reject("checkpoint_unavailable",
                    "That preserved work is no longer resumable (it was just "
                    "rejected as unreadable, claimed by another resume, or "
                    "expired). Nothing was resumed — ask fresh for what you need.")
            if (preserved["generation"] != row.get("ledger_generation")
                    or str(preserved.get("user_id") or "") != self.authority.owner_id):
                return reject("stale_binding")
            unknown = row.get("unknown_effects")
            if isinstance(unknown, str):
                unknown = json.loads(unknown)
            unresolved = manager._unresolved_ops(preserved)
            if unknown or unresolved:
                # Preserve the same original safety transition, not a fresh run.
                await asyncio.to_thread(manager._store.mark_ops_manual_sync,
                                        key, preserved["generation"])
                await asyncio.to_thread(manager._store.reject_resumable_sync,
                                        key, "unresolved operations require manual resolution")
                manager._release_calibration(key)
                names = ", ".join(sorted({str(op.get("tool_name") or "unknown")
                                          for op in (unresolved or unknown)}))
                return reject("unknown_effects",
                    f"I can't safely continue that work: {len(unresolved) or len(unknown)} "
                    f"interrupted operation(s) ({names or 'unknown'}) have UNKNOWN outcomes — "
                    "they may or may not have applied, and I will not re-run "
                    "them automatically. Verify their current state, then ask "
                    "fresh for whatever is still needed.")
            waiter = manager._waiters.pop(key, None)
            if waiter is not None:
                waiter.cancel()
            # This performs the actual codec restore, integrity, original
            # author/content, current tools, transcript repair, budget restore
            # and single-winner lease acquisition. Never replace it with a
            # desktop decoder or call try_explicit_resume's latest-row lookup.
            turn, _original, reason = await self._rebuild(manager, key, preserved)
            if turn is None:
                return reject(reason or "not_resumable")
            try:
                with self.store.transaction() as connection:
                    current = self._target(params)
                    if (not self.permissions.is_owner(self.authority.owner_id)
                            or getattr(self.requests, "_closed", False)
                            or not current or current["state"] not in {"interrupted", "suspended"}
                            or self._busy(cid)):
                        await_release = True
                    else:
                        await_release = False
                        next_generation = params["generation"] + 1
                        connection.execute("""UPDATE desktop_requests
                            SET generation=?,state='running',
                            started_at=?,ended_at=NULL,ledger_generation=?
                            WHERE request_id=? AND generation=?""",
                                           (next_generation, _now(),
                                            turn.durability.lease.generation,
                                            params["request_id"], params["generation"]))
                        self._receipt(params, "admitted", emit=False)
                        self.events.append("request.started",
                                           {"kind": "request", "id": params["request_id"]},
                                           {"conversation_id": cid,
                                            "request_id": params["request_id"],
                                            "generation": next_generation})
                if await_release:
                    turn.durability._stop_heartbeats()
                    await asyncio.to_thread(manager._store.release_acquired_sync,
                                            turn.durability.lease)
                    return reject("busy_or_revoked")
            except BaseException:
                turn.durability._stop_heartbeats()
                await asyncio.to_thread(manager._store.release_acquired_sync,
                                        turn.durability.lease)
                raise
            # Scheduling, task authority, execution envelope, final delivery and
            # cancellation settlement remain with the same request runner.
            try:
                await self.requests.launch_resume(
                    self.requests.get_request(params["request_id"]), turn)
            except BaseException:
                # Admission was durable, but no task could take ownership.
                # Preserve an interruption for explicit fresh-control recovery,
                # not a running phantom or automatic fresh execution.
                turn.durability._stop_heartbeats()
                await asyncio.to_thread(manager._store.release_acquired_sync,
                                        turn.durability.lease)
                with self.store.transaction() as connection:
                    connection.execute("""UPDATE desktop_requests SET state='interrupted',ended_at=?
                        WHERE request_id=? AND generation=? AND state='running'""",
                                       (_now(), params["request_id"], next_generation))
                    self.events.append("request.interrupted",
                                       {"kind": "request", "id": params["request_id"]},
                                       {"conversation_id": cid, "request_id": params["request_id"],
                                        "generation": next_generation, "unknown_effects": 0})
                    self._finish(params["control_command_id"], response_error(
                        "internal", "Control outcome is unknown", "outcome_unknown"))
                raise
            return {"ok": True, "result": {"disposition": "admitted"}}

    async def _rebuild(self, manager, key, preserved):
        # Lease acquisition runs in a thread inside the existing manager. An
        # IPC caller disappearing must not cancel its await and lose the handle
        # to a lease which the thread acquired moments later.
        task = asyncio.create_task(manager._validate_and_rebuild(key, preserved))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            turn, _original, _reason = await task
            if turn is not None:
                turn.durability._stop_heartbeats()
                await asyncio.to_thread(manager._store.release_acquired_sync,
                                        turn.durability.lease)
            raise

    def _busy(self, conversation_id: str) -> bool:
        if conversation_id in self.channel_state.active_requests:
            return True
        return self.store.connection.execute("""SELECT 1 FROM desktop_requests
            WHERE conversation_id=? AND state IN ('queued','running','stop_requested') LIMIT 1""",
                                             (conversation_id,)).fetchone() is not None

    def _reject_resume(self, params: dict, reason: str) -> dict:
        self._receipt(params, "rejected", emit=False)
        return {"ok": True, "result": {"disposition": "rejected", "reason": reason}}

    def recover_after_restart(self) -> int:
        """Close lost process-local steering mailboxes; never recreate input.

        Called once by the service graph after requests' interruption sweep and
        before admitting workers. Pending identities remain unknown. Requested
        stops are not confirmed by a restart or by a newer successful request.
        """
        with self.store.transaction() as connection:
            rows = connection.execute("SELECT * FROM desktop_controls "
                                      "WHERE kind='steer' AND disposition='queued'").fetchall()
            for row in rows:
                self._receipt(dict(row), "closed", row["sequence"])
        if rows:
            self._changed()
        return len(rows)

    def _changed(self) -> None:
        if self.on_changed is not None:
            self.on_changed()


Controls = ControlService
