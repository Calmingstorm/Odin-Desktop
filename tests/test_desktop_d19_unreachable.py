"""Fail-on-invocation proofs for legacy D19 guards, on the composed profile.

No readiness override, fake executor, desktop input or production profile. The
provider/keyring boundaries and Unix RPC helpers are the existing D19 fixtures.
Restored background admission uses the real request-bound owner. Trace spies
prove only these bounded flows avoid the old guards, not universal reachability.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import shlex
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src import restart, setup_wizard
from src.computer.integration import ComputerIntegration
from src.desktop.computer_binding import ComputerBindingService, ComputerForegroundBinding
from src.discord import (
    delivery,
    intake_pipeline,
    scheduled_events,
    scheduled_report,
    slash_commands,
    tool_loop,
    wiring,
)
from src.discord.native_tools import media as media_tools
from src.discord.native_tools.channel_ops import ChannelOpsTools
from src.llm.types import LLMResponse
from src.tools import output_authorization, runtime_delivery
from src.tools.result_validator import ToolResult
from src.web import api as web_api
from src.web import websocket as web_websocket
from src.web.api import agents_loops, config_admin, sessions_chat, skills_api
from tests.test_desktop_core_lifecycle import request
from tests.test_desktop_d19_behaviour import composed as composed  # shared pytest fixture
from tests.test_desktop_d19_behaviour import (
    configure_agent_fixture,
    conversation,
    rpc,
    tool_results,
    turn,
)

# Patch existing runtime objects with raising spies, not fabricated dotted names.
# __init__ is patched rather than replacing DeliveryService's class identity.
CALLABLE_GUARDS = {
    "017": (output_authorization, "owner_output_scope"),
    "027": (tool_loop, "_require_phase2_wiring"),
    "028": (delivery.DeliveryService, "__init__"),
    "032": (intake_pipeline, "_require_phase2_admission"),
    "037": (slash_commands, "register_commands"),
    "038": (wiring, "build_services"),
    "039": (wiring, "build_components"),
    "040": (wiring, "start_mcp"),
    # Batch A: Odin-only owners Desktop never composes or calls.
    "002": (media_tools.MediaTools, "_publish_attachment"),
    "036": (scheduled_report.ScheduledReportPaginationService, "post"),
    "044-load": (scheduled_report.ScheduledReportPaginationService, "_load"),
    "044-page": (scheduled_report.ScheduledReportPaginationService, "project_page"),
    "044-store": (scheduled_report.ScheduledReportPaginationService, "store_projection"),
    "047": (restart, "reexec"),
    "048": (setup_wizard, "is_setup_needed"),
    "050": (web_api, "require_phase2"),
    "050-loops": (agents_loops, "register_loops"),
    "050-agents": (agents_loops, "register_agents"),
    "050-processes": (agents_loops, "register_processes"),
    "050-setup": (config_admin, "register_setup_wizard"),
    "050-status": (config_admin, "register_status_info"),
    "050-actions": (config_admin, "register_quick_actions"),
    "050-personality": (config_admin, "register_personality"),
    "050-diagnostics": (config_admin, "register_startup_diagnostics"),
    "050-chat": (sessions_chat, "register_chat"),
    "050-sessions": (sessions_chat, "register_sessions"),
    "050-trajectories": (sessions_chat, "register_trajectories"),
    "050-agent-trajectories": (sessions_chat, "register_agent_trajectories"),
    "050-skills": (skills_api, "register_skills"),
    "050-websocket": (web_websocket, "setup_websocket"),
    # Batch B: Desktop composes its own computer admission and management.
    "029": (ComputerIntegration, "_context"),
    "030-operator": (ComputerIntegration, "_operator_context"),
    "030-stop": (ComputerIntegration, "stop_channel"),
}


def _missing_reader_return():
    """Locate the real inline backstop by AST, then bind to its code object."""
    handler = ChannelOpsTools._handle_read_conversation
    source, start = inspect.getsourcelines(handler)
    tree = ast.parse(textwrap.dedent("".join(source)))
    branches = [node for node in ast.walk(tree) if isinstance(node, ast.If)
                and ast.dump(node.test) == ast.dump(ast.parse(
                    "self.read_visible_history is None", mode="eval").body)]
    assert len(branches) == 1
    assert len(branches[0].body) == 1
    backstop = branches[0].body[0]
    assert isinstance(backstop, ast.Return)
    assert "Conversation history is unavailable" in ast.literal_eval(backstop.value)
    lines = set(range(start + backstop.lineno - 1, start + backstop.end_lineno))
    assert lines & {line for _, _, line in handler.__code__.co_lines()}
    return handler.__code__, lines


def _runtime_guard_branches():
    """Bind the exact mis-composition raises, not the successful delivery calls."""
    targets = {
        "014": [runtime_delivery.deliver_runtime_output,
                runtime_delivery.deliver_runtime_result],
        "015": [runtime_delivery._require_retention_authority],
    }
    messages = {
        "014": "Output retention unavailable: no authenticated executor consumer is "
               "configured. Do not replay the tool.",
        "015": "Output authority unavailable. Do not replay the tool.",
    }
    branches = {}
    for row, handlers in targets.items():
        branches[row] = []
        for handler in handlers:
            source, start = inspect.getsourcelines(handler)
            tree = ast.parse(textwrap.dedent("".join(source)))
            raises = [node for node in ast.walk(tree) if isinstance(node, ast.Raise)
                      and isinstance(node.exc, ast.Call) and node.exc.args
                      and isinstance(node.exc.args[0], ast.Constant)
                      and node.exc.args[0].value == messages[row]]
            assert len(raises) == 1
            node = raises[0]
            lines = set(range(start + node.lineno - 1, start + node.end_lineno))
            assert lines & {line for _, _, line in handler.__code__.co_lines()}
            branches[row].append((handler.__code__, lines))
    return branches


def _raise_lines(handler, prefix):
    """The exact raise of a guard whose function also runs on admitted paths."""
    source, start = inspect.getsourcelines(handler)
    tree = ast.parse(textwrap.dedent("".join(source)))
    raises = [node for node in ast.walk(tree) if isinstance(node, ast.Raise)
              and isinstance(node.exc, ast.Call) and node.exc.args
              and isinstance(node.exc.args[0], ast.Constant)
              and str(node.exc.args[0].value).startswith(prefix)]
    assert len(raises) == 1, handler.__name__
    node = raises[0]
    lines = set(range(start + node.lineno - 1, start + node.end_lineno))
    assert lines & {line for _, _, line in handler.__code__.co_lines()}
    return handler.__code__, lines


def _scheduled_fence_branches():
    """Scheduled runs enter these functions. Their raises fire only outside admission
    (033, 034) or when a mis-composed report publisher refuses (035)."""
    return {
        "033": [_raise_lines(scheduled_events._require_phase2,
                             "Scheduled execution requires Phase 2")],
        "034": [_raise_lines(scheduled_events._publish_notice,
                             "Conversation publication is unavailable until Phase 2")],
        "035": [_raise_lines(scheduled_events.ScheduledEventHandlers._on_scheduled_task_inner,
                             "Scheduled report publication unavailable")],
    }


def _image_delivery_return():
    """generate_image's early return when no durable publisher is composed."""
    handler = media_tools.MediaTools._handle_generate_image
    source, start = inspect.getsourcelines(handler)
    tree = ast.parse(textwrap.dedent("".join(source)))
    returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)
               and isinstance(node.value, ast.Call)
               and any(keyword.arg == "output" and isinstance(keyword.value, ast.Name)
                       and keyword.value.id == "_DELIVERY_UNAVAILABLE"
                       for keyword in node.value.keywords)]
    assert len(returns) == 1
    node = returns[0]
    lines = set(range(start + node.lineno - 1, start + node.end_lineno))
    assert lines & {line for _, _, line in handler.__code__.co_lines()}
    return [(handler.__code__, lines)]


