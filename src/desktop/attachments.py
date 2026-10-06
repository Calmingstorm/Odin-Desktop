"""Durable scoped uploads and the existing Odin attachment-processing seam.

The transport owns command receipts, except chunks, which are offset-idempotent.
All bytes live in the profile JournalStore, never in a window-supplied path.
Submission adoption joins the conversation/message/receipt transaction. Processing
and knowledge ingestion are deliberately not part of that synchronous transaction.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .commands import JournalStore, canonical_json, response_error

CHUNK_BYTES = 512 * 1024
# The copied processor accepts 50 MiB archives. Do not impose the fixture's
# 25 MiB archive cap or its executable MIME deny-list on Odin (D17).
ATTACHMENT_BYTES = 50 * 1024 * 1024
ATTACHMENTS_PER_TURN = 10
UPLOAD_TTL_SECONDS = 24 * 60 * 60
ATTACHMENT_TABLES = {
    "desktop_uploads": {
        "upload_id", "client_attachment_id", "conversation_id", "binding", "name",
        "mime", "size", "received", "state", "sha256", "ref", "expires_at",
    },
    "desktop_upload_chunks": {"upload_id", "offset", "data"},
    "desktop_attachment_adoptions": {"ref", "request_id", "message_id", "add_to_knowledge"},
}


class AttachmentError(ValueError):
    def __init__(self, code: str, message: str, disposition: str = "rejected") -> None:
        super().__init__(message)
        self.code, self.message, self.disposition = code, message, disposition


@dataclass(frozen=True)
class VerifiedAttachment:
    """Invocation-owned stream accepted by src.discord.attachments unchanged."""

    filename: str
    content_type: str
    size: int
    _data: bytes

    async def read(self) -> bytes:
        return self._data


class AttachmentService:
    def __init__(
        self, store: JournalStore,
        require_conversation: Callable[[sqlite3.Connection, str], object], *,
        clock: Callable[[], float] = time.time,
        chunk_bytes: int = CHUNK_BYTES, attachment_bytes: int = ATTACHMENT_BYTES,
        attachments_per_turn: int = ATTACHMENTS_PER_TURN,
        ttl_seconds: int = UPLOAD_TTL_SECONDS,
    ) -> None:
        for value in (chunk_bytes, attachment_bytes, attachments_per_turn, ttl_seconds):
            if type(value) is not int or value <= 0:
                raise ValueError("Attachment limits must be positive integers")
        if chunk_bytes > CHUNK_BYTES:
            raise ValueError("Chunk limit must fit a bounded transport frame")
        self.store = store
        self.require_conversation = require_conversation
        self.clock = clock
        self.chunk_bytes = chunk_bytes
        self.attachment_bytes = attachment_bytes
        self.attachments_per_turn = attachments_per_turn
        self.ttl_seconds = ttl_seconds
        with store.transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_uploads (
                upload_id TEXT PRIMARY KEY, client_attachment_id TEXT NOT NULL UNIQUE,
                conversation_id TEXT NOT NULL, binding TEXT NOT NULL,
                name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
                received INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL,
                sha256 TEXT, ref TEXT UNIQUE, expires_at REAL NOT NULL)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_upload_chunks (
                upload_id TEXT NOT NULL REFERENCES desktop_uploads(upload_id),
                offset INTEGER NOT NULL, data BLOB NOT NULL,
                PRIMARY KEY(upload_id,offset))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_attachment_adoptions (
                ref TEXT NOT NULL REFERENCES desktop_uploads(ref),
                request_id TEXT NOT NULL, message_id TEXT NOT NULL,
                add_to_knowledge INTEGER NOT NULL,
                PRIMARY KEY(ref,request_id))""")

    @property
    def limits(self) -> dict:
        return {"chunk_bytes": self.chunk_bytes, "attachment_bytes": self.attachment_bytes,
                "attachments_per_turn": self.attachments_per_turn}

    @staticmethod
    def _string(params: dict, key: str) -> str:
        value = params.get(key)
        if type(value) is not str or not value:
            raise AttachmentError("bad_request", f"Invalid or missing parameter: {key}")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise AttachmentError("bad_request", f"Invalid parameter: {key}") from None
        return value

    @staticmethod
    def _integer(params: dict, key: str) -> int:
        value = params.get(key)
        if type(value) is not int or value < 0:
            raise AttachmentError("bad_request", f"Invalid or missing parameter: {key}")
        return value

    @staticmethod
    def _metadata(row: sqlite3.Row) -> dict:
        return {key: row[key] for key in ("ref", "name", "mime", "size")}

    def handle(self, method: str, params: dict) -> dict:
        """Return an envelope; caller journals mutations, but NEVER chunks.

        Refusals are caught *inside* the transaction: a bad digest must durably
        destroy upload bytes, not roll their destruction back with an exception.
        Storage failures remain exceptions, so the enclosing admission rolls back.
        """
        handlers = {"attachments.begin": self._begin, "attachments.chunk": self._chunk,
                    "attachments.commit": self._commit, "attachments.cancel": self._cancel}
        with self.store.transaction() as connection:
            try:
                if type(params) is not dict or method not in handlers:
                    raise AttachmentError("bad_request", "Invalid attachment method or parameters")
                return {"ok": True, "result": handlers[method](connection, params)}
            except AttachmentError as exc:
                return response_error(exc.code, exc.message, exc.disposition)

    def _begin(self, connection: sqlite3.Connection, params: dict) -> dict:
        client_id = self._string(params, "client_attachment_id")
        conversation_id = self._string(params, "conversation_id")
        self.require_conversation(connection, conversation_id)
        size = self._integer(params, "size")
        name, mime = params.get("name"), params.get("mime")
        if type(name) is not str or type(mime) is not str:
            raise AttachmentError("bad_request", "Invalid attachment name or MIME type")
        name = name or "file"
        mime = mime or "application/octet-stream"
        try:
            binding = canonical_json({"conversation_id": conversation_id, "size": size,
                                      "name": name, "mime": mime})
        except (ValueError, UnicodeError):
            raise AttachmentError("bad_request", "Invalid attachment name or MIME type") from None
        previous = connection.execute(
            "SELECT * FROM desktop_uploads WHERE client_attachment_id=?", (client_id,),
        ).fetchone()
        if previous is not None:
            if binding != previous["binding"]:
                raise AttachmentError("id_conflict", "Attachment identity has different parameters")
            self._active(connection, previous, allow_committed=True)
            return self._begin_result(previous)
        if size > self.attachment_bytes:
            raise AttachmentError("too_large", "Attachment exceeds the announced byte limit")
        upload_id = "u_" + uuid.uuid4().hex
        expires_at = self.clock() + self.ttl_seconds
        connection.execute("""INSERT INTO desktop_uploads
            (upload_id,client_attachment_id,conversation_id,binding,name,mime,size,state,expires_at)
            VALUES (?,?,?,?,?,?,?,'uploading',?)""",
            (upload_id, client_id, conversation_id, binding, name, mime, size, expires_at))
        return self._begin_result(connection.execute(
            "SELECT * FROM desktop_uploads WHERE upload_id=?", (upload_id,)).fetchone())

    def _begin_result(self, row: sqlite3.Row) -> dict:
        return {"upload_id": row["upload_id"], "chunk_bytes": self.chunk_bytes,
                "expires_at": datetime.fromtimestamp(row["expires_at"], UTC).isoformat()}

    def _discard(self, connection: sqlite3.Connection, row: sqlite3.Row, state: str) -> None:
        connection.execute("DELETE FROM desktop_upload_chunks WHERE upload_id=?",
                           (row["upload_id"],))
        connection.execute("UPDATE desktop_uploads SET state=?,received=0 WHERE upload_id=?",
                           (state, row["upload_id"]))

    def _active(self, connection: sqlite3.Connection, row: sqlite3.Row,
                *, allow_committed: bool = False) -> None:
        if row["state"] not in {"uploading", "committed"}:
            raise AttachmentError("expired", "Upload is no longer available")
        adopted = row["ref"] and connection.execute(
            "SELECT 1 FROM desktop_attachment_adoptions WHERE ref=?", (row["ref"],),
        ).fetchone()
        if row["expires_at"] <= self.clock() and not adopted:
            self._discard(connection, row, "expired")
            raise AttachmentError("expired", "Upload has expired")
        self.require_conversation(connection, row["conversation_id"])
        if row["state"] == "committed" and not allow_committed:
            raise AttachmentError("bad_request", "Upload is already committed")

    def _upload(self, connection: sqlite3.Connection, params: dict) -> sqlite3.Row:
        upload_id = self._string(params, "upload_id")
        row = connection.execute("SELECT * FROM desktop_uploads WHERE upload_id=?",
                                 (upload_id,)).fetchone()
        if row is None:
            raise AttachmentError("expired", "Upload is no longer available")
        return row

    def _chunk(self, connection: sqlite3.Connection, params: dict) -> dict:
        row = self._upload(connection, params)
        self._active(connection, row)
        offset = self._integer(params, "offset")
        encoded = params.get("data_b64")
        if type(encoded) is not str:
            raise AttachmentError("bad_request", "Chunk is not base64")
        if len(encoded) > 4 * ((self.chunk_bytes + 2) // 3):
            raise AttachmentError("too_large", "Chunk exceeds the announced byte limit")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise AttachmentError("bad_request", "Chunk is not base64") from None
        if len(data) > self.chunk_bytes or offset + len(data) > row["size"]:
            raise AttachmentError("too_large", "More bytes than the upload permits")
        if offset < row["received"]:
            # Match the fixture: any already-written identical byte range is a retry,
            # even when the retry uses a different chunk boundary.
            end = offset + len(data)
            if end > row["received"]:
                raise AttachmentError("bad_request", "Chunks must arrive in order")
            pieces = connection.execute("""SELECT offset,data FROM desktop_upload_chunks
                WHERE upload_id=? AND offset<? AND offset+length(data)>? ORDER BY offset""",
                (row["upload_id"], end, offset))
            existing = b"".join(bytes(part["data"])[max(0, offset-part["offset"]):
                                                     end-part["offset"]] for part in pieces)
            if existing != data:
                raise AttachmentError("bad_request", "Repeated offset has different bytes")
        elif offset != row["received"]:
            raise AttachmentError("bad_request", "Chunks must arrive in order")
        elif data:
            connection.execute("INSERT INTO desktop_upload_chunks VALUES (?,?,?)",
                               (row["upload_id"], offset, data))
            connection.execute("UPDATE desktop_uploads SET received=received+? WHERE upload_id=?",
                               (len(data), row["upload_id"]))
        return {"received": max(row["received"], offset + len(data))}

    def _digest(self, connection: sqlite3.Connection, row: sqlite3.Row) -> str:
        digest = hashlib.sha256()
        offset = 0
        for chunk in connection.execute("""SELECT offset,data FROM desktop_upload_chunks
            WHERE upload_id=? ORDER BY offset""", (row["upload_id"],)):
            if chunk["offset"] != offset:
                raise AttachmentError("bad_request", "Attachment bytes are incomplete")
            digest.update(chunk["data"])
            offset += len(chunk["data"])
        if offset != row["size"]:
            raise AttachmentError("bad_request", "Attachment bytes are incomplete")
        return digest.hexdigest()

    def _commit(self, connection: sqlite3.Connection, params: dict) -> dict:
        row = self._upload(connection, params)
        self._active(connection, row, allow_committed=True)
        digest = params.get("sha256")
        if type(digest) is not str or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            if row["state"] == "uploading":
                self._discard(connection, row, "failed")
            raise AttachmentError("bad_request", "Invalid SHA256 digest")
        digest = digest.lower()
        if row["state"] == "committed":
            if digest != row["sha256"]:
                raise AttachmentError("id_conflict", "Upload was committed with a different digest")
            return {"attachment": self._metadata(row)}
        try:
            actual = self._digest(connection, row)
            if row["received"] != row["size"] or actual != digest:
                raise AttachmentError("bad_request", "Upload does not match its size and digest")
        except AttachmentError:
            self._discard(connection, row, "failed")
            raise
        ref = "a_" + uuid.uuid4().hex
        connection.execute("""UPDATE desktop_uploads SET state='committed',sha256=?,ref=?
            WHERE upload_id=?""", (digest, ref, row["upload_id"]))
        return {"attachment": {"ref": ref, "name": row["name"], "mime": row["mime"],
                               "size": row["size"]}}

    def _cancel(self, connection: sqlite3.Connection, params: dict) -> dict:
        upload_id = self._string(params, "upload_id")
        row = connection.execute("SELECT * FROM desktop_uploads WHERE upload_id=?",
                                 (upload_id,)).fetchone()
        if row is not None:
            adopted = row["ref"] and connection.execute(
                "SELECT 1 FROM desktop_attachment_adoptions WHERE ref=?", (row["ref"],),
            ).fetchone()
            if adopted:
                raise AttachmentError("busy", "Attachment belongs to an admitted submission")
            self._discard(connection, row, "cancelled")
        return {"disposition": "cancelled"}

    def adopt_for_submission(
        self, connection: sqlite3.Connection, conversation_id: str, request_id: str,
        message_id: str, attachments: list[dict],
    ) -> list[dict]:
        """Call inside the shared submission transaction, before message insertion.

        Errors must roll back admission; caller may catch them outside the
        transaction to journal a refusal. Duplicate semantic submission IDs must be
        checked by the request service *before* adoption.
        """
        if connection is not self.store.connection or not connection.in_transaction:
            raise ValueError("Attachment adoption requires the shared admission transaction")
        self.require_conversation(connection, conversation_id)
        if type(attachments) is not list:
            raise AttachmentError("bad_request", "Attachments must be a list")
        if len(attachments) > self.attachments_per_turn:
            raise AttachmentError("too_large", "Too many attachments for one submission")
        selected = []
        seen = set()
        for item in attachments:
            if type(item) is not dict or type(item.get("add_to_knowledge", False)) is not bool:
                raise AttachmentError("bad_request", "Invalid attachment knowledge choice")
            ref = self._string(item, "ref")
            if ref in seen:
                raise AttachmentError("bad_request", "Duplicate attachment reference")
            seen.add(ref)
            row = connection.execute("SELECT * FROM desktop_uploads WHERE ref=?", (ref,)).fetchone()
            if row is None or row["conversation_id"] != conversation_id:
                raise AttachmentError("not_found", "Attachment unavailable in this conversation")
            self._active(connection, row, allow_committed=True)
            if row["state"] != "committed" or self._digest(connection, row) != row["sha256"]:
                raise AttachmentError("bad_request", "Attachment could not be verified")
            previous = connection.execute("""SELECT message_id,add_to_knowledge
                FROM desktop_attachment_adoptions WHERE ref=? AND request_id=?""",
                (ref, request_id)).fetchone()
            knowledge = item.get("add_to_knowledge", False)
            if previous and tuple(previous) != (message_id, int(knowledge)):
                raise AttachmentError("id_conflict", "Attachment adoption has different parameters")
            selected.append((row, knowledge))
        for row, knowledge in selected:
            connection.execute("""INSERT OR IGNORE INTO desktop_attachment_adoptions
                VALUES (?,?,?,?)""", (row["ref"], request_id, message_id, int(knowledge)))
        return [self._metadata(row) for row, _ in selected]

    def streams_for_request(self, conversation_id: str, request_id: str
                            ) -> list[tuple[VerifiedAttachment, bool]]:
        """Core-only processing/explicit knowledge seam, never an arbitrary read."""
        with self.store.transaction() as connection:
            self.require_conversation(connection, conversation_id)
            rows = connection.execute("""SELECT u.*,a.add_to_knowledge
                FROM desktop_uploads u JOIN desktop_attachment_adoptions a ON a.ref=u.ref
                WHERE u.conversation_id=? AND a.request_id=? ORDER BY a.rowid""",
                (conversation_id, request_id)).fetchall()
            result = []
            for row in rows:
                if row["state"] != "committed" or self._digest(connection, row) != row["sha256"]:
                    raise AttachmentError("bad_request", "Attachment could not be verified")
                data = b"".join(chunk[0] for chunk in connection.execute(
                    "SELECT data FROM desktop_upload_chunks WHERE upload_id=? ORDER BY offset",
                    (row["upload_id"],)))
                result.append((VerifiedAttachment(row["name"], row["mime"], row["size"], data),
                               bool(row["add_to_knowledge"])))
            return result

    def expire(self) -> int:
        with self.store.transaction() as connection:
            rows = connection.execute("""SELECT u.* FROM desktop_uploads u
                WHERE u.state IN ('uploading','committed') AND u.expires_at<=?
                AND NOT EXISTS (SELECT 1 FROM desktop_attachment_adoptions a WHERE a.ref=u.ref)""",
                (self.clock(),)).fetchall()
            for row in rows:
                self._discard(connection, row, "expired")
            return len(rows)

    def delete_conversation(self, connection: sqlite3.Connection, conversation_id: str) -> None:
        """Compose with conversation deletion; retain admitted-identity tombstones."""
        if connection is not self.store.connection or not connection.in_transaction:
            raise ValueError("Attachment deletion requires the shared conversation transaction")
        rows = connection.execute("SELECT * FROM desktop_uploads WHERE conversation_id=?",
                                  (conversation_id,)).fetchall()
        for row in rows:
            connection.execute("DELETE FROM desktop_attachment_adoptions WHERE ref=?",
                               (row["ref"],))
            self._discard(connection, row, "deleted")
