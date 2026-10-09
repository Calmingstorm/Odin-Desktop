"""Harmless real managers and genuine local owner, no signals/subprocesses."""
from __future__ import annotations

import asyncio
import copy
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from src.agents.manager import AgentInfo, AgentManager, AgentState
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStorageError, JournalStore
from src.desktop.controls import ControlService
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.work import WorkService
from src.discord.background_task import BackgroundTask
from src.discord.channel_state import ChannelStateRegistry
from src.permissions.manager import PermissionManager
from src.tools.autonomous_loop import LoopInfo, LoopManager
from src.tools.process_manager import ProcessInfo


@dataclass(frozen=True)
class Admission:
    owner_id: str
    conversation_id: str
    request_id: str = "run"
    generation: int = 1


class Admissions:
    """Stub admission boundary, not an authorization stub: exact issued identity."""
    def __init__(self):
        self.issued = []

    def issue(self, owner, cid, run="run"):
        message = Admission(owner, cid, run)
        self.issued.append(message)
        return message

    def assert_bound_request(self, message):
        if not any(message is item for item in self.issued):
            raise PermissionError("Unadmitted request")

    assert_preserved_request = assert_bound_request


class Processes:
    def __init__(self):
        self._processes = {}
        self.calls = []

    async def kill(self, pid, *, authorized):
        item = self._processes[pid]
        assert authorized(item)
        self.calls.append(pid)
        item.status = "unknown"  # deliberately unproven, no signal in a test
        return "cleanup unverified"


