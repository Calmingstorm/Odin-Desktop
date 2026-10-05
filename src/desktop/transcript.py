"""Committed visible messages, immutable branch context and coherent snapshots."""
from __future__ import annotations

import json
from uuid import uuid4

from .commands import JournalStore, canonical_json
from .conversations import (
    ConversationError,
    ConversationStore,
    domain_transaction,
    now,
    require_string,
)
from .events import EventJournal


class TranscriptStore:
    def __init__(self, store: JournalStore, events: EventJournal,
                 conversations: ConversationStore, *, state_provider=None) -> None:
        if conversations.store is not store or events.store is not store:
            raise ValueError("Transcript, conversation and event journals must share storage")
        self.store, self.events, self.conversations = store, events, conversations
        if state_provider is not None:
            conversations.state_provider = state_provider
        conversations.transcript = self

    @staticmethod
    def public(message: dict) -> dict:
        return json.loads(canonical_json({key: value for key, value in message.items()
                                         if key not in
                                         ("conversation_id", "position", "context_reset")}))

    def position(self, conversation_id: str, message_id: str) -> int:
        require_string(message_id, "message_id")
        row = self.store.connection.execute("""SELECT position FROM desktop_messages
            WHERE conversation_id=? AND message_id=?""", (conversation_id, message_id)).fetchone()
        if row is None:
            raise ConversationError("not_found", "Message not found in this conversation")
        return row[0]

    def cutoff(self, conversation_id: str, message_id: str | None = None) -> tuple[int, str | None]:
        with domain_transaction(self.store) as db:
            self.conversations.get(conversation_id)
            if message_id is not None:
                return self.position(conversation_id, message_id), message_id
            row = db.execute("""SELECT position,message_id FROM desktop_messages
                WHERE conversation_id=? ORDER BY position DESC LIMIT 1""",
                             (conversation_id,)).fetchone()
            return (row[0], row[1]) if row else (0, None)

    def commit(self, conversation_id: str, role: str, text: str, **metadata) -> dict:
        if role not in ("user", "assistant", "notice") or type(text) is not str:
            raise ConversationError("bad_request", "Invalid committed message")
        allowed = {"id", "created_at", "request_id", "client_submission_id",
                   "attachments", "artifacts", "context_reset"}
        if set(metadata) - allowed:
            raise ConversationError("bad_request", "Invalid message metadata")
        for key in ("request_id", "client_submission_id"):
            if key in metadata:
                require_string(metadata[key], key)
        for key in ("attachments", "artifacts"):
            if key in metadata and (type(metadata[key]) is not list or
                                    any(type(item) is not dict for item in metadata[key])):
                raise ConversationError("bad_request", "Invalid message metadata")
        if "context_reset" in metadata and (
                role != "notice" or type(metadata["context_reset"]) is not bool):
            raise ConversationError("bad_request", "Invalid context reset notice")
        message = {"id": metadata.get("id", "m_" + uuid4().hex), "role": role, "text": text,
                   "created_at": metadata.get("created_at", now()),
                   **{key: value for key, value in metadata.items()
                      if key not in ("id", "created_at")}}
        require_string(message["id"], "id")
        require_string(message["created_at"], "created_at")
        with domain_transaction(self.store) as db:
            conversation = self.conversations.get(conversation_id)
            existing = db.execute(
                "SELECT conversation_id,record FROM desktop_messages WHERE message_id=?",
                (message["id"],)).fetchone()
            if existing is not None and "created_at" not in metadata:
                message["created_at"] = json.loads(existing[1])["created_at"]
            encoded = canonical_json(message)
            if existing is not None:
                if existing[0] != conversation_id or existing[1] != encoded:
                    raise ConversationError("id_conflict", "Message ID is already bound")
                return self.public(json.loads(existing[1]))
            position = db.execute(
                "SELECT COALESCE(MAX(position),0)+1 FROM desktop_messages").fetchone()[0]
            db.execute("INSERT INTO desktop_messages VALUES (?,?,?,?,?,?,?)",
                       (position, message["id"], conversation_id, role, text,
                        message["created_at"], encoded))
            self.events.append("message.committed", {"kind": "message", "id": message["id"]},
                               {"conversation_id": conversation_id,
                                "message": self.public(message)})
            if role == "assistant":
                conversation["unread"] += 1
            self.conversations._changed(conversation)
            return self.public(json.loads(encoded))

    @staticmethod
    def _limit(limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ConversationError("bad_request", "limit must be between 1 and 100")

    def list(self, conversation_id: str, before: str | None = None, limit: int = 100) -> dict:
        self._limit(limit)
        with domain_transaction(self.store) as db:
            self.conversations.get(conversation_id)
            cutoff = (self.position(conversation_id, before)
                      if before is not None else 9223372036854775807)
            rows = db.execute("""SELECT record FROM desktop_messages
                WHERE conversation_id=? AND position<? ORDER BY position DESC LIMIT ?""",
                              (conversation_id, cutoff, limit + 1)).fetchall()
            return {"items": [self.public(json.loads(row[0])) for row in reversed(rows[:limit])],
                    "has_more": len(rows) > limit, "watermark": self.events.high}

    def all_messages(self, conversation_id: str | None = None) -> list[dict]:
        with domain_transaction(self.store) as db:
            if conversation_id is not None:
                self.conversations.get(conversation_id)
            rows = db.execute("SELECT conversation_id,record FROM desktop_messages "
                              + ("WHERE conversation_id=? " if conversation_id is not None else "")
                              + "ORDER BY position",
                              (conversation_id,) if conversation_id is not None else ())
            return [{"conversation_id": row[0], **self.public(json.loads(row[1]))} for row in rows]

    def model_context(self, conversation_id: str, *,
                      through_position: int | None = None) -> list[dict]:
        with domain_transaction(self.store) as db:
            row = self.conversations._row(conversation_id)
            context_start = row["context_position"]
            if through_position is not None:
                context_start = db.execute("""SELECT COALESCE(MAX(position),0) FROM desktop_messages
                    WHERE conversation_id=? AND position<=? AND role='notice'
                    AND json_extract(record,'$.context_reset')=1""",
                                           (conversation_id, through_position)).fetchone()[0]
            inherited = ([json.loads(item[0]) for item in db.execute(
                "SELECT record FROM desktop_inheritance WHERE conversation_id=? ORDER BY ordinal",
                (conversation_id,))] if context_start == 0 else [])
            cutoff = through_position if through_position is not None else 9223372036854775807
            rows = db.execute("""SELECT record FROM desktop_messages WHERE conversation_id=?
                AND position>? AND position<=?
                AND role IN ('user','assistant') ORDER BY position""",
                              (conversation_id, context_start, cutoff))
            return inherited + [json.loads(item[0]) for item in rows]

    def read_conversation(self, conversation_id: str, *, limit: int = 100) -> list[dict]:
        """Internal read; the model adapter binds the authenticated current ID."""
        return self.list(conversation_id, limit=limit)["items"]

    def snapshot(self, conversation_id: str, limit: int = 100) -> dict:
        with domain_transaction(self.store):
            conversation = self.conversations.get(conversation_id)
            page = self.list(conversation_id, limit=limit)
            state = self.conversations.state(conversation_id)
            running, queued = state["running"], state["queued"]
            shown = {item["request_id"] for item in page["items"] if item.get("request_id")}
            bound = {item["request_id"] for item in queued}
            if running:
                shown.add(running["request_id"])
                bound.add(running["request_id"])
            return {"watermark": self.events.high, "conversation": conversation,
                    "messages": {"items": page["items"], "has_more": page["has_more"]},
                    "running": running, "queued": queued, "recent": state["recent"][-20:],
                    "unresolved": state["unresolved"],
                    "tools": {key: value for key, value in sorted(state["tools"].items())
                              if key in shown},
                    "controls": [item for item in state["controls"] if item["request_id"] in bound]}

    def handle(self, method: str, params: dict) -> dict:
        if type(params) is not dict or "conversation_id" not in params:
            raise ConversationError("bad_request", "Missing conversation_id")
        if method == "messages.list":
            if "limit" not in params:
                raise ConversationError("bad_request", "Missing limit")
            return self.list(params["conversation_id"], params.get("before"), params["limit"])
        if method == "conversation.snapshot":
            return self.snapshot(params["conversation_id"], params.get("limit", 100))
        raise ConversationError("bad_request", "Unknown transcript method")