def _skill_delivery_fallbacks():
    """Bind the mis-composition raises of SkillTools' injected delivery seam."""
    from src.discord.native_tools.skills_tools import SkillTools

    branches = []
    for method, inner in ((SkillTools._assert_delivery, None),
                          (SkillTools._skill_message_cb, "_skill_msg"),
                          (SkillTools._skill_file_cb, "_skill_file")):
        source, start = inspect.getsourcelines(method)
        tree = ast.parse(textwrap.dedent("".join(source)))
        raises = [node for node in ast.walk(tree) if isinstance(node, ast.Raise)
                  and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name)
                  and node.exc.func.id == "NotImplementedError" and node.exc.args
                  and isinstance(node.exc.args[0], ast.Name)
                  and node.exc.args[0].id == "_DELIVERY_UNAVAILABLE"]
        assert len(raises) == 1, method.__name__
        code = method.__code__
        if inner is not None:
            [code] = [const for const in code.co_consts
                      if inspect.iscode(const) and const.co_name == inner]
        node = raises[0]
        lines = set(range(start + node.lineno - 1, start + node.end_lineno))
        assert lines & {line for _, _, line in code.co_lines()}
        branches.append((code, lines))
    return branches


@pytest.fixture
def guard_spies(monkeypatch):
    spies = {}
    original_codes = {}
    for row, (owner, attribute) in CALLABLE_GUARDS.items():
        original = getattr(owner, attribute)  # must already exist
        assert inspect.isfunction(original)
        assert Path(inspect.getfile(inspect.unwrap(original))).resolve().is_relative_to(
            Path(__file__).resolve().parents[1] / "src")
        spy_type = AsyncMock if inspect.iscoroutinefunction(original) else Mock
        spy = spy_type(side_effect=AssertionError(f"D19-{row} legacy guard invoked"))
        monkeypatch.setattr(owner, attribute, spy)
        assert getattr(owner, attribute) is spy
        spies[row] = spy
        code_spy = Mock(side_effect=AssertionError(f"D19-{row} legacy guard alias invoked"))
        spies[f"{row}-original-code"] = code_spy
        # @contextmanager wrappers share contextlib.helper's code object. Bind
        # the actual guarded generator, not every context manager in Python.
        original_codes[inspect.unwrap(original).__code__] = code_spy
    # Globals used by the retained entry functions must resolve to these spies.
    assert (tool_loop._LoopMessageProxy.__init__.__globals__["_require_phase2_wiring"]
            is spies["027"])
    assert (intake_pipeline.MessageIntake.handle.__globals__["_require_phase2_admission"]
            is spies["032"])
    code, lines = _missing_reader_return()
    spies["001"] = Mock(side_effect=AssertionError("D19-001 missing-reader backstop invoked"))
    visited = {"handler": 0, "reader": 0}
    reader_codes = set()
    runtime_branches = _runtime_guard_branches()
    runtime_branches["009"] = _skill_delivery_fallbacks()
    runtime_branches.update(_scheduled_fence_branches())
    runtime_branches["002-image"] = _image_delivery_return()
    for row in runtime_branches:
        spies[row] = Mock(side_effect=AssertionError(f"D19-{row} runtime backstop invoked"))
        visited[row] = 0
    # Positive paths: Desktop's own computer admission and management owners.
    positive_codes = {ComputerForegroundBinding._context.__code__: "computer-binding",
                      ComputerBindingService.handle.__code__: "computer-management"}
    visited.update(dict.fromkeys(positive_codes.values(), 0))

    def trace(frame, event, arg):
        # An imported alias can bypass the patched module attribute. Bind
        # an additional raising spy to the original code object, e.g. the guard
        # imported by turn_resume, rather than leaving that alias unobserved.
        if event == "call" and frame.f_code in original_codes:
            original_codes[frame.f_code]()
        if event == "call" and frame.f_code in positive_codes:
            visited[positive_codes[frame.f_code]] += 1
            return None
        if frame.f_code is code:
            if event == "call":
                visited["handler"] += 1
            elif event == "line" and frame.f_lineno in lines:
                spies["001"]()
            return trace
        if frame.f_code in reader_codes and event == "call":
            visited["reader"] += 1
        for row, branches in runtime_branches.items():
            for branch_code, branch_lines in branches:
                if frame.f_code is branch_code:
                    if event == "call":
                        visited[row] += 1
                    elif event == "line" and frame.f_lineno in branch_lines:
                        spies[row]()
                    return trace
        return None

    previous = sys.gettrace()
    assert previous is None, "This code-object spy must not displace another tracing owner"
    sys.settrace(trace)
    try:
        yield SimpleNamespace(spies=spies, visited=visited, reader_codes=reader_codes)
    finally:
        sys.settrace(previous)
        # Some legacy callers swallow exceptions; call counts still fail closed.
        for spy in spies.values():
            spy.assert_not_called()