@pytest.fixture
def work(tmp_path):
    paths = ProfilePaths.from_xdg("test", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    authority.acquire_runtime()
    context = authority.authenticate_local(peer_uid=authority.owner_uid)
    permissions = PermissionManager(authority)
    token = permissions.set_request_owner(context)
    store = JournalStore(paths.data_dir / "journal.sqlite3", "test")
    events = EventJournal(store)
    conversations = ConversationStore(store, events)
    cid = conversations.create()["conversation"]["id"]
    requests = Admissions()
    service = WorkService(store, events, authority=authority, permissions=permissions,
        requests=requests, conversations=conversations, agents=AgentManager(), tasks={},
        loops=LoopManager(), processes=Processes())
    message = requests.issue(context.owner_id, cid)
    yield service, message, context
    store.close()
    permissions.reset_request_owner(token)
    authority.release_runtime()


def bound(record, action, **extra):
    return {key: record[key] for key in ("kind", "id", "manager_generation", "run_id",
            "conversation_id", "generation")} | {"action": action} | extra


def agent(service, message, id="a", **kw):
    item = AgentInfo(id=id, label="test", goal="harmless", channel_id=message.conversation_id,
                     requester_id=message.owner_id, requester_name="Owner", **kw)
    item.transition(AgentState.READY)
    service.agents._agents[id] = item
    return item


def test_only_admitted_manager_work_has_durable_destination(work):
    service, message, _context = work
    item = agent(service, message)
    assert service.list() == {"items": []}
    with pytest.raises(PermissionError):
        service.register("agent", "a", Admission(message.owner_id, message.conversation_id))
    record = service.register("agent", "a", message)
    assert record["run_id"] == message.request_id
    assert record["generation"] == 1
    assert record["conversation_id"] == message.conversation_id
    item.channel_id = "foreign"
    assert service.list()["items"][0]["state"] == "interrupted"
    assert service.list()["items"][0]["actions"] == []


@pytest.mark.asyncio
async def test_process_pid_reuse_cannot_cancel_successor(work):
    service, message, context = work
    item = ProcessInfo(777, "harmless", "stub", 1, owner_id=message.owner_id,
                       origin_channel=message.conversation_id, generation="old")
    service.processes._processes[777] = item
    old = service.register("process", "777", message)
    service.processes._processes[777] = ProcessInfo(777, "successor", "stub", 2,
        owner_id=message.owner_id, origin_channel=message.conversation_id, generation="new")
    receipt = await service.apply(bound(old, "stop"), owner_context=context)
    assert receipt["disposition"] == "not_available"
    assert service.processes.calls == []


@pytest.mark.asyncio
async def test_unknown_process_cleanup_never_becomes_done(work):
    service, message, context = work
    service.authorize_process = lambda _info: True  # this test owns no real host or process
    service.processes._processes[777] = ProcessInfo(777, "harmless", "stub", 1,
        owner_id=message.owner_id, origin_channel=message.conversation_id, generation="g")
    record = service.register("process", "777", message)
    receipt = await service.apply(bound(record, "stop"), owner_context=context)
    assert receipt["disposition"] == "requested"
    assert receipt["settlement"]["state"] == "unknown"
    assert service.processes.calls == [777]


@pytest.mark.asyncio
async def test_process_control_requires_current_retained_authorizer(work):
    service, message, context = work
    service.processes._processes[777] = ProcessInfo(777, "harmless", "stub", 1,
        owner_id=message.owner_id, origin_channel=message.conversation_id, generation="g")
    record = service.register("process", "777", message)
    refused = await service.apply(bound(record, "stop"), owner_context=context)
    assert refused["error"]["code"] == "unauthorized"
    service.authorize_process = lambda _info: False
    refused = await service.apply(bound(record, "stop"), owner_context=context)
    assert refused["error"]["code"] == "unauthorized"
    assert service.processes.calls == []


@pytest.mark.asyncio
async def test_parent_correction_is_queued_not_consumed_and_budgets_unchanged(work):
    service, message, context = work
    item = agent(service, message, max_iterations=7, max_children=2, max_depth=1)
    record = service.register("agent", "a", message)
    receipt = await service.apply(bound(record, "steer", text="correct the goal"),
                                  owner_context=context)
    assert receipt["disposition"] == "queued"
    assert receipt["consumed"] is False
    assert item.last_consumed_sequence == 0
    assert item.inbox_sequence == 1
    assert (item.max_iterations, item.max_children, item.max_depth) == (7, 2, 1)
    item.transition(AgentState.COMPLETED)
    terminal = service.list()["items"][0]
    assert terminal["detail"]["inbox_events"][0]["event"] == "queued"
    assert terminal["actions"] == []


def test_display_execution_missing_provenance_is_unknown_not_live_config(work):
    service, message, _context = work
    item = agent(service, message)
    item.has_executed = True
    service.display_config = SimpleNamespace(config=SimpleNamespace(
        openai_codex=SimpleNamespace(model="live-model", reasoning_effort="high")))
    record = service.register("agent", "a", message)
    assert record["detail"]["display_source"] == "last_execution"
    assert record["detail"]["display_model"] == ""
    assert record["detail"]["display_reasoning_effort"] == ""


@pytest.mark.asyncio
async def test_terminal_parent_does_not_claim_tree_completion(work):
    service, message, context = work
    parent = agent(service, message)
    child = agent(service, message, "child", parent_id="a", root_id="a")
    parent.children_ids.append(child.id)
    parent.transition(AgentState.COMPLETED)
    child._task = asyncio.create_task(asyncio.sleep(100))
    record = service.register("agent", "a", message)
    assert record["settlement"]["state"] == "pending"
    assert record["detail"]["unsettled_descendants"] == ["child"]
    receipt = await service.apply(bound(record, "cancel"), owner_context=context)
    assert receipt["disposition"] == "requested"
    await asyncio.gather(child._task, return_exceptions=True)
    child.transition(AgentState.KILLED)
    assert service.list()["items"][0]["settlement"]["state"] == "settled"


@pytest.mark.asyncio
async def test_task_status_before_teardown_is_not_settlement(work):
    service, message, _context = work
    item = BackgroundTask("t", "noop", [], message.conversation_id, "Owner",
                          requester_id=message.owner_id)
    release = asyncio.Event()
    item._asyncio_task = asyncio.create_task(release.wait())
    service.tasks["t"] = item
    record = service.register("task", "t", message)
    item.status = "cancelled"
    assert service.refresh(record)["settlement"]["state"] == "pending"
    release.set()
    await item._asyncio_task
    await asyncio.sleep(0)
    assert service.list()["items"][0]["settlement"]["state"] == "settled"


def test_reopen_without_manager_retains_binding_unknown_no_replay(work):
    service, message, _context = work
    agent(service, message)
    original = service.register("agent", "a", message)
    service.agents._agents.clear()
    saved = service.list()["items"][0]
    assert saved["run_id"] == original["run_id"]
    assert saved["manager_generation"] == original["manager_generation"]
    assert saved["settlement"]["state"] == "unknown"
    assert saved["actions"] == []


@pytest.mark.asyncio
async def test_session_or_payload_owner_never_authorizes_control(work):
    service, message, context = work
    agent(service, message)
    record = service.register("agent", "a", message)
    forged = SimpleNamespace(**{key: getattr(context, key) for key in
        ("owner_id", "profile_id", "runtime_id", "installation_id", "owner_uid")})
    receipt = await service.apply(bound(record, "cancel", owner_id=context.owner_id,
                                       session_token="irrelevant"), owner_context=forged)
    assert receipt["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_native_control_routes_bound_command_to_control_service(work):
    service, message, _context = work
    agent(service, message)
    record = service.register("agent", "a", message)
    calls = []
    class Controls:
        async def dispatch(self, method, params):
            calls.append((method, params))
            return {"disposition": "requested"}
    service.controls = Controls()
    await service.control_native(message, "agent", "a", "cancel")
    assert calls[0][0] == "work.control"
    assert calls[0][1]["run_id"] == record["run_id"]
    assert calls[0][1]["manager_generation"] == record["manager_generation"]
    assert service.agents._agents["a"]._cancel_event.is_set() is False


@pytest.mark.asyncio
async def test_loop_stop_observes_actual_settlement(work):
    service, message, context = work
    item = LoopInfo("loop", "harmless", "silent", 60, None, 2,
                    message.conversation_id, message.owner_id, "Owner")
    item._task = asyncio.create_task(asyncio.sleep(100))
    service.loops._loops[item.id] = item
    record = service.register("loop", item.id, message)
    receipt = await service.apply(bound(record, "stop"), owner_context=context)
    assert item._task.done()
    assert receipt["disposition"] == "done"
    assert receipt["settlement"]["resource_release"] == "manager_task_finished"


@pytest.mark.asyncio
async def test_schedule_identity_revision_and_actual_run_settlement(work):
    service, message, context = work
    schedule = {"id": "s", "_generation": "schedule-generation", "_revision": 4,
                "created_at": "fixed", "requester_id": message.owner_id,
                "channel_id": message.conversation_id, "description": "harmless",
                "paused": False, "last_run_binding": {"run_id": "prior-run"},
                "settlement": {"state": "unknown"}}
    class Scheduler:
        def list_all(self):
            return [schedule]

        async def desktop_control(self, id, action, *, expected_binding):
            # A harmless stub, the actual scheduler must check under its lock.
            assert id == "s" and action == "pause"
            assert expected_binding == {"generation": "schedule-generation", "revision": 4,
                                        "owner_id": message.owner_id,
                                        "conversation_id": message.conversation_id}
            schedule["paused"] = True
            schedule["_revision"] += 1
            return {"disposition": "done"}
    service.scheduler = Scheduler()
    record = service.register_schedule(schedule)
    assert record["manager_generation"] == "schedule-generation"
    assert record["detail"]["last_run_binding"] == {"run_id": "prior-run"}
    stale = await service.apply(bound(record, "pause", revision=3), owner_context=context)
    assert stale["reason"] == "stale_revision"
    receipt = await service.apply(bound(record, "pause", revision=4), owner_context=context)
    assert receipt["disposition"] == "done"
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "paused"
    assert receipt["settlement"]["last_run"]["state"] == "unknown"


def test_unqualified_schedule_controls_not_advertised(work):
    service, message, _context = work
    schedule = {"id": "s", "created_at": "immutable", "requester_id": message.owner_id,
                "channel_id": message.conversation_id}
    service.scheduler = SimpleNamespace(list_all=lambda: [schedule])
    assert service.register_schedule(schedule)["actions"] == []



_SAME = object()


def _ended_schedule(work, tmp_path, history_lines, latest_run="r1", *, removed_run=_SAME,
                    removal=True, removed_generation="g1", binding_generation="g1"):
    """A registered schedule its scheduler then removed, with a harmless history file.

    `latest_run` is the latest run Work heard start; None means it heard none.
    `removed_run` is the latest run the scheduler's removal record names (by default the
    same run; None means the definition never ran). Without `removal` the scheduler has
    no record of removing it, as after a removal by an older version.
    """
    service, message, _context = work
    def binding(run_id, generation="g1"):
        return {"run_id": run_id, "generation": generation} if run_id else None
    schedule = {"id": "s", "_generation": "g1", "created_at": "fixed",
                "requester_id": message.owner_id, "channel_id": message.conversation_id,
                "description": "harmless", "settlement": "completed",
                "last_run_binding": binding(latest_run)}
    held, removed = [schedule], []
    history = tmp_path / "schedule_history.jsonl"
    history.write_text("".join(line + "\n" for line in history_lines))
    service.scheduler = SimpleNamespace(
        list_all=lambda: list(held), _in_flight=set(), history=SimpleNamespace(path=history),
        removed_definition=lambda sid: next((dict(r) for r in removed if r["id"] == sid), None))
    record = service.register_schedule(schedule)
    assert record["state"] == "scheduled"
    held.clear()
    if removal:
        removed.append({"id": "s", "generation": removed_generation, "run_binding": None,
                        "last_run_binding": binding(
                            latest_run if removed_run is _SAME else removed_run,
                            binding_generation)})
    return service


def _run(status, run_id="r1", generation="g1", schedule_id="s"):
    import json as _json
    return _json.dumps({"schedule_id": schedule_id, "status": status,
                        "run_binding": {"generation": generation, "run_id": run_id}})


@pytest.mark.parametrize(("history", "latest", "expected"), [
    ([_run("success")], "r1", "completed"),
    ([_run("failure")], "r1", "failed"),
    ([_run("unknown")], "r1", "unknown"),
    ([_run("failure", "r0"), _run("success")], "r1", "completed"),
    ([_run("success"), _run("failure", "r0")], "r1", "completed"),  # only the latest run counts
    ([_run("success", "r0")], "r1", "unknown"),    # the latest run left no entry: not the older
    ([], "r1", "unknown"),
    ([_run("success", schedule_id="other")], "r1", "unknown"),
    ([], None, "cancelled"),                       # no run was ever admitted
    (["not json", _run("success")], "r1", "completed"),
])
def test_schedule_the_scheduler_dropped_ends_with_its_latest_run(work, tmp_path, history, latest,
                                                                 expected):
    service = _ended_schedule(work, tmp_path, history, latest)
    item = service.list({"kind": "schedule"})["items"][0]
    assert item["state"] == expected
    assert item["settlement"]["state"] == ("unknown" if expected == "unknown" else "settled")
    assert item["actions"] == []


@pytest.mark.parametrize(("history", "expected"), [
    ([_run("success", "r1"), _run("failure", "r2")], "failed"),
    ([_run("success", "r1")], "unknown"),          # r2 left no entry: never r1's success
    ([_run("success", "r1"), _run("success", "r2")], "completed"),
])
def test_removed_schedule_settles_from_the_scheduler_record_not_works_older_binding(
        work, tmp_path, history, expected):
    """Work last heard r1 start; the scheduler removed the definition after r2."""
    service = _ended_schedule(work, tmp_path, history, "r1", removed_run="r2")
    item = service.list({"kind": "schedule"})["items"][0]
    assert item["state"] == expected
    assert item["detail"]["last_run_binding"]["run_id"] == "r2"


@pytest.mark.parametrize("missing", ["no_record", "other_generation"])
def test_removed_schedule_without_its_removal_record_is_unknown(work, tmp_path, missing):
    """Removed by an older version, or the record was pruned: the latest run can't be named,
    so even Work's own binding with a matching success settles nothing."""
    service = _ended_schedule(work, tmp_path, [_run("success")], "r1",
                              removal=missing == "other_generation",
                              removed_generation="g0")
    item = service.list({"kind": "schedule"})["items"][0]
    assert item["state"] == "unknown" and item["settlement"]["state"] == "unknown"


def test_removed_schedule_whose_latest_run_is_an_earlier_generations_is_unknown(work, tmp_path):
    """The definition moved to a new generation after its last run: that run isn't this
    generation's, and nothing says this generation never ran."""
    service = _ended_schedule(work, tmp_path, [_run("success")], "r1", binding_generation="g0")
    item = service.list({"kind": "schedule"})["items"][0]
    assert item["state"] == "unknown" and item["settlement"]["state"] == "unknown"


def test_schedule_is_not_ended_without_a_scheduler_or_while_it_is_held(work, tmp_path):
    service = _ended_schedule(work, tmp_path, [_run("success")])
    scheduler = service.scheduler
    service.scheduler = None  # not loaded: nothing can be concluded about its schedules
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "scheduled"
    service.scheduler = scheduler
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "completed"


def test_schedule_without_run_tracking_concludes_nothing(work, tmp_path):
    service = _ended_schedule(work, tmp_path, [_run("success")])
    del service.scheduler._in_flight  # another scheduler adapter: running state unknown
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "scheduled"


async def _real_schedule(work, tmp_path, run, action="reminder", one_time=False):
    """A real Scheduler wired as CoreService wires it: its run observer registers each run
    with Work as it starts. `run` is the inert action body: the callback for a reminder, the
    outbound executor (no HTTP) for a webhook, which never reaches the callback."""
    from datetime import UTC, datetime, timedelta

    from src.scheduler.scheduler import Scheduler
    service, message, _context = work
    scheduler = Scheduler(str(tmp_path / "schedules.json"), desktop_recovery=True)
    service.scheduler = scheduler
    scheduler.run_observer = service.register_schedule
    if action == "webhook":
        async def execute(config):
            await run(config)
            return {"status_code": 200}

        async def no_callback(schedule):
            raise AssertionError("a webhook action never runs the callback")

        scheduler._execute_webhook = execute
        scheduler._callback = no_callback
        extra = {"webhook_config": {"url": "https://example.invalid/inert", "method": "POST"}}
    else:
        scheduler._callback = run
        extra = {}
    when = ({"run_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()} if one_time
            else {"cron": "0 0 * * *"})
    schedule = await scheduler.add(f"inert {action}", action, message.conversation_id,
                                   requester_id=message.owner_id, **when, **extra)
    service.register_schedule(schedule)
    return service, scheduler, schedule


async def _earlier_success(service, scheduler, schedule):
    """A completed earlier run that Work has seen, as its last run."""
    await scheduler.run_now(schedule["id"])
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "scheduled"


def _lose_next_work_write(service):
    """Exactly the next Work transaction fails, as a locked database would; later ones work."""
    import sqlite3
    real, pending = service.store.transaction, [True]

    def transaction(*args, **kwargs):
        if pending[0]:
            pending[0] = False
            raise sqlite3.OperationalError("inert: database is locked")
        return real(*args, **kwargs)
    service.store.transaction = transaction
    return pending


def _durable_run_ids(service):
    """The run IDs Work's stored schedule record names, read without a Work refresh."""
    import json as _json
    with service.store.transaction() as connection:
        [row] = connection.execute(
            "SELECT record FROM desktop_work WHERE kind='schedule'").fetchall()
    detail = _json.loads(row[0])["detail"]
    return {(detail.get(key) or {}).get("run_id") for key in ("run_binding", "last_run_binding")}


def _restarted(service, tmp_path):
    from src.scheduler.scheduler import Scheduler
    again = WorkService(service.store, service.events, authority=service.authority,
        permissions=service.permissions, requests=service.requests,
        conversations=service.conversations, agents=AgentManager(), tasks={},
        loops=LoopManager(), processes=Processes())
    again.scheduler = Scheduler(str(tmp_path / "schedules.json"), desktop_recovery=True)
    return again


@pytest.mark.parametrize("action", ["reminder", "webhook"])
@pytest.mark.parametrize("earlier", [False, True])
@pytest.mark.parametrize("notice", ["observed", "lost"])
@pytest.mark.parametrize(("ending", "expected"), [
    ("success", "completed"),            # its own success
    ("failure", "failed"),               # an earlier success never settles a failing run
    ("cancel", "unknown"),               # cancelled: no entry for this run
    ("history_unavailable", "unknown"),  # the run's entry couldn't be written
])
async def test_schedule_deleted_while_running_settles_only_from_that_run(
        work, tmp_path, action, earlier, notice, ending, expected):
    """`lost`: the Work write as the newest run starts fails once, so Work never hears it
    start. Nothing reads Work during the run; a restarted Work reads first."""
    started, finish, failing, seen = asyncio.Event(), asyncio.Event(), [False], {}

    async def run(_payload):
        current = next(s for s in seen["scheduler"].list_all() if s["id"] == seen["id"])
        seen["run_id"] = current["run_binding"]["run_id"]
        started.set()
        await finish.wait()
        if failing[0]:
            raise RuntimeError("inert run failure")

    service, scheduler, schedule = await _real_schedule(work, tmp_path, run, action)
    seen.update(scheduler=scheduler, id=schedule["id"])
    if earlier:
        finish.set()
        await _earlier_success(service, scheduler, schedule)
        started.clear()
        finish.clear()
    failing[0] = ending == "failure"
    if ending == "history_unavailable":
        async def unavailable(**_entry):
            raise OSError("inert: history disk unavailable")
        scheduler.history.record = unavailable
    lost = _lose_next_work_write(service) if notice == "lost" else [False]
    running = asyncio.create_task(scheduler.run_now(schedule["id"]))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await scheduler.delete(schedule["id"])  # no Work read while it runs
        if ending == "cancel":
            running.cancel()
    finally:
        finish.set()
        try:
            await running
        except (asyncio.CancelledError, OSError):
            pass
    assert lost == [False]  # the observer's write took the one failure
    assert (seen["run_id"] in _durable_run_ids(service)) == (notice == "observed")
    for view in (_restarted(service, tmp_path), service):
        item = view.list({"kind": "schedule"})["items"][0]
        assert item["state"] == expected
        assert item["settlement"]["state"] == ("unknown" if expected == "unknown" else "settled")
        assert item["detail"]["run_binding"]["run_id"] == seen["run_id"]


@pytest.mark.parametrize("action", ["reminder", "webhook"])
async def test_schedule_deleted_while_running_shows_running(work, tmp_path, action):
    started, finish = asyncio.Event(), asyncio.Event()

    async def run(_payload):
        started.set()
        await finish.wait()

    service, scheduler, schedule = await _real_schedule(work, tmp_path, run, action)
    running = asyncio.create_task(scheduler.run_now(schedule["id"]))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await scheduler.delete(schedule["id"])
        during = service.list({"kind": "schedule"})["items"][0]
        assert during["state"] == "running" and during["settlement"]["state"] == "pending"
    finally:
        finish.set()
        await running
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "completed"


@pytest.mark.parametrize("action", ["reminder", "webhook"])
@pytest.mark.parametrize("notice", ["observed", "lost"])
async def test_one_time_schedule_retired_after_its_run_ends_completed(
        work, tmp_path, action, notice):
    seen = {}

    async def run(_payload):
        current = next(s for s in seen["scheduler"].list_all() if s["id"] == seen["id"])
        seen["run_id"] = current["run_binding"]["run_id"]

    service, scheduler, schedule = await _real_schedule(work, tmp_path, run, action, one_time=True)
    seen.update(scheduler=scheduler, id=schedule["id"])
    lost = _lose_next_work_write(service) if notice == "lost" else [False]
    await scheduler.run_now(schedule["id"])
    assert scheduler.list_all() == []  # the scheduler retired it itself
    assert lost == [False]
    assert (seen["run_id"] in _durable_run_ids(service)) == (notice == "observed")
    for view in (_restarted(service, tmp_path), service):
        item = view.list({"kind": "schedule"})["items"][0]
        assert item["state"] == "completed" and item["settlement"]["state"] == "settled"
        assert item["detail"]["run_binding"]["run_id"] == seen["run_id"]


@pytest.mark.parametrize("action", ["reminder", "webhook"])
@pytest.mark.parametrize("damage", [
    None,                    # the complete record: the cancelled newest run is unknown
    "missing_bindings",      # never "no run", so never cancelled
    "current_binding_list",  # never the older binding, so never the older success
    "unsupported_version",   # with the newest binding gone, as if the format changed
])
async def test_damaged_removal_record_settles_nothing_after_a_restart(
        work, tmp_path, action, damage):
    import json
    started, finish = asyncio.Event(), asyncio.Event()

    async def run(_payload):
        started.set()
        await finish.wait()

    service, scheduler, schedule = await _real_schedule(work, tmp_path, run, action)
    finish.set()
    await _earlier_success(service, scheduler, schedule)
    started.clear()
    finish.clear()
    running = asyncio.create_task(scheduler.run_now(schedule["id"]))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await scheduler.delete(schedule["id"])
        running.cancel()
    finally:
        finish.set()
        try:
            await running
        except asyncio.CancelledError:
            pass
    path = scheduler.data_path.with_name("schedules_removed.json")
    doc = json.loads(path.read_text())
    record = doc["removed"][-1]
    assert record["run_binding"]["run_id"] != record["last_run_binding"]["run_id"]
    if damage == "missing_bindings":
        del record["run_binding"], record["last_run_binding"]
    elif damage == "current_binding_list":
        record["run_binding"] = []
    elif damage == "unsupported_version":
        doc["version"], record["run_binding"] = 999, None
    path.write_text(json.dumps(doc))
    for view in (_restarted(service, tmp_path), service):
        item = view.list({"kind": "schedule"})["items"][0]
        assert item["state"] == "unknown" and item["settlement"]["state"] == "unknown"


@pytest.mark.parametrize("action", ["reminder", "webhook"])
async def test_real_schedule_deleted_before_it_ever_ran_ends_cancelled(work, tmp_path, action):
    async def run(_payload):
        raise AssertionError("never runs")

    service, scheduler, schedule = await _real_schedule(work, tmp_path, run, action)
    await scheduler.delete(schedule["id"])
    for view in (_restarted(service, tmp_path), service):
        item = view.list({"kind": "schedule"})["items"][0]
        assert item["state"] == "cancelled" and item["settlement"]["state"] == "settled"


@pytest.mark.parametrize("failed", [False, True])
async def test_idle_real_schedule_deleted_after_a_run_ends_with_it(work, tmp_path, failed):
    async def run(_payload):
        if failed:
            raise RuntimeError("inert run failure")

    service, scheduler, schedule = await _real_schedule(work, tmp_path, run)
    await scheduler.run_now(schedule["id"])
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "scheduled"
    await scheduler.delete(schedule["id"])
    item = service.list({"kind": "schedule"})["items"][0]
    assert item["state"] == ("failed" if failed else "completed")


def test_a_failing_run_observer_never_stops_the_run(tmp_path):
    from src.scheduler.scheduler import Scheduler
    scheduler = Scheduler(str(tmp_path / "schedules.json"), desktop_recovery=True)
    seen = []

    def broken(definition):
        seen.append(definition["run_binding"]["run_id"])
        raise RuntimeError("inert observer failure")

    scheduler.run_observer = broken
    schedule = {"id": "s", "run_binding": {"run_id": "r1"}}
    scheduler._schedules = [copy.deepcopy(schedule)]
    scheduler._observe_run_start(schedule)  # logged, not raised
    assert seen == ["r1"]

    def mutating(definition):
        definition["run_binding"]["run_id"] = "changed by the observer"
    scheduler.run_observer = mutating
    scheduler._observe_run_start(schedule)
    assert scheduler._schedules == [schedule]  # the observer gets a copy
    scheduler._observe_run_start({"id": "s", "run_binding": {"run_id": "other"}})
    assert seen == ["r1"]  # a stale binding is never reported as the starting run


def test_ended_schedule_keeps_its_state_after_later_history(work, tmp_path):
    service = _ended_schedule(work, tmp_path, [], latest_run=None)
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "cancelled"
    service.scheduler.history.path.write_text(_run("success") + "\n")
    assert service.list({"kind": "schedule"})["items"][0]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_runtime_owner_revocation_denies_existing_control(work):
    service, message, context = work
    agent(service, message)
    record = service.register("agent", "a", message)
    service.authority.release_runtime()
    receipt = await service.apply(bound(record, "cancel"), owner_context=context)
    assert receipt["error"]["code"] == "unauthorized"
    assert service.agents._agents["a"]._cancel_event.is_set() is False


def test_manager_prune_retains_actual_terminal_not_interrupted(work):
    service, message, _context = work
    item = agent(service, message)
    item.transition(AgentState.COMPLETED)
    record = service.register("agent", "a", message)
    assert record["settlement"]["state"] == "settled"
    service.agents._agents.clear()
    assert service.list()["items"][0]["state"] == "completed"
    assert service.list()["items"][0]["actions"] == []


def test_registration_never_rebinds_existing_manager_generation(work):
    service, message, _context = work
    agent(service, message)
    service.register("agent", "a", message)
    successor = service.requests.issue(message.owner_id, message.conversation_id, "other-run")
    with pytest.raises(ValueError, match="another binding"):
        service.register("agent", "a", successor)
    assert service.list()["items"][0]["run_id"] == message.request_id


def test_registration_parent_cannot_change_destination_or_owner(work):
    service, message, _context = work
    agent(service, message)
    foreign = service.requests.issue("other-owner", message.conversation_id)
    with pytest.raises(PermissionError, match="admission binding"):
        service.register("agent", "a", foreign, parent_message=message)
    assert service.list() == {"items": []}


def test_work_publication_is_transactional_on_storage_failure(work, monkeypatch):
    service, message, _context = work
    item = agent(service, message)
    record = service.register("agent", "a", message)
    item.transition(AgentState.COMPLETED)
    def unavailable(*_args, **_kw):
        raise OSError("journal unavailable")
    monkeypatch.setattr(service.events, "append", unavailable)
    with pytest.raises(JournalStorageError):
        service.refresh(record)
    saved = service.binding(bound(record, "cancel"))
    assert saved["state"] == "running"
    assert saved["settlement"]["state"] == "pending"


def test_protocol_work_id_does_not_retarget_reused_manager_id(work):
    service, message, _context = work
    first = agent(service, message)
    old = service.register("agent", first.id, message)
    service.agents._agents.clear()
    successor = agent(service, message)
    successor.created_at += 1
    new_message = service.requests.issue(message.owner_id, message.conversation_id, "new-run")
    new = service.register("agent", successor.id, new_message)
    assert old["id"] != new["id"]
    assert old["manager_id"] == new["manager_id"]
    assert service.resolve("agent", old["id"])["actions"] == []
    assert service.resolve("agent", new["id"])["actions"] == ["cancel", "steer"]


@pytest.mark.asyncio
async def test_revocation_while_waiting_work_lock_cannot_dispatch(work):
    service, message, context = work
    agent(service, message)
    record = service.register("agent", "a", message)
    lock = asyncio.Lock()
    await lock.acquire()
    service._locks[("agent", "a")] = lock
    control = asyncio.create_task(service.apply(bound(record, "cancel"), owner_context=context))
    await asyncio.sleep(0)
    service.authority.release_runtime()
    lock.release()
    receipt = await control
    assert receipt["error"]["code"] == "unauthorized"
    assert service.agents._agents["a"]._cancel_event.is_set() is False


@pytest.mark.asyncio
async def test_admitted_loop_cancel_before_first_instruction_settles_stopped(work):
    service, message, _context = work
    entered = []
    settled = []
    @asynccontextmanager
    async def execution(info):
        entered.append(info.id)
        yield
    async def publish(*_args):
        raise AssertionError("cancelled loop must not publish an iteration")
    async def iteration(*_args):
        raise AssertionError("cancelled loop must not execute an iteration")
    id = service.loops.start_admitted_loop("harmless", SimpleNamespace(id=message.conversation_id),
        message.owner_id, "Owner", iteration, before_start=lambda _info: None,
        execution=execution, publish=publish, on_settled=lambda info: settled.append(info.status))
    info = service.loops._loops[id]
    info._task.cancel()
    await asyncio.gather(info._task, return_exceptions=True)
    await asyncio.sleep(0)
    assert entered == []
    assert settled == ["stopped"]
    assert info.status == "stopped"


@pytest.mark.asyncio
async def test_real_control_service_minimal_protocol_duplicate_does_not_repeat(work):
    service, message, _context = work
    item = agent(service, message)
    record = service.register("agent", "a", message)
    controls = ControlService(service.store, service.events, service.requests,
        ChannelStateRegistry(), authority=service.authority, permissions=service.permissions)
    controls.work = service
    service.controls = controls
    params = {"control_command_id": "once", "kind": "agent", "id": record["id"],
              "action": "steer", "text": "parent correction"}
    first = await controls.dispatch("work.control", params)
    assert first["ok"]
    assert first["result"]["disposition"] == "queued"
    assert item.inbox_sequence == 1
    item.transition(AgentState.COMPLETED)
    repeat = await controls.dispatch("work.control", params)
    assert repeat == first
    assert item.inbox_sequence == 1
    changed = await controls.dispatch("work.control", dict(params, text="different"))
    assert changed["error"]["code"] == "id_conflict"


@pytest.mark.asyncio
async def test_real_control_service_pending_receipt_is_unknown_not_replayed(work, monkeypatch):
    service, message, _context = work
    item = agent(service, message)
    record = service.register("agent", "a", message)
    controls = ControlService(service.store, service.events, service.requests,
        ChannelStateRegistry(), authority=service.authority, permissions=service.permissions)
    controls.work = service
    calls = []
    async def dispatched_then_unknown(*_args, **_kw):
        calls.append("dispatch")
        raise RuntimeError("lost receipt")
    monkeypatch.setattr(service, "apply", dispatched_then_unknown)
    params = {"control_command_id": "unknown", "kind": "agent", "id": record["id"],
              "action": "cancel"}
    first = await controls.dispatch("work.control", params)
    assert first["error"]["disposition"] == "outcome_unknown"
    second = await controls.dispatch("work.control", params)
    assert second["error"]["disposition"] == "outcome_unknown"
    assert calls == ["dispatch"]
    assert item._cancel_event.is_set() is False
