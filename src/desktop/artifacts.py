"""Core-issued binary references and stored report pages.

Published files belong to the transcript, not the 24-hour evidence cache. Binary
tool evidence remains in OutputStore under its original TTL/quota and authority;
the journal holds only a reference. No window-supplied path is ever opened.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections.abc import Callable

from ..llm.secret_scrubber import scrub_output_secrets
from ..tools.output_retention import BinarySnapshot, OutputStore, RetentionError
from .commands import JournalStore, canonical_json

ARTIFACT_SCHEMA = {
    "desktop_artifacts": {"ref", "owner", "conversation_id", "request_id", "name",
                          "mime", "size", "kind", "sha256", "tool", "hosts", "data",
                          "source_cursor", "expires_at"},
    "desktop_reports": {"report_id", "owner", "conversation_id", "request_id", "pages",
                        "tool", "hosts"},
}


class ResultReadError(ValueError):
    """Protocol-facing read error; no storage details or source paths."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _integer(value: int, maximum: int | None = None) -> int:
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        raise ResultReadError("bad_request", "Expected a bounded nonnegative integer")
    return value


def _retention_error(exc: RetentionError) -> ResultReadError:
    text = str(exc)
    if "Permission denied" in text:
        return ResultReadError("unauthorized", "Originating output scope is no longer authorized")
    if "Invalid output cursor" in text:
        return ResultReadError("bad_request", "Invalid output cursor")
    return ResultReadError("expired", "Retained output expired or unavailable")


