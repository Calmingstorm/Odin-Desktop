"""Committed local delivery for the existing guarded engine and application.

GuardedReply is minted by the trusted request adapter after the real runner
returns. This module does not duplicate its response guards. A sink receives
committed events only and must deduplicate by delivery_id; reconnect repairs
publication, never tool execution. IPC can consume the journal without a sink.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Protocol

from ..llm.secret_scrubber import scrub_output_secrets
from .commands import canonical_json
from .events import EventJournal
from .notifications import NotificationService, utc_now

DELIVERY_SCHEMA = {
    "desktop_delivery_outbox": {"delivery_id", "conversation_id", "request_id", "kind",
        "payload", "event_seq", "state", "created_at", "delivered_at"},
    "desktop_notifications": {"dedupe_key", "conversation_id", "request_id", "payload",
        "outcome", "created_at", "acked_at"},
    "desktop_staged_files": {"ordinal", "conversation_id", "request_id", "generation",
        "owner", "data", "name", "mime", "kind", "tool", "hosts"},
}


class PublicationEventJournal(EventJournal):
    """Real event journal with synchronous retention-independent frame capture."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._captures = []

    @contextmanager
    def capture(self):
        frames = []
        self._captures.append(frames)
        try:
            yield frames
        finally:
            self._captures.pop()

    def _append(self, *args, **kwargs):
        frame = super()._append(*args, **kwargs)
        for capture in self._captures:
            capture.append(frame)
        return frame


@dataclass(frozen=True, slots=True)
class RequestContext:
    conversation_id: str
    request_id: str
    generation: int
    owner_id: str
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class GuardedReply:
    context: RequestContext
    text: str
    _seal: object = field(repr=False, compare=False)


class DeliverySink(Protocol):
    async def deliver(self, delivery_id: str, frame: dict) -> bool:
        """Accept a committed frame idempotently; True means accepted, not seen."""


@dataclass(frozen=True, slots=True)
class ArtifactPost:
    """Exact bytes from an existing file producer, never a window-supplied path."""
    data: bytes
    name: str
    mime: str
    kind: str = "file"
    tool: str = "post_file"
    hosts: tuple = ()


class ArtifactPublisher:
    """Inject the existing authorized ArtifactStore and preserve its checks."""
    def __init__(self, artifacts, events):
        self.artifacts, self.events = artifacts, events

    def validate_stage(self, context: RequestContext, artifact: ArtifactPost) -> None:
        """Check producer authority now, and again on actual publication."""
        if not self.artifacts._allowed(artifact.tool, artifact.hosts, context.owner_id):
            from .artifacts import ResultReadError

            raise ResultReadError("unauthorized", "Originating result scope is not authorized")

    def __call__(self, context: RequestContext, files) -> list[dict]:
        if self.artifacts.store is not self.events.store:
            raise ValueError("Artifact publication must share the event transaction")
        descriptors = []
        for file in files:
            if not isinstance(file, ArtifactPost):
                # Existing transport file producers supply an already selected
                # binary stream. Snapshot that object, not a name that could now
                # resolve to different bytes, and do not consume/close it.
                stream = getattr(file, "fp", None)
                name = getattr(file, "filename", None)
                if not isinstance(name, str) or not name or not hasattr(stream, "read"):
                    raise TypeError("Artifact delivery requires producer-owned bytes or stream")
                position = stream.tell()
                try:
                    data = stream.read()
                finally:
                    stream.seek(position)
                if type(data) is not bytes:
                    raise TypeError("Artifact streams must be binary")
                mime = getattr(file, "mime", None) or mimetypes.guess_type(name)[0]
                mime = mime or "application/octet-stream"
                file = ArtifactPost(data, name, mime,
                    "image" if mime.startswith("image/") else "file",
                    getattr(file, "tool", "post_file"), tuple(getattr(file, "hosts", ())))
            descriptor = self.artifacts.publish(file.data, owner=context.owner_id,
                conversation_id=context.conversation_id, request_id=context.request_id,
                name=file.name, mime=file.mime, kind=file.kind, tool=file.tool, hosts=file.hosts)
            self.events.append("artifact.published", {"kind": "artifact", "id": descriptor["ref"]},
                {"conversation_id": context.conversation_id, "request_id": context.request_id,
                 "artifact": descriptor})
            descriptors.append(descriptor)
        return descriptors


