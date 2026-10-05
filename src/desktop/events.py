"""Durable profile event sequence and bounded decimal-cursor catchup."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from .commands import JournalStorageError, JournalStore, canonical_json


def _sequence(value: int | str) -> int:
    if type(value) is int and 0 <= value <= 9223372036854775807:
        return value
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,18}", value):
        result = int(value)
        if result <= 9223372036854775807:
            return result
    raise ValueError("Expected a decimal event cursor")


class EventJournal:
    def __init__(self, store: JournalStore, max_events: int = 10000) -> None:
        if type(max_events) is not int or not 0 <= max_events <= 9223372036854775807:
            raise ValueError("Expected a nonnegative event retention limit")
        self.store = store
        self.max_events = max_events

    @property
    def high(self) -> str:
        with self.store.transaction() as connection:
            return str(connection.execute("SELECT event_high FROM journal_meta").fetchone()[0])

    def append(self, event_type: str, entity: dict, payload: dict, at: str | None = None) -> dict:
        with self.store.transaction():
            return self._append(event_type, entity, payload, at)

    def _append(self, event_type: str, entity: dict, payload: dict, at: str | None) -> dict:
        if not isinstance(event_type, str) or not event_type or type(entity) is not dict:
            raise ValueError("Expected an event type and entity")
        if type(payload) is not dict:
            raise ValueError("Expected an event payload")
        if at is None:
            at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        else:
            try:
                parsed = datetime.fromisoformat(at)
                if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("Expected a UTC event timestamp") from None
        with self.store.transaction() as connection:
            seq = connection.execute("SELECT event_high FROM journal_meta").fetchone()[0] + 1
            if seq > 9223372036854775807:
                raise JournalStorageError()
            frame = {"t": "evt", "seq": seq, "cursor": str(seq), "type": event_type,
                     "entity": entity, "at": at, "payload": payload}
            encoded = canonical_json(frame)
            connection.execute("INSERT INTO journal_events(seq,frame) VALUES (?,?)", (seq, encoded))
            connection.execute("UPDATE journal_meta SET event_high=?", (seq,))
            cutoff = connection.execute("""SELECT seq FROM journal_events ORDER BY seq DESC
                LIMIT 1 OFFSET ?""", (self.max_events,)).fetchone()
            if cutoff is not None:
                connection.execute("DELETE FROM journal_events WHERE seq<=?", (cutoff[0],))
                connection.execute("UPDATE journal_meta SET event_floor=?", (cutoff[0],))
            return json.loads(encoded)

    def between(self, after_seq: int | str, through_seq: int | str | None = None) -> list[dict]:
        after = _sequence(after_seq)
        through = _sequence(through_seq) if through_seq is not None else None
        with self.store.transaction() as connection:
            if through is None:
                through = connection.execute("SELECT event_high FROM journal_meta").fetchone()[0]
            return [json.loads(row[0]) for row in connection.execute(
                "SELECT frame FROM journal_events WHERE seq>? AND seq<=? ORDER BY seq",
                (after, through))]

    def catchup(self, after: str | None) -> tuple[bool, str, list[dict]]:
        with self.store.transaction() as connection:
            high, floor = connection.execute(
                "SELECT event_high,event_floor FROM journal_meta").fetchone()
            if after is None:
                return False, str(high), []
            try:
                cursor = _sequence(after) if isinstance(after, str) else -1
            except ValueError:
                cursor = -1
            if not floor <= cursor <= high:
                return True, str(high), []
            return False, str(high), self.between(cursor, high)
