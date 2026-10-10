"""Scheduler execution history — persistent JSONL log of schedule runs.

Records every scheduler execution with timing, status, and error details.
Supports querying by schedule ID with pagination and optional pruning.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles

from ..desktop.platform.variants import windows_variant
from ..odin_log import get_logger

log = get_logger("scheduler.history")

# Maximum entries to keep per schedule (oldest pruned on write)
DEFAULT_MAX_ENTRIES = 200
# Maximum total entries in the history file before compaction
MAX_TOTAL_ENTRIES = 5000


class ScheduleHistory:
    """Append-only JSONL log for scheduler execution records."""

    def __init__(
        self,
        path: str | None = None,
        max_entries_per_schedule: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        from ..runtime_paths import runtime_profile_paths

        self.path = (
            Path(path)
            if path is not None
            else runtime_profile_paths().data_dir / "schedule_history.jsonl"
        )
        if path is None:
            from ..desktop.paths import private_directory

            private_directory(self.path.parent)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._max_per_schedule = max_entries_per_schedule
        self._records_since_prune = 0
        self._auto_prune_interval = 100
        self._lock = asyncio.Lock()

    async def record(
        self,
        *,
        schedule_id: str,
        description: str,
        action: str,
        status: str,
        duration_ms: int,
        error: str | None = None,
        retry_attempt: int = 0,
        run_binding: dict | None = None,
    ) -> dict[str, Any]:
        """Record a schedule execution. Returns the saved entry."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "schedule_id": schedule_id,
            "description": description,
            "action": action,
            "status": status,
            "duration_ms": duration_ms,
        }
        if error:
            entry["error"] = error[:500]
        if retry_attempt > 0:
            entry["retry_attempt"] = retry_attempt
        if run_binding is not None:
            entry["run_binding"] = dict(run_binding)

        line = json.dumps(entry, default=str) + "\n"
        async with self._lock:
            await self._settle_io(self._append(line))
        return entry

    @staticmethod
    async def _settle_io(operation: Coroutine[Any, Any, Any]) -> Any:
        """Retain the history lock until all threaded I/O and close calls settle."""
        worker = asyncio.create_task(operation)
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
        result = worker.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _append(self, line: str) -> None:
        try:
            async with aiofiles.open(self.path, "a") as f:
                await f.write(line)
        except Exception as e:
            log.error("Failed to write schedule history: %s", e)

        self._records_since_prune += 1
        if self._records_since_prune >= self._auto_prune_interval:
            self._records_since_prune = 0
            await self._prune_locked()

    async def record_interrupted(self, pending: dict) -> None:
        """Strict, durable recovery append; failures leave the outbox intact.

        Read the entire file under the history lock rather than treating an
        unreadable store as empty, as the best-effort live query does.
        """
        async with self._lock:
            await self._settle_io(asyncio.to_thread(self._record_interrupted_sync, pending))

    @windows_variant("src.desktop.platform.windows_engine:record_interrupted_sync")
    def _record_interrupted_sync(self, pending: dict) -> None:
        evidence = ("schedule_id", "status", "run_binding", "error")
        if pending.get("status") != "unknown":
            raise ValueError("Interrupted recovery history must have unknown status")
        # a+ creates a missing file without truncating an existing one. Any
        # read/parse/write/sync failure propagates instead of claiming success.
        with self.path.open("a+", encoding="utf-8") as file:
            file.seek(0)
            entries = [json.loads(line) for line in file if line.strip()]
            recorded = any(
                all(entry.get(key) == pending.get(key) for key in evidence)
                for entry in entries
            )
            if not recorded:
                entry = {"timestamp": datetime.now(UTC).isoformat(), **pending}
                file.write(json.dumps(entry, default=str) + "\n")
            # Sync existing matches too: readback after a failed fsync is not
            # evidence of durability, even though the bytes are visible.
            file.flush()
            os.fsync(file.fileno())
        # Persist file creation before retiring its durable scheduler outbox.
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    async def query(
        self,
        schedule_id: str | None = None,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query history entries (most recent first).

        Args:
            schedule_id: Filter to a specific schedule. None = all.
            status: Filter by status (success/failure).
            limit: Max entries to return.
        """
        if not self.path.exists():
            return []

        results: list[dict] = []
        try:
            async with aiofiles.open(self.path) as f:
                lines = await f.readlines()
        except Exception as e:
            log.error("Failed to read schedule history: %s", e)
            return []

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if schedule_id and entry.get("schedule_id") != schedule_id:
                continue
            if status and entry.get("status") != status:
                continue

            results.append(entry)
            if len(results) >= limit:
                break

        return results

    async def stats(self, schedule_id: str) -> dict[str, Any]:
        """Compute summary stats for a schedule: total runs, successes,
        failures, avg duration, last run time."""
        entries = await self.query(schedule_id, limit=self._max_per_schedule)

        if not entries:
            return {
                "schedule_id": schedule_id,
                "total_runs": 0,
                "successes": 0,
                "failures": 0,
                "avg_duration_ms": 0,
                "last_run": None,
            }

        successes = sum(1 for e in entries if e.get("status") == "success")
        failures = sum(1 for e in entries if e.get("status") == "failure")
        durations = [e.get("duration_ms", 0) for e in entries]
        avg_dur = int(sum(durations) / len(durations)) if durations else 0

        return {
            "schedule_id": schedule_id,
            "total_runs": len(entries),
            "successes": successes,
            "failures": failures,
            "avg_duration_ms": avg_dur,
            "last_run": entries[0].get("timestamp") if entries else None,
        }

    async def prune(self) -> int:
        async with self._lock:
            return await self._settle_io(self._prune_locked())

    @windows_variant("src.desktop.platform.windows_engine:prune_locked")
    async def _prune_locked(self) -> int:
        """Compact history file, keeping only the most recent entries per schedule.

        Returns the number of entries removed.
        """
        if not self.path.exists():
            return 0

        try:
            async with aiofiles.open(self.path) as f:
                lines = await f.readlines()
        except Exception as e:
            log.error("Failed to read history for pruning: %s", e)
            return 0

        # Parse all entries
        entries: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        if len(entries) <= MAX_TOTAL_ENTRIES:
            return 0

        # Keep most recent N per schedule
        from collections import defaultdict
        by_schedule: dict[str, list[dict]] = defaultdict(list)
        for entry in entries:
            sid = entry.get("schedule_id", "unknown")
            by_schedule[sid].append(entry)

        kept: list[dict] = []
        for sid, sid_entries in by_schedule.items():
            # Entries are in chronological order; keep last N
            kept.extend(sid_entries[-self._max_per_schedule:])

        # Sort by timestamp to maintain chronological order
        kept.sort(key=lambda e: e.get("timestamp", ""))

        removed = len(entries) - len(kept)
        if removed > 0:
            try:
                content = "".join(json.dumps(e, default=str) + "\n" for e in kept)
                tmp = self.path.with_suffix(".tmp")
                async with aiofiles.open(tmp, "w") as f:
                    await f.write(content)
                    await f.flush()
                    await asyncio.to_thread(os.fsync, f.fileno())
                tmp.replace(self.path)
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    await asyncio.to_thread(os.fsync, directory)
                finally:
                    os.close(directory)
                log.info("Pruned %d history entries", removed)
            except Exception as e:
                log.error("Failed to write pruned history: %s", e)
                return 0

        return removed
