"""Native controls of work that has ended answer as Odin's tools do (D17).

Desktop routes kill_agent, send_to_agent, cancel_task, stop_loop and manage_process kill
through Work's journaled controls. Work offers no control for an unknown or ended target,
and every such call got one generic refusal ("bound work control is not available"), found
when a 1.4.0 battery killed an agent that had already finished. Odin's managers answer those
calls themselves: an ended agent's kill still reaches its running descendants, the rest are
failures in the managers' own words. Each answer here is checked against that manager's own
answer in the same state, where the manager's call changes nothing.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from src.agents.manager import AgentInfo, AgentManager, AgentState
from src.desktop.commands import response_error
from src.desktop.work import UNAVAILABLE
from src.discord.background_task import BackgroundTask
from src.tools.autonomous_loop import LoopInfo
from src.tools.execution_outcome import ToolFailure, is_tool_failure
from src.tools.handlers.system import SystemTools
from src.tools.process_manager import AgentJobCleanup, ProcessInfo, ProcessRegistry
from tests import test_desktop_work as work_suite
from tests.test_desktop_work import agent
from tests.test_desktop_work_native import native_controls

work = work_suite.work


def _journal(service):
    with service.store.transaction() as db:
        return [json.loads(row["binding"])[2] for row in
                db.execute("SELECT binding FROM desktop_controls").fetchall()]


def _record_id(service, manager_id):
    [record] = [r for r in service.list({"kind": "agent"})["items"]
                if r["manager_id"] == manager_id]
    return record["id"]


def _failure(result, text):
    assert result == text
    assert isinstance(result, ToolFailure) and is_tool_failure(result)


# --- kill_agent ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_killing_a_finished_agent_is_odins_answer_not_a_refusal(work, monkeypatch):
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    done = agent(service, message, "done")
    service.register("agent", done.id, message)
    done.transition(AgentState.COMPLETED)

    result = await handler._handle_kill_agent(message, {"agent_id": "done"})

    assert result == ("Agent 'done' already in terminal state: completed. "
                      "Kill signal sent to 0 descendant(s).")
    assert not is_tool_failure(result)  # Odin's kill of an ended agent succeeds
    assert result == service.agents.kill_with_receipt("done")[0]
    assert _journal(service) == []  # nothing to control, nothing journaled


@pytest.mark.asyncio
async def test_killing_an_unknown_agent_is_odins_not_found(work, monkeypatch):
    service, message, _context = work
    handler = native_controls(service, monkeypatch)

    result = await handler._handle_kill_agent(message, {"agent_id": "nobody"})

    _failure(result, "Error: Agent 'nobody' not found.")
    assert result == service.agents.kill_with_receipt("nobody")[0]


def _lineage(manager, message, *edges):
    """Running agents by (id, parent), the first one the root; returns them by ID."""
    items = {}
    for agent_id, parent in edges:
        item = AgentInfo(id=agent_id, label=agent_id, goal="harmless",
                         channel_id=message.conversation_id, requester_id=message.owner_id,
                         requester_name="Owner", parent_id=parent,
                         root_id=edges[0][0] if parent else None)
        item.transition(AgentState.READY)
        manager._agents[agent_id] = item
        if parent:
            items[parent].children_ids.append(agent_id)
        items[agent_id] = item
    return items


def _tree(manager, message):
    """A parent that finished while its child and grandchild still run."""
    items = _lineage(manager, message, ("p", None), ("c", "p"), ("g", "c"))
    items["p"].transition(AgentState.COMPLETED)
    return items["p"], items["c"], items["g"]


def _retire(manager, agent_id):
    """Odin's cleanup removes an agent some minutes after it ends; its lineage stays while a
    descendant runs."""
    assert manager._remove_agent(agent_id, source="test")
    assert agent_id not in manager._agents and agent_id in manager._retired_lineage


def _running(item):
    """An agent's run in flight, ending KILLED when its task is cancelled."""
    async def run():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            item.transition(AgentState.KILLED)

    item._task = asyncio.create_task(run())


