"""Durable identities and synchronous SQLite transactions for profile journals."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .paths import private_directory


class JournalStorageError(RuntimeError):
    """Storage failure with no path or database diagnostic exposure."""

    def __init__(self) -> None:
        super().__init__("Durable journal storage is unavailable")


def response_error(code: str, message: str, disposition: str = "rejected") -> dict:
    return {"ok": False, "error": {
        "code": code, "message": message, "disposition": disposition,
    }}


def canonical_json(value: Any) -> str:
    """Accept JSON values only, without nonfinite numbers or Python extensions."""
    def validate(item: Any) -> None:
        if item is None or type(item) in (bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is str:
            item.encode("utf-8", errors="strict")
            return
        if type(item) is list:
            for child in item:
                validate(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for key, child in item.items():
                validate(key)
                validate(child)
            return
        raise ValueError("Expected finite JSON values")

    validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def _invalid_binding(value: Any) -> str:
    # Tag invalid JSON input separately for durable validation refusals.
    def tagged(item: Any) -> Any:
        if type(item) is dict:
            pairs = [[tagged(key), tagged(child)] for key, child in item.items()]
            return ["dict", sorted(pairs, key=lambda pair: json.dumps(pair[0]))]
        if type(item) in (list, tuple):
            return [type(item).__name__, [tagged(child) for child in item]]
        if type(item) is float:
            return ["float", str(item)]
        if item is None or type(item) in (str, bool, int):
            return [type(item).__name__, item]
        raise ValueError("Expected JSON input")

    return json.dumps(tagged(value), ensure_ascii=True, separators=(",", ":"))


class JournalStore:
    """Private FULL-synchronous storage; thread-confined, never across an await.

    Nested transactions join their parent. A nested failure marks that parent
    rollback-only, even if the exception is caught.
    """

    def __init__(self, path: Path, profile_id: str, *, identity: str | None = None) -> None:
        self.profile_id = profile_id
        self.identity = identity
        self._depth = 0
        self._rollback_only = False
        self._closed = False
        self._directory_fd = -1
        self._connection: sqlite3.Connection | None = None
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("Expected a profile identifier")
        try:
            path = Path(path)
            private_directory(path.parent)
            self._directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for name in (path.name, path.name + "-journal", path.name + "-wal", path.name + "-shm"):
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=self._directory_fd)
                except FileNotFoundError:
                    continue
                try:
                    self._check_file(os.fstat(fd))
                finally:
                    os.close(fd)
            fd = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o600, dir_fd=self._directory_fd)
            try:
                info = os.fstat(fd)
                self._check_file(info)
                existing = info.st_size > 0
            finally:
                os.close(fd)
            anchored = f"/proc/self/fd/{self._directory_fd}/{path.name}"
            self._connection = sqlite3.connect(anchored, isolation_level=None, timeout=5)
            self._connection.row_factory = sqlite3.Row
            if existing:
                tables = {row[0] for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if tables != {"journal_meta", "command_receipts", "journal_events"}:
                    raise JournalStorageError()
                rows = self.connection.execute(
                    "SELECT profile_id,identity FROM journal_meta").fetchall()
                if len(rows) != 1 or tuple(rows[0]) != (profile_id, identity):
                    raise JournalStorageError()
                columns = {
                    "journal_meta": {"singleton", "profile_id", "identity", "event_high",
                                     "event_floor"},
                    "command_receipts": {"command_id", "binding", "state", "response",
                                         "created_at", "finished_at", "unknown_outcome"},
                    "journal_events": {"seq", "frame"},
                }
                for table, expected_columns in columns.items():
                    actual = {row[1] for row in self.connection.execute(
                        f"PRAGMA table_info({table})")}
                    if actual != expected_columns:
                        raise JournalStorageError()
            self._connection.execute("PRAGMA journal_mode=DELETE")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            with self.transaction():
                tables = {row[0] for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                expected = {"journal_meta", "command_receipts", "journal_events"}
                if existing and tables != expected:
                    raise JournalStorageError()
                self.connection.execute("""CREATE TABLE IF NOT EXISTS journal_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    profile_id TEXT NOT NULL, identity TEXT, event_high INTEGER NOT NULL DEFAULT 0,
                    event_floor INTEGER NOT NULL DEFAULT 0)""")
                self.connection.execute("""INSERT OR IGNORE INTO journal_meta
                    (singleton,profile_id,identity) VALUES (1,?,?)""", (profile_id, identity))
                row = self.connection.execute(
                    "SELECT profile_id,identity FROM journal_meta").fetchone()
                if row[0] != profile_id or row[1] != identity:
                    raise JournalStorageError()
                self.connection.execute("""CREATE TABLE IF NOT EXISTS command_receipts (
                    command_id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','final','expired')),
                    response TEXT, created_at REAL NOT NULL, finished_at REAL,
                    unknown_outcome INTEGER NOT NULL DEFAULT 0)""")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS journal_events (
                    seq INTEGER PRIMARY KEY, frame TEXT NOT NULL)""")
            os.fsync(self._directory_fd)
        except Exception:
            self.close()
            raise JournalStorageError() from None

    @staticmethod
    def _check_file(info: os.stat_result) -> None:
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise JournalStorageError()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._closed or self._connection is None:
            raise JournalStorageError()
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        outer = self._depth == 0
        if outer:
            self._rollback_only = False
            try:
                self.connection.execute("BEGIN IMMEDIATE")
            except Exception:
                raise JournalStorageError() from None
        self._depth += 1
        try:
            yield self.connection
            if outer:
                if self._rollback_only:
                    raise JournalStorageError()
                try:
                    self.connection.commit()
                except Exception:
                    raise JournalStorageError() from None
        except BaseException as exc:
            self._rollback_only = True
            if outer:
                try:
                    self.connection.rollback()
                except Exception:
                    self.close()
            if isinstance(exc, (sqlite3.Error, OSError)):
                raise JournalStorageError() from None
            raise
        finally:
            self._depth -= 1

    def close(self) -> None:
        self._closed = True
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None
        if self._directory_fd != -1:
            os.close(self._directory_fd)
            self._directory_fd = -1