class ArtifactStore:
    def __init__(self, store: JournalStore, *, output_store: OutputStore | None = None,
                 authorize: Callable | None = None, chunk_bytes: int = 65536,
                 clock: Callable = time.time) -> None:
        if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= 1048576:
            raise ValueError("Expected a positive frame-bounded chunk size")
        self.store, self.output_store = store, output_store
        self.authorize, self.chunk_bytes, self.clock = authorize, chunk_bytes, clock
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_artifacts (
                ref TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation_id TEXT NOT NULL,
                request_id TEXT NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL,
                size INTEGER NOT NULL, kind TEXT NOT NULL, sha256 TEXT NOT NULL,
                tool TEXT NOT NULL, hosts TEXT NOT NULL, data BLOB,
                source_cursor TEXT, expires_at REAL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_reports (
                report_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                conversation_id TEXT NOT NULL, request_id TEXT NOT NULL,
                pages TEXT NOT NULL, tool TEXT NOT NULL, hosts TEXT NOT NULL)""")

    def _allowed(self, tool: str, hosts: tuple, owner: str, *, evidence: bool = False) -> bool:
        # Delegate to the real executor's current policy/scope/host binding checks.
        # A core reference is an identifier, not an authorization grant.
        return bool(owner and self.authorize is not None
                    and (not evidence or self.authorize("get_tool_output", (), owner))
                    and self.authorize(tool, hosts, owner))

    @staticmethod
    def _binding(owner: str, conversation_id: str, request_id: str) -> None:
        if not all(type(value) is str and value for value in
                   (owner, conversation_id, request_id)):
            raise ValueError("Expected an admitted result binding")

    @staticmethod
    def _descriptor(row, *, available: bool = True) -> dict:
        return {"ref": row["ref"], "name": row["name"], "mime": row["mime"],
                "size": row["size"], "kind": row["kind"], "available": available}

    def publish(self, data: bytes, *, owner: str, conversation_id: str, request_id: str,
                name: str, mime: str, kind: str = "file", tool: str = "post_file",
                hosts: tuple = ()) -> dict:
        """Persist a posted file in the same transaction as its committed message."""
        self._binding(owner, conversation_id, request_id)
        if type(data) is not bytes or kind not in {"image", "file", "report"}:
            raise ValueError("Expected opaque bytes and an artifact kind")
        if not all(type(value) is str and value for value in (name, mime, tool)):
            raise ValueError("Expected artifact metadata")
        if not self._allowed(tool, hosts, owner):
            raise ResultReadError("unauthorized", "Originating result scope is not authorized")
        ref = uuid.uuid4().hex
        with self.store.transaction() as db:
            db.execute("INSERT INTO desktop_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                ref, owner, conversation_id, request_id, scrub_output_secrets(name),
                scrub_output_secrets(mime), len(data), kind, hashlib.sha256(data).hexdigest(),
                tool, canonical_json(list(hosts)), data, None, None))
            row = db.execute("SELECT * FROM desktop_artifacts WHERE ref=?", (ref,)).fetchone()
            return self._descriptor(row)

    def register_retained(self, snapshot: BinarySnapshot, *, owner: str,
                          conversation_id: str, request_id: str) -> dict:
        """Issue an idempotent reference to existing evidence without copying bytes.

        Reload through OutputStore before using the snapshot's ID. A caller-held
        dataclass cannot manufacture scope, host identity, or fresh TTL.
        """
        self._binding(owner, conversation_id, request_id)
        if self.output_store is None or not isinstance(snapshot, BinarySnapshot):
            raise ResultReadError("expired", "Retained binary output is unavailable")
        current, _ = self._read_evidence(f"{snapshot.result_id}:0", owner, conversation_id)
        if not isinstance(current, BinarySnapshot):
            raise ResultReadError("bad_request", "Expected retained binary output")
        source_cursor = f"{current.result_id}:0"
        with self.store.transaction() as db:
            row = db.execute("""SELECT * FROM desktop_artifacts WHERE owner=?
                AND conversation_id=? AND request_id=? AND source_cursor=?""",
                (owner, conversation_id, request_id, source_cursor)).fetchone()
            if row is None:
                ref = uuid.uuid4().hex
                kind = "image" if current.kind == "image" else "file"
                db.execute("INSERT INTO desktop_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    ref, owner, conversation_id, request_id, f"attachment-{current.content_index}",
                    current.media_type, len(current.data), kind, current.sha256, current.tool,
                    canonical_json(list(current.hosts)), None, source_cursor, current.expires_at))
                row = db.execute("SELECT * FROM desktop_artifacts WHERE ref=?", (ref,)).fetchone()
            return {"ref": row["ref"], "kind": current.kind, "mime": current.media_type,
                    "size": len(current.data), "sha256": current.sha256}

    def _read_evidence(self, cursor: str, owner: str, conversation_id: str):
        if self.output_store is None:
            raise ResultReadError("expired", "Retained output is unavailable")
        if not self._allowed("get_tool_output", (), owner):
            raise ResultReadError("unauthorized", "Output retrieval is not authorized")
        try:
            return self.output_store.read(
                cursor, owner=owner, channel=conversation_id,
                authorize=lambda tool, hosts: self._allowed(tool, hosts, owner, evidence=True))
        except RetentionError as exc:
            raise _retention_error(exc) from None

    def read(self, ref: str, offset: int, length: int, *, owner: str,
             conversation_id: str | None = None) -> dict:
        _integer(offset)
        _integer(length, self.chunk_bytes)
        if type(ref) is not str:
            raise ResultReadError("bad_request", "Expected an artifact reference")
        with self.store.transaction() as db:
            # Metadata is checked before loading a potentially large BLOB.
            row = db.execute("""SELECT ref,owner,conversation_id,tool,hosts,size,
                source_cursor,expires_at FROM desktop_artifacts WHERE ref=?""", (ref,)).fetchone()
            if (row is None or row["owner"] != owner
                    or (conversation_id is not None and row["conversation_id"] != conversation_id)
                    or (row["expires_at"] is not None and row["expires_at"] <= self.clock())):
                raise ResultReadError("not_found", "Artifact is unavailable")
            if not self._allowed(row["tool"], tuple(json.loads(row["hosts"])), owner,
                                 evidence=row["source_cursor"] is not None):
                raise ResultReadError(
                    "unauthorized", "Originating result scope is no longer authorized")
            if offset > row["size"]:
                raise ResultReadError("bad_request", "Invalid artifact byte offset")
            end = min(row["size"], offset + length)
            if row["source_cursor"] is not None:
                try:
                    snapshot, _ = self._read_evidence(
                        row["source_cursor"], owner, row["conversation_id"])
                except ResultReadError as exc:
                    if exc.code == "expired":
                        raise ResultReadError("not_found", "Artifact is unavailable") from None
                    raise
                if not isinstance(snapshot, BinarySnapshot):
                    raise ResultReadError("not_found", "Artifact is unavailable")
                data = snapshot.data[offset:end]
            else:
                data = db.execute("SELECT substr(data,?,?) FROM desktop_artifacts WHERE ref=?",
                                  (offset + 1, end - offset, ref)).fetchone()[0]
            return {"data_b64": base64.b64encode(data).decode("ascii"),
                    "size": row["size"], "eof": end == row["size"]}

    def publish_report(self, pages: list[str], *, owner: str, conversation_id: str,
                       request_id: str, tool: str, hosts: tuple = ()) -> dict:
        self._binding(owner, conversation_id, request_id)
        if type(pages) is not list or not pages or any(type(page) is not str for page in pages):
            raise ValueError("Expected stored report text pages")
        if not self._allowed(tool, hosts, owner):
            raise ResultReadError("unauthorized", "Originating report scope is not authorized")
        report_id = uuid.uuid4().hex
        with self.store.transaction() as db:
            db.execute("INSERT INTO desktop_reports VALUES (?,?,?,?,?,?,?)", (
                report_id, owner, conversation_id, request_id,
                canonical_json([scrub_output_secrets(page) for page in pages]),
                tool, canonical_json(list(hosts))))
        return {"report_id": report_id, "pages": len(pages)}

    def page(self, report_id: str, page: int, *, owner: str,
             conversation_id: str | None = None) -> dict:
        _integer(page)
        with self.store.transaction() as db:
            row = db.execute("""SELECT owner,conversation_id,tool,hosts FROM desktop_reports
                WHERE report_id=?""", (report_id,)).fetchone()
            if (row is None or row["owner"] != owner
                    or (conversation_id is not None and row["conversation_id"] != conversation_id)):
                raise ResultReadError("not_found", "Report is unavailable")
            if not self._allowed(row["tool"], tuple(json.loads(row["hosts"])), owner):
                raise ResultReadError(
                    "unauthorized", "Originating report scope is no longer authorized")
            pages = json.loads(db.execute("SELECT pages FROM desktop_reports WHERE report_id=?",
                                          (report_id,)).fetchone()[0])
            if not 1 <= page <= len(pages):
                raise ResultReadError("bad_request", "Invalid report page")
            return {"page": page, "pages": len(pages),
                    "text": scrub_output_secrets(pages[page - 1])}

    def delete_conversation(self, conversation_id: str) -> None:
        """Join the transcript deletion transaction; never extend evidence TTL."""
        with self.store.transaction() as db:
            db.execute("DELETE FROM desktop_artifacts WHERE conversation_id=?", (conversation_id,))
            db.execute("DELETE FROM desktop_reports WHERE conversation_id=?", (conversation_id,))
