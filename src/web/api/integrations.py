"""Phase 2: owner-scoped MCP/webhook validate-persist-adopt-reconcile commands.

Require private secret patches/mask refusal, portable process ownership,
publication locks and drain-before-cancellation after commit begins.
"""
import asyncio

from . import require_phase2


async def _drain_mcp_management(operation, *, commit_started: asyncio.Event):
    """Abort a management operation while queued; drain it after commit starts."""
    task = asyncio.create_task(operation, name="mcp-management-mutation")
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not commit_started.is_set():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
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


def register_mcp_servers(*args, **kwargs):
    require_phase2("MCP management")


def register_outbound_webhooks(*args, **kwargs):
    require_phase2("Outbound integration management")