@pytest.mark.asyncio
@pytest.mark.parametrize("retired", [True, False], ids=["retired", "listed"])
async def test_killing_an_ended_parent_stops_its_running_descendants(work, monkeypatch, retired):
    """Odin's kill cascades from an ended agent. While the parent is listed its own Work card
    offers the cancel. Once Odin's cleanup retires it the card has none, and the topmost
    running descendant's own control carries the kill down the tree."""
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    reaped = []

    def reaper(agent_ids):
        reaped.append(set(agent_ids))
        cleanup = AgentJobCleanup(jobs=[("g1", 41)], starts=0)

        async def settle():
            return {"jobs": {"g1": "stopped"}, "starts": []}

        cleanup.task = asyncio.create_task(settle())
        return cleanup

    service.agents.set_job_reaper(reaper)
    tree = _tree(service.agents, message)
    for item in tree:
        service.register("agent", item.id, message)
    if retired:
        _retire(service.agents, "p")
    _parent, child, grandchild = tree
    _running(child)
    _running(grandchild)
    await asyncio.sleep(0)
    # Odin's own answer, from his manager holding the same tree.
    odin = AgentManager()
    _tree(odin, message)
    if retired:
        _retire(odin, "p")
    expected = odin.kill_with_receipt("p")[0]
    assert expected == ("Agent 'p' already in terminal state: completed. "
                        "Kill signal sent to 2 descendant(s).")

    result = await handler._handle_kill_agent(message, {"agent_id": "p"})

    [control] = _journal(service)
    if retired:
        assert result == f"{expected} Stopped 1 background job(s) it started (PID 41)."
        assert not is_tool_failure(result)
        assert (control["id"], control["action"]) == (_record_id(service, "c"), "cancel")
    else:  # Work's receipt for the parent's own card, as before
        response = json.loads(result)
        assert response["ok"] and response["result"]["jobs"]["summary"] == (
            "Stopped 1 background job(s) it started (PID 41).")
        assert (control["id"], control["action"]) == (_record_id(service, "p"), "cancel")
    assert reaped == [{"c", "g"}]
    await asyncio.gather(child._task, grandchild._task)
    assert child.status == grandchild.status == "killed"


@pytest.mark.asyncio
async def test_an_ended_agent_between_running_ones_is_crossed_once(work, monkeypatch):
    """Odin's review F1: p (ended, cleaned up) > c (running) > t (ended) > g (running). The
    control on c reaches g through t, as Odin's cascade does. A second control on g would
    cancel it again while the first cancel's cleanup runs, and cut that cleanup short."""
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    edges = (("p", None), ("c", "p"), ("t", "c"), ("g", "t"))
    items = _lineage(service.agents, message, *edges)
    for item in items.values():
        service.register("agent", item.id, message)
    for agent_id in ("p", "t"):
        items[agent_id].transition(AgentState.COMPLETED)
    _retire(service.agents, "p")
    cleanup_entered, allow_cleanup, cleaned, reaped = asyncio.Event(), asyncio.Event(), [], []

    def reaper(agent_ids):
        reaped.append(set(agent_ids))
        cleanup = AgentJobCleanup(jobs=[("g1", 41)], starts=0)

        async def settle():  # the jobs' cleanup settles while g's own cleanup still runs
            await cleanup_entered.wait()
            return {"jobs": {"g1": "stopped"}, "starts": []}

        cleanup.task = asyncio.create_task(settle())
        return cleanup

    async def run(item):
        try:
            try:
                await asyncio.sleep(100)
            finally:
                if item.id == "g":
                    cleanup_entered.set()
                    await allow_cleanup.wait()
                    cleaned.append(item.id)
        except asyncio.CancelledError:
            item.transition(AgentState.KILLED)

    service.agents.set_job_reaper(reaper)
    for agent_id in ("c", "g"):
        items[agent_id]._task = asyncio.create_task(run(items[agent_id]))
    await asyncio.sleep(0)
    odin = AgentManager()
    twin = _lineage(odin, message, *edges)
    for agent_id in ("p", "t"):
        twin[agent_id].transition(AgentState.COMPLETED)
    _retire(odin, "p")
    expected = odin.kill_with_receipt("p")[0]
    assert expected.endswith("Kill signal sent to 2 descendant(s).")

    result = await handler._handle_kill_agent(message, {"agent_id": "p"})

    assert result == f"{expected} Stopped 1 background job(s) it started (PID 41)."
    assert [control["id"] for control in _journal(service)] == [_record_id(service, "c")]
    assert reaped == [{"c", "g"}]
    assert (items["c"]._task.cancelling(), items["g"]._task.cancelling()) == (1, 1)
    allow_cleanup.set()
    await asyncio.gather(items["c"]._task, items["g"]._task)
    assert cleaned == ["g"]


