"""Durable step-three admission and task-owned binding to the retained engine."""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

from ..discord.response_guards import scrub_response_secrets
from ..error_presentation import format_user_facing_error
from ..turn_state.codec import compute_content_digest
from ..turn_state.durability import TurnDurability
from ..turn_state.store import TurnKey, TurnStatus
from .commands import canonical_json, response_error
from .conversations import ConversationError, domain_transaction, now, require_string
from .errors import NoLLMProviderError

REQUEST_SCHEMA = {
    "desktop_requests": {"request_id", "conversation_id", "message_id", "owner", "generation",
                         "state", "text", "attachments", "created_at", "started_at", "ended_at",
                         "unknown_effects", "ledger_generation"},
    "desktop_submissions": {"client_submission_id", "binding", "response"},
}
_execution = ContextVar("desktop_engine_execution", default=None)


@dataclass(frozen=True, slots=True)
class LocalAuthor:
    id: str
    display_name: str

    def __str__(self):
        return self.display_name


@dataclass(frozen=True, slots=True)
class LocalChannel:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class EngineRequest:
    conversation_id: str
    request_id: str
    generation: int
    owner_id: str
    owner_name: str
    message_id: str
    content: str
    channel: LocalChannel
    author: LocalAuthor
    _seal: object = field(repr=False, compare=False)
    attachments: tuple = ()
    allowed_tools: None = None
    _odin_source: str = "conversation"

    @property
    def id(self):
        # The retained engine's message identity is the durable request, not
        # the separate visible transcript message or a content-derived hash.
        return self.request_id

    @property
    def turn_key(self):
        return TurnKey("conversation", self.conversation_id, self.request_id)

    @property
    def request_context(self):
        from .delivery import RequestContext

        return RequestContext(self.conversation_id, self.request_id, self.generation,
                              self.owner_id, self.message_id)