@pytest.fixture
async def guarded_core(guard_spies, composed):
    reader = composed.core.engine.deps.native_tools.owners["channel_ops"]
    assert type(reader) is ChannelOpsTools
    assert reader._handle_read_conversation.__func__ is ChannelOpsTools._handle_read_conversation
    assert inspect.iscoroutinefunction(reader.read_visible_history)
    assert reader.read_visible_history.__module__ == "src.desktop.services"
    guard_spies.reader_codes.add(reader.read_visible_history.__code__)
    return composed


@pytest.mark.parametrize("flow", [
    "chat_history", "background_admission", "mcp_start_stop", "skill_delivery",
    "scheduled_runs", "computer_stop", "shutdown",
])
async def test_composed_flows_never_invoke_legacy_guards(guarded_core, guard_spies, flow):
    """All twelve spies are installed before CoreService.start and through close."""
    graph = guarded_core
    if flow == "chat_history":
        cid = await conversation(graph)
        graph.core.transcript.commit(cid, "assistant", "D19 real history branch marker")
        await turn(graph, cid, "read_conversation", {"limit": 10})
        assert "D19 real history branch marker" in str(tool_results(graph))
        assert guard_spies.visited["handler"] > 0
        assert guard_spies.visited["reader"] > 0
        # Also exercise real executor output ownership, beyond a native read.
        await turn(graph, cid, "memory_manage", {
            "action": "save", "scope": "global", "key": "d19_guard", "value": "saved"})
        assert graph.core.management.executor._load_all_memory()["global"]["d19_guard"] == "saved"
        await turn(graph, cid, "generate_file", {"filename": "d19.txt", "content": "durable"})
        assert any(row.get("artifacts") for row in graph.core.transcript.list(cid)["items"])
        assert guard_spies.visited["014"] > 0
        assert guard_spies.visited["015"] > 0
    elif flow == "background_admission":
        tasks = graph.core.engine.deps.channel_state.background_tasks
        assert not tasks
        cid = await conversation(graph)
        await turn(graph, cid, "delegate_task", {
            "description": "Bounded background admission proof",
            "steps": [{"tool_name": "memory_manage", "tool_input": {
                "action": "save", "scope": "global", "key": "d19_guard_background",
                "value": "run"}}],
        })
        assert "delegate_task" in {row["name"] for row in graph.provider.calls[0]["tools"]}
        assert len(tasks) == 1
        async with asyncio.timeout(5):
            while any(task.status in {"pending", "running"} for task in tasks.values()):
                await asyncio.sleep(.01)
        task = next(iter(tasks.values()))
        assert task.status == "completed", task.results
        assert task.requester_id == graph.core.authority.owner_id
        assert graph.core.management.executor._load_all_memory()["global"][
            "d19_guard_background"] == "run"
        work = (await rpc(graph, "work.list", {"kind": "task"}))["items"]
        assert len(work) == 1 and work[0]["state"] == "completed"
        assert work[0]["conversation_id"] == cid
        assert graph.core.requests.get_request(work[0]["request_id"])["state"] == "completed"
        assert guard_spies.visited["014"] > 0
        assert guard_spies.visited["015"] > 0
    elif flow == "skill_delivery":
        # A real skill's message and file reach the composed request-owned delivery,
        # running every injected-delivery function without reaching its fallback.
        definition = {"name": "d19_delivery", "description": "Private delivery proof",
                      "input_schema": {"type": "object", "properties": {}}}
        code = (f"SKILL_DEFINITION = {definition!r}\n"
                "async def execute(inp, context):\n"
                "    await context.post_message('d19 delivered message')\n"
                "    await context.post_file(b'd19 bytes', 'd19.txt')\n"
                "    return 'delivered'\n")
        saved = await rpc(graph, "skills.save", {"name": "d19_delivery", "code": code})
        assert "created" in saved["result"]
        cid = await conversation(graph)
        await turn(graph, cid, "d19_delivery")
        items = graph.core.transcript.list(cid)["items"]
        assert any("d19 delivered message" in (item.get("text") or "") for item in items)
        assert any(item.get("artifacts") for item in items)
        assert guard_spies.visited["009"] > 0
    elif flow == "scheduled_runs":
        # Real admitted scheduled runs enter both fences without reaching their raises.
        from datetime import UTC, datetime, timedelta

        cid = await conversation(graph)
        # Provisioning creates the local command workspace for a real profile.
        Path(graph.core.config.tools.local_working_dir).mkdir(parents=True, mode=0o700)
        reminder = await rpc(graph, "schedules.save", {
            "description": "D19 guard reminder", "action": "reminder", "channel_id": cid,
            "run_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "message": "D19 guard reminder delivered"})
        await rpc(graph, "schedules.run", {"id": reminder["id"]})
        check = await rpc(graph, "schedules.save", {
            "description": "D19 guard check", "action": "check", "channel_id": cid,
            "cron": "0 0 1 1 *", "tool_name": "run_command",
            "tool_input": {"host": "localhost", "command": "printf ran"}})
        await rpc(graph, "schedules.run", {"id": check["id"]})
        # A report check publishes through Desktop's real report owner (035).
        pages = json.dumps({"format": "paginated_embed_v1", "pages": [
            {"title": "D19 stored status", "description": "All quiet"}]})
        report = await rpc(graph, "schedules.save", {
            "description": "D19 guard report", "action": "check", "channel_id": cid,
            "cron": "0 0 1 1 *", "tool_name": "run_command",
            "tool_input": {"host": "localhost", "command": "printf %s " + shlex.quote(pages)},
            "report_format": "paginated_embed_v1"})
        await rpc(graph, "schedules.run", {"id": report["id"]})
        scheduler = graph.core.engine.deps.scheduler
        for _ in range(500):
            items = graph.core.transcript.list(cid)["items"]
            delivered = any("D19 guard reminder delivered" in str(item) for item in items)
            ran = any(item["id"] == check["id"] and item.get("last_run")
                      for item in scheduler.list_all())
            reported = any(artifact["kind"] == "report"
                           for item in items for artifact in item.get("artifacts", []))
            if delivered and ran and reported:
                break
            await asyncio.sleep(0.02)
        assert delivered, graph.core.transcript.list(cid)["items"]
        assert ran, scheduler.list_all()
        assert reported, graph.core.transcript.list(cid)["items"]
        assert guard_spies.visited["033"] > 0
        assert guard_spies.visited["034"] > 0
        assert guard_spies.visited["035"] > 0
    elif flow == "computer_stop":
        # Desktop stops a running turn through control.stop and its own foreground
        # binding, and serves computer management itself; Odin's operator and
        # stop_channel admission is never entered (029, 030).
        foreground = graph.core.computer_foreground
        assert type(foreground) is ComputerForegroundBinding
        assert type(foreground)._context is not ComputerIntegration._context
        assert type(foreground)._operator_context is guard_spies.spies["030-operator"]
        assert type(foreground).stop_channel is guard_spies.spies["030-stop"]
        cid = await conversation(graph)
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked(**_kwargs):
            entered.set()
            await release.wait()
            return LLMResponse(text="The stopped turn has settled.")

        graph.provider.chat_with_tools = blocked
        try:
            receipt = await rpc(graph, "submission.send", {
                "client_submission_id": "d19-computer-stop", "conversation_id": cid,
                "text": "Wait until stopped"})
            await asyncio.wait_for(entered.wait(), 10)
            stop = await rpc(graph, "control.stop", {
                "control_command_id": "d19-computer-stop", "conversation_id": cid,
                "request_id": receipt["request_id"], "generation": 1})
            assert stop == {"disposition": "requested"}
        finally:
            release.set()
            del graph.provider.chat_with_tools
        await asyncio.wait_for(asyncio.gather(*graph.core.requests._tasks), timeout=20)
        assert graph.core.requests.get_request(receipt["request_id"])["state"] == "cancelled"
        assert guard_spies.visited["computer-binding"] > 0
        assert (await rpc(graph, "computer.status"))["session"] is None
        # Stop stays available while computer use is disabled (recovery).
        missing = await request(graph.reader, graph.writer, "computer.stop", {
            "session_id": "not-a-real-session", "generation": 1})
        assert missing["error"]["code"] == "not_found", missing
        assert guard_spies.visited["computer-management"] > 0
    elif flow == "mcp_start_stop":
        from src.tools.mcp.manager import MCPManager

        service = graph.core.management.mcp
        assert isinstance(service.manager, MCPManager)
        assert (await rpc(graph, "mcp.status"))["started"]
        # Real supervised transport, against only a test-owned stdio child.
        await rpc(graph, "mcp.set_global_enabled", {"enabled": True})
        await rpc(graph, "mcp.save", {
            "name": "d19_guard", "transport": "stdio", "command": sys.executable,
            "args": [str(Path(__file__).parent / "fakes" / "mcp_stdio_server.py"), "legacy"],
            "enabled": True,
        })
        async with asyncio.timeout(15):
            while (await rpc(graph, "mcp.status"))["connected_count"] != 1:
                await asyncio.sleep(0.02)
        status = await rpc(graph, "mcp.status")
        assert status["published_tool_count"] > 0
        await rpc(graph, "mcp.set_enabled", {"name": "d19_guard", "enabled": False})
        status = await rpc(graph, "mcp.status")
        assert status["connected_count"] == status["published_tool_count"] == 0
        await rpc(graph, "mcp.delete", {"name": "d19_guard"})
        await service.close()
        assert (await rpc(graph, "mcp.status"))["closed"]
    else:
        await turn(graph, await conversation(graph))
        receipt = await rpc(graph, "runtime.shutdown", {"reason": "Private guard proof complete"})
        assert receipt["disposition"] == "accepted"
        await graph.core.close()
        assert graph.provider.closed
        assert graph.core.engine.producers_quiesced
        assert graph.core.engine.cleanup_outcome["state"] == "released"
    for spy in guard_spies.spies.values():
        spy.assert_not_called()


@pytest.mark.parametrize("row", list(CALLABLE_GUARDS))
async def test_fail_spies_are_attached_to_existing_callable_targets(monkeypatch, row):
    """Positive controls: each patched target really raises when invoked."""
    owner, attribute = CALLABLE_GUARDS[row]
    original = getattr(owner, attribute)
    assert inspect.isfunction(original)
    spy = (AsyncMock if inspect.iscoroutinefunction(original) else Mock)(
        side_effect=AssertionError(f"D19-{row} guard positive control"))
    monkeypatch.setattr(owner, attribute, spy)
    with pytest.raises(AssertionError, match=f"D19-{row} guard positive control"):
        if inspect.iscoroutinefunction(original):
            await getattr(owner, attribute)()
        else:
            getattr(owner, attribute)()
    spy.assert_called_once()


def test_original_guard_code_spy_catches_preimported_resume_alias():
    """Patching tool_loop alone cannot see the earlier turn_resume import."""
    from src.discord import turn_resume

    alias = turn_resume._require_phase2_wiring
    assert alias is tool_loop._require_phase2_wiring
    spy = Mock(side_effect=AssertionError("original guard code invoked"))

    def trace(frame, event, arg):
        if event == "call" and frame.f_code is alias.__code__:
            spy()
        return None

    previous = sys.gettrace()
    assert previous is None
    sys.settrace(trace)
    try:
        with pytest.raises(AssertionError, match="original guard code invoked"):
            alias()
    finally:
        sys.settrace(previous)
    spy.assert_called_once()


async def test_missing_reader_branch_spy_positive_control():
    """The branch trace catches the actual backstop, not every history read."""
    code, lines = _missing_reader_return()
    spy = Mock(side_effect=AssertionError("actual missing-reader branch"))

    def trace(frame, event, arg):
        if frame.f_code is code:
            if event == "line" and frame.f_lineno in lines:
                spy()
            return trace
        return None

    previous = sys.gettrace()
    assert previous is None
    sys.settrace(trace)
    try:
        with pytest.raises(AssertionError, match="actual missing-reader branch"):
            await ChannelOpsTools()._handle_read_conversation(object(), {"limit": 1})
    finally:
        sys.settrace(previous)
    spy.assert_called_once()


async def test_skill_delivery_fallback_spy_positive_control():
    """Without injected delivery, each fallback's actual raise is observed."""
    from src.discord.native_tools.skills_tools import SkillTools

    branches = _skill_delivery_fallbacks()
    spy = Mock()

    def trace(frame, event, arg):
        for code, lines in branches:
            if frame.f_code is code:
                if event == "line" and frame.f_lineno in lines:
                    spy(code.co_name)
                return trace
        return None

    tools = SkillTools(skill_manager=None, tool_catalog=None, prompt_builder=None)
    previous = sys.gettrace()
    assert previous is None
    sys.settrace(trace)
    try:
        with pytest.raises(NotImplementedError):
            await tools._skill_message_cb(object())("text")
        tools.assert_request = lambda message: None
        with pytest.raises(NotImplementedError):
            await tools._skill_message_cb(object())("text")
        with pytest.raises(NotImplementedError):
            await tools._skill_file_cb(object(), "stage", "producer")(b"x", "x.txt")
    finally:
        sys.settrace(previous)
    assert [call.args[0] for call in spy.call_args_list] == [
        "_assert_delivery", "_skill_msg", "_skill_file"]


@pytest.mark.parametrize("row", ["033", "034"])
async def test_scheduled_fence_spies_positive_control(row):
    """Outside an admitted scheduled run, each fence's actual raise is observed."""
    [(code, lines)] = _scheduled_fence_branches()[row]
    spy = Mock(side_effect=AssertionError(f"D19-{row} actual fence"))

    def trace(frame, event, arg):
        if frame.f_code is code:
            if event == "line" and frame.f_lineno in lines:
                spy()
            return trace
        return None

    previous = sys.gettrace()
    assert previous is None
    sys.settrace(trace)
    try:
        with pytest.raises(AssertionError, match=f"D19-{row} actual fence"):
            if row == "033":
                scheduled_events._require_phase2()
            else:
                await scheduled_events._publish_notice("c_fixture", "text")
    finally:
        sys.settrace(previous)
    spy.assert_called_once()


async def test_image_delivery_return_spy_positive_control_and_desktop_override():
    """The base media owner returns the fallback; Desktop's owner never can."""
    [(code, lines)] = _image_delivery_return()
    spy = Mock(side_effect=AssertionError("D19-002 actual image fallback"))

    def trace(frame, event, arg):
        if frame.f_code is code:
            if event == "line" and frame.f_lineno in lines:
                spy()
            return trace
        return None

    owner = media_tools.MediaTools.__new__(media_tools.MediaTools)
    owner.image_selector = object()
    previous = sys.gettrace()
    assert previous is None
    sys.settrace(trace)
    try:
        with pytest.raises(AssertionError, match="D19-002 actual image fallback"):
            await owner._handle_generate_image(object(), {"prompt": "fixture"})
    finally:
        sys.settrace(previous)
    spy.assert_called_once()


async def test_report_publication_backstop_positive_control(composed, monkeypatch):
    """A refusing report publisher reaches the actual 035 raise, once."""
    graph = composed
    [(code, lines)] = _scheduled_fence_branches()["035"]
    hits = []

    def trace(frame, event, arg):
        if frame.f_code is code:
            if event == "line" and frame.f_lineno in lines:
                hits.append(frame.f_lineno)
            return trace
        return None

    async def refuse(*_args):
        raise NotImplementedError("D19-035 positive control")

    monkeypatch.setattr(graph.core._scheduled_handlers, "_publish_report", refuse)
    Path(graph.core.config.tools.local_working_dir).mkdir(parents=True, mode=0o700)
    cid = await conversation(graph)
    saved = await rpc(graph, "schedules.save", {
        "description": "D19 refused report", "action": "check", "channel_id": cid,
        "cron": "0 0 1 1 *", "tool_name": "run_command",
        "tool_input": {"host": "localhost", "command": "printf ran"},
        "report_format": "paginated_embed_v1"})
    scheduler = graph.core.engine.deps.scheduler
    previous = sys.gettrace()
    assert previous is None
    sys.settrace(trace)
    try:
        await rpc(graph, "schedules.run", {"id": saved["id"]})
        for _ in range(500):
            if any(item["id"] == saved["id"] and item.get("last_run")
                   for item in scheduler.list_all()):
                break
            await asyncio.sleep(0.02)
    finally:
        sys.settrace(previous)
    assert hits, scheduler.list_all()
    history = await rpc(graph, "schedules.history", {"id": saved["id"]})
    assert history[-1]["status"] != "success", history


async def test_composed_media_owner_always_has_durable_publication(composed):
    """Desktop's media owner overrides both fallback seams under an admitted core."""
    owner = composed.core.engine.deps.native_tools.owners["media"]
    assert type(owner) is not media_tools.MediaTools
    assert type(owner)._publish_attachment is not media_tools.MediaTools._publish_attachment
    assert owner._delivery_available() is True


@pytest.mark.parametrize("case", ["text_consumer", "result_consumer", "permission", "policy"])
def test_runtime_miscomposition_branch_spies_positive_control(case):
    """Each backstop's actual raise is observed under deliberately malformed input."""
    row = "014" if case.endswith("consumer") else "015"
    branches = _runtime_guard_branches()[row]
    spy = Mock(side_effect=AssertionError(f"D19-{row} actual runtime branch"))
    visited = []

    def trace(frame, event, arg):
        for code, lines in branches:
            if frame.f_code is code:
                if event == "line":
                    visited.append(frame.f_lineno)
                    if frame.f_lineno in lines:
                        spy()
                return trace
        return None

    previous = sys.gettrace()
    assert previous is None
    sys.settrace(trace)
    try:
        with pytest.raises(AssertionError, match=f"D19-{row} actual runtime branch"):
            if case == "text_consumer":
                runtime_delivery.deliver_runtime_output(
                    object(), "bounded", tool_name="fixture", tool_input={}, user_id="owner")
            elif case == "result_consumer":
                runtime_delivery.deliver_runtime_result(object(), ToolResult(output="bounded"))
            elif case == "permission":
                runtime_delivery._require_retention_authority(
                    SimpleNamespace(_builtin_policy=object()), "fixture", "owner")
            else:
                class MissingPolicy:
                    def check_permission(self, *_args):
                        return None

                runtime_delivery._require_retention_authority(MissingPolicy(), "fixture", "owner")
    finally:
        sys.settrace(previous)
    assert visited
    spy.assert_called_once()


async def test_restored_agent_context_requires_admission_and_reaches_real_registration(
    guarded_core,
):
    """Trace the real admission line, not an obsolete unconditional spawn fence.

    The two old diagnostics are removed, not merely dead after an earlier raise.
    Stored envelopes still cannot invent current authority. A composed admission
    reaches registration and settles with the legacy guard spies still active.
    """
    graph = guarded_core
    configure_agent_fixture(graph)
    cid = await conversation(graph)
    receipt = await turn(graph, cid)
    preserved = graph.core.requests.fetch_request(cid, receipt["request_id"])
    owner = graph.core.engine.deps.native_tools.owners["agents"]
    handler = type(owner)._handle_spawn_agent
    source, start = inspect.getsourcelines(handler)
    node = ast.parse(textwrap.dedent("".join(source))).body[0]
    assert isinstance(node, ast.AsyncFunctionDef)
    for obsolete in (
        "Phase 2 agent request admission and invocation context is not implemented.",
        "Phase 2 agent invocation context is not implemented.",
    ):
        assert obsolete not in handler.__code__.co_consts
        assert not [part for part in ast.walk(node) if isinstance(part, ast.Constant)
                    and part.value == obsolete]
    registration = [part for part in ast.walk(node) if isinstance(part, ast.Call)
                    and isinstance(part.func, ast.Attribute)
                    and part.func.attr == "register_background"]
    assert len(registration) == 1
    admission_line = start + registration[0].lineno - 1
    assert admission_line in {line for _, _, line in handler.__code__.co_lines()}
    visited = []
    previous = sys.gettrace()

    def trace(frame, event, arg):
        if frame.f_code is handler.__code__:
            if event == "line":
                visited.append(frame.f_lineno)
            return trace
        return previous(frame, event, arg) if previous else None

    sys.settrace(trace)
    try:
        with pytest.raises(PermissionError, match="Foreign request binding"):
            await owner._handle_spawn_agent(preserved, {"label": "fixture", "goal": "no execution"})
        assert admission_line in visited
        assert not graph.core.engine.deps.agent_manager._agents
        assert not list(graph.core.store.connection.execute(
            "SELECT request_id FROM desktop_background_requests WHERE kind='agent'"))
        visited.clear()
        await turn(graph, cid, "spawn_agent", {"label": "fixture", "goal": "Bounded result"},
                   background_replies=1)
        assert admission_line in visited
        assert "spawn_agent" in {row["name"] for row in graph.provider.calls[0]["tools"]}
        agents = graph.core.engine.deps.agent_manager._agents
        assert len(agents) == 1
        agent = next(iter(agents.values()))
        await asyncio.wait_for(agent._task, 5)
        assert agent.requester_id == graph.core.authority.owner_id
        assert agent.iteration_count <= 4
        work = (await rpc(graph, "work.list", {"kind": "agent"}))["items"]
        assert len(work) == 1 and work[0]["state"] == "completed"
        assert work[0]["settlement"]["state"] == "settled"
        assert graph.core.requests.get_request(work[0]["request_id"])["state"] == "completed"
    finally:
        sys.settrace(previous)