@pytest.mark.asyncio
async def test_a_journal_failure_after_the_cancel_keeps_the_outcome_unknown(work, monkeypatch):
    """Odin's review F2: the descendant's cancel was applied, then the journal couldn't record
    its receipt. The kill's answer stays uncertain and never counts that cancel as not sent."""
    from src.desktop.commands import JournalStorageError
    from src.discord.tool_loop import _unwrap_native_result

    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    tree = _tree(service.agents, message)
    for item in tree:
        service.register("agent", item.id, message)
    _retire(service.agents, "p")

    def fail(*_args):
        raise JournalStorageError()

    monkeypatch.setattr(service.controls, "_finish", fail)

    result = await handler._handle_kill_agent(message, {"agent_id": "p"})

    error = response_error("storage_unavailable", "Durable control storage is unavailable",
                           "outcome_unknown")
    _failure(result, "Agent 'p' already in terminal state: completed. Kill signal confirmed for "
                     "0 of 2 running descendant(s); outcome unknown for 2 (outcome_unknown=true). "
                     f"Agent 'c': {json.dumps(error, sort_keys=True)}")
    tool_result, _output = _unwrap_native_result(result)
    assert not tool_result.ok and tool_result.uncertain_outcome
    assert all(item._cancel_event.is_set() for item in tree[1:])  # the cancel was applied
    with service.store.transaction() as db:
        assert [tuple(row) for row in db.execute(
            "SELECT disposition, response FROM desktop_controls")] == [("pending", None)]


@pytest.mark.asyncio
async def test_a_refusal_before_the_cancel_is_a_definite_failure(work, monkeypatch):
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    tree = _tree(service.agents, message)
    for item in tree:
        service.register("agent", item.id, message)
    _retire(service.agents, "p")
    monkeypatch.setattr(service.controls, "work", None)  # refused before any reservation

    result = await handler._handle_kill_agent(message, {"agent_id": "p"})

    error = response_error("capability_unavailable", "Work controls are unavailable")
    _failure(result, "Agent 'p' already in terminal state: completed. Kill signal confirmed for "
                     "0 of 2 running descendant(s). "
                     f"Agent 'c': {json.dumps(error, sort_keys=True)}")
    assert result.uncertain_outcome is False
    assert not any(item._cancel_event.is_set() for item in tree[1:])
    assert _journal(service) == []


@pytest.mark.asyncio
async def test_a_running_descendant_without_a_work_record_is_named(work, monkeypatch):
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    tree = _tree(service.agents, message)
    service.register("agent", "p", message)
    _retire(service.agents, "p")

    result = await handler._handle_kill_agent(message, {"agent_id": "p"})

    _failure(result, "Agent 'p' already in terminal state: completed. Kill signal confirmed for "
                     f"0 of 2 running descendant(s). Agent 'c': {UNAVAILABLE}")
    assert result.uncertain_outcome is False
    assert [item.status for item in tree[1:]] == ["running", "running"]
    assert _journal(service) == []


@pytest.mark.asyncio
async def test_a_live_agent_without_a_work_record_keeps_the_refusal(work, monkeypatch):
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    live = agent(service, message, "live")

    assert await handler._handle_kill_agent(message, {"agent_id": "live"}) == UNAVAILABLE
    assert await handler._handle_send_to_agent(
        message, {"agent_id": "live", "message": "hello"}) == UNAVAILABLE
    assert not live._cancel_event.is_set() and live.inbox_sequence == 0


@pytest.mark.asyncio
async def test_without_the_control_service_every_control_is_refused(work):
    service, message, _context = work
    live = agent(service, message, "live")
    done = agent(service, message, "done")
    for item in (live, done):
        service.register("agent", item.id, message)
    done.transition(AgentState.COMPLETED)
    assert service.controls is None

    for agent_id in ("live", "done", "nobody"):
        assert await service.control_native(message, "agent", agent_id, "cancel") == UNAVAILABLE
    assert not live._cancel_event.is_set()


@pytest.mark.asyncio
async def test_another_owners_request_or_work_learns_nothing(work, monkeypatch):
    service, message, _context = work
    native_controls(service, monkeypatch)
    done = agent(service, message, "done")
    done.transition(AgentState.COMPLETED)
    cid = service.conversations.create()["conversation"]["id"]
    foreign = service.requests.issue("other-owner", cid, "foreign-run")
    for agent_id in ("done", "nobody"):
        assert await service.control_native(foreign, "agent", agent_id, "cancel") == UNAVAILABLE
    done.requester_id = "other-owner"
    assert await service.control_native(message, "agent", "done", "cancel") == UNAVAILABLE


# --- send_to_agent, cancel_task, stop_loop ---------------------------------------------------


@pytest.mark.asyncio
async def test_messaging_an_ended_or_unknown_agent_is_odins_failure(work, monkeypatch):
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    done = agent(service, message, "done")
    service.register("agent", done.id, message)
    done.transition(AgentState.TIMEOUT)

    for agent_id, text in (
            ("done", "Error: Agent 'done' is not running (status: timeout)."),
            ("nobody", "Error: Agent 'nobody' not found.")):
        result = await handler._handle_send_to_agent(
            message, {"agent_id": agent_id, "message": "hello"})
        _failure(result, text)
        assert result == service.agents.send(agent_id, "hello")
    assert done.inbox_sequence == 0


