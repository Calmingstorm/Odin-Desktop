"""Native orchestration hooks and owner-bound journal controls, no real effects.

The cross-conversation cases use the work suite's genuine local authority and
exact-identity admission stub; real request sealing remains in the core suites.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from src.desktop.controls import ControlService
from src.discord.background_task import (
    BackgroundTask,
    _send_conversational_followup,
    _send_progress,
    _send_summary,
)
from src.discord.channel_state import ChannelStateRegistry
from src.discord.native_tools.agents_tasks import AgentTaskTools
from src.tools.autonomous_loop import LoopInfo, LoopManager
from tests import test_desktop_work as work_suite
from tests.test_desktop_work import agent as admitted_agent

work = work_suite.work


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
async def test_loop_cancel_before_first_instruction_settles_stopped():
    manager = LoopManager()
    calls = []

    @asynccontextmanager
    async def execution(info):
        calls.append("execution")
        yield

    async def publish(info, text):
        calls.append("publication")

    async def iterate(*args):
        calls.append("iteration")
        return "Must not execute."

    def settled(info):
        assert info._task.done()
        assert info._task.cancelled()
        calls.append(info.status)

    loop_id = manager.start_admitted_loop(
        "goal", Destination(), "owner", "Owner", iterate,
        before_start=lambda info: calls.append("admission"),
        execution=execution, publish=publish, on_settled=settled,
    )
    # Cancel synchronously, without yielding after the worker is queued.
    info = manager._loops[loop_id]
    info._task.cancel()
    await asyncio.gather(info._task, return_exceptions=True)
    await asyncio.sleep(0)
    assert info.status == "stopped"
    assert calls == ["admission", "stopped"]


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


def native_controls(service, monkeypatch):
    controls = ControlService(service.store, service.events, service.requests,
        ChannelStateRegistry(), authority=service.authority, permissions=service.permissions)
    controls.work = service
    service.controls = controls
    handler = AgentTaskTools.__new__(AgentTaskTools)
    handler._work_service = service
    handler._agent_manager = service.agents
    handler._loop_manager = service.loops
    handler._get_config = lambda: SimpleNamespace(agents=SimpleNamespace())
    async def emit(*_args):
        pass
    handler._turn_recorder = SimpleNamespace(_emit_lifecycle_event=emit)
    # No unrelated webhook task is needed to prove the actual control receipt.
    monkeypatch.setattr("src.discord.native_tools.agents_tasks.fire_and_forget",
                        lambda coroutine, **_kwargs: coroutine.close())
    return handler


def other_conversation(service, message):
    cid = service.conversations.create()["conversation"]["id"]
    return service.requests.issue(message.owner_id, cid, "controlling-run")


def journal_receipt(service, record, action, response):
    with service.store.transaction() as db:
        rows = db.execute("SELECT * FROM desktop_controls").fetchall()
    matches = [row for row in rows if json.loads(row["binding"])[2]["id"] == record["id"]]
    assert len(matches) == 1
    row = matches[0]
    assert row["conversation_id"] == record["conversation_id"]
    assert row["request_id"] == record["request_id"]
    assert row["generation"] == record["generation"]
    assert json.loads(row["response"]) == response
    params = json.loads(row["binding"])[2]
    assert params["action"] == action
    for key in ("kind", "id", "manager_generation", "run_id", "generation", "conversation_id"):
        assert params[key] == record[key]
    return params


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel_task", "kill_agent", "send_to_agent", "stop_loop"])
async def test_native_cross_conversation_controls_journal_original_binding(work, monkeypatch,
                                                                          operation):
    service, message_a, _context = work
    message_b = other_conversation(service, message_a)
    handler = native_controls(service, monkeypatch)
    if operation == "cancel_task":
        item = BackgroundTask("task-a", "harmless", [], message_a.conversation_id, "Owner",
                              requester_id=message_a.owner_id)
        service.tasks[item.task_id] = item
        kind, manager_id, action = "task", item.task_id, "cancel"
        values = {"task_id": manager_id}
    elif operation == "stop_loop":
        item = LoopInfo("loop-a", "harmless", "silent", 60, None, 2,
                        message_a.conversation_id, message_a.owner_id, "Owner")
        service.loops._loops[item.id] = item
        kind, manager_id, action = "loop", item.id, "stop"
        values = {"loop_id": manager_id}
    else:
        item = admitted_agent(service, message_a, "agent-a")
        kind, manager_id = "agent", item.id
        action = "steer" if operation == "send_to_agent" else "cancel"
        values = {"agent_id": manager_id, "message": "owner correction from B"}
    record = service.register(kind, manager_id, message_a)
    assert service.list({"conversation_id": message_b.conversation_id})["items"] == []
    response = json.loads(await getattr(handler, f"_handle_{operation}")(message_b, values))
    assert response["ok"], response
    assert response["result"]["run_id"] == message_a.request_id
    assert response["result"]["generation"] == message_a.generation
    if operation == "send_to_agent":
        assert response["result"]["disposition"] == "queued"
        assert response["result"]["consumed"] is False
        assert item.inbox_sequence == 1
        assert item.last_consumed_sequence == 0
    elif operation == "stop_loop":
        assert item.status == "stopped"
    else:
        assert item._cancel_event.is_set()
    params = journal_receipt(service, record, action, response)
    # Retrying a receipt uses the original A binding, not B or a successor.
    assert await service.controls.dispatch("work.control", params) == response
    if operation == "send_to_agent":
        assert item.inbox_sequence == 1


@pytest.mark.asyncio
async def test_native_stop_all_journals_owner_loops_across_conversations(work, monkeypatch):
    service, message_a, _context = work
    message_b = other_conversation(service, message_a)
    handler = native_controls(service, monkeypatch)
    records = []
    for suffix, message in (("a", message_a), ("b", message_b)):
        item = LoopInfo(f"loop-{suffix}", "harmless", "silent", 60, None, 2,
                        message.conversation_id, message.owner_id, "Owner")
        service.loops._loops[item.id] = item
        records.append(service.register("loop", item.id, message))
    foreign = LoopInfo("foreign-loop", "harmless", "silent", 60, None, 2,
                       message_a.conversation_id, "other-owner", "Other")
    terminal = LoopInfo("finished-loop", "harmless", "silent", 60, None, 2,
                        message_a.conversation_id, message_a.owner_id, "Owner", status="completed")
    service.loops._loops.update({foreign.id: foreign, terminal.id: terminal})
    results = [json.loads(line) for line in
               (await handler._handle_stop_loop(message_b, {"loop_id": "all"})).splitlines()]
    assert len(results) == 2
    for record, response in zip(records, results, strict=True):
        assert response["ok"], response
        assert response["result"]["disposition"] == "done"
        assert service.loops._loops[record["manager_id"]].status == "stopped"
        journal_receipt(service, record, "stop", response)
    assert foreign.status == "running"
    assert terminal.status == "completed"
    result = await handler._handle_stop_loop(message_b, {"loop_id": "all"})
    assert result == "No active loops to stop."
    with service.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM desktop_controls").fetchone()[0] == 2


def test_native_list_agents_remains_conversation_scoped(work, monkeypatch):
    service, message_a, _context = work
    message_b = other_conversation(service, message_a)
    handler = native_controls(service, monkeypatch)
    admitted_agent(service, message_a, "agent-a")
    assert handler._handle_list_agents(SimpleNamespace(
        channel=SimpleNamespace(id=message_b.conversation_id))) == "No agents running."
    admitted_agent(service, message_b, "agent-b")
    result = handler._handle_list_agents(SimpleNamespace(
        channel=SimpleNamespace(id=message_b.conversation_id)))
    assert "`agent-b`" in result
    assert "`agent-a`" not in result


@pytest.mark.asyncio
async def test_native_owner_global_control_rejects_foreign_or_unadmitted_request(work, monkeypatch):
    service, message_a, _context = work
    item = admitted_agent(service, message_a, "agent-a")
    service.register("agent", item.id, message_a)
    native_controls(service, monkeypatch)
    cid = service.conversations.create()["conversation"]["id"]
    foreign = service.requests.issue("other-owner", cid, "foreign-run")
    assert (await service.control_native(foreign, "agent", item.id, "cancel")).startswith("Error:")
    with pytest.raises(PermissionError, match="Unadmitted request"):
        await service.control_native(object(), "agent", item.id, "cancel")
    assert not item._cancel_event.is_set()
    with service.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM desktop_controls").fetchone()[0] == 0
