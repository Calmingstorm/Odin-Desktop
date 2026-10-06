"""Durable notification intents and app acknowledgements, never human delivery."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from ..llm.secret_scrubber import scrub_output_secrets
from .commands import canonical_json


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class NotificationService:
    def __init__(self, store, events) -> None:
        self.store, self.events = store, events
        with store.transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_notifications (
                dedupe_key TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                request_id TEXT, payload TEXT NOT NULL, outcome TEXT,
                created_at TEXT NOT NULL, acked_at TEXT)""")

    def intent(self, *, conversation_id: str, message_id: str, category: str,
               preview: str, dedupe_key: str, request_id: str | None = None) -> dict:
        payload = {"conversation_id": conversation_id, "message_id": message_id,
                   "category": category, "preview": scrub_output_secrets(preview),
                   "dedupe_key": dedupe_key}
        if any(not isinstance(payload[key], str) or not payload[key]
               for key in ("conversation_id", "message_id", "category", "dedupe_key")):
            raise ValueError("Expected notification identity")
        encoded = canonical_json(payload)
        with self.store.transaction() as connection:
            previous = connection.execute(
                "SELECT payload FROM desktop_notifications WHERE dedupe_key=?",
                (dedupe_key,)).fetchone()
            if previous is not None:
                if previous[0] != encoded:
                    raise ValueError("Notification identity conflict")
                return json.loads(previous[0])
            connection.execute("""INSERT INTO desktop_notifications
                (dedupe_key,conversation_id,request_id,payload,created_at)
                VALUES (?,?,?,?,?)""",
                (dedupe_key, conversation_id, request_id, encoded, utc_now()))
            self.events.append("notification.intent", {"kind": "notification", "id": dedupe_key},
                               payload)
        return payload

    def ack(self, dedupe_key: str, outcome: str) -> dict:
        if not isinstance(dedupe_key, str) or not dedupe_key:
            raise ValueError("Expected a notification identity")
        if outcome not in ("shown", "suppressed", "failed"):
            raise ValueError("Expected a notification acknowledgement outcome")
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT outcome FROM desktop_notifications WHERE dedupe_key=?",
                (dedupe_key,)).fetchone()
            if row is None:
                return {"ok": False, "error": {"code": "not_found",
                        "message": "Notification intent not found",
                        "disposition": "not_dispatched"}}
            if row[0] is not None and row[0] != outcome:
                return {"ok": False, "error": {"code": "id_conflict",
                        "message": "Notification already acknowledged",
                        "disposition": "not_dispatched"}}
            if row[0] is None:
                connection.execute("""UPDATE desktop_notifications SET outcome=?,acked_at=?
                    WHERE dedupe_key=?""", (outcome, utc_now(), dedupe_key))
        return {"ok": True, "result": {"disposition": "recorded"}}

    def handle(self, method: str, params: dict) -> dict | None:
        if method != "notifications.ack":
            return None
        try:
            return self.ack(params["dedupe_key"], params["outcome"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": {"code": "bad_request",
                    "message": "Invalid notification acknowledgement",
                    "disposition": "not_dispatched"}}

    def pending(self) -> list[dict]:
        with self.store.transaction() as connection:
            return [json.loads(row[0]) for row in connection.execute(
                "SELECT payload FROM desktop_notifications WHERE outcome IS NULL "
                "ORDER BY created_at,dedupe_key")]

    def recover(self) -> int:
        """Re-emit unacknowledged intents after restart/reset with the same key.

        The app deduplicates the key, not the event cursor. A failed or suppressed
        acknowledgement is terminal and never becomes another notification.
        """
        with self.store.transaction():
            pending = self.pending()
            for payload in pending:
                self.events.append("notification.intent",
                    {"kind": "notification", "id": payload["dedupe_key"]}, payload)
            return len(pending)
