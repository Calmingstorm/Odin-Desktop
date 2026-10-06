"""Test-only admission/seed plus external tool boundary; actual core owns everything else.

Invoked only inside real-core-isolation's disposable PID namespace/HOME. No
provider, account, remote host or external network is used. Local child commands
write counters only under the disposable HOME. Agent
and process records are controlled metadata seeds, not execution qualification.
"""
import asyncio
import json
import os
import runpy
import shlex
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from src.agents.manager import AgentInfo, AgentState
from src.desktop.core import CoreService
from src.discord.background_task import BackgroundTask, run_background_task
from src.tools import ToolResult
from src.tools.process_manager import ProcessInfo

root = Path(os.environ["HOME"])
assert root.as_posix().startswith("/tmp/odrc-")
assert os.getuid() != 0
assert b"real-core-isolation.mjs" in Path("/proc/1/cmdline").read_bytes()
assert b"--inside-run" in Path("/proc/1/cmdline").read_bytes()
original_start = CoreService.start
original_init = CoreService.__init__


class MemoryKeyring:
    """Ephemeral external Secret Service boundary, not native keyring proof."""
    def __init__(self):
        self.values = {}

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.values[(namespace, name)] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


def isolated_init(self, *args, **kwargs):
    assert "secret_backend" not in kwargs
    original_init(self, *args, secret_backend=MemoryKeyring(), **kwargs)


