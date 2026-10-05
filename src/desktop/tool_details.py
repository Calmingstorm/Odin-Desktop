"""Scrubbed tool receipts and reauthorized retained evidence, never tool replay."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from ..llm.secret_scrubber import scrub_output_secrets
from ..tools.output_delivery import DeliveredOutput, render_page
from ..tools.output_retention import BinarySnapshot, OutputStore
from .artifacts import ArtifactStore, ResultReadError, _integer
from .commands import JournalStore, canonical_json

TOOL_DETAIL_SCHEMA = {
    "desktop_tool_details": {"request_id", "invocation_id", "owner", "conversation_id",
                             "tool", "target", "arguments", "previews", "cursor",
                             "attachment_cursor", "hosts"},
}


def _scrub_json(value):
    # Use the copied lexical scrubber, preserving JSON framing and scalar types.
    return json.loads(scrub_output_secrets(canonical_json(value)))


def _preview(delivered_output: str) -> tuple[list[dict], str | None, str | None]:
    """Understand only code-owned canonical envelopes, not an output's claims."""
    cleaned = scrub_output_secrets(str(delivered_output))
    previews = [{"label": "Output preview", "text": cleaned, "truncated": False}]
    cursor = attachment_cursor = None
    if not isinstance(delivered_output, DeliveredOutput):
        return previews, cursor, attachment_cursor
    previews[0]["truncated"] = bool(delivered_output.truncated)
    text, separator, pointer = cleaned.partition("\n[output retention] ")
    if separator:
        try:
            manifest = json.loads(pointer)
            if (manifest.get("kind") == "tool_attachment_manifest"
                    and manifest.get("retention") == "retained"):
                attachment_cursor = manifest["retrieval"]["arguments"]["cursor"]
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    try:
        envelope = json.loads(text)
    except ValueError:
        envelope = None
    if (isinstance(envelope, dict) and envelope.get("kind") == "tool_output"
            and envelope.get("retention") == "retained"):
        # Always start at zero: an initial tail is context, never page evidence.
        cursor = f"{envelope['result_id']}:0"
        previews = [{"label": "Head preview",
                     "text": envelope.get("head", envelope.get("text", "")),
                     "truncated": bool(envelope.get("truncated"))}]
        tail = envelope.get("tail")
        if isinstance(tail, dict) and tail.get("text"):
            previews.append({"label": "Tail preview (context only)", "text": tail["text"],
                             "truncated": True})
    else:
        # RankedOutput's short summary has a discoverable retained pointer.
        match = re.search(r"\nfull matches: get_tool_output cursor=([0-9a-f]{32}:0)$", text)
        if match:
            cursor = match[1]
        previews[0]["text"] = text
    return previews, cursor, attachment_cursor


