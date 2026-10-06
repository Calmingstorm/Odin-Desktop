"""Conversation domain state shares the command/event journal's transactions."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from .commands import JournalStore, canonical_json, response_error
from .events import EventJournal

DOMAIN_SCHEMA = {
    "desktop_conversations": {"id", "record", "context_position", "read_position"},
    "desktop_messages": {"position", "message_id", "conversation_id", "role", "text",
                         "created_at", "record"},
    "desktop_inheritance": {"conversation_id", "ordinal", "record"},
    "desktop_request_context": {"request_id", "conversation_id", "context_position"},
}


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ConversationError(ValueError):
    def __init__(self, code: str, message: str, disposition: str = "rejected") -> None:
        super().__init__(message)
        self.code, self.message, self.disposition = code, message, disposition

    def response(self) -> dict:
        return response_error(self.code, self.message, self.disposition)


def require_string(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ConversationError("bad_request", f"Invalid or missing parameter: {name}")
    return value


@contextmanager
def domain_transaction(store: JournalStore):
    """Roll back refusals without poisoning a final command receipt transaction."""
    refused = None
    with store.transaction() as db:
        savepoint = "domain_" + uuid4().hex
        db.execute("SAVEPOINT " + savepoint)
        try:
            yield db
        except ConversationError as error:
            db.execute("ROLLBACK TO " + savepoint)
            refused = error
        finally:
            db.execute("RELEASE " + savepoint)
    if refused is not None:
        raise refused


class ConversationStore:
    """Request-state providers and deletion hooks execute inside the shared transaction.

    Providers expose snapshot(id) with running, queued, recent, unresolved, tools,
    controls. Hooks may update SQLite only; external file cleanup is post-commit.
    This is a storage seam, not a replacement request runner.
    """
    def __init__(self, store: JournalStore, events: EventJournal, *,
                 state_provider=None, delete_hooks=()) -> None:
        if events.store is not store:
            raise ValueError("Conversation and event journals must share storage")
        self.store, self.events = store, events
        self.state_provider = state_provider
        self.delete_hooks = tuple(delete_hooks)
        self.transcript = None
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_conversations (
                id TEXT PRIMARY KEY, record TEXT NOT NULL,
                context_position INTEGER NOT NULL DEFAULT 0,
                read_position INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_messages (
                position INTEGER PRIMARY KEY, message_id TEXT NOT NULL UNIQUE,
                conversation_id TEXT NOT NULL REFERENCES desktop_conversations(id)
                    ON DELETE CASCADE,
                role TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
                record TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_inheritance (
                conversation_id TEXT NOT NULL REFERENCES desktop_conversations(id)
                    ON DELETE CASCADE,
                ordinal INTEGER NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(conversation_id, ordinal))""")
            db.execute("CREATE INDEX IF NOT EXISTS desktop_messages_conversation "
                       "ON desktop_messages(conversation_id, position)")
            # Private execution lineage, never public message metadata.
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_request_context (
                request_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL
                    REFERENCES desktop_conversations(id) ON DELETE CASCADE,
                context_position INTEGER NOT NULL)""")

    def _row(self, id: str):
        require_string(id, "id")
        row = self.store.connection.execute(
            "SELECT * FROM desktop_conversations WHERE id=?", (id,)).fetchone()
        if row is None:
            raise ConversationError("not_found", "Conversation not found")
        return row

    def get(self, id: str) -> dict:
        with domain_transaction(self.store):
            return json.loads(self._row(id)["record"])

    def _write(self, record: dict) -> None:
        self.store.connection.execute("UPDATE desktop_conversations SET record=? WHERE id=?",
                                      (canonical_json(record), record["id"]))

    def _changed(self, record: dict) -> None:
        record["rev"] += 1
        record["updated_at"] = now()
        self._write(record)
        self.events.append("conversation.updated",
                           {"kind": "conversation", "id": record["id"], "rev": record["rev"]},
                           {"conversation": record})

    def state(self, id: str) -> dict:
        empty = {"running": None, "queued": [], "recent": [], "unresolved": [],
                 "tools": {}, "controls": []}
        if self.state_provider is None:
            return empty
        provider = self.state_provider
        state = provider.snapshot(id) if hasattr(provider, "snapshot") else provider(id)
        if type(state) is not dict or any(key not in state for key in empty):
            raise ValueError("Request state provider must supply the complete snapshot projection")
        return json.loads(canonical_json(state))

    @staticmethod
    def activity(state: dict) -> dict:
        def binding(value):
            return {key: value[key] for key in ("request_id", "generation")}
        return {"running": binding(state["running"]) if state["running"] else None,
                "queued": [binding(item) for item in state["queued"]]}

    def list(self) -> dict:
        with domain_transaction(self.store) as db:
            records = [json.loads(row[0]) for row in db.execute(
                "SELECT record FROM desktop_conversations")]
            records.sort(key=lambda item: (item["updated_at"], item["id"]))
            return {"items": [{**item, "activity": self.activity(self.state(item["id"]))}
                              for item in records], "watermark": self.events.high}

    def create(self, title: str = "Chat", parent_id: str | None = None,
               from_message_id: str | None = None) -> dict:
        if type(title) is not str:
            raise ConversationError("bad_request", "Invalid parameter: title")
        if parent_id is None and from_message_id is not None:
            raise ConversationError("bad_request", "from_message_id requires parent_id")
        with domain_transaction(self.store) as db:
            inherited, origin = [], None
            if parent_id is not None:
                parent = self.get(parent_id)
                if self.transcript is None:
                    raise RuntimeError("Transcript service is not connected")
                cutoff = self.transcript.cutoff(parent_id, from_message_id)
                inherited = self.transcript.model_context(parent_id, through_position=cutoff[0])
                origin = {"conversation_id": parent_id, "message_id": cutoff[1],
                          "title": parent["title"]}
            record = {"id": "c_" + uuid4().hex, "title": (title or "Chat")[:200],
                      "rev": 1, "parent_id": parent_id, "inherited_from": origin,
                      "updated_at": now(), "unread": 0, "archived": False}
            db.execute("INSERT INTO desktop_conversations(id,record) VALUES (?,?)",
                       (record["id"], canonical_json(record)))
            for ordinal, message in enumerate(inherited):
                frozen = {key: message[key] for key in
                          ("id", "role", "text", "created_at", "attachments", "artifacts")
                          if key in message}
                frozen["inherited_from"] = message.get("inherited_from", {
                    "conversation_id": parent_id, "message_id": message["id"]})
                db.execute("INSERT INTO desktop_inheritance VALUES (?,?,?)",
                           (record["id"], ordinal, canonical_json(frozen)))
            self.events.append("conversation.created",
                               {"kind": "conversation", "id": record["id"], "rev": 1},
                               {"conversation": record})
            return {"conversation": record}

    def _revision(self, id: str, expected_rev: int) -> dict:
        if type(expected_rev) is not int or expected_rev < 1:
            raise ConversationError("bad_request", "Invalid or missing parameter: expected_rev")
        record = self.get(id)
        if expected_rev != record["rev"]:
            raise ConversationError("stale_binding", "Conversation changed since it was read",
                                    "stale_binding")
        return record

    def update(self, id: str, expected_rev: int, **changes) -> dict:
        if "title" in changes and type(changes["title"]) is not str:
            raise ConversationError("bad_request", "Invalid parameter: title")
        if "archived" in changes and type(changes["archived"]) is not bool:
            raise ConversationError("bad_request", "Invalid parameter: archived")
        with domain_transaction(self.store):
            record = self._revision(id, expected_rev)
            if "title" in changes:
                record["title"] = changes["title"][:200]
            if "archived" in changes:
                record["archived"] = changes["archived"]
            self._changed(record)
            return {"conversation": record}

    def _idle(self, id: str) -> None:
        state = self.state(id)
        if state["running"] or state["queued"]:
            raise ConversationError("busy", "Conversation has active work",
                                    "not_dispatched")

    def delete(self, id: str, expected_rev: int) -> dict:
        with domain_transaction(self.store) as db:
            record = self._revision(id, expected_rev)
            self._idle(id)
            for hook in self.delete_hooks:
                hook(id)
            db.execute("DELETE FROM desktop_conversations WHERE id=?", (id,))
            self.events.append("conversation.deleted",
                               {"kind": "conversation", "id": id, "rev": record["rev"] + 1},
                               {"conversation_id": id})
            return {"disposition": "deleted"}

    def reset_context(self, id: str, expected_rev: int) -> dict:
        with domain_transaction(self.store) as db:
            record = self._revision(id, expected_rev)
            if self.transcript is None:
                raise RuntimeError("Transcript service is not connected")
            notice = self.transcript.commit(
                id, "notice", "Model context reset.", context_reset=True)
            position = self.transcript.position(id, notice["id"])
            db.execute("UPDATE desktop_conversations SET context_position=? WHERE id=?",
                       (position, id))
            return {"conversation": self.get(record["id"])}

    def mark_read(self, id: str, through_message_id: str) -> dict:
        with domain_transaction(self.store) as db:
            record = self.get(id)
            if self.transcript is None:
                raise RuntimeError("Transcript service is not connected")
            position = self.transcript.position(id, through_message_id)
            read = max(position, self._row(id)["read_position"])
            db.execute("UPDATE desktop_conversations SET read_position=? WHERE id=?", (read, id))
            record["unread"] = db.execute("""SELECT COUNT(*) FROM desktop_messages
                WHERE conversation_id=? AND position>? AND role='assistant'""",
                                          (id, read)).fetchone()[0]
            self._changed(record)
            return {"conversation": record}

    def handle(self, method: str, params: dict) -> dict:
        if type(params) is not dict:
            raise ConversationError("bad_request", "Method params must be an object")
        if method == "conversations.list":
            return self.list()
        fields = {
            "conversations.create": (self.create, ("title", "parent_id", "from_message_id"), ()),
            "conversations.update": (self.update, ("id", "expected_rev", "title", "archived"),
                                     ("id", "expected_rev")),
            "conversations.delete": (self.delete, ("id", "expected_rev"), ("id", "expected_rev")),
            "conversations.reset_context": (self.reset_context, ("id", "expected_rev"),
                                            ("id", "expected_rev")),
            "conversations.mark_read": (self.mark_read, ("id", "through_message_id"),
                                        ("id", "through_message_id")),
        }
        if method not in fields:
            raise ConversationError("bad_request", "Unknown conversation method")
        call, allowed, required = fields[method]
        if any(key not in params for key in required):
            raise ConversationError("bad_request", "Missing conversation parameter")
        return call(**{key: params[key] for key in allowed if key in params})