async def seed(self, *args, **kwargs):
    await original_start(self, *args, **kwargs)
    # Clock seeding must not race the autonomous scheduler's real next-minute
    # tick. Retain its callbacks/owners and exercise _tick explicitly below.
    await self.engine.deps.scheduler.stop()
    # Reopening only reconciles durable records. Never seed/replay a second run.
    marker = root / "work-proof.json"
    if marker.exists():
        return
    owner = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
    token = self.permissions.set_request_owner(owner)
    try:
        cid = self.conversations.create(title="Chat")["conversation"]["id"]
        deps = self.engine.deps
        counts = {"background": 0, "report": 0}
        def count(name):
            counts[name] += 1
            (root / "work-tool-counts.json").write_text(json.dumps(counts))

        # Completed task/report use the real executor's harmless local printf.
        # Only deliberately waiting external-tool behavior is substituted.
        real_execute = deps.tool_executor.execute
        completed_command = "printf 'effect\\n' >> " + shlex.quote(str(root / "background-effects")) + "; printf 'Harmless local step finished.'"
        report_output = json.dumps({"format": "paginated_embed_v1", "pages": [
            {"title": "Stored local report", "description": "Page one, produced once."},
            {"title": "Stored local report", "description": "Page two, no rerun."}
        ]})
        # A plain JSON stdout contract, without a redirect diagnostic appended
        # by run_command's mutation classifier. Counter is written by the real
        # disposable local child, not a mocked dispatcher or publication hook.
        report_program = "from pathlib import Path; p=Path(" + repr(str(root / "report-effects")) + "); p.open('a').write('effect\\n'); print(" + repr(report_output) + ")"
        report_command = "python3 -c " + shlex.quote(report_program)
        async def controlled_tool(tool, inp, *, user_id=None, **kw):
            assert tool == "run_command" and user_id == owner.owner_id
            if inp == {"command": completed_command} or inp == {"command": report_command}:
                result = await real_execute(tool, inp, user_id=user_id, **kw)
                return result
            assert inp in ({"command": "proof:wait"}, {"command": "proof:lost"})
            count("background")
            if inp["command"] == "proof:wait":
                await asyncio.sleep(3600)
            if inp["command"] == "proof:lost":
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    (root / "work-cancel-entered").write_text("External cleanup is pending")
                    await asyncio.sleep(0.8)
                    raise
            return ToolResult(output="Harmless local step finished.", ok=True, tool_name=tool)
        deps.tool_executor.execute = controlled_tool

        parent = self.requests._register_background("task", uuid4().hex, "Proof admission", cid, owner.owner_id)
        async with self.requests.background_execution(parent):
            agents = deps.native_owners["agents"]
            for label, command in [("Harmless completed task", completed_command), ("Harmless cancellable task", "proof:wait"),
                                   ("Harmless lost-receipt task", "proof:lost")]:
                await agents._handle_delegate_task(parent, {"description": label, "steps": [
                    {"tool_name": "run_command", "tool_input": {"command": command}}]})
            # Workflow is a real BackgroundTask with a distinct durable kind.
            message = self.requests.register_background(parent, "workflow", uuid4().hex, "Harmless workflow")
            workflow = BackgroundTask("proof-workflow", "Harmless workflow", [], cid, owner.owner_id, requester_id=owner.owner_id)
            deps.channel_state.background_tasks[workflow.task_id] = workflow
            self.work.register("workflow", workflow.task_id, message, parent_message=parent)
            async def workflow_run():
                async with self.requests.background_execution(message):
                    await run_background_task(workflow, deps.tool_executor, deps.skill_manager)
            workflow._asyncio_task = asyncio.create_task(workflow_run())

            agent_message = self.requests.register_background(parent, "agent", uuid4().hex, "Controlled agent mailbox")
            agent = AgentInfo(id="proof-agent", label="Controlled agent mailbox", goal="No provider execution", channel_id=cid,
                              requester_id=owner.owner_id, requester_name="Owner", max_iterations=7)
            agent.transition(AgentState.READY)
            deps.agent_manager._agents[agent.id] = agent
            self.work.register("agent", agent.id, agent_message, parent_message=parent)

            process_message = self.requests.register_background(parent, "process", uuid4().hex, "Unknown restored process")
            process = ProcessInfo(777, "Metadata only, no OS process", "localhost", time.time(), status="unknown",
                                  owner_id=owner.owner_id, origin_channel=cid, restored=True, containment="unqualified_seed")
            self.work.processes._processes[777] = process
            self.work.register("process", "777", process_message, parent_message=parent)

            loop_message = self.requests.register_background(parent, "loop", uuid4().hex, "Harmless waiting loop")
            async def iterate(*args):
                await asyncio.sleep(3600)
                return "Never reached"
            deps.loop_manager.start_admitted_loop("Harmless waiting loop", loop_message.channel, owner.owner_id, "Owner", iterate,
                before_start=lambda info: self.work.register("loop", info.id, loop_message, parent_message=parent),
                execution=lambda info: self.requests.background_execution(loop_message),
                publish=lambda info, text: self._publish_background(loop_message, text),
                on_settled=lambda info: self.work.refresh_all(), max_iterations=1)

        reminder = await self.schedules.invoke("schedules.save", {"description": "D12 missed reminder", "action": "reminder",
            "channel_id": cid, "cron": "* * * * *", "message": "Harmless catch-up notice"}, owner=owner)
        manual = await self.schedules.invoke("schedules.save", {"description": "D12 manual recovery check", "action": "check",
            "channel_id": cid, "cron": "* * * * *", "tool_name": "run_command", "tool_input": {"command": report_command}}, owner=owner)
        report = await self.schedules.invoke("schedules.save", {"description": "Stored report producer", "action": "check",
            "channel_id": cid, "cron": "0 0 1 1 *", "tool_name": "run_command", "tool_input": {"command": report_command},
            "report_format": "paginated_embed_v1"}, owner=owner)
        async with deps.scheduler._lock:
            values = deps.scheduler.list_all()
            for item in values:
                if item["id"] in {reminder["id"], manual["id"]}:
                    item["next_run"] = (datetime.now(UTC) - timedelta(hours=4)).isoformat()
            await deps.scheduler._publish(values)
        await deps.scheduler._tick()
        await self.schedules.invoke("schedules.run", {"id": report["id"]}, owner=owner)
        # Avoid a genuine next-minute reminder racing gate assertions.
        await self.schedules.invoke("schedules.save", {"id": reminder["id"], "paused": True}, owner=owner)
        for item in deps.scheduler.list_all():
            self.work.register_schedule(item)
        completed = next(t for t in deps.channel_state.background_tasks.values() if t.description == "Harmless completed task")
        await completed._asyncio_task
        await workflow._asyncio_task
        self.work.refresh_all()
        report_id = self.store.connection.execute("SELECT report_id FROM desktop_reports").fetchone()[0]
        marker.write_text(json.dumps({"conversation_id": cid, "report_id": report_id, "reminder_id": reminder["id"],
                                      "recovery_id": manual["id"], "producer_id": report["id"]}))
    finally:
        self.permissions.reset_request_owner(token)


CoreService.__init__ = isolated_init
CoreService.start = seed
runpy.run_module("src", run_name="__main__")