class ToolDetailsStore:
    def __init__(self, store: JournalStore, *, output_store: OutputStore,
                 artifacts: ArtifactStore, authorize=None, preview_chars: int = 12000) -> None:
        if type(preview_chars) is not int or not 1 <= preview_chars <= 65536:
            raise ValueError("Expected bounded preview size")
        self.store, self.output_store, self.artifacts = store, output_store, artifacts
        self.authorize, self.preview_chars = authorize, preview_chars
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_tool_details (
                request_id TEXT NOT NULL, invocation_id TEXT NOT NULL,
                owner TEXT NOT NULL, conversation_id TEXT NOT NULL,
                tool TEXT NOT NULL, target TEXT, arguments TEXT NOT NULL,
                previews TEXT NOT NULL, cursor TEXT, attachment_cursor TEXT,
                hosts TEXT NOT NULL, PRIMARY KEY (request_id,invocation_id))""")

    def _allowed(self, tool, hosts, owner):
        return bool(owner and self.authorize is not None and self.authorize(tool, hosts, owner))

    def record(self, *, request_id: str, invocation_id: str, owner: str,
               conversation_id: str, tool: str, arguments: dict,
               delivered_output: str, target: str | None = None, hosts: tuple = (),
               cursor: str | None = None, attachment_cursor: str | None = None) -> None:
        """Record an actual sink result, joining its parent journal transaction.

        Explicit cursors are for the real executor's retention callback. This
        service never retains a delivered preview as though it were full evidence.
        """
        ArtifactStore._binding(owner, conversation_id, request_id)
        if (not invocation_id or type(arguments) is not dict
                or not isinstance(delivered_output, str)):
            raise ValueError("Expected an invocation receipt")
        if not self._allowed(tool, hosts, owner):
            raise ResultReadError("unauthorized", "Originating output scope is not authorized")
        previews, inferred, inferred_attachments = _preview(delivered_output)
        cursor = cursor or inferred
        attachment_cursor = attachment_cursor or inferred_attachments
        # Verify retained pointers now, without loading bytes through text routes.
        for pointer in (cursor, attachment_cursor):
            if pointer:
                self.artifacts._read_evidence(pointer, owner, conversation_id)
        bounded = []
        for preview in previews:
            text = scrub_output_secrets(str(preview["text"]))
            bounded.append({"label": preview["label"], "text": text[:self.preview_chars],
                            "truncated": bool(
                                preview["truncated"] or len(text) > self.preview_chars)})
        with self.store.transaction() as db:
            db.execute("""INSERT INTO desktop_tool_details VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(request_id,invocation_id) DO UPDATE SET
                target=excluded.target, arguments=excluded.arguments,
                previews=excluded.previews, cursor=excluded.cursor,
                attachment_cursor=excluded.attachment_cursor, hosts=excluded.hosts
                WHERE desktop_tool_details.owner=excluded.owner
                AND desktop_tool_details.conversation_id=excluded.conversation_id
                AND desktop_tool_details.tool=excluded.tool""", (
                    request_id, invocation_id, owner, conversation_id, tool,
                    scrub_output_secrets(target) if target is not None else None,
                    canonical_json(_scrub_json(arguments)), canonical_json(bounded), cursor,
                    attachment_cursor, canonical_json(list(hosts))))

    def detail(self, request_id: str, invocation_id: str, *, owner: str,
               conversation_id: str | None = None) -> dict:
        with self.store.transaction() as db:
            meta = db.execute("""SELECT owner,conversation_id,tool,hosts
                FROM desktop_tool_details
                WHERE request_id=? AND invocation_id=?""", (request_id, invocation_id)).fetchone()
            if (meta is None or meta["owner"] != owner
                    or (conversation_id is not None
                        and meta["conversation_id"] != conversation_id)):
                raise ResultReadError("not_found", "Tool detail is unavailable")
            if not self._allowed(meta["tool"], tuple(json.loads(meta["hosts"])), owner):
                raise ResultReadError(
                    "unauthorized", "Originating output scope is no longer authorized")
            row = db.execute("""SELECT * FROM desktop_tool_details
                WHERE request_id=? AND invocation_id=?""",
                             (request_id, invocation_id)).fetchone()
            output = {}
            pointer = row["cursor"] or row["attachment_cursor"]
            if pointer:
                try:
                    snapshot, _ = self.artifacts._read_evidence(
                        pointer, owner, row["conversation_id"])
                except ResultReadError as exc:
                    if exc.code != "expired":
                        raise
                    # Details survive evidence expiry; do not advertise a dead cursor.
                else:
                    output = {"cursor": pointer,
                              "expires_at": datetime.fromtimestamp(
                                  snapshot.expires_at, UTC).isoformat()}
            result = {"tool": row["tool"], "arguments": _scrub_json(json.loads(row["arguments"])),
                      "previews": _scrub_json(json.loads(row["previews"])), "output": output}
            if row["target"] is not None:
                result["target"] = scrub_output_secrets(row["target"])
            return result

    def _binding_for_cursor(self, cursor, *, owner, conversation_id):
        if type(cursor) is not str or not re.fullmatch(r"[0-9a-f]{32}:[0-9]+", cursor):
            raise ResultReadError("bad_request", "Invalid output cursor")
        prefix = cursor.split(":")[0] + ":%"
        with self.store.transaction() as db:
            row = db.execute("""SELECT request_id,attachment_cursor,conversation_id
                FROM desktop_tool_details WHERE owner=?
                AND (? IS NULL OR conversation_id=?)
                AND (cursor LIKE ? OR attachment_cursor LIKE ?) LIMIT 1""",
                (owner, conversation_id, conversation_id, prefix, prefix)).fetchone()
            if row is None:
                # Binary refs may have been obtained through a retained manifest.
                row = db.execute("""SELECT request_id,NULL AS attachment_cursor,conversation_id
                    FROM desktop_artifacts WHERE owner=?
                    AND (? IS NULL OR conversation_id=?) AND source_cursor LIKE ? LIMIT 1""",
                    (owner, conversation_id, conversation_id, prefix)).fetchone()
            if row is None:
                raise ResultReadError("expired", "Retained output is unavailable")
            return row[0], row[1], row[2]

    def output(self, cursor: str, limit: int, *, owner: str,
               conversation_id: str | None = None) -> dict:
        _integer(limit, 65536)
        if limit == 0:
            raise ResultReadError("bad_request", "Expected a positive output character limit")
        request_id, attachment_cursor, conversation_id = self._binding_for_cursor(
            cursor, owner=owner, conversation_id=conversation_id)
        snapshot, offset = self.artifacts._read_evidence(cursor, owner, conversation_id)
        expires = datetime.fromtimestamp(snapshot.expires_at, UTC).isoformat()
        attachments = []
        if isinstance(snapshot, BinarySnapshot):
            attachments.append(self.artifacts.register_retained(
                snapshot, owner=owner, conversation_id=conversation_id, request_id=request_id))
            return {"text": "", "attachments": attachments, "eof": True, "expires_at": expires}
        # OutputStore's canonical binary manifest is discoverable without paging
        # JSON fragments through the text UI. Each blob independently reauthorizes.
        manifest = None
        if snapshot.text.startswith('{"attachments":'):
            try:
                parsed = json.loads(snapshot.text)
                if isinstance(parsed.get("attachments"), list) and all(
                        item.get("kind") == "tool_attachment" for item in parsed["attachments"]):
                    manifest = parsed["attachments"]
            except (ValueError, TypeError, AttributeError):
                pass
        if manifest is not None:
            for item in manifest:
                binary, _ = self.artifacts._read_evidence(
                    item["retrieval"]["arguments"]["cursor"], owner, conversation_id)
                if not isinstance(binary, BinarySnapshot):
                    raise ResultReadError("expired", "Retained binary output is unavailable")
                attachments.append(self.artifacts.register_retained(
                    binary, owner=owner, conversation_id=conversation_id, request_id=request_id))
            return {"text": "", "attachments": attachments, "eof": True, "expires_at": expires}
        # Compose the copied renderer: Unicode offsets, whole ranked matches,
        # secret-safe old manifests, and no initial tail/duplicate evidence.
        page = json.loads(render_page(snapshot, offset=offset, limit=limit, budget=524288))
        if attachment_cursor and attachment_cursor != cursor:
            attachments = self.output(attachment_cursor, limit, owner=owner,
                                      conversation_id=conversation_id)["attachments"]
        result = {"text": page["text"], "attachments": attachments,
                  "eof": not page["truncated"], "expires_at": expires}
        if page["cursor"]:
            result["next_cursor"] = page["cursor"]
        return result

    def delete_conversation(self, conversation_id: str) -> None:
        with self.store.transaction() as db:
            db.execute("DELETE FROM desktop_tool_details WHERE conversation_id=?",
                       (conversation_id,))