class DurableDelivery:
    def __init__(self, store, events, *, transcript_commit, notifications=None,
                 sink: DeliverySink | None = None, artifact_converter=None,
                 tool_details=None, assert_context=None) -> None:
        self.store, self.events = store, events
        self.transcript_commit = transcript_commit
        self.notifications = notifications or NotificationService(store, events)
        self.sink = sink
        self.artifact_converter = artifact_converter
        self.tool_details = tool_details
        self.assert_context = assert_context
        self._seal = object()
        self._drain_lock = asyncio.Lock()
        self.active_tasks = 0
        if events.store is not store:
            raise ValueError("Delivery and events must share a durable store")
        with store.transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_delivery_outbox (
                delivery_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                request_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL,
                event_seq INTEGER NOT NULL, state TEXT NOT NULL,
                created_at TEXT NOT NULL, delivered_at TEXT)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_staged_files (
                ordinal INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL,
                request_id TEXT NOT NULL, generation INTEGER NOT NULL, owner TEXT NOT NULL,
                data BLOB NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL,
                kind TEXT NOT NULL, tool TEXT NOT NULL, hosts TEXT NOT NULL)""")
            # Capture every domain event before retention prunes it, inside its
            # originating SQLite transaction, including worker lifecycle events.
            connection.execute("""CREATE TRIGGER IF NOT EXISTS desktop_event_outbox
                AFTER INSERT ON journal_events BEGIN
                INSERT OR IGNORE INTO desktop_delivery_outbox
                (delivery_id,conversation_id,request_id,kind,payload,event_seq,state,created_at)
                VALUES ('event:' || NEW.seq,
                    COALESCE(json_extract(NEW.frame,'$.payload.conversation_id'),
                             json_extract(NEW.frame,'$.payload.conversation.id'), ''),
                    COALESCE(json_extract(NEW.frame,'$.payload.request_id'),
                             json_extract(NEW.frame,'$.payload.message.request_id')),
                    json_extract(NEW.frame,'$.type'),NEW.frame,NEW.seq,'pending',
                    json_extract(NEW.frame,'$.at'));
                END""")

    def _context(self, destination) -> RequestContext:
        if isinstance(destination, LocalDestination):
            if destination.delivery is not self:
                raise PermissionError("Foreign delivery destination")
            destination = destination.context
        if not isinstance(destination, RequestContext):
            destination = getattr(destination, "request_context", None)
        if (not isinstance(destination, RequestContext)
                or any(not isinstance(value, str) or not value for value in
                       (destination.conversation_id, destination.request_id, destination.owner_id))
                or type(destination.generation) is not int or destination.generation < 1):
            raise PermissionError("Delivery requires an admitted request context")
        if self.assert_context is not None:
            self.assert_context(destination)
        return destination

    def guarded_reply(self, context: RequestContext, text: str) -> GuardedReply:
        """Trusted adapter seam, never a model-visible alternative guard."""
        return GuardedReply(self._context(context), text, self._seal)

    async def send_reply(self, message, text: str, *, guarded: GuardedReply | None = None,
                         files=None, reference=None, consume_staged=True) -> dict | None:
        context = self._context(message)
        if (not isinstance(guarded, GuardedReply) or guarded._seal is not self._seal
                or guarded.context != context or guarded.text != text):
            raise PermissionError("Only a guarded final reply may be committed")
        return await self._send(context, text, "assistant", files, notify=True,
                                consume_staged=consume_staged)

    async def send(self, channel, text: str = "", *, files=None, file=None,
                   reference=None) -> dict | None:
        """Sanctioned notices or tool artifact posts, never model response previews."""
        if file is not None:
            if files is not None:
                raise ValueError("Specify file or files, not both")
            files = [file]
        return await self._send(self._context(channel), text, "notice", files, notify=False)

    async def send_chunked(self, message, text: str, *, guarded=None) -> dict | None:
        # No Discord length constraint: keep the exact guarded transcript reply.
        return await self.send_reply(message, text, guarded=guarded)

    def stage_file(self, destination, artifact: ArtifactPost) -> None:
        """Retain producer bytes for this generation's guarded final reply.

        Staging is not publication. Conversion, authorization and consumption
        occur atomically with the final transcript commit, never on a notice.
        """
        context = self._context(destination)
        if not isinstance(artifact, ArtifactPost) or type(artifact.data) is not bytes:
            raise TypeError("Staging requires producer-owned artifact bytes")
        if (artifact.kind not in {"image", "file", "report"}
                or not all(type(value) is str and value
                           for value in (artifact.name, artifact.mime, artifact.tool))):
            raise ValueError("Expected artifact metadata")
        if self.artifact_converter is None:
            raise RuntimeError("Artifact publication unavailable; do not replay the tool")
        validate = getattr(self.artifact_converter, "validate_stage", None)
        if validate is None:
            raise RuntimeError("Artifact staging authorization unavailable")
        validate(context, artifact)
        if self.store.connection.execute(
                "SELECT 1 FROM desktop_delivery_outbox WHERE delivery_id=?",
                (self._reply_key(context),)).fetchone() is not None:
            raise PermissionError("The final reply for this generation is already committed")
        with self.store.transaction() as db:
            db.execute("""INSERT INTO desktop_staged_files
                (conversation_id,request_id,generation,owner,data,name,mime,kind,tool,hosts)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                context.conversation_id, context.request_id, context.generation, context.owner_id,
                artifact.data, scrub_output_secrets(artifact.name), artifact.mime, artifact.kind,
                artifact.tool, canonical_json(deepcopy(list(artifact.hosts)))))

    def _staged_files(self, context):
        return [ArtifactPost(row["data"], row["name"], row["mime"], row["kind"], row["tool"],
                             tuple(json.loads(row["hosts"])))
                for row in self.store.connection.execute("""SELECT * FROM desktop_staged_files
                    WHERE conversation_id=? AND request_id=? AND generation<=? AND owner=?
                    ORDER BY ordinal""", (context.conversation_id, context.request_id,
                                          context.generation, context.owner_id))]

    async def send_with_retry(self, message, text: str, as_reply=True, files=None,
                              *, guarded=None) -> dict | None:
        if guarded is not None:
            return await self.send_reply(message, text, guarded=guarded, files=files)
        return await self.send(message, text, files=files)

    async def _send(self, context, text, role, files, *, notify, consume_staged=True):
        if not isinstance(text, str):
            raise ValueError("Expected reply text")
        if not text.strip() and not files and role != "assistant":
            return None
        with self.store.transaction(), self._capture() as frames:
            if role == "assistant":
                previous = self.store.connection.execute(
                    "SELECT payload FROM desktop_delivery_outbox WHERE delivery_id=?",
                    (self._reply_key(context),)).fetchone()
                if previous is not None:
                    message = json.loads(previous[0])["payload"]["message"]
                    if message["text"] != scrub_output_secrets(text):
                        raise ValueError("Guarded reply identity conflict")
                    return message
            artifacts = []
            if role == "assistant" and consume_staged:
                files = list(files or ()) + self._staged_files(context)
            if not text.strip() and not files:
                return None
            if files:
                if self.artifact_converter is None:
                    raise RuntimeError("Artifact publication unavailable; do not replay the tool")
                artifacts = self.artifact_converter(context, files)
                if not isinstance(artifacts, list):
                    raise TypeError("Artifact publication must return committed descriptors")
            message = self.transcript_commit(conversation_id=context.conversation_id,
                role=role, text=scrub_output_secrets(text), request_id=context.request_id,
                artifacts=artifacts)
            if role == "assistant" and consume_staged:
                self.store.connection.execute("""DELETE FROM desktop_staged_files
                    WHERE conversation_id=? AND request_id=? AND generation<=? AND owner=?""",
                    (context.conversation_id, context.request_id,
                     context.generation, context.owner_id))
            if notify:
                self.notifications.intent(conversation_id=context.conversation_id,
                    message_id=message["id"], category="reply", preview=message["text"][:240],
                    dedupe_key=f"reply:{message['id']}", request_id=context.request_id)
            for frame in frames:
                self._enqueue(context, frame)
        await self.drain()
        return message

    @contextmanager
    def _capture(self):
        capture = getattr(self.events, "capture", None)
        if capture is None:
            raise RuntimeError("Delivery requires a publication-capturing event journal")
        with capture() as frames:
            yield frames

    def delete_conversation(self, conversation_id: str) -> None:
        """Join deletion; never resurrect private content through recovery."""
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM desktop_delivery_outbox WHERE conversation_id=?",
                               (conversation_id,))
            connection.execute("DELETE FROM desktop_notifications WHERE conversation_id=?",
                               (conversation_id,))
            connection.execute("DELETE FROM desktop_staged_files WHERE conversation_id=?",
                               (conversation_id,))

    def _enqueue(self, context, frame):
        delivery_id = f"event:{frame['seq']}"
        if (frame["type"] == "message.committed"
                and frame["payload"]["message"]["role"] == "assistant"):
            delivery_id = self._reply_key(context)
            self.store.connection.execute("""UPDATE desktop_delivery_outbox
                SET delivery_id=?,request_id=? WHERE delivery_id=?""",
                (delivery_id, context.request_id, f"event:{frame['seq']}"))
        self._enqueue_bound(context.conversation_id, context.request_id, frame, delivery_id)

    def _enqueue_bound(self, conversation_id, request_id, frame, delivery_id):
        self.store.connection.execute("""INSERT OR IGNORE INTO desktop_delivery_outbox
            (delivery_id,conversation_id,request_id,kind,payload,event_seq,state,created_at)
            VALUES (?,?,?,?,?,?,?,?)""", (delivery_id, conversation_id,
                request_id, frame["type"], canonical_json(frame), frame["seq"],
                "pending", utc_now()))
        self.store.connection.execute("""UPDATE desktop_delivery_outbox
            SET conversation_id=?,request_id=? WHERE delivery_id=?""",
            (conversation_id, request_id, delivery_id))

    @staticmethod
    def _reply_key(context):
        return f"reply:{context.request_id}:{context.generation}"

    def tool_started(self, context, *, invocation_id, tool, summary, target=None) -> dict:
        context = self._context(context)
        payload = {"conversation_id": context.conversation_id, "request_id": context.request_id,
                   "invocation_id": invocation_id, "tool": tool,
                   "summary": scrub_output_secrets(summary)}
        if target is not None:
            payload["target"] = scrub_output_secrets(target)
        return self._tool_event(context, "tool.started", invocation_id, payload)

    def tool_settled(self, context, *, invocation_id, outcome, duration_ms,
                     exit_code=None, evidence_ref=None) -> dict:
        context = self._context(context)
        if outcome not in ("success", "failure", "unknown"):
            raise ValueError("Invalid tool settlement")
        if type(duration_ms) is not int or duration_ms < 0:
            raise ValueError("Expected a nonnegative measured duration")
        if exit_code is not None and type(exit_code) is not int:
            raise ValueError("Expected an integer exit code")
        payload = {"conversation_id": context.conversation_id, "request_id": context.request_id,
                   "invocation_id": invocation_id, "outcome": outcome, "duration_ms": duration_ms}
        if exit_code is not None:
            payload["exit_code"] = exit_code
        if evidence_ref is not None:
            payload["evidence_ref"] = evidence_ref
        return self._tool_event(context, "tool.settled", invocation_id, payload)

    def _tool_event(self, context, kind, invocation_id, payload):
        with self.store.transaction():
            rows = self.store.connection.execute("""SELECT payload FROM desktop_delivery_outbox
                WHERE request_id=? AND kind=?""", (context.request_id, kind))
            for row in rows:
                previous = json.loads(row[0])
                if previous["payload"]["invocation_id"] == invocation_id:
                    if previous["payload"] != payload:
                        raise ValueError("Tool event identity conflict")
                    return previous
            frame = self.events.append(kind, {"kind": "tool", "id": invocation_id}, payload)
            self._enqueue(context, frame)
        return frame

    async def recover(self) -> int:
        """Repair publications without replaying requests or tool effects."""
        with self.store.transaction(), self._capture() as frames:
            self.notifications.recover()
            for frame in frames:
                payload = frame["payload"]
                row = self.store.connection.execute(
                    "SELECT request_id FROM desktop_notifications WHERE dedupe_key=?",
                    (payload["dedupe_key"],)).fetchone()
                self._enqueue_bound(payload["conversation_id"], row[0], frame,
                                    f"event:{frame['seq']}")
        return await self.drain()

    async def drain(self) -> int:
        """Failed/unknown sink sends stay repairable; only idempotent sinks qualify."""
        if self.store._depth or self.sink is None:
            # Never transport inside an outer transaction. Its owner drains after commit.
            return 0
        count = 0
        async with self._drain_lock:
            while True:
                with self.store.transaction() as connection:
                    row = connection.execute("""SELECT delivery_id,payload
                        FROM desktop_delivery_outbox
                        WHERE state='pending' ORDER BY event_seq LIMIT 1""").fetchone()
                if row is None:
                    break
                try:
                    accepted = await self.sink.deliver(row[0], json.loads(row[1]))
                except Exception:
                    break
                if accepted is not True:
                    break
                with self.store.transaction() as connection:
                    connection.execute("""UPDATE desktop_delivery_outbox SET state='delivered',
                        delivered_at=? WHERE delivery_id=?""", (utc_now(), row[0]))
                count += 1
        return count

    async def set_status(self, text=None, task_start=False, task_end=False):
        # Runner presence is not a reply and never leaks candidate model text.
        if task_start:
            self.active_tasks += 1
        if task_end:
            self.active_tasks = max(0, self.active_tasks - 1)


@dataclass(frozen=True, slots=True)
class LocalDestination:
    context: RequestContext
    delivery: DurableDelivery

    @property
    def id(self):
        return self.context.conversation_id

    @property
    def request_context(self):
        return self.context

    async def send(self, text="", **kwargs):
        return await self.delivery.send(self, text, **kwargs)

    async def send_reply(self, text, **kwargs):
        return await self.delivery.send_reply(self, text, **kwargs)


ResponseDelivery = DurableDelivery
DeliveryService = DurableDelivery
