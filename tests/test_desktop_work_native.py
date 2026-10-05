"""Native orchestration hooks, not platform/owner-authority qualification.

Real request sealing and ControlService authority are covered by the work/core
integration suites. These narrow tests never manufacture a privileged envelope.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from src.discord.background_task import (
    BackgroundTask,
    _send_conversational_followup,
    _send_progress,
    _send_summary,
)
from src.discord.native_tools.agents_tasks import AgentTaskTools
from src.tools.autonomous_loop import LoopManager


class Destination:
    id = "conversation"

    async def send(self, text):
        raise AssertionError("send-shaped objects are not admission/publication")


@pytest.mark.asyncio
async def test_loop_legacy_send_shape_does_not_start():
    manager = LoopManager()
    result = manager.start_loop("goal", Destination(), "owner", "Owner", None)
    assert result.startswith("Error:")
    assert manager._loops == {}


@pytest.mark.asyncio
async def test_loop_admission_failure_never_executes():
    manager = LoopManager()
    calls = []

    def admit(info):
        assert manager._loops[info.id] is info
        calls.append("admission")
        raise OSError("durable storage unavailable")

    @asynccontextmanager
    async def execution(info):
        calls.append("execution")
        yield

    async def publish(info, text):
        calls.append("publication")

    with pytest.raises(OSError):
        manager.start_admitted_loop(
            "goal", Destination(), "owner", "Owner", None,
            before_start=admit, execution=execution, publish=publish,
            on_settled=lambda info: calls.append("settlement"),
        )
    await asyncio.sleep(0)
    assert calls == ["admission"]
    assert manager._loops == {}


@pytest.mark.asyncio
async def test_loop_executes_in_context_and_settles_after_task_done():
    manager = LoopManager()
    calls = []
    context_active = False

    def admit(info):
        calls.append("admission")
        assert info._task is None

    @asynccontextmanager
    async def execution(info):
        nonlocal context_active
        context_active = True
        calls.append("enter")
        try:
            yield
        finally:
            context_active = False
            calls.append("exit")

    async def iterate(*args):
        assert context_active
        calls.append("iteration")
        return "result"

    async def publish(info, text):
        assert context_active
        calls.append("publication")

    def settled(info):
        assert info._task.done()
        assert info.status == "completed"
        calls.append("settlement")

    loop_id = manager.start_admitted_loop(
        "goal", Destination(), "owner", "Owner", iterate,
        before_start=admit, execution=execution, publish=publish,
        on_settled=settled, max_iterations=1,
    )
    await manager._loops[loop_id]._task
    await asyncio.sleep(0)
    assert calls[0:3] == ["admission", "enter", "iteration"]
    assert calls[-2:] == ["exit", "settlement"]
    assert calls.count("publication") == 2


@pytest.mark.asyncio
async def test_background_rendering_and_injected_publication():
    task = BackgroundTask("task", "description", [], "conversation", "owner")
    assert await _send_progress(task, None) == task.progress_text
    await _send_summary(task)
    published = []

    async def publish(kind, text):
        published.append((kind, text))

    async def followup(*args):
        return "A concise followup."

    task.publish = publish
    await _send_progress(task, None)
    await _send_summary(task)
    await _send_conversational_followup(task, followup)
    assert published == [
        ("progress", task.progress_text), ("summary", task.summary_text),
        ("followup", task.followup_text),
    ]


@pytest.mark.asyncio
async def test_cancelled_followup_does_not_publish():
    task = BackgroundTask("task", "description", [], "conversation", "owner")
    published = []

    async def publish(*args):
        published.append(args)

    async def followup(*args):
        task.cancel()
        return "Must not publish."

    task.publish = publish
    await _send_conversational_followup(task, followup)
    assert published == []
    assert task.followup_text == ""


@pytest.mark.asyncio
async def test_native_control_handlers_delegate_only_to_control_service():
    handler = AgentTaskTools.__new__(AgentTaskTools)
    calls = []

    class Work:
        async def control_native(self, message, kind, manager_id, action, *, text=None):
            calls.append((message, kind, manager_id, action, text))
            return {"disposition": "queued", "consumed": False}

    # A correlation sentinel is passed unchanged. WorkService integration tests
    # prove only sealed, current-owner requests can authorize the effect.
    message = object()
    handler._work_service = Work()
    await handler._handle_cancel_task(message, {"task_id": "task"})
    await handler._handle_kill_agent(message, {"agent_id": "agent"})
    result = await handler._handle_send_to_agent(
        message, {"agent_id": "agent", "message": "correction"}
    )
    assert calls == [
        (message, "task", "task", "cancel", None),
        (message, "agent", "agent", "cancel", None),
        (message, "agent", "agent", "steer", "correction"),
    ]
    assert '"consumed": false' in result


def test_missing_background_hooks_refuse_creation():
    handler = AgentTaskTools.__new__(AgentTaskTools)
    handler._background_admission = None
    handler._work_service = None
    handler._publish_background = None
    with pytest.raises(RuntimeError, match="No work was started"):
        handler._require_background()
