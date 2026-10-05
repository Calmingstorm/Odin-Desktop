"""Neutral host serialization/publication helpers; owner commands await Phase 2.

Require trusted installation-owned registry/enrollment, explicit fingerprints,
scope/audit, persistence before adoption and draining of committed mutations.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from ...config.persistence import DELETE_CONFIG_PATH
from ...config.schema import ToolHost
from . import require_phase2


def _tool_host_dump(host: ToolHost) -> dict[str, Any]:
    return host.model_dump()


def _leaf_changes(before: dict[str, Any], after: dict[str, Any]) -> list:
    changes: list = []
    for alias in before.keys() - after.keys():
        changes.append((("tools", "hosts", alias), DELETE_CONFIG_PATH))
    for alias in after.keys() - before.keys():
        changes.append((("tools", "hosts", alias), after[alias]))
    for alias in before.keys() & after.keys():
        old, new = before[alias], after[alias]
        for field in old.keys() | new.keys():
            if field not in new:
                changes.append((("tools", "hosts", alias, field), DELETE_CONFIG_PATH))
            elif old.get(field) != new.get(field):
                changes.append((("tools", "hosts", alias, field), new[field]))
    return changes


async def _drain_host_mutation(operation, *, commit_started: asyncio.Event):
    """Cancel queued/preflight work; once persistence begins, drain publication."""
    task = asyncio.create_task(operation, name="host-management-mutation")
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not commit_started.is_set():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise
            cancelled = True
            current = asyncio.current_task()
            if current is not None:
                while current.cancelling():
                    current.uncancel()
    result = await task
    if cancelled:
        raise asyncio.CancelledError
    return result


def register_hosts(*args, **kwargs):
    require_phase2("Managed-host commands")
