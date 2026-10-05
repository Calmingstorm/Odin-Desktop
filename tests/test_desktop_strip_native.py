"""Phase 1 native-domain strip and fail-closed boundary proofs."""

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_package_import_is_neutral():
    module = importlib.import_module("src.discord.native_tools")
    assert module.__all__ == []
    assert not hasattr(module, "NativeToolDispatcher")


def test_social_registrations_and_handlers_are_removed():
    for name in ("registry", "channel_ops"):
        source = (ROOT / f"src/discord/native_tools/{name}.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in {
                    "set_permission", "add_reaction", "create_poll", "purge_messages",
                    "read_channel",
                }
    from src.discord.native_tools.channel_ops import ChannelOpsTools
    assert not any(hasattr(ChannelOpsTools, name) for name in (
        "_handle_purge", "_handle_add_reaction", "_handle_create_poll", "_handle_set_permission",
    ))


@pytest.mark.asyncio
async def test_history_gate_never_looks_up_foreign_conversation():
    from src.discord.native_tools.channel_ops import ChannelOpsTools
    calls = []

    async def reader(request, *, limit):
        calls.append((request, limit))
        return ["[01:02:03] owner: recorded context"]

    tools = ChannelOpsTools(read_visible_history=reader)
    request = object()
    result = await tools._handle_read_conversation(request, {"channel_id": "other"})
    assert "Only 'limit'" in result
    assert calls == []
    result = await tools._handle_read_conversation(request, {"limit": 999})
    assert calls == [(request, 100)]
    assert result.startswith("[Conversation history: 1 messages read.")
    assert "do not paste or echo these messages" in result


@pytest.mark.asyncio
async def test_history_unwired_and_actual_permission_error_are_distinct():
    from src.discord.native_tools.channel_ops import ChannelOpsTools
    result = await ChannelOpsTools()._handle_read_conversation(object(), {})
    assert "Phase 2" in result

    async def deny(request, *, limit):
        raise PermissionError("denied")

    tools = ChannelOpsTools(read_visible_history=deny)
    assert await tools._handle_read_conversation(object(), {}) == (
        "Permission denied — cannot read this conversation."
    )


def test_composition_gates_have_no_effectful_fallback():
    from src.discord.wiring import Phase2WiringRequired, build_components, build_services
    for function in (build_components, build_services):
        with pytest.raises(Phase2WiringRequired, match="Phase 2"):
            function()


@pytest.mark.asyncio
async def test_unwired_agent_and_scheduled_admission_fail_before_effects():
    from src.discord.native_tools.agents_tasks import AgentTaskTools
    from src.discord.native_tools.scheduling import SchedulingTools

    # Empty instances prove the admission gate precedes access to executors,
    # stores, providers, or request-shaped transport attributes.
    agents = object.__new__(AgentTaskTools)
    with pytest.raises(RuntimeError, match="Phase 2"):
        await agents._handle_delegate_task(None, {})
    with pytest.raises(RuntimeError, match="Phase 2"):
        agents._handle_start_loop(None, {})
    with pytest.raises(RuntimeError, match="Phase 2"):
        await agents._handle_spawn_agent(None, {})
    schedules = SchedulingTools(scheduler=None)
    with pytest.raises(RuntimeError, match="Phase 2"):
        await schedules._handle_schedule_task(None, {})
    with pytest.raises(RuntimeError, match="Phase 2"):
        await schedules._handle_update_schedule({})


@pytest.mark.asyncio
async def test_generated_file_cannot_report_durable_delivery_success():
    from src.discord.native_tools.media import MediaTools
    tools = MediaTools(get_config=lambda: None, browser_manager=None, tool_executor=None)
    result = await tools._handle_generate_file(None, {"filename": "sample.txt", "content": "safe"})
    assert "Phase 2" in result
    assert result.startswith("Failed to post file:")


@pytest.mark.asyncio
async def test_request_owned_stop_does_not_poison_replacement():
    from src.discord.channel_state import ChannelStateRegistry
    state = ChannelStateRegistry()
    old_event = state.set_active_request("conversation", "old")
    _, waiter = state.request_stop("conversation")
    new_event = state.set_active_request("conversation", "new")
    state.finish_stop("conversation", "old", "settled")
    assert old_event.is_set()
    assert not new_event.is_set()
    assert state.active_requests["conversation"] == "new"
    assert (await waiter).confirmed


@pytest.mark.asyncio
async def test_computer_cleanup_task_is_shared_without_native_work():
    from src.discord.wiring import close_computer_once
    calls = []

    class OwnedCleanup:
        async def close(self):
            calls.append("closed")

    services = SimpleNamespace(computer=OwnedCleanup())
    await close_computer_once(services)
    await close_computer_once(services)
    assert calls == ["closed"]


def test_conversation_logger_refuses_path_selector(tmp_path):
    from src.discord.channel_logger import ChannelLogger
    logger = ChannelLogger(tmp_path)
    logger.log_message(SimpleNamespace(conversation_id="../foreign", owner_id="owner"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_report_projection_is_durable_navigation_not_publication(tmp_path):
    import json

    from src.discord.scheduled_report import (
        PaginatedEmbedV1Renderer,
        ScheduledReportPaginationService,
        ScheduledReportRendererRegistry,
    )

    registry = ScheduledReportRendererRegistry()
    registry.register(PaginatedEmbedV1Renderer())
    path = tmp_path / "reports.json"
    service = ScheduledReportPaginationService(registry=registry, data_path=path)
    raw = json.dumps({
        "format": "paginated_embed_v1", "pages": [{"title": "One"}, {"title": "Two"}],
    })
    first = await service.store_projection("report", "conversation", "paginated_embed_v1", raw)
    assert first["title"] == "One"
    assert (await service.project_page("report", "conversation", "next"))["title"] == "Two"
    reloaded = ScheduledReportPaginationService(registry=registry, data_path=path)
    assert (await reloaded.project_page("report", "conversation"))["title"] == "Two"
    with pytest.raises(PermissionError):
        await reloaded.project_page("report", "foreign")
    with pytest.raises(ValueError, match="do not replay"):
        await reloaded.store_projection("report", "conversation", "paginated_embed_v1", raw)
    with pytest.raises(NotImplementedError, match="Phase 2"):
        await reloaded.post("conversation", "paginated_embed_v1", raw)


def test_owned_files_have_no_transport_imports():
    names = [
        "attachments", "background_task", "channel_logger", "channel_state",
        "intake_pipeline", "scheduled_events", "scheduled_report", "slash_commands", "wiring",
    ]
    paths = [ROOT / f"src/discord/{name}.py" for name in names]
    paths += list((ROOT / "src/discord/native_tools").glob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(alias.name != "discord" and not alias.name.startswith("discord.")
                           for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "discord", path
                assert not (node.module or "").startswith("discord."), path


@pytest.mark.asyncio
async def test_background_cancel_waits_for_owned_settlement():
    import asyncio

    from src.discord.background_task import BackgroundTask

    started = asyncio.Event()
    settled = asyncio.Event()
    task = BackgroundTask("task", "safe cancellation", [], "conversation", "owner")

    async def work():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            settled.set()

    task._asyncio_task = asyncio.create_task(work())
    await started.wait()
    assert await task.request_cancel()
    assert settled.is_set()
    assert task._asyncio_task.done()
    assert task.status == "cancelled"
    assert not await task.request_cancel()
