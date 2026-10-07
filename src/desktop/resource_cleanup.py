"""Durable observation of existing runtime owners, never new input authority.

The retained owners decide release truth. This bridge neither constructs them
for teardown nor treats PID exit as descendant/native-resource cleanup.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from ..permissions.persistence import write_private_atomic

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
_BOOT_ID_SHAPE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def current_boot_id() -> str | None:
    """This boot's kernel identity, or None when it cannot be read or is malformed."""
    try:
        value = BOOT_ID.read_text().strip()
    except OSError:
        return None
    return value if _BOOT_ID_SHAPE.fullmatch(value) else None


class ResourceCleanupError(RuntimeError):
    """Existing owners did not establish durable cleanup."""


class ResourceCleanupJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.previous_unknown = None
        self.previous_unknown_count = 0
        self.latest_unknown_boot_id = None
        boot = current_boot_id()
        try:
            previous = json.loads(path.read_text())
            if (not isinstance(previous, dict) or previous.get("version") != 1
                    or previous.get("state") not in {"running", "complete", "unknown"}):
                raise ValueError("Invalid cleanup evidence")
            self.previous_unknown = previous.get("previous_unknown")
            self.previous_unknown_count = int(previous.get("previous_unknown_count", 0))
            self.latest_unknown_boot_id = previous.get("latest_unknown_boot_id")
            if previous["state"] != "complete":
                # Retain the first unresolved receipt, not an exponentially
                # nested chain of every later interrupted startup.
                self.previous_unknown = self.previous_unknown or {
                    key: previous[key]
                    for key in ("state", "at", "resources", "boot_id") if key in previous
                }
                self.previous_unknown_count += 1
                # The first unresolved lifetime stays the notice; the newest one decides how
                # long the package fence holds. One without a recorded boot is this boot.
                self.latest_unknown_boot_id = previous.get("boot_id") or boot
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            self.previous_unknown = {"state": "unknown", "reason": "cleanup_evidence_unreadable"}
            self.latest_unknown_boot_id = boot
        # The package fence holds an unknown for the rest of the boot it happened in. One
        # recorded before boots were, or from unreadable evidence, is stamped now and only
        # once: it can only be from this boot or an earlier one.
        if isinstance(self.previous_unknown, dict) and "boot_id" not in self.previous_unknown:
            self.previous_unknown = {**self.previous_unknown, "boot_id": boot}
        if self.previous_unknown is not None and not self.latest_unknown_boot_id:
            self.latest_unknown_boot_id = (self.previous_unknown.get("boot_id")
                                           if isinstance(self.previous_unknown, dict) else boot)
        self.current = {"version": 1, "state": "running", "resources": {}, "boot_id": boot,
                        "latest_unknown_boot_id": self.latest_unknown_boot_id,
                        "previous_unknown": self.previous_unknown,
                        "previous_unknown_count": self.previous_unknown_count}
        self._write()

    def public(self) -> dict:
        return {"state": self.current["state"], "resources": self.current["resources"],
                "previous_unknown": self.previous_unknown,
                "previous_unknown_count": self.previous_unknown_count,
                "reconciliation_required": self.previous_unknown is not None
                or self.current["state"] == "unknown",
                "effects_undone": False, "replay": False}

    def finish(self, resources: dict) -> None:
        self.current["resources"] = resources
        self.current["state"] = (
            "complete" if all(row["state"] in {"not_started", "released"}
                              for row in resources.values()) else "unknown"
        )
        self._write()
        if self.current["state"] == "unknown":
            raise ResourceCleanupError("Runtime resource cleanup is unverified")

    def _write(self) -> None:
        self.current["at"] = datetime.now(UTC).isoformat()
        if not write_private_atomic(self.path, json.dumps(self.current, sort_keys=True)):
            raise ResourceCleanupError("Runtime resource cleanup durability is unverified")


async def close_existing_execution_owners(core, management) -> dict:
    """Reuse the engine's original barriers, never retry them to improve evidence."""
    engine = getattr(core, "engine", None)
    if engine is not None:
        retained = getattr(engine, "execution_cleanup_results", None)
        resources = deepcopy(retained) if retained is not None else {
            name: {"state": "unknown", "reason": "engine_cleanup_not_complete"}
            for name in ("computer", "processes")
        }
        outcome = getattr(engine, "cleanup_outcome", None)
        resources["engine"] = deepcopy(outcome) if outcome is not None else {
            "state": "unknown", "reason": "engine_cleanup_not_complete",
        }
        if getattr(core, "_engine_cleanup_failed", False):
            resources["engine"]["state"] = "unknown"
        return resources
    executor = getattr(management, "executor", None)
    registry = getattr(executor, "_process_registry", None)
    computer = getattr(core, "computer", None)
    if computer is None:
        computer = getattr(management, "computer", None)
    return await close_execution_owners(computer=computer, registry=registry)


async def close_execution_owners(*, computer, registry, resources=None) -> dict:
    """Observe these exact existing owners after their producers settle.

    The caller retains the first result. Native readback stays read-only and
    attached to the original durable store across its owner's close barrier.
    """
    resources = {} if resources is None else resources
    resources.update({name: {"state": "unknown", "reason": "cleanup_not_complete"}
                      for name in ("computer", "processes")})
    for name, owner, method in (
        ("computer", computer, "close"), ("processes", registry, "shutdown"),
    ):
        if owner is None:
            resources[name] = {"state": "not_started"}
            continue
        native_reader = None
        native_identity = None
        native_path = None
        if name == "computer":
            controller = getattr(owner, "controller", owner)
            store = getattr(controller, "store", None)
            if store is not None:
                try:
                    with store.lock:
                        filename = store.db.execute("PRAGMA database_list").fetchone()[2]
                    native_path = Path(filename)
                    native_identity = native_path.lstat()
                    # Read-only readback before integration closes its connection.
                    # No new ComputerStore, grant or recovery sweep is created.
                    native_reader = sqlite3.connect(native_path.as_uri() + "?mode=ro", uri=True)
                except Exception:
                    native_reader = None
        try:
            await getattr(owner, method)()
        except asyncio.CancelledError:
            resources[name] = {"state": "unknown", "error_type": "CancelledError"}
            raise
        except Exception as error:
            # Cancellation is not release. Retain the owner and persist only an
            # inert type name, never exception text/user content or credentials.
            resources[name] = {"state": "unknown", "error_type": type(error).__name__}
        else:
            unresolved = []
            if name == "computer":
                if store is not None:
                    try:
                        if native_reader is None or native_path is None:
                            raise ValueError("No native readback")
                        current = native_path.lstat()
                        if (current.st_dev, current.st_ino) != (
                            native_identity.st_dev, native_identity.st_ino,
                        ):
                            raise ValueError("Native store identity changed")
                        rows = native_reader.execute(
                            "SELECT session_id FROM sessions WHERE state IN "
                            "('starting','active','paused','quarantined')",
                        ).fetchall()
                        unresolved = [row[0] for row in rows]
                    except Exception:
                        # A closed/unreadable store cannot prove dormant grants
                        # retired, even when no backend is live in this process.
                        unresolved = ["durable_native_state_unreadable"]
            resources[name] = {
                "state": "unknown" if unresolved else "released", "method": method,
                "evidence": "retained_owner_cleanup_barrier",
                **({"unresolved_sessions": unresolved} if unresolved else {}),
            }
        finally:
            if native_reader is not None:
                native_reader.close()
    return resources
