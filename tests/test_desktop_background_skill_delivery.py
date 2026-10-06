"""Independent retained managers execute real SkillContext delivery after admission.

Only the external model boundary is deterministic. Request sealing, native
dispatch, SkillManager, host reads, manager workers and durable publication are
the real profile-local engine composition, not foreground child-task substitutes.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.config.schema import OpenAICompatibleModelProfile, ToolHost
from src.discord.response_guards import scrub_response_secrets
from src.llm.types import LLMResponse, ToolCall
from src.tools.output_authorization import host_binding
from tests.test_desktop_background_core import cleanup, session
from tests.test_desktop_core_lifecycle import request
from tests.test_desktop_request_core import Provider, settled

SKILL_NAME = "background_delivery_probe"
SKILL_SOURCE = '''
SKILL_DEFINITION = {
    "name": "background_delivery_probe", "description": "Profile-local delivery proof",
    "input_schema": {"type": "object", "properties": {
        "path": {"type": "string"}, "fail_after_stage": {"type": "boolean"}},
        "required": ["path"]}}
CONTEXT = None
READ = None
EXECUTIONS = 0
async def execute(inp, context):
    global CONTEXT, READ, EXECUTIONS
    CONTEXT = context
    EXECUTIONS += 1
    READ = await context.read_file("localhost", inp["path"], raw=True)
    if "host-read-marker" not in READ:
        raise ValueError("The real local read did not return the fixture")
    await context.post_message("background exact marker\\npassword=fixture-secret")
    await context.post_file(READ.encode("utf-8"), "host-proof.txt", "host caption")
    await context.post_file(b"opaque\\x00\\xffbytes", "opaque.bin", "binary caption")
    await context.post_message("Files staged, not attached to this interim notice.")
    if inp.get("fail_after_stage"):
        raise ValueError("Harmless fixture failure after durable staging")
    return "Background delivery complete."
'''


async def wait_until(predicate, *, timeout=30):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.01)


class IndependentProvider(Provider):
    """Gate only model responses, never admission, manager or delivery authority."""

    def __init__(self, kind, source_path, fail_after_stage=False):
        super().__init__()
        self.kind, self.source_path = kind, source_path
        self.fail_after_stage = fail_after_stage
        self.origin = None
        self.origin_calls = 0
        self.worker_calls = 0
        self.worker_entered = asyncio.Event()
        self.worker_release = asyncio.Event()
        self.final_entered = asyncio.Event()
        self.final_release = asyncio.Event()
        self.worker_message = None
        self.offered = set()

    async def chat_with_tools(self, **kwargs):
        self.calls += 1
        message = self.core.requests.current_bound_request()
        self.offered.update(tool["name"] for tool in kwargs.get("tools", []))
        if self.core.requests.is_background(message):
            self.worker_message = message
            self.worker_calls += 1
            if self.worker_calls == 1:
                self.worker_entered.set()
                await self.worker_release.wait()
                assert self.core.requests.get_request(self.origin)["state"] == "completed"
                skills = self.core.engine.deps.native_tools.skills
                # Real authority remains active; changing the envelope does not
                # make its owner, destination or generation admissible.
                for foreign in (replace(message, request_id=self.origin),
                                replace(message, conversation_id="wrong-conversation"),
                                replace(message, generation=message.generation + 1)):
                    with pytest.raises(PermissionError):
                        await skills._skill_message_cb(foreign)("wrong request")
                    for mode in ("send", "stage"):
                        with pytest.raises(PermissionError):
                            await skills._skill_file_cb(foreign, mode, SKILL_NAME)(
                                b"wrong", "wrong.txt")
                return LLMResponse(tool_calls=[ToolCall("deliver", "invoke_skill", {
                    "name": SKILL_NAME, "input": {"path": str(self.source_path)}})],
                    stop_reason="tool_use")
            self.final_entered.set()
            await self.final_release.wait()
            return LLMResponse(text="Background final result.")
        if self.origin is None:
            self.origin = message.request_id
        if message.request_id != self.origin:
            return LLMResponse(text="Later foreground result, with no background files.")
        self.origin_calls += 1
        if self.origin_calls != 1:
            return LLMResponse(text="The independent work was admitted.")
        if self.kind == "schedule":
            # Define native scheduled work, then exercise schedules.run after
            # origin settlement, through its independent scheduler admission.
            tool, values = "schedule_task", {
                "description": "Independent skill delivery", "action": "workflow",
                "run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "steps": [{"tool_name": "invoke_skill", "tool_input": {
                    "name": SKILL_NAME, "input": {"path": str(self.source_path),
                        "fail_after_stage": self.fail_after_stage}}}], "max_retries": 0}
        elif self.kind == "agent":
            tool, values = "spawn_agent", {
                "label": "independent-delivery", "goal": "Execute the delivery probe"}
        else:
            tool, values = "start_loop", {
                "goal": "Execute the delivery probe", "mode": "notify",
                "interval_seconds": 10, "max_iterations": 1}
        return LLMResponse(tool_calls=[ToolCall("admit", tool, values)],
                           stop_reason="tool_use")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,mode,fail_after_stage", [
    ("schedule", "stage", False), ("schedule", "send", False),
    ("schedule", "stage", True), ("agent", "send", False),
    ("agent", "stage", False), ("loop", "send", False), ("loop", "stage", False)])
async def test_independent_background_skill_delivery_preserves_authority_and_stages_final(
        tmp_path, kind, mode, fail_after_stage):
    source = tmp_path / "host-source.txt"
    source.write_text("host-read-marker\nsecond source line\n", encoding="utf-8")
    provider = IndependentProvider(kind, source, fail_after_stage)
    # Correctness proof on a shared host, not a setup latency SLA.
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider, setup_timeout=30)
    try:
        config = core.config
        config.agents.model = "compat:test"
        config.agents.max_iterations = 4
        config.openai_compatible.model_profiles["test"] = OpenAICompatibleModelProfile(
            total_window_tokens=200000, max_output_tokens=10000,
            supports_thinking_mode=True)
        config.tools.hosts["localhost"] = ToolHost(address="localhost")
        core.engine.deps.host_registry.publish(config.tools.hosts)
        manager = core.engine.deps.skill_manager
        assert "created" in manager.create_skill(SKILL_NAME, SKILL_SOURCE).lower()
        module = sys.modules[manager._skills[SKILL_NAME].module_name]
        if mode == "send":
            # Exercise the retained callback's explicit supported policy input,
            # not an alternative executor or owner/admission seam. Autonomous
            # production defaults remain stage; this case qualifies immediate
            # send under the very same independently admitted manager identity.
            dispatcher = core.engine.deps.native_tools
            original_dispatch = dispatcher.dispatch

            async def select_send(tool_name, tool_input, **kwargs):
                if tool_name == "invoke_skill" and tool_input.get("name") == SKILL_NAME:
                    kwargs["skill_file_delivery"] = "send"
                return await original_dispatch(tool_name, tool_input, **kwargs)

            dispatcher.dispatch = select_send
        created = await request(reader, writer, "conversations.create")
        other = created["result"]["conversation"]["id"]

        params = {"client_submission_id": "admit-independent", "conversation_id": cid,
                  "text": "Admit independent background delivery"}
        admitted = await request(reader, writer, "submission.send", params)
        assert admitted["ok"], admitted
        origin = admitted["result"]["request_id"]
        await wait_until(lambda: core.requests.get_request(origin)["state"] == "completed")
        assert provider.origin == origin
        assert module.EXECUTIONS == 0  # execution cannot precede origin settlement

        if kind == "schedule":
            schedules = core.engine.deps.scheduler.list_all()
            assert len(schedules) == 1
            # This RPC executes the entire real host-reading skill workflow.
            # Its outer fixture deadline is not a three-second product SLA.
            ran = await request(reader, writer, "schedules.run", {"id": schedules[0]["id"]},
                                timeout=30)
            assert ran["ok"] and ran["result"]["status"] == (
                "failure" if fail_after_stage else "success"), ran
        else:
            await asyncio.wait_for(provider.worker_entered.wait(), 30)
            worker = provider.worker_message
            assert worker.request_id != origin
            assert worker.conversation_id == cid and worker.owner_id == core.authority.owner_id
            with pytest.raises(PermissionError):
                core.requests.assert_bound_request(worker)
            provider.worker_release.set()
            await asyncio.wait_for(provider.final_entered.wait(), 30)
            # Both files are durable but neither skill interim notice consumes
            # them. The final provider response is still deliberately withheld.
            staged_count = core.store.connection.execute(
                "SELECT COUNT(*) FROM desktop_staged_files WHERE request_id=?",
                (worker.request_id,)).fetchone()[0]
            interim_files = [row for row in core.transcript.list(cid)["items"]
                             if row.get("artifacts")]
            if mode == "stage":
                assert staged_count == 2
                assert interim_files == []
            else:
                assert staged_count == 0
                assert len(interim_files) == 2
                assert [row["text"] for row in interim_files] == ["host caption", "binary caption"]
                assert all(row["request_id"] == worker.request_id for row in interim_files)
                assert core.requests.get_request(worker.request_id)["state"] == "running"
            provider.final_release.set()
            owner = (next(iter(core.engine.deps.agent_manager._agents.values()))
                     if kind == "agent" else
                     next(iter(core.engine.deps.loop_manager._loops.values())))
            await asyncio.wait_for(owner._task, 30)
            await asyncio.sleep(0)  # actual manager done callback owns settlement

        await wait_until(lambda: module.EXECUTIONS == 1)
        await wait_until(lambda: any(row.get("artifacts")
                                    for row in core.transcript.list(cid)["items"]))
        await settled(core)
        rows = core.transcript.list(cid)["items"]
        notice = next(row for row in rows if row["text"].startswith("background exact marker"))
        assert notice["text"] == scrub_response_secrets(
            "background exact marker\npassword=fixture-secret")
        assert "fixture-secret" not in notice["text"]
        rid = notice["request_id"]
        assert rid != origin
        worker = core.requests.fetch_request(cid, rid)
        assert worker.owner_id == core.authority.owner_id
        assert core.requests.get_request(rid)["state"] == (
            "failed" if fail_after_stage else "completed")
        bg = core.store.connection.execute(
            "SELECT * FROM desktop_background_requests WHERE request_id=?", (rid,)).fetchone()
        assert bg["kind"] == {"schedule": "schedule", "agent": "agent",
                              "loop": "loop_iteration"}[kind]
        if kind == "agent":
            agents = list(core.engine.deps.agent_manager._agents.values())
            assert len(agents) == 1 and agents[0]._task.done()
            assert agents[0].status == "completed"
            assert bg["parent_request_id"] == origin
        elif kind == "loop":
            loops = list(core.engine.deps.loop_manager._loops.values())
            assert len(loops) == 1 and loops[0]._task.done()
            assert loops[0].status == "completed" and loops[0].iteration_count == 1
            assert bg["parent_request_id"] != origin
        else:
            history = await core.engine.deps.scheduler.history.query()
            assert len(history) == 1 and history[0]["status"] == (
                "unknown" if fail_after_stage else "success"), history
            assert history[0]["run_binding"]["conversation_id"] == cid
            if fail_after_stage:
                # The retained manager marks a post-effect exception uncertain
                # and quarantines it, never retrying the already posted files.
                quarantined = core.engine.deps.scheduler.list_all()
                assert len(quarantined) == 1 and quarantined[0]["paused"]
                assert quarantined[0]["inert_reason"]
                refused = await request(reader, writer, "schedules.run", {
                    "id": quarantined[0]["id"]})
                assert not refused["ok"], refused
                assert module.EXECUTIONS == 1
            else:
                assert core.engine.deps.scheduler.list_all() == []

        attachments = [row for row in rows if row.get("artifacts")]
        assert len(attachments) == (1 if mode == "stage" else 2)
        assert all(row["request_id"] == rid for row in attachments)
        assert all(rows.index(row) > rows.index(notice) for row in attachments)
        files = [a for row in attachments for a in row["artifacts"]]
        assert [a["name"] for a in files] == ["host-proof.txt", "opaque.bin"]
        assert [a["mime"] for a in files] == ["text/plain", "application/octet-stream"]
        if kind == "schedule" and mode == "stage":
            assert attachments[0]["role"] == "notice"
            if fail_after_stage:
                assert attachments[0]["text"] == ""  # producer files, not forged success text
            else:
                assert attachments[0]["text"].startswith("**Workflow:")
        assert not next(row for row in rows if row["text"].startswith("Files staged"))["artifacts"]
        expected_host = host_binding(core.engine.deps.host_registry.get("localhost"))
        for artifact, expected in zip(files,
                                      [module.READ.encode("utf-8"), b"opaque\x00\xffbytes"],
                                      strict=True):
            read = await request(reader, writer, "artifacts.read", {
                "ref": artifact["ref"], "offset": 0, "length": 10000})
            assert read["ok"], read
            assert base64.b64decode(read["result"]["data_b64"]) == expected
            stored = core.store.connection.execute(
                "SELECT * FROM desktop_artifacts WHERE ref=?", (artifact["ref"],)).fetchone()
            assert stored["tool"] == SKILL_NAME
            assert stored["request_id"] == rid and stored["conversation_id"] == cid
            assert json.loads(stored["hosts"]) == [expected_host]
        assert "host-read-marker" in module.READ
        assert core.store.connection.execute(
            "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 0
        outbox = core.store.connection.execute(
            "SELECT payload FROM desktop_delivery_outbox WHERE request_id=?", (rid,)).fetchall()
        assert any(notice["id"] in row[0] for row in outbox)
        assert all(any(attachment["id"] in row[0] for row in outbox)
                   for attachment in attachments)
        assert all("fixture-secret" not in row[0] for row in outbox)
        assert core.transcript.list(other)["items"] == []
        # Durable delivery repair is a receipt replay, not a skill effect replay.
        delivery_ids = [row["id"] for row in core.transcript.list(cid)["items"]]
        for _ in range(2):
            await core.delivery.recover()
            snapshot = await request(reader, writer, "conversation.snapshot", {
                "conversation_id": cid})
            assert snapshot["ok"], snapshot
            assert [row["id"] for row in core.transcript.list(cid)["items"]] == delivery_ids
            assert module.EXECUTIONS == 1

        before = len(rows)
        with pytest.raises(PermissionError):
            await module.CONTEXT.post_message("stale background callback")
        with pytest.raises(PermissionError):
            await module.CONTEXT.post_file(b"stale", "stale.txt")
        for refused_mode in ("send", "stage"):
            with pytest.raises(PermissionError):
                await core.engine.deps.native_tools.skills._skill_file_cb(
                    worker, refused_mode, SKILL_NAME)(b"unbound", "unbound.txt")
        with pytest.raises(PermissionError):
            async with core.requests.background_execution(worker):
                pytest.fail("A completed background execution was replayed")
        assert len(core.transcript.list(cid)["items"]) == before
        duplicate = await request(reader, writer, "submission.send", params)
        assert duplicate["result"] == admitted["result"]
        later = await request(reader, writer, "submission.send", {
            "client_submission_id": "later", "conversation_id": cid, "text": "A later turn"})
        assert later["ok"], later
        await settled(core)
        assert module.EXECUTIONS == 1
        assert not any(row.get("artifacts") for row in core.transcript.list(cid)["items"]
                       if row["request_id"] == later["result"]["request_id"])
        assert len([row for row in core.transcript.list(cid)["items"] if row.get("artifacts")]) == (
            1 if mode == "stage" else 2)
    finally:
        provider.worker_release.set()
        provider.final_release.set()
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
async def test_real_loop_stop_after_skill_staging_flushes_once_without_success_text(tmp_path):
    """Cancel the retained loop through authenticated IPC, not a task shim."""
    source = tmp_path / "cancel-host-source.txt"
    source.write_text("host-read-marker\ncancellation fixture\n", encoding="utf-8")
    provider = IndependentProvider("loop", source)
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, provider, setup_timeout=30)
    try:
        config = core.config
        config.tools.hosts["localhost"] = ToolHost(address="localhost")
        core.engine.deps.host_registry.publish(config.tools.hosts)
        manager = core.engine.deps.skill_manager
        assert "created" in manager.create_skill(SKILL_NAME, SKILL_SOURCE).lower()
        module = sys.modules[manager._skills[SKILL_NAME].module_name]
        admitted = await request(reader, writer, "submission.send", {
            "client_submission_id": "admit-cancellable-loop", "conversation_id": cid,
            "text": "Admit independent staged delivery"})
        assert admitted["ok"], admitted
        origin = admitted["result"]["request_id"]
        await wait_until(lambda: core.requests.get_request(origin)["state"] == "completed")
        await asyncio.wait_for(provider.worker_entered.wait(), 30)
        worker = provider.worker_message
        assert worker.request_id != origin and worker.conversation_id == cid
        provider.worker_release.set()
        await asyncio.wait_for(provider.final_entered.wait(), 30)
        assert module.EXECUTIONS == 1
        assert core.store.connection.execute(
            "SELECT COUNT(*) FROM desktop_staged_files WHERE request_id=?",
            (worker.request_id,)).fetchone()[0] == 2
        assert not any(row.get("artifacts") for row in core.transcript.list(cid)["items"])
        listing = await request(reader, writer, "work.list", {"kind": "loop"})
        assert listing["ok"], listing
        item, = listing["result"]["items"]
        control = {"control_command_id": "stop-staged-loop", "kind": "loop",
                   "id": item["id"], "action": "stop"}
        stopped = await request(reader, writer, "work.control", control)
        assert stopped["ok"] and stopped["result"]["disposition"] == "done", stopped
        await settled(core)
        loop, = core.engine.deps.loop_manager._loops.values()
        assert loop._task.done() and loop.status == "stopped"
        assert core.requests.get_request(worker.request_id)["state"] == "interrupted"
        rows = core.transcript.list(cid)["items"]
        final, = [row for row in rows if row.get("artifacts")]
        assert final["request_id"] == worker.request_id
        assert final["role"] == "notice" and final["text"] == ""
        assert not any(row["text"] == "Background final result." for row in rows)
        assert [artifact["name"] for artifact in final["artifacts"]] == [
            "host-proof.txt", "opaque.bin"]
        expected_host = host_binding(core.engine.deps.host_registry.get("localhost"))
        for artifact, expected in zip(final["artifacts"],
                                      [module.READ.encode("utf-8"), b"opaque\x00\xffbytes"],
                                      strict=True):
            read = await request(reader, writer, "artifacts.read", {
                "ref": artifact["ref"], "offset": 0, "length": 10000})
            assert read["ok"] and base64.b64decode(read["result"]["data_b64"]) == expected
            stored = core.store.connection.execute(
                "SELECT * FROM desktop_artifacts WHERE ref=?", (artifact["ref"],)).fetchone()
            assert stored["tool"] == SKILL_NAME
            assert json.loads(stored["hosts"]) == [expected_host]
        assert core.store.connection.execute(
            "SELECT COUNT(*) FROM desktop_staged_files").fetchone()[0] == 0
        assert worker.request_id not in core.requests._background_finalizing
        before = [row["id"] for row in rows]
        duplicate = await request(reader, writer, "work.control", control)
        assert duplicate["result"] == stopped["result"]
        await core.delivery.recover()
        assert [row["id"] for row in core.transcript.list(cid)["items"]] == before
        assert module.EXECUTIONS == 1
        with pytest.raises(PermissionError):
            await module.CONTEXT.post_file(b"late", "late.txt")
        with pytest.raises(PermissionError):
            async with core.requests.background_execution(worker):
                pytest.fail("Cancelled iteration was replayed")
    finally:
        provider.worker_release.set()
        provider.final_release.set()
        await cleanup(core, writer, rfd, wfd)
