"""Fail-on-invocation proofs for legacy D19 guards, on the composed profile.

No readiness override, fake executor, desktop input or production profile. The
provider/keyring boundaries and Unix RPC helpers are the existing D19 fixtures.
Background admission is currently refused, not restored: this test deliberately
does not turn a stale delegate_task request into an invented background owner.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.discord import delivery, intake_pipeline, slash_commands, tool_loop, wiring
from src.discord.native_tools.channel_ops import ChannelOpsTools
from src.tools import output_authorization
from tests.test_desktop_d19_behaviour import composed as composed  # shared pytest fixture
from tests.test_desktop_d19_behaviour import (
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

    def trace(frame, event, arg):
        # An imported alias can bypass the patched module attribute. Bind
        # an additional raising spy to the original code object, e.g. the guard
        # imported by turn_resume, rather than leaving that alias unobserved.
        if event == "call" and frame.f_code in original_codes:
            original_codes[frame.f_code]()
        if frame.f_code is code:
            if event == "call":
                visited["handler"] += 1
            elif event == "line" and frame.f_lineno in lines:
                spies["001"]()
            return trace
        if frame.f_code in reader_codes and event == "call":
            visited["reader"] += 1
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
    "chat_history", "background_admission_refusal", "mcp_start_stop", "shutdown",
])
async def test_composed_flows_never_invoke_legacy_guards(guarded_core, guard_spies, flow):
    """All nine spies are installed before CoreService.start and through close."""
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
    elif flow == "background_admission_refusal":
        tasks = graph.core.engine.deps.channel_state.background_tasks
        before = dict(tasks)
        cid = await conversation(graph)
        await turn(graph, cid, "delegate_task", {
            "description": "Bounded background admission proof",
            "steps": [{"tool_name": "memory_manage", "tool_input": {
                "action": "save", "scope": "global", "key": "never", "value": "run"}}],
        }, expected_state="failed")
        assert "delegate_task" not in {row["name"] for row in graph.provider.calls[0]["tools"]}
        assert "Output capability unavailable" in graph.core.transcript.read_conversation(
            cid)[-1]["text"]
        assert tasks == before
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


async def test_agent_invocation_context_is_dead_after_unconditional_spawn_fence(guarded_core):
    """D19-006 is not the reachable D19-005 admission refusal.

    Unlike row001, Python does not even emit bytecode for this obsolete raise.
    Prove that structurally, trace the precise real method, and reach its earlier
    fence without disabling readiness or fabricating a task-owned agent context.
    """
    graph = guarded_core
    owner = graph.core.engine.deps.native_tools.owners["agents"]
    handler = type(owner)._handle_spawn_agent
    source, start = inspect.getsourcelines(handler)
    node = ast.parse(textwrap.dedent("".join(source))).body[0]
    assert isinstance(node, ast.AsyncFunctionDef)
    first = node.body[1]  # function docstring precedes the unconditional fence
    assert isinstance(first, ast.Raise)
    assert ast.literal_eval(first.exc.args[0]) == (
        "Phase 2 agent request admission and invocation context is not implemented.")
    dead = [part for part in node.body if isinstance(part, ast.Raise)
            and isinstance(part.exc, ast.Call)
            and part.exc.args
            and isinstance(part.exc.args[0], ast.Constant)
            and part.exc.args[0].value == "Phase 2 agent invocation context is not implemented."]
    assert len(dead) == 1
    dead_line = start + dead[0].lineno - 1
    assert dead_line not in {line for _, _, line in handler.__code__.co_lines()}
    assert "Phase 2 agent invocation context is not implemented." not in handler.__code__.co_consts
    visited = []
    spy = Mock(side_effect=AssertionError("D19-006 dead invocation context reached"))
    previous = sys.gettrace()

    def trace(frame, event, arg):
        if frame.f_code is handler.__code__:
            if event == "line":
                visited.append(frame.f_lineno)
                if frame.f_lineno == dead_line:
                    spy()
            return trace
        return previous(frame, event, arg) if previous else None

    sys.settrace(trace)
    try:
        # Directly exercise the actual owner to distinguish unreachable 006
        # from reachable 005. This is deliberately not a composed admission.
        with pytest.raises(RuntimeError, match="agent request admission and invocation context"):
            await owner._handle_spawn_agent(None, {"label": "fixture", "goal": "no execution"})
        assert visited and start + first.lineno - 1 in visited
        for tool, arguments in [
            ("spawn_agent", {"label": "fixture", "goal": "no execution", "model": "compat:test"}),
            ("get_agent_results", {"agent_id": "fixture"}),
        ]:
            await turn(graph, await conversation(graph), tool, arguments, expected_state="failed")
            assert tool not in {row["name"] for row in graph.provider.calls[0]["tools"]}
    finally:
        sys.settrace(previous)
    spy.assert_not_called()
    assert not graph.core.engine.deps.agent_manager._agents