class RequestService:
    def __init__(self, store, conversations, transcript, *, engine, permissions,
                 authority, delivery, attachments=None):
        self.store, self.conversations, self.transcript = store, conversations, transcript
        self.events = conversations.events
        self.engine, self.permissions, self.authority = engine, permissions, authority
        self.delivery, self.attachments = delivery, attachments
        self._seal = object()
        self._workers = {}
        self._tasks = set()
        self._closed = False
        self._session_epochs = {}
        runner = getattr(engine, "runner", None)
        if runner is not None:
            runner._record_tool_detail = self.record_tool_detail
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_requests (
                request_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL, owner TEXT NOT NULL,
                generation INTEGER NOT NULL, state TEXT NOT NULL, text TEXT NOT NULL,
                attachments TEXT NOT NULL, created_at TEXT NOT NULL,
                started_at TEXT, ended_at TEXT, unknown_effects TEXT NOT NULL,
                ledger_generation TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_submissions (
                client_submission_id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                response TEXT NOT NULL)""")
            # Upgrade step-three profiles made before execution lineage existed.
            # Those profiles refused reset while work ran, so the most recent
            # notice at start time is unambiguous. Queued work stays unbound.
            db.execute("""INSERT OR IGNORE INTO desktop_request_context
                SELECT r.request_id,r.conversation_id,COALESCE((
                    SELECT MAX(m.position) FROM desktop_messages m
                    WHERE m.conversation_id=r.conversation_id AND m.created_at<=r.started_at
                    AND json_extract(m.record,'$.context_reset')=1),0)
                FROM desktop_requests r JOIN desktop_conversations c ON c.id=r.conversation_id
                WHERE r.started_at IS NOT NULL""")
        conversations.state_provider = self
        audit = getattr(engine.deps, "audit", None)
        if audit is not None and hasattr(audit, "set_event_callback"):
            previous = getattr(audit, "_event_callback", None)

            async def observe(entry):
                await self.observe_tool_event(entry)
                if previous is not None:
                    await previous(entry)

            audit.set_event_callback(observe)

    def recover_interrupted(self):
        """Project crash-owned work as interrupted, never replay it as queued."""
        with self.store.transaction() as db:
            rows = list(db.execute("SELECT * FROM desktop_requests WHERE state IN "
                                   "('running','stop_requested')"))
            for row in rows:
                message = self.fetch_request(row["conversation_id"], row["request_id"])
                self._finish(message, "interrupted")

    def get_request(self, request_id):
        row = self.store.connection.execute(
            "SELECT * FROM desktop_requests WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row is not None else None

    def binding(self, conversation_id, request_id, generation):
        row = self.get_request(request_id)
        return row if (row and row["conversation_id"] == conversation_id
                       and type(generation) is int and row["generation"] == generation) else None

    def _owner(self):
        if not self.permissions.is_owner(self.authority.owner_id):
            raise ConversationError("unauthorized", "Authenticated profile owner required")
        return self.authority.owner_id

    def handle(self, method, params):
        if method != "submission.send":
            return response_error("capability_unavailable",
                                  "Request service does not serve this method")
        try:
            return {"ok": True, "result": self.submit(params)}
        except ConversationError as error:
            return error.response()

    def submit(self, params):
        """Ordinary admission; transport intake must use handle_async first."""
        if type(params) is not dict:
            raise ConversationError("bad_request", "Method params must be an object")
        owner = self._owner()
        sid = require_string(params.get("client_submission_id"), "client_submission_id")
        cid = require_string(params.get("conversation_id"), "conversation_id")
        text = params.get("text")
        attachments = params.get("attachments", [])
        binding = canonical_json(params)
        with domain_transaction(self.store) as db:
            old = db.execute("SELECT binding,response FROM desktop_submissions "
                             "WHERE client_submission_id=?", (sid,)).fetchone()
            if old is not None:
                if old[0] != binding:
                    raise ConversationError("id_conflict", "Submission ID is already bound")
                return json.loads(old[1])
            self.conversations.get(cid)
            if type(text) is not str or type(attachments) is not list:
                raise ConversationError("bad_request", "Invalid text or attachments")
            if not text.strip() and not attachments:
                raise ConversationError("bad_request", "A message needs text or attachments")
            if self._closed:
                raise ConversationError("busy", "The core is quiescing", "not_dispatched")
            rid, mid = "r_" + uuid4().hex, "m_" + uuid4().hex
            metadata = []
            if attachments:
                if self.attachments is None:
                    raise ConversationError("capability_unavailable",
                                            "Attachment service unavailable")
                try:
                    metadata = self.attachments.adopt_for_submission(db, cid, rid, mid, attachments)
                except Exception as error:
                    if hasattr(error, "code"):
                        raise ConversationError(error.code, error.message,
                                                error.disposition) from None
                    raise
            db.execute("""INSERT INTO desktop_requests VALUES (?,?,?,?,1,'queued',?,?,?,NULL,
                          NULL,'[]',NULL)""",
                       (rid, cid, mid, owner, text, canonical_json(metadata), now()))
            self.transcript.commit(cid, "user", text, id=mid, request_id=rid,
                                   client_submission_id=sid, attachments=metadata)
            self.events.append("request.queued", {"kind": "request", "id": rid},
                               {"conversation_id": cid, "request_id": rid, "generation": 1})
            response = {"disposition": "accepted", "request_id": rid, "message_id": mid}
            db.execute("INSERT INTO desktop_submissions VALUES (?,?,?)",
                       (sid, binding, canonical_json(response)))
            return response

    async def handle_async(self, method, params, *, controls):
        """Consume bare resume before attachments, prompt construction or history.

        Reserve a submission receipt before awaited checks. Lost ACKs and
        restarts cannot reinterpret recognized commands as fresh execution.
        """
        if method != "submission.send":
            return self.handle(method, params)
        try:
            if type(params) is not dict:
                raise ConversationError("bad_request", "Method params must be an object")
            owner = self._owner()
            sid = require_string(params.get("client_submission_id"), "client_submission_id")
            cid = require_string(params.get("conversation_id"), "conversation_id")
            text, attachments = params.get("text"), params.get("attachments", [])
            binding = canonical_json(params)
            from ..discord.turn_resume import TurnResumeManager
            with domain_transaction(self.store) as db:
                old = db.execute("SELECT binding,response FROM desktop_submissions "
                                 "WHERE client_submission_id=?", (sid,)).fetchone()
                if old is not None:
                    if old[0] != binding:
                        raise ConversationError("id_conflict", "Submission ID is already bound")
                    return {"ok": True, "result": json.loads(old[1])}
                self.conversations.get(cid)
                if type(text) is not str or type(attachments) is not list:
                    raise ConversationError("bad_request", "Invalid text or attachments")
                if not TurnResumeManager.is_resume_trigger(text):
                    return {"ok": True, "result": self.submit(params)}
                row = db.execute("""SELECT * FROM desktop_requests WHERE conversation_id=?
                    AND state IN ('suspended','interrupted')
                    ORDER BY (owner=?) DESC, COALESCE(ended_at,created_at) DESC,
                    request_id DESC LIMIT 1""", (cid, owner)).fetchone()
                if row is None:
                    return {"ok": True, "result": self.submit(params)}
                row = dict(row)
                pending = {"disposition": "outcome_unknown", "request_id": row["request_id"],
                           "message_id": row["message_id"]}
                db.execute("INSERT INTO desktop_submissions VALUES (?,?,?)",
                           (sid, binding, canonical_json(pending)))
            noticed = False

            def notice(body):
                nonlocal noticed
                self._owner()
                self.transcript.commit(cid, "notice", body, request_id=row["request_id"],
                                       client_submission_id=sid)
                noticed = True

            try:
                answer = await controls.dispatch("control.resume", {
                    "control_command_id": "submission-resume:" + sid,
                    "conversation_id": cid, "request_id": row["request_id"],
                    "generation": row["generation"]}, on_notice=notice)
            except Exception:
                answer = response_error("internal", "Control outcome is unknown", "outcome_unknown")
            result = {**pending, **answer.get("result", {})}
            if not noticed and result["disposition"] != "admitted":
                notice("I recognized the resume command, but resuming failed internally "
                       "while safely checking the preserved work. Nothing was resumed or "
                       "started fresh — try `resume` again later.")
            # submission.send keeps its public admission vocabulary even when
            # the accepted work is a resumed generation, not a fresh request.
            if result["disposition"] == "admitted":
                result["disposition"] = "accepted"
            with self.store.transaction() as db:
                db.execute("UPDATE desktop_submissions SET response=? WHERE client_submission_id=?",
                           (canonical_json(result), sid))
            return {"ok": True, "result": result}
        except ConversationError as error:
            return error.response()

    def snapshot(self, conversation_id):
        rows = [dict(row) for row in self.store.connection.execute(
            "SELECT * FROM desktop_requests WHERE conversation_id=? ORDER BY created_at,request_id",
            (conversation_id,))]
        def bind(row):
            return {"request_id": row["request_id"], "generation": row["generation"]}
        active = [row for row in rows if row["state"] in ("running", "stop_requested")]
        queued = [{**bind(row), "message_id": row["message_id"]} for row in rows
                  if row["state"] == "queued"]
        terminal = [{**bind(row), "outcome": row["state"],
                     "unknown_effects": len(json.loads(row["unknown_effects"])),
                     "at": row["ended_at"]} for row in rows
                    if row["state"] in ("completed", "failed", "cancelled",
                                        "interrupted", "suspended")]
        controls = []
        tables = {row[0] for row in self.store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "desktop_controls" in tables:
            controls = [dict(row) for row in self.store.connection.execute(
                "SELECT control_command_id,kind,request_id,generation,disposition,sequence "
                "FROM desktop_controls WHERE conversation_id=? AND kind IN ('stop','steer')",
                (conversation_id,))]
            bound = {(row["request_id"], row["generation"]) for row in active}
            bound.update((row["request_id"], row["generation"]) for row in queued)
            controls = [control for control in controls
                        if (control["request_id"], control["generation"]) in bound]
        running = {**bind(active[0]), "started_at": active[0]["started_at"]} if active else None
        return {"running": running,
                "queued": queued, "recent": terminal[-20:],
                "unresolved": [row for row in terminal if row["unknown_effects"]],
                "tools": self._snapshot_tools(conversation_id, tables), "controls": controls}

    def _snapshot_tools(self, conversation_id, tables):
        # The durable publication outbox survives event retention and sink ACKs.
        # Pair by invocation identity, not tool name or completion order.
        if "desktop_delivery_outbox" not in tables:
            return {}
        tools = {}
        for row in self.store.connection.execute("""SELECT o.payload FROM desktop_delivery_outbox o
                JOIN desktop_requests r ON r.request_id=o.request_id
                AND r.conversation_id=o.conversation_id
                WHERE o.conversation_id=? AND o.kind IN ('tool.started','tool.settled')
                ORDER BY o.event_seq""", (conversation_id,)):
            frame = json.loads(row[0])
            payload = frame["payload"]
            rid, invocation = payload["request_id"], payload["invocation_id"]
            item = tools.setdefault(rid, {}).setdefault(invocation, {"invocation_id": invocation})
            item.update({key: payload[key] for key in
                         ("tool", "target", "summary", "outcome", "exit_code", "duration_ms")
                         if key in payload})
        return {rid: list(items.values()) for rid, items in tools.items()}

    async def observe_tool_event(self, entry):
        """Project the retained runner's existing audit fan-out, never candidates."""
        kind = entry.get("type")
        if kind not in ("tool_start", "tool_end"):
            return
        meta = entry.get("metadata") or {}
        rid = entry.get("turn_id") or meta.get("turn_id")
        invocation = entry.get("call_id") or meta.get("call_id")
        row = self.get_request(rid) if rid else None
        if (row is None or not invocation or entry.get("channel_id") != row["conversation_id"]):
            return
        from .delivery import RequestContext
        context = RequestContext(row["conversation_id"], rid, row["generation"],
                                 row["owner"], row["message_id"])
        if kind == "tool_start":
            tool = entry.get("action")
            if not tool:
                return
            self.delivery.tool_started(context, invocation_id=invocation, tool=tool,
                                       summary=tool)
        else:
            error = entry.get("error") or meta.get("error")
            # The durable operation state, not a prose error guess, decides
            # whether an external effect's outcome is unknown.
            unknown = bool(meta.get("uncertain_outcome"))
            ledger = self.engine.deps.turn_store
            if ledger is not None:
                with ledger._write_lock:
                    op = ledger._require().execute("""SELECT state FROM operations
                        WHERE source='conversation' AND channel_id=? AND message_id=?
                        AND tool_call_id=? ORDER BY generation_seq DESC LIMIT 1""",
                        (row["conversation_id"], rid, invocation)).fetchone()
                    unknown = unknown or bool(op and op[0] in
                        ("OUTCOME_UNKNOWN", "MANUAL_RESOLUTION_REQUIRED"))
            elapsed = entry.get("execution_time_ms", meta.get("elapsed_ms", 0))
            self.delivery.tool_settled(context, invocation_id=invocation,
                outcome="unknown" if unknown else "failure" if error else "success",
                duration_ms=max(0, int(elapsed or 0)))

    def record_tool_detail(self, message, block, arguments, delivered_output):
        """Preserve the actual authorized sink output, not truncated audit text."""
        self.assert_bound_request(message)
        details = getattr(self.delivery, "tool_details", None)
        if details is None:
            return
        from ..tools.output_authorization import accessed_hosts, request_scope_id
        hosts = list((accessed_hosts.get() or {}).values())
        scope = request_scope_id.get()
        if scope:
            hosts.append({"scope": scope})
        details.record(request_id=message.request_id, invocation_id=block.id,
            owner=message.owner_id, conversation_id=message.conversation_id,
            tool=block.name, arguments=arguments, delivered_output=delivered_output,
            hosts=tuple(hosts))

    def fetch_request(self, conversation_id, request_id):
        row = self.get_request(request_id)
        if row is None or row["conversation_id"] != conversation_id:
            from ..discord.turn_resume import ConversationMessageNotFound
            raise ConversationMessageNotFound("Original request not found")
        self.conversations.get(conversation_id)
        from .delivery import LocalDestination, RequestContext
        destination = LocalDestination(RequestContext(conversation_id, request_id,
            row["generation"], row["owner"], row["message_id"]), self.delivery)
        return EngineRequest(conversation_id, request_id, row["generation"], row["owner"],
                             "Owner", row["message_id"], row["text"],
                             destination,
                             LocalAuthor(row["owner"], "Owner"), self._seal,
                             tuple(json.loads(row["attachments"])))

    def assert_request(self, message, *, allow_terminal=False):
        binding = _execution.get()
        if (not isinstance(message, EngineRequest) or message._seal is not self._seal
                or binding != (self, asyncio.current_task(), message)
                or not self.permissions.is_owner(message.owner_id)):
            raise PermissionError("The engine requires the current admitted request owner")
        row = self.binding(message.conversation_id, message.request_id, message.generation)
        allowed = {"running", "stop_requested"}
        if allow_terminal:
            allowed.update({"completed", "failed", "cancelled", "suspended", "interrupted"})
        if row is None or row["state"] not in allowed:
            raise PermissionError("The admitted request binding is no longer current")

    def assert_preserved_request(self, message):
        """Validate a fetched checkpoint source before an execution task exists."""
        if (not isinstance(message, EngineRequest) or message._seal is not self._seal
                or not self.permissions.is_owner(message.owner_id)):
            raise PermissionError("Preserved work requires its authenticated profile owner")
        row = self.binding(message.conversation_id, message.request_id, message.generation)
        if row is None or row["text"] != message.content or row["owner"] != message.owner_id:
            raise PermissionError("The preserved request binding is no longer current")

    def assert_delivery_context(self, context):
        # Native tool children inherit the admitted task context. They may post
        # artifacts, but may not grant themselves another execution identity.
        binding = _execution.get()
        if not binding or binding[0] is not self or binding[1].done():
            raise PermissionError("Delivery requires an active admitted task")
        message = binding[2]
        if context != message.request_context:
            raise PermissionError("Foreign request delivery context")
        row = self.binding(context.conversation_id, context.request_id, context.generation)
        if row is None or row["owner"] != context.owner_id:
            raise PermissionError("Request delivery binding is no longer current")
        if not self.permissions.is_owner(context.owner_id):
            raise PermissionError("Authenticated profile owner required")

    def assert_bound_request(self, message):
        """Read/publication authority for retained runner-owned tool children."""
        if not isinstance(message, EngineRequest) or message._seal is not self._seal:
            raise PermissionError("Untrusted request envelope")
        binding = _execution.get()
        if not binding or binding[2] is not message:
            raise PermissionError("Foreign request binding")
        self.assert_delivery_context(message.request_context)

    def _seed_session_context(self, message):
        sessions = getattr(self.engine.deps, "sessions", None)
        if sessions is None:
            return
        cid = message.conversation_id
        epoch = self.conversations._row(cid)["context_position"]
        if self._session_epochs.get(cid) == epoch:
            return
        # Seed once per execution lineage, preserving retained compaction. Use
        # today's context, not this input's historical position: it may have
        # been queued before a reset. Exclude inputs not yet executed (including
        # this one, which EngineServices adds with processed attachments).
        excluded = {message.request_id} | {row[0] for row in self.store.connection.execute(
            "SELECT request_id FROM desktop_requests WHERE conversation_id=? AND state='queued'",
            (cid,))}
        history = [item for item in self.transcript.model_context(cid)
                   if item.get("request_id") not in excluded]
        sessions.reset(cid)
        self.engine.deps.channel_state.recent_actions.pop(cid, None)
        for item in history:
            sessions.add_message(cid, item["role"], item["text"], user_id=message.owner_id)
        self._session_epochs[cid] = epoch

    def _fence_settled_context(self, message):
        """Retire old cache only after runner, handoff and accounting settle.

        Resetting SessionManager mid-turn would make handoff/history and result
        accounting create a new session with old writes. The durable transcript
        fence takes effect immediately; keep the admitted cache until settlement.
        """
        if self.context_is_current(message):
            return
        cid = message.conversation_id
        epoch = self.conversations._row(cid)["context_position"]
        sessions = getattr(self.engine.deps, "sessions", None)
        # A preserved old checkpoint can resume after newer turns. Its runner
        # owns its checkpoint messages, not today's compacted session cache.
        if self._session_epochs.get(cid) != epoch:
            if sessions is not None:
                sessions.reset(cid)
            self._session_epochs.pop(cid, None)
        self.engine.deps.channel_state.recent_actions.pop(cid, None)

    def context_is_current(self, message):
        """Internal accounting fence; request generations never change lineage."""
        row = self.store.connection.execute(
            "SELECT context_position FROM desktop_request_context WHERE request_id=?",
            (message.request_id,)).fetchone()
        return (row is None or row[0] ==
                self.conversations._row(message.conversation_id)["context_position"])

    async def fetch_message(self, conversation_id, request_id):
        message = self.fetch_request(conversation_id, request_id)
        self.assert_preserved_request(message)
        return message

    async def admit_turn(self, message, *, system_prompt, tools, session_snapshot):
        self.assert_request(message)
        store = self.engine.deps.turn_store
        handle = TurnDurability.disabled()
        if store is None:
            return handle
        handle.blocked = "admission_error"
        if not store.available:
            return handle
        def digest(text):
            return hashlib.sha256(text.encode("utf-8")).hexdigest()
        lease, disposition = await asyncio.to_thread(
            store.admit_turn_sync, message.turn_key, guild_id=None, user_id=message.owner_id,
            content_digest=compute_content_digest(message.content), code_version="0.1.0.dev1",
            prompt_policy_hash=digest(system_prompt),
            tool_catalog_hash=digest(",".join(sorted(
                tool.get("name", "") for tool in (tools or [])))),
            session_snapshot=session_snapshot)
        if lease is None:
            handle.blocked = ("admission_error" if disposition == "store_unavailable"
                              else disposition)
            return handle
        with self.store.transaction() as db:
            db.execute("UPDATE desktop_requests SET ledger_generation=? WHERE request_id=? "
                       "AND generation=?",
                       (lease.generation, message.request_id, message.generation))
        handle = TurnDurability(store, lease)
        handle._start_heartbeats()
        return handle

    async def after_commit(self):
        if self._closed:
            return
        for row in self.store.connection.execute(
                "SELECT DISTINCT conversation_id FROM desktop_requests WHERE state='queued'"):
            cid = row[0]
            task = self._workers.get(cid)
            if task is None or task.done():
                task = asyncio.create_task(self._drain(cid), name=f"desktop-request:{cid}")
                self._workers[cid] = task
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _drain(self, cid):
        # Authentication follows persisted profile identity, never a connected
        # window. Reconnecting cannot replace or remove the destination.
        owner = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
        token = self.permissions.set_request_owner(owner)
        try:
            async with self.engine.deps.channel_state.lock_for(cid):
                while not self._closed:
                    row = self.store.connection.execute(
                        "SELECT * FROM desktop_requests WHERE conversation_id=? AND state='queued' "
                        "ORDER BY created_at,request_id LIMIT 1", (cid,)).fetchone()
                    if row is None:
                        return
                    with self.store.transaction() as db:
                        active = db.execute(
                            "SELECT 1 FROM desktop_requests WHERE conversation_id=? "
                            "AND state IN ('running','stop_requested')", (cid,)).fetchone()
                        if active:
                            return
                        db.execute("UPDATE desktop_requests SET state='running',started_at=? "
                                   "WHERE request_id=? AND state='queued'",
                                   (now(), row["request_id"]))
                        db.execute("INSERT OR IGNORE INTO desktop_request_context VALUES (?,?,?)",
                                   (row["request_id"], cid,
                                    self.conversations._row(cid)["context_position"]))
                        self.events.append("request.started",
                                           {"kind": "request", "id": row["request_id"]},
                                           {"conversation_id": cid, "request_id": row["request_id"],
                                            "generation": row["generation"]})
                    await self._execute(self.fetch_request(cid, row["request_id"]))
        finally:
            self.permissions.reset_request_owner(token)

    async def _execute(self, message, st=None):
        token = _execution.set((self, asyncio.current_task(), message))
        failure_notice = False
        try:
            self.assert_request(message)
            failure_notice = True
            if st is None:
                self._seed_session_context(message)
            images = []
            content = message.content
            if st is None and self.attachments is not None and message.attachments:
                from ..discord.attachments import AttachmentProcessor, infer_attachment_intent
                streams = self.attachments.streams_for_request(
                    message.conversation_id, message.request_id)
                # Explicit ingestion remains a service seam, not automatic
                # ingestion of attached content or an app-supplied path.
                if any(add for _stream, add in streams):
                    ingest = getattr(self.engine, "ingest_attachment", None)
                    if ingest is None:
                        raise RuntimeError("Explicit attachment ingestion is not wired")
                    for stream, add in streams:
                        if add:
                            await ingest(message, stream)
                cfg = self.engine.deps.get_config().attachments
                processor = AttachmentProcessor(
                    temp_dir=cfg.temp_directory, inline_max_bytes=cfg.inline_text_max_bytes,
                    preview_max_chars=cfg.preview_max_chars,
                    large_preview_chars=cfg.large_preview_chars,
                    archive_max_bytes=cfg.archive_max_bytes,
                    archive_max_files=cfg.archive_max_files,
                    archive_extract_max_bytes=cfg.archive_extract_max_bytes,
                    archive_preview_total_chars=cfg.archive_preview_total_chars,
                    archive_preview_file_max_bytes=cfg.archive_preview_file_max_bytes,
                    image_max_bytes=cfg.image_max_bytes, pdf_max_bytes=cfg.pdf_max_bytes,
                    retention_hours=cfg.retention_hours)
                processed = await processor.process(
                    [stream for stream, _add in streams], conversation_id=message.conversation_id,
                    request_id=message.request_id, intent=infer_attachment_intent(content, None))
                content += processed.inline_text
                images = processed.image_blocks
                if processed.retained_content:
                    manifest = self.engine.deps.tool_executor.retain_attachments(
                        processed.retained_content, tool_name="get_tool_output",
                        user_id=message.owner_id, channel_id=message.conversation_id)
                    content += ("\n[Full attachment contents in labelled source order.]\n"
                                + canonical_json(manifest))
            result = (await self.engine.runner.run_resumed(st) if st is not None
                      else await self.engine.run(message, content=content, image_blocks=images))
            # A returned result owns its existing guarded reply. Publication or
            # accounting failures must not add a contradictory execution notice.
            failure_notice = False
            ledger = self.engine.deps.turn_store
            status = ledger.turn_status_sync(message.turn_key) if ledger is not None else None
            outcome = ("suspended" if status == TurnStatus.SUSPENDED else
                       "cancelled" if status == TurnStatus.TERMINAL_CANCELLED else
                       "failed" if result[2] else "completed")
            # Publication and session-cache failure cannot erase a completed
            # effect or reopen its execution identity.
            self._finish(message, outcome)
            text, _sent, is_error, _tools, _handoff = result
            text = scrub_response_secrets(text)
            from .delivery import RequestContext
            context = RequestContext(message.conversation_id, message.request_id,
                                     message.generation,
                                     message.owner_id, message.message_id)
            guarded = self.delivery.guarded_reply(context, text)
            await self.delivery.send_reply(context, text, guarded=guarded)
            await self.engine.record_result(message, result)
        except asyncio.CancelledError:
            self._finish(message, "interrupted")
            raise
        except Exception as error:
            # D17: Odin explains pre-reply failures in the conversation. This is
            # typed core provenance, never an invented model reply or an effect retry.
            self._finish(message, "failed")
            from ..odin_log import get_logger
            get_logger("desktop.requests").error("Admitted request failed: %s",
                                                 type(error).__name__)
            if failure_notice:
                text = ("No LLM provider available. Please try again later."
                        if isinstance(error, NoLLMProviderError) else
                        f"Tool execution timed out: {format_user_facing_error(error)}"
                        if isinstance(error, TimeoutError) else
                        f"Tool execution failed: {format_user_facing_error(error)}")
                try:
                    await self.delivery.send(message, text)
                except Exception as publication_error:
                    # Keep the terminal request fenced even if its notice cannot
                    # be stored or published. Never retry the runner to repair it.
                    get_logger("desktop.requests").error(
                        "Request failure notice could not be published: %s",
                        type(publication_error).__name__)
        finally:
            try:
                self._fence_settled_context(message)
            finally:
                _execution.reset(token)

    def _finish(self, message, outcome):
        with self.store.transaction() as db:
            row = self.binding(message.conversation_id, message.request_id, message.generation)
            if row is None:
                return
            if row["state"] not in ("running", "stop_requested"):
                return
            unknown = json.loads(row["unknown_effects"])
            ledger = self.engine.deps.turn_store
            # A dead store may refuse before obtaining a ledger lease. There
            # are no admitted effects to project in that case. If a lease did
            # exist, preserve fail-closed projection instead of losing unknowns.
            if ledger is not None and (ledger.available or row["ledger_generation"] is not None):
                # This projection is complete for the bound request, unlike
                # the deliberately bounded diagnostics observer. Terminal
                # unknown effects cannot disappear behind its page limit.
                with ledger._write_lock:
                    connection = ledger._require()
                    operations = connection.execute("""SELECT tool_call_id,tool_name,state,
                        effect_class,generation_seq FROM operations
                        WHERE source=? AND channel_id=? AND message_id=?
                        AND state IN ('OUTCOME_UNKNOWN','MANUAL_RESOLUTION_REQUIRED',
                                      'RUNNING','PREPARED')
                        ORDER BY generation_seq,tool_call_id""",
                        ("conversation", message.conversation_id, message.request_id)).fetchall()
                    from ..tools.effect_classifier import ToolEffectClass
                    columns = ("tool_call_id", "tool_name", "state", "effect_class",
                               "generation_seq")
                    unknown = [dict(zip(columns, op, strict=True)) for op in operations
                               if op[3] != ToolEffectClass.EFFECT_FREE_OBSERVATION]
            db.execute("UPDATE desktop_requests SET state=?,ended_at=?,unknown_effects=? "
                       "WHERE request_id=? AND generation=?",
                       (outcome, now(), canonical_json(unknown), message.request_id,
                        message.generation))
            self.events.append("request." + outcome, {"kind": "request", "id": message.request_id},
                               {"conversation_id": message.conversation_id,
                                "request_id": message.request_id, "generation": message.generation,
                                "unknown_effects": len(unknown)})

    async def launch_auto_resume(self, st, original, preserved):
        """Promote a rebuilt checkpoint under the manager's channel lock.

        The caller retains the lease unless this returns True. Admission is
        synchronous through scheduling, so a queued newer input cannot slip
        between the busy check and generation transition.
        """
        self.assert_preserved_request(original)
        cid, rid = original.conversation_id, original.request_id
        with self.store.transaction() as db:
            row = self.binding(cid, rid, original.generation)
            busy = db.execute("""SELECT 1 FROM desktop_requests WHERE conversation_id=?
                AND state IN ('queued','running','stop_requested') LIMIT 1""", (cid,)).fetchone()
            if (self._closed or not row or row["state"] != "suspended" or busy
                    or not self.context_is_current(original)
                    or row["ledger_generation"] != preserved["generation"]
                    or json.loads(row["unknown_effects"])):
                return False
            generation = row["generation"] + 1
            db.execute("""UPDATE desktop_requests SET generation=?,state='running',
                started_at=?,ended_at=NULL,ledger_generation=?
                WHERE request_id=? AND generation=?""",
                       (generation, now(), st.durability.lease.generation, rid, row["generation"]))
            self.events.append("request.started", {"kind": "request", "id": rid},
                               {"conversation_id": cid, "request_id": rid,
                                "generation": generation})
        try:
            await self.launch_resume(self.get_request(rid), st)
        except BaseException:
            # The manager releases the acquired lease. Preserve the admitted
            # generation for explicit recovery, never a running phantom.
            self._finish(self.fetch_request(cid, rid), "interrupted")
            raise
        return True

    async def launch_resume(self, row, st):
        message = self.fetch_request(row["conversation_id"], row["request_id"])
        st.message = message
        async def resumed():
            owner = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
            token = self.permissions.set_request_owner(owner)
            try:
                async with self.engine.deps.channel_state.lock_for(message.conversation_id):
                    await self._execute(message, st)
            finally:
                self.permissions.reset_request_owner(token)
                await self.after_commit()
        task = asyncio.create_task(resumed(), name=f"desktop-resume:{message.request_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self):
        self._closed = True
        for row in self.store.connection.execute(
                "SELECT DISTINCT conversation_id FROM desktop_requests "
                "WHERE state IN ('running','stop_requested')"):
            cid = row[0]
            self.engine.deps.channel_state.request_stop(cid)
        tasks = list(self._tasks)
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=5)
            for task in pending:
                task.cancel()
            if pending:
                _done, pending = await asyncio.wait(pending, timeout=5)
            if pending:
                # A task can suppress cancellation while an effect settles.
                # Keep storage and profile ownership; teardown is not complete.
                raise RuntimeError("Request shutdown incomplete: execution is still settling")

    def delete_conversation(self, conversation_id):
        """Erase request content while preserving admitted identity tombstones."""
        self.store.connection.execute("UPDATE desktop_requests SET text='',attachments='[]' "
                                      "WHERE conversation_id=?", (conversation_id,))
