"""Core composition boundary and shared ordered shutdown.

Phase 2 must wire authenticated durable admission and native conversation
surfaces. No transport-shaped service facade is constructed in Phase 1.
Shutdown retains upstream ordering and cleanup vetoes.
"""

from __future__ import annotations

import asyncio

from ..odin_log import get_logger
from ..tools.process_manager import ProcessCleanupError

log = get_logger("core")


class Phase2WiringRequired(RuntimeError):  # noqa: N818
    """Request/control/durable-surface composition is not implemented."""


def build_services(*args, **kwargs):
    raise Phase2WiringRequired("Phase 2 core service composition is not implemented.")


def build_components(*args, **kwargs):
    raise Phase2WiringRequired("Phase 2 request/control/durable-surface wiring is not implemented.")


async def start_mcp(*args, **kwargs):
    raise Phase2WiringRequired("Phase 2 supervised capability startup is not implemented.")


async def close_computer_once(bot) -> None:
    """Release desktop authority once, including independent service teardown."""
    existing = getattr(bot, "_computer_cleanup_task", None)
    if existing is not None:
        await asyncio.shield(existing)
        return

    async def close() -> None:
        computer = getattr(bot, "computer", None)
        if computer is None:
            return
        try:
            await computer.close()
        except Exception:
            log.exception("Computer cleanup unverified")
            from ..restart import block_reexec

            block_reexec("computer cleanup unverified")

    task = asyncio.create_task(close(), name="computer-cleanup")
    bot._computer_cleanup_task = task
    await asyncio.shield(task)


async def shutdown_services(bot) -> None:
    """Stop services and persist state in upstream shutdown order.

    Component attributes are looked up via getattr because they may not be
    present (some are config-gated, some late-bound). Order matters: stop
    work-producers before consumers, and persist user-visible state
    (sessions) last.
    """
    await close_computer_once(bot)

    quota_check = getattr(bot, "codex_quota_check", None)
    if quota_check is not None:
        try:
            await quota_check.close()
        except Exception:
            log.exception("Error stopping Codex quota check")

    channel_state = getattr(bot, "channel_state", None)
    if channel_state is not None:
        # Close pending steering before disconnecting conversation delivery.
        # Shutdown waits (bounded); turns never wait on receipt transport.
        await channel_state.shutdown_steering()

    loop_manager = getattr(bot, "loop_manager", None)
    if loop_manager is not None:
        try:
            # Cancel AND await tasks so finally blocks settle before exit.
            await loop_manager.shutdown()
        except Exception:
            log.exception("Error stopping loop_manager")

    scheduler = getattr(bot, "scheduler", None)
    if scheduler is not None:
        try:
            await scheduler.stop()
        except Exception:
            log.exception("Error stopping scheduler")

    mcp_manager = getattr(bot, "mcp_manager", None)
    if mcp_manager is not None:
        try:
            await mcp_manager.shutdown()
        except Exception:
            log.exception("Error stopping mcp_manager")

    usage_rollup = getattr(bot, "usage_rollup", None)
    if usage_rollup is not None:
        try:
            await usage_rollup.stop()
        except Exception:
            log.exception("Error stopping usage_rollup")

    # Never construct a process registry solely to tear it down.
    tool_executor = getattr(bot, "tool_executor", None)
    process_registry = getattr(tool_executor, "_process_registry", None)
    if process_registry is not None:
        try:
            await process_registry.shutdown()
        except Exception as cleanup_err:
            log.exception(
                "Process cleanup could not be verified — surviving "
                "descendants may outlive this process"
            )
            from ..restart import block_reexec

            detail = (
                str(cleanup_err)
                if isinstance(cleanup_err, ProcessCleanupError)
                else f"{type(cleanup_err).__name__}: {cleanup_err}"
            )
            block_reexec(f"process cleanup unverified: {detail}")

    knowledge = getattr(bot, "knowledge", None)
    if knowledge is not None:
        try:
            knowledge.close()
        except Exception:
            log.exception("Error closing knowledge")

    turn_store = getattr(getattr(bot, "services", None), "turn_store", None)
    if turn_store is not None:
        try:
            turn_store.close()
        except Exception:
            log.exception("Error closing turn_store")

    sessions = getattr(bot, "sessions", None)
    if sessions is not None:
        try:
            sessions.save_all()
        except Exception:
            log.exception("Error saving sessions")

    dispatcher = getattr(bot, "outbound_webhook_dispatcher", None)
    if dispatcher is not None:
        try:
            await dispatcher.close()
        except Exception:
            log.exception("Error closing outbound_webhook_dispatcher")

    agent_mgr = getattr(bot, "agent_manager", None)
    if agent_mgr is not None:
        try:
            active = [a for a in agent_mgr._agents.values() if a._sm.is_active]
            agent_tasks = [a._task for a in active if getattr(a, "_task", None) is not None]
            for agent in active:
                agent_mgr.kill(agent.id, cascade=True)
            if agent_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*agent_tasks, return_exceptions=True), 10.0,
                    )
                except TimeoutError:
                    log.warning(
                        "Shutdown: %d agent task(s) did not finish in 10s", len(agent_tasks)
                    )
            await agent_mgr.cleanup()
            log.info("Shutdown: killed %d active agent(s)", len(active))
        except Exception:
            log.exception("Error cleaning up agent_manager")

    executor = getattr(bot, "tool_executor", None)
    if executor is not None:
        pool = getattr(executor, "ssh_pool", None)
        if pool is not None:
            try:
                await pool.close_all()
            except Exception:
                log.exception("Error closing SSH pool")

    # One shared deadline for live AND retired provider generations.
    from ..llm.client_lifecycle import shutdown_provider_clients

    try:
        await shutdown_provider_clients(getattr(bot, "llm_gateway", None))
    except Exception:
        log.exception("Error closing provider clients")

    _components = getattr(bot, "components", None)
    _media = getattr(_components, "media_tools", None)
    _selector = getattr(_media, "image_selector", None)
    _image_backend = getattr(_selector, "openai", None)
    if _image_backend is not None:
        try:
            await _image_backend.close()
        except Exception:
            log.exception("Error closing image backend")

    browser = getattr(bot, "browser_manager", None)
    if browser is not None:
        try:
            await browser.shutdown()
        except Exception:
            log.exception("Error shutting down browser_manager")
