"""Diagnostic alternative: frozen assertions, real admitted owner and runner.

Historical collaborators characterize a trace, not network/native E2E effects.
Permission is the production executor's gate, never the historical fake denial.
This intentionally reports incompatible literal goldens instead of normalizing
actual observations into the old requester/request identities.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import sys
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from tests.desktop_adapters import step8_review_steering as admitted

SOURCE_PATH = "tests/test_chat_steering_parity.py"
SOURCE_SHA256 = "48cf45bcceed1be223a2cf8428af0a9eff3e57b695b1d147a3e6fe7a843233ec"
# Filled with literal whole-node digests, not a broad symbol rewrite rule.
SETUP_HUNKS = [
    (147, 4, "402276aab6ab74518a15b379054b9426b8fe64e023874d0ea6fc208187d96e25",
     "runner = module._fixture_runner"),
    (254, 4, "543be3790f48c215e774c09a39060ffc8e952d55515f6661b2bf98139e117634",
     "runner._channel_state = runner._channel_state"),
    (262, 4, "07db6669e9477776676e881726c8f7121605f88655185ac1cb49a0a041dbe439",
     "runner._tool_executor = real_permission(runner, events)"),
    (276, 0, "88d4bd5dd5b6829395ee43d82fa919a7d6b2d2da4fcaca92e585e3f4c94d42fc",
     "async def _run(module, scenario, *, iteration=0, cap=3, resumed=False, "
     "initial_messages=None):\n    return await admitted_run(module, scenario, "
     "iteration=iteration, cap=cap, resumed=resumed, initial_messages=initial_messages)"),
]


def real_permission(runner, events):
    executor = runner._tool_executor
    original = executor.check_permission

    def check(name, user_id):
        graph = runner._review_graph
        assert user_id == graph.state.message.owner_id == admitted.owner_id()
        assert graph.requests.permissions.is_owner(user_id)
        # Tool children inherit admission; the parent task must remain alive.
        assert not graph.worker.done()
        denial = original(name, user_id)
        graph.permission_observations.append((name, user_id, denial))
        runner._parity_permissions.append((name, user_id))
        events.append(f"permission:{name}:{user_id}")
        return denial

    executor.check_permission = check
    return executor


class ObservedDurability:
    """Observe historical hook inputs while executing actual lease writes."""
    def __init__(self, actual, events):
        self.actual, self.events, self.checkpoints = actual, events, []

    def __getattr__(self, name):
        return getattr(self.actual, name)

    async def on_llm_response(self, st, calls):
        self.events.append("checkpoint.wi1:" + ",".join(call.id for call in calls))
        self.checkpoints.append(("wi1", st.iteration, copy.deepcopy(st.messages)))
        return await self.actual.on_llm_response(st, calls)

    async def before_tool(self, call):
        self.events.append(f"checkpoint.wi2:{call.id}")
        return await self.actual.before_tool(call)

    async def after_tool(self, call, *, ok, uncertain, result_text):
        self.events.append(f"checkpoint.wi3:{call.id}:{ok}:{uncertain}:{result_text}")
        return await self.actual.after_tool(call, ok=ok, uncertain=uncertain,
                                            result_text=result_text)

    async def on_batch_settled(self, st):
        self.events.append("checkpoint.wi4")
        self.checkpoints.append(("wi4", st.iteration, copy.deepcopy(st.messages)))
        return await self.actual.on_batch_settled(st)

    async def settle_terminal(self, *, cancelled, is_error):
        self.events.append(f"checkpoint.terminal:{cancelled}:{is_error}")
        return await self.actual.settle_terminal(cancelled=cancelled, is_error=is_error)

    async def on_guard_injection(self, st):
        self.events.append("checkpoint.guard")
        return await self.actual.on_guard_injection(st)


def mailbox(st):
    return (st._inbox.qsize(), st._inbox_event.is_set(), st.inbox_sequence,
            st.last_consumed_sequence, list(st.inbox_events))


async def run(module, scenario, *, iteration=0, cap=3, resumed=False,
              initial_messages=None):
    graph, _llm = admitted._graph([])
    observations = []
    graph.permission_observations = []

    async def execute(message, **_kwargs):
        runner = graph.runner
        graph.worker = asyncio.current_task()
        graph.requests.assert_request(message)
        assert graph.requests._workers[graph.cid] is graph.worker
        assert message.owner_id == admitted.owner_id()
        original_prepare = runner._prepare_chat_turn
        from src.discord.tool_loop import CHAT_POLICY
        st = await original_prepare(message, copy.deepcopy(module._ORIGINAL),
                                    "system", None, CHAT_POLICY)
        graph.state = st
        assert st.durability.lease is not None
        row = graph.requests.get_request(message.request_id)
        assert row["ledger_generation"] == st.durability.lease.generation
        assert runner._tool_executor.check_permission("read_only", message.owner_id) is None
        assert runner._tool_executor.check_permission("read_only", "requester-1") is not None
        graph.requests.assert_request(st.message)
        events = []
        module._fixture_runner = runner
        instrumented = module._instrument(module, scenario, events)
        assert instrumented is runner
        st.messages = copy.deepcopy(initial_messages if initial_messages is not None
                                    else module._ORIGINAL)
        st.iteration, st.chat_cap, st.trace = iteration, cap, module._Trace(events)
        st.policy = module.SimpleNamespace(skill_file_delivery=False)
        st.durability = ObservedDurability(st.durability, events)
        original_cancel = st._cancel
        previous_cancel = asyncio.Event()
        previous_cancel.set()
        if resumed:
            runner._channel_state.set_active_request(st._ch_id, "previous", previous_cancel)
            previous_cancel.set()
        else:
            runner._channel_state.set_active_request(st._ch_id, st._req_id, st._cancel)
        events.clear()
        before = mailbox(st)
        tasks_before = {task for task in asyncio.all_tasks() if not task.done()}
        graph.requests.assert_request(st.message)
        result = await (runner.run_resumed(st) if resumed else runner._run_chat_iterations(st))
        tasks_after = {task for task in asyncio.all_tasks() if not task.done()}
        observations.append({
            "result": result, "events": list(events), "messages": st.messages,
            "iteration": st.iteration, "tools": st.tools_used_in_loop,
            "continuations": st.continuation_count, "wait_pending": st.wait_judgment_pending,
            "inbox_before": before, "inbox_after": mailbox(st),
            "new_tasks": tasks_after - tasks_before,
            "generations": runner._parity_generations, "bindings": runner._parity_bindings,
            "inbox_bindings": runner._parity_inbox_bindings,
            "permissions": runner._parity_permissions, "dispatches": runner._parity_dispatches,
            "checkpoints": st.durability.checkpoints,
            "rebound_cancel": st._cancel is original_cancel,
            "previous_cancelled": previous_cancel.is_set(),
            "active_requests": dict(runner._channel_state.active_requests),
            "op_details": st._op_tool_details,
        })
        # Fresh cases characterize the loop-only boundary, just as the frozen
        # suite did. The actual admission lease is still settled, outside that
        # measured boundary. Resume executes the real guarded entry itself.
        if not resumed:
            await st.durability.actual.settle_terminal(cancelled=False, is_error=result[2])
            runner._channel_state.clear_active_request(st._ch_id, st._req_id)
        graph.requests.assert_request(st.message)
        return result

    failures = []

    async def observed_execute(*args, **kwargs):
        try:
            return await execute(*args, **kwargs)
        except Exception as error:
            failures.append(error)
            # Diagnostic failures must retire their actual temporary lease too.
            if getattr(graph, "state", None) is not None:
                await graph.state.durability.settle_terminal(cancelled=False, is_error=True)
            raise

    graph.engine.run = observed_execute
    response = graph.requests.submit({"client_submission_id": "parity-case",
                                      "conversation_id": graph.cid,
                                      "text": "original request"})
    assert graph.requests.get_request(response["request_id"])["state"] == "queued"
    await graph.requests.after_commit()
    await asyncio.gather(*list(graph.requests._tasks))
    row = graph.requests.get_request(response["request_id"])
    assert row["ledger_generation"] is not None
    if failures:
        from src.turn_state.store import TurnStatus
        assert row["state"] == "failed"
        assert graph.engine.deps.turn_store.turn_status_sync(graph.state.message.turn_key) == (
            TurnStatus.TERMINAL_FAILED)
        raise failures[0]
    assert len(observations) == 1, row
    assert row["state"] == ("failed" if observations[0]["result"][2] else "completed")
    from src.turn_state.store import TurnStatus
    assert graph.engine.deps.turn_store.turn_status_sync(graph.state.message.turn_key) == (
        TurnStatus.TERMINAL_FAILED if observations[0]["result"][2]
        else TurnStatus.TERMINAL_COMPLETED)
    return observations[0]


def adapt(source, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("parity frozen bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    rules = SETUP_HUNKS if hunks is None else hunks
    if len({(r[0], r[1], r[2]) for r in rules}) != len(rules):
        raise ValueError("duplicate parity setup hunk")
    if rules != SETUP_HUNKS:
        raise ValueError("exact parity setup allowlist changed")
    replay = []
    for line, column, digest, replacement in rules:
        matches = [(path, node) for path, node in admitted._paths(original)
                   if getattr(node, "lineno", None) == line
                   and getattr(node, "col_offset", None) == column
                   and hashlib.sha256(dump(node).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("parity setup hunk must match exactly once")
        path, node = matches[0]
        admitted._put(tree, path, ast.copy_location(ast.parse(replacement).body[0], node))
        replay.append((path, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("parity assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for path, node in replay:
        admitted._put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("parity complete AST reverse replay failed")
    return original, tree


def load(namespace):
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_review_parity_exact")
    module.__file__ = SOURCE_PATH
    async def admitted_run(_production_module, scenario, **kwargs):
        return await run(module, scenario, **kwargs)

    module.__dict__.update(real_permission=real_permission, admitted_run=admitted_run)
    sys.modules[module.__name__] = module
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    register_module(namespace, module, prefix="review_parity_exact")
    return original, tree