@pytest.mark.asyncio
async def test_cancelling_an_ended_or_unknown_task_is_odins_failure(work, monkeypatch):
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    task = BackgroundTask("task-a", "harmless", [], message.conversation_id, "Owner",
                          requester_id=message.owner_id)
    service.tasks[task.task_id] = task
    service.register("task", task.task_id, message)
    task.status = "completed"

    _failure(await handler._handle_cancel_task(message, {"task_id": "task-a"}),
             "Task `task-a` is not running (status: completed).")
    _failure(await handler._handle_cancel_task(message, {"task_id": "nothing"}),
             "No task found with ID `nothing`.")
    assert await task.request_cancel() is False  # Odin's own check: it isn't running
    assert task.status == "completed"


@pytest.mark.asyncio
async def test_stopping_an_ended_or_unknown_loop_is_odins_failure_and_no_event(work,
                                                                              monkeypatch):
    service, message, _context = work
    handler = native_controls(service, monkeypatch)
    emitted = []

    async def emit(event, data):
        emitted.append(event)

    handler._turn_recorder._emit_lifecycle_event = emit
    loop = LoopInfo("loop-a", "harmless", "silent", 60, None, 2,
                    message.conversation_id, message.owner_id, "Owner", status="stopped")
    service.loops._loops[loop.id] = loop

    for loop_id, text in (("loop-a", "Loop `loop-a` is not running (status: stopped)."),
                          ("nothing", "No loop found with ID `nothing`.")):
        result = await handler._handle_stop_loop(message, {"loop_id": loop_id})
        _failure(result, text)
        assert result == await service.loops.stop_loop(loop_id)
    assert emitted == []  # Odin announces only a loop that was stopped


# --- manage_process kill -----------------------------------------------------------------------


class _Registry:
    """Odin's registry answers, in the states where its kill changes nothing."""

    _remote_cleanup_caveat = staticmethod(ProcessRegistry._remote_cleanup_caveat)

    def __init__(self):
        self._processes = {}

    async def kill(self, pid, *, authorized=None):
        return await ProcessRegistry.kill(self, pid, authorized=authorized)


def _process(message, pid, **kwargs):
    return ProcessInfo(pid, "harmless", "stub", 1, owner_id=message.owner_id,
                       origin_channel=message.conversation_id, generation="g", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
async def test_stopping_an_ended_or_unknown_process_is_the_registrys_answer(work, monkeypatch,
                                                                          remote):
    service, message, _context = work
    native_controls(service, monkeypatch)
    service.processes = _Registry()
    service.processes._processes[778] = _process(
        message, 778, status="completed", session_confirmed_empty=True,
        containment="process_group_only", remote=remote)
    service.register("process", "778", message)
    caveat = " containment=process_group_only; escaped descendants are unverified."

    for pid, text in (("778", "Process 778 already completed." + (caveat if remote else "")),
                      ("779", "No process with PID 779.")):
        result = await service.control_native(message, "process", pid, "stop")
        _failure(result, text)
        assert result == await service.processes.kill(int(pid))


@pytest.mark.asyncio
async def test_a_restored_process_is_read_only_evidence(work, monkeypatch):
    service, message, _context = work
    native_controls(service, monkeypatch)
    service.processes = _Registry()
    restored = _process(message, 780)
    restored.restored = True
    service.processes._processes[780] = restored
    service.register("process", "780", message)

    service.authorize_process = lambda _info: True
    _failure(await service.control_native(message, "process", "780", "stop"),
             "Error: retained process evidence is read-only.")
    assert await service.processes.kill(780, authorized=lambda _info: True) == (
        "Error: retained process evidence is read-only.")
    for authorize in (lambda _info: False, None):
        service.authorize_process = authorize
        _failure(await service.control_native(message, "process", "780", "stop"),
                 "Error: process access denied.")


@pytest.mark.asyncio
@pytest.mark.parametrize(("answer", "code"), [
    (ToolFailure("No process with PID 9."), 1),
    (ToolFailure("Process 9 already completed."), 1),
    (UNAVAILABLE, 1),
    ('{"ok": true, "result": {"disposition": "requested"}}', 0),
])
async def test_manage_process_kill_through_work_keeps_odins_exit_codes(answer, code):
    """Odin's kill exits 1 when there was nothing to stop; Work's answer keeps that."""
    calls = []

    async def control(pid):
        calls.append(pid)
        return answer

    class Registry:
        def output_info(self, pid, cursor):
            return None

    tools = SystemTools.__new__(SystemTools)
    tools._process_registry = lambda: Registry()
    tools._desktop_process_control = control

    assert await tools._handle_manage_process({"action": "kill", "pid": 9}) == (answer, code)
    assert calls == [9]
