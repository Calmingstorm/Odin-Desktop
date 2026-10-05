"""IPC composition of actual managers, sealed requests and durable result reads."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.llm.types import LLMResponse, ToolCall
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, service, settled


class ToolProvider(Provider):
    def __init__(self, name, values):
        super().__init__()
        self.name, self.values = name, values
        self.offered = set()
        self.history = []

    async def chat_with_tools(self, **kwargs):
        self.calls += 1
        self.history.append(kwargs.get("messages", []))
        self.offered.update(tool["name"] for tool in kwargs.get("tools", []))
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall("call", self.name, self.values)],
                               stop_reason="tool_use")
        return LLMResponse(text="The requested work was admitted.")


async def session(tmp_path, provider):
    paths, socket_path, token_file = profile(tmp_path)
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    await core.start(read_fd)
    reader, writer, _ = await connect(socket_path)
    cid = (await request(reader, writer, "conversations.create"))["result"]["conversation"]["id"]
    return core, reader, writer, cid, read_fd, write_fd


async def cleanup(core, writer, read_fd, write_fd):
    writer.close()
    await writer.wait_closed()
    await core.close()
    os.close(read_fd)
    os.close(write_fd)


@pytest.mark.asyncio
async def test_real_core_native_task_uses_retained_dispatch_and_stored_destination(tmp_path):
    provider = ToolProvider("delegate_task", {"description": "Read temporary memory", "steps": [
        {"tool_name": "memory_manage", "tool_input": {"action": "list"}}]})
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    try:
        admitted = await request(reader, writer, "submission.send", {
            "client_submission_id": "task", "conversation_id": cid,
            "text": "Delegate a temporary memory read"})
        assert admitted["ok"]
        await settled(core)
        async with asyncio.timeout(5):
            while any(t.status in {"pending", "running"} for t in
                      core.engine.deps.channel_state.background_tasks.values()):
                await asyncio.sleep(.01)
        tasks = list(core.engine.deps.channel_state.background_tasks.values())
        assert len(tasks) == 1
        assert tasks[0].status == "completed", tasks[0].results
        assert "delegate_task" in provider.offered
        work = (await request(reader, writer, "work.list", {"kind": "task"}))["result"]["items"]
        assert len(work) == 1 and work[0]["state"] == "completed"
        assert work[0]["conversation_id"] == cid
        messages = core.transcript.list(cid)["items"]
        assert any(m["request_id"] == work[0]["request_id"] for m in messages)
        response = await request(reader, writer, "work.control", {
            "control_command_id": "settled-task", "kind": "task", "id": work[0]["id"],
            "action": "cancel"})
        assert response["result"]["disposition"] == "not_available"
    finally:
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
async def test_ipc_schedule_report_read_never_reexecutes_and_control_is_deduplicated(
        tmp_path, monkeypatch):
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, Provider())
    calls = []
    output = json.dumps({"format": "paginated_embed_v1", "pages": [
        {"title": "Stored status", "description": "All quiet"}]})

    async def dispatch(message, tool, values):
        core.requests.assert_request(message)
        calls.append((message.request_id, tool, values))
        return output

    monkeypatch.setattr(core._scheduled_handlers, "_dispatch_tool", dispatch)
    try:
        saved = await request(reader, writer, "schedules.save", {
            "description": "Status report", "action": "check", "channel_id": cid,
            "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "tool_name": "run_command", "tool_input": {"command": "true", "host": "localhost"},
            "report_format": "paginated_embed_v1"})
        assert saved["ok"], saved
        sid = saved["result"]["id"]
        listing = await request(reader, writer, "work.list", {"kind": "schedule"})
        items = listing["result"]["items"]
        assert len(items) == 1
        control = {"control_command_id": "run-check", "kind": "schedule", "id": items[0]["id"],
                   "action": "run_now"}
        ran = await request(reader, writer, "work.control", control)
        assert ran["ok"], ran
        assert len(calls) == 1, ran
        assert (await request(reader, writer, "work.control", control))["result"] == ran["result"]
        assert len(calls) == 1
        messages = core.transcript.list(cid)["items"]
        reports = [a for m in messages for a in m.get("artifacts", []) if a["kind"] == "report"]
        assert len(reports) == 1
        for _ in range(2):
            page = await request(reader, writer, "reports.page", {
                "report_id": reports[0]["ref"], "page": 1})
            assert page["ok"], page
            assert "Stored status" in page["result"]["text"]
        assert len(calls) == 1
        history = await request(reader, writer, "schedules.history", {"id": sid})
        assert history["ok"] and history["result"][-1]["status"] == "success", history
        posture = await request(reader, writer, "turn_state.list", {})
        assert posture["ok"] and posture["result"]["availability"] == "available"
    finally:
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
async def test_real_native_loop_uses_sealed_iteration_and_actual_settlement(tmp_path):
    provider = ToolProvider("start_loop", {"goal": "Read status", "mode": "silent",
        "max_iterations": 1, "interval_seconds": 10})
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    try:
        accepted = await request(reader, writer, "submission.send", {
            "client_submission_id": "loop", "conversation_id": cid,
            "text": "Run one status iteration"})
        assert accepted["ok"]
        await settled(core)
        loops = list(core.engine.deps.loop_manager._loops.values())
        assert len(loops) == 1
        await asyncio.wait_for(loops[0]._task, 5)
        work = (await request(reader, writer, "work.list", {"kind": "loop"}))["result"]["items"]
        assert len(work) == 1
        assert work[0]["state"] == "completed", work
        assert work[0]["settlement"]["state"] == "settled", work
        rows = list(core.store.connection.execute(
            "SELECT r.state FROM desktop_requests r JOIN desktop_background_requests b "
            "ON b.request_id=r.request_id WHERE b.kind='loop_iteration'"))
        assert len(rows) == 1 and rows[0][0] == "completed"
    finally:
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
async def test_real_native_agent_keeps_manager_budgets_and_completion(tmp_path):
    from src.config.schema import OpenAICompatibleModelProfile

    provider = ToolProvider("spawn_agent", {"label": "status", "goal": "Read status"})
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    core.config.agents.model = "compat:test"
    core.config.openai_compatible.model_profiles["test"] = OpenAICompatibleModelProfile(
        total_window_tokens=200000, max_output_tokens=10000, supports_thinking_mode=True)
    core.config.agents.max_iterations = 4
    try:
        accepted = await request(reader, writer, "submission.send", {
            "client_submission_id": "agent", "conversation_id": cid, "text": "Spawn status work"})
        assert accepted["ok"]
        await settled(core)
        agents = list(core.engine.deps.agent_manager._agents.values())
        assert len(agents) == 1, provider.history
        await asyncio.wait_for(agents[0]._task, 5)
        work = (await request(reader, writer, "work.list", {"kind": "agent"}))["result"]["items"]
        assert len(work) == 1 and work[0]["state"] == "completed", work
        assert work[0]["settlement"]["state"] == "settled"
        assert agents[0].iteration_count <= 4
        assert agents[0].requester_id == core.authority.owner_id
        assert core.requests.get_request(work[0]["request_id"])["state"] == "completed"
    finally:
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
async def test_scheduler_background_task_inherits_owner_without_a_window(tmp_path):
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, Provider())
    try:
        saved = await request(reader, writer, "schedules.save", {
            "description": "Quiet reminder", "action": "reminder", "channel_id": cid,
            "run_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
            "message": "The reminder ran without a connected window."})
        assert saved["ok"], saved
        writer.close()
        await writer.wait_closed()
        async with asyncio.timeout(5):
            while not any("The reminder ran without a connected window." in m["text"]
                          for m in core.transcript.list(cid)["items"]):
                await asyncio.sleep(.05)
        async with asyncio.timeout(5):
            while not (history := await core.engine.deps.scheduler.history.query(
                    saved["result"]["id"])):
                await asyncio.sleep(.01)
        assert history[-1]["status"] == "success"
        assert history[-1]["run_binding"]["owner_id"] == core.authority.owner_id
    finally:
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
async def test_schedule_failure_alert_has_separate_settled_delivery_identity(tmp_path, monkeypatch):
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, Provider())
    effects = []

    async def fail(message, *_args):
        core.requests.assert_request(message)
        effects.append(message.request_id)
        raise RuntimeError("Harmless stub failure")

    monkeypatch.setattr(core._scheduled_handlers, "_dispatch_tool", fail)
    try:
        saved = await request(reader, writer, "schedules.save", {
            "description": "Failure notice", "action": "check", "channel_id": cid,
            "cron": "0 0 * * *", "tool_name": "run_command",
            "tool_input": {"command": "true", "host": "localhost"}, "max_retries": 0})
        assert saved["ok"], saved
        for _index in range(3):
            run = await request(reader, writer, "schedules.run", {"id": saved["result"]["id"]})
            assert run["result"]["status"] == "failure", run
        assert len(effects) == 3
        assert any("Scheduled task failing" in m["text"]
                   for m in core.transcript.list(cid)["items"])
        notices = list(core.store.connection.execute(
            "SELECT r.state FROM desktop_requests r JOIN desktop_background_requests b "
            "ON r.request_id=b.request_id WHERE b.run_id LIKE '%:failure:3'"))
        assert len(notices) == 1 and notices[0][0] == "completed"
        assert core.store.connection.execute(
            "SELECT COUNT(*) FROM desktop_requests WHERE state='admitted'").fetchone()[0] == 0
    finally:
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
async def test_native_process_is_registered_with_immutable_public_work_id(tmp_path):
    from src.config.schema import ToolHost

    provider = ToolProvider("manage_process", {"action": "start", "host": "localhost",
                                             "command": "true"})
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider)
    core.config.tools.hosts["localhost"] = ToolHost(address="localhost")
    core.engine.deps.host_registry.publish(core.config.tools.hosts)
    Path(core.config.tools.local_working_dir).mkdir(parents=True, mode=0o700)
    try:
        accepted = await request(reader, writer, "submission.send", {
            "client_submission_id": "process", "conversation_id": cid,
            "text": "Run a harmless disposable process"})
        assert accepted["ok"]
        await settled(core)
        items = (await request(reader, writer, "work.list", {"kind": "process"}))["result"]["items"]
        assert items, json.dumps(provider.history)
        assert len(items) == 1
        assert items[0]["id"] != items[0]["manager_id"]
        assert items[0]["conversation_id"] == cid
        assert items[0]["request_id"] == accepted["result"]["request_id"]
        async with asyncio.timeout(5):
            while (items := (await request(reader, writer, "work.list", {
                    "kind": "process"}))["result"]["items"])[0]["settlement"]["state"] != "settled":
                await asyncio.sleep(.01)
        assert items[0]["settlement"]["resource_release"] == "confirmed"
    finally:
        await cleanup(core, writer, rfd, wfd)