class CommandJournal:
    def __init__(self, store: JournalStore) -> None:
        self.store = store

    def check(self, command_id: str, method: str, params: Any) -> dict | None:
        """Replay/check an existing identity without reserving an uncached read."""
        try:
            try:
                binding = "json:" + canonical_json([self.store.profile_id, method, params])
            except (ValueError, TypeError, UnicodeError, RecursionError):
                binding = "invalid:" + _invalid_binding([self.store.profile_id, method, params])
            with self.store.transaction() as connection:
                row = connection.execute("SELECT * FROM command_receipts WHERE command_id=?",
                                         (command_id,)).fetchone()
                return self._replay(row, binding) if row is not None else None
        except (JournalStorageError, sqlite3.Error, OSError):
            return response_error("storage_unavailable", "Durable command storage is unavailable",
                                  "outcome_unknown")
        except (ValueError, TypeError, RecursionError):
            return response_error("bad_request", "Expected finite JSON parameters")

    @staticmethod
    def _replay(row: sqlite3.Row, binding: str) -> dict:
        if row["binding"] != binding:
            return response_error("id_conflict", "Command ID has a different binding")
        if row["state"] == "expired":
            return response_error("receipt_expired", "Command receipt has expired",
                                  "outcome_unknown")
        if row["state"] == "pending":
            return response_error("internal", "Command outcome is unknown", "outcome_unknown")
        return json.loads(row["response"])

    def execute(self, command_id: str, method: str, params: Any,
                handler: Callable[[], dict]) -> dict:
        """Reserve durably, then call a synchronous zero-argument handler once.

        Refusals are final receipts. Never call inside an existing transaction:
        reservation must commit before handler code can run. Handler's result
        and event appends commit together. A pending admission is never retried.
        """
        if not isinstance(command_id, str) or not command_id:
            return response_error("bad_request", "Expected a command identifier")
        valid = isinstance(method, str) and bool(method) and type(params) is dict
        try:
            binding = "json:" + canonical_json([self.store.profile_id, method, params])
        except (ValueError, TypeError, UnicodeError, RecursionError):
            valid = False
            try:
                binding = "invalid:" + _invalid_binding([self.store.profile_id, method, params])
            except (ValueError, TypeError, RecursionError):
                return response_error("bad_request", "Expected finite JSON parameters")
        try:
            if self.store._depth:
                raise JournalStorageError()
            with self.store.transaction() as connection:
                row = connection.execute("SELECT * FROM command_receipts WHERE command_id=?",
                                         (command_id,)).fetchone()
                if row is not None:
                    answer = self._replay(row, binding)
                else:
                    connection.execute("""INSERT INTO command_receipts
                        (command_id,binding,state,created_at) VALUES (?,?,'pending',?)""",
                                       (command_id, binding, time.time()))
                    answer = None
            if answer is not None:
                return answer
            with self.store.transaction() as connection:
                answer = handler() if valid else response_error(
                    "bad_request", "Expected finite JSON parameters")
                encoded = canonical_json(answer)
                if (type(answer) is not dict or type(answer.get("ok")) is not bool
                        or (answer["ok"] and "result" not in answer)
                        or (not answer["ok"] and (
                            type(answer.get("error")) is not dict
                            or any(type(answer["error"].get(key)) is not str
                                   for key in ("code", "message", "disposition"))))):
                    raise ValueError("Handler returned an invalid response")
                unknown = not answer["ok"] and answer["error"].get(
                    "disposition") == "outcome_unknown"
                connection.execute("""UPDATE command_receipts SET state='final',response=?,
                    finished_at=?,unknown_outcome=? WHERE command_id=?""",
                                   (encoded, time.time(), int(unknown), command_id))
            return json.loads(encoded)
        except (JournalStorageError, sqlite3.Error, OSError):
            return response_error("storage_unavailable", "Durable command storage is unavailable",
                                  "outcome_unknown")
        except Exception:
            return response_error("internal", "Command outcome is unknown", "outcome_unknown")

    def prune(self, before: float) -> int:
        """Expire bodies, never bindings or unknown/pending outcomes."""
        if not isinstance(before, (int, float)) or not math.isfinite(before):
            raise ValueError("Expected a finite Unix timestamp")
        with self.store.transaction() as connection:
            cursor = connection.execute("""UPDATE command_receipts SET state='expired',response=NULL
                WHERE state='final' AND unknown_outcome=0 AND finished_at < ?""", (before,))
            return cursor.rowcount
