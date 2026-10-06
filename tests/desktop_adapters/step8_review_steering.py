"""Exact frozen steering runtime with real request-worker admission.

The race harness pauses production preparation inside EngineServices.run. The
original cases release that same authenticated worker, never an unadmitted
make_bot or __new__ runner. No production admission/permission gate is patched.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import copy
import hashlib
import sys
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from scripts.maintenance.fixture_corpus import register_module as _register_module
from tests.desktop_adapters import step8_wait
from tests.desktop_adapters.process_cases import temporary_owner

_owner = contextvars.ContextVar("review_steering_owner", default=None)
SOURCES = {
    "parity": ("tests/test_chat_steering_parity.py",
               "48cf45bcceed1be223a2cf8428af0a9eff3e57b695b1d147a3e6fe7a843233ec"),
    "runtime": ("tests/test_chat_steering_runtime.py",
                "b41818cc97a50a4794cac024b953f7199369b225e863e1c9b4c34b2e32cc3f2b"),
}
CORPUS_SELECTIONS = {"test_chat_steering_runtime": None}
CORPUS_EXCLUSIONS = {"test_chat_steering_runtime": [{
    "case": "test_tool_batch_pairs_checkpoint_before_replan_no_stale_judgment_or_handoff",
    "reviewer": "Claude, review of #35",
    "reason": "Removed Discord admin/multi-requester steering: this case admits user 999999 "
              "as admin and asserts a distinct numeric Discord requester retains tool authority; "
              "desktop has exactly one authenticated canonical profile owner.",
    "source_path": "tests/test_chat_steering_runtime.py",
    "source_sha256": "b41818cc97a50a4794cac024b953f7199369b225e863e1c9b4c34b2e32cc3f2b",
}]}


def register_module(namespace, module, *, prefix, excluded):
    """Exact local exclusion until shared accounting adds that keyword.

    Never a selection list: all frozen tests are exported except the one
    canonical case-level removed-surface pin above. The original module stays
    intact for corpus/hash and reverse-replay verification.
    """
    expected = [item["case"] for item in CORPUS_EXCLUSIONS.get(
        "test_chat_steering_runtime" if prefix.endswith("runtime") else
        "test_chat_steering_parity", ())]
    if excluded != expected:
        raise ValueError("steering exact exclusion allowlist changed")
    exported = ModuleType(module.__name__ + "_export")
    exported.__dict__.update({key: value for key, value in module.__dict__.items()
                              if key not in excluded})
    _register_module(namespace, exported, prefix=prefix)


async def owner_fixture(tmp_path):
    with temporary_owner(tmp_path / "review-steering-owner") as state:
        state.graphs = []
        token = _owner.set(state)
        try:
            yield state
        finally:
            try:
                for graph in state.graphs:
                    try:
                        await graph.requests.close()
                        await graph.engine.close()
                    finally:
                        graph.journal.close()
            finally:
                _owner.reset(token)


def owner_id():
    state = _owner.get()
    if state is None or not state.manager.is_owner(state.authority.owner_id):
        raise RuntimeError("steering requires authenticated temporary owner")
    return state.authority.owner_id


def _graph(script):
    state = _owner.get()
    owner_id()
    # Established constructor composes real production owners and ledger.
    token = step8_wait._fixture.set(SimpleNamespace(
        paths=state.paths, manager=state.manager, authority=state.authority,
        workspace=state.workspace, graphs=[]))
    try:
        graph, llm = step8_wait.build(script)
    finally:
        step8_wait._fixture.reset(token)
    state.graphs.append(graph)
    graph.runner = graph.engine.runner
    graph.runner._review_graph = graph
    graph.counter, graph.results, graph.errors = 0, [], []
    return graph, llm


async def _submit(graph, text):
    graph.counter += 1
    response = graph.requests.submit({"client_submission_id": f"case-{graph.counter}",
                                     "conversation_id": graph.cid, "text": text})
    graph.rid = response["request_id"]
    assert graph.requests.get_request(graph.rid)["state"] == "queued"
    await graph.requests.after_commit()


async def prepare(script, *, cap=8):
    graph, llm = _graph(script)
    runner = graph.runner
    prepared, release = asyncio.Event(), asyncio.Event()
    graph.release = release
    graph.outcome = asyncio.get_running_loop().create_future()
    original_prepare = runner._prepare_chat_turn
    original_run = runner._run_with_guards
    checkpoints = []

    async def pause_prepare(*args, **kwargs):
        state = await original_prepare(*args, **kwargs)
        assert state.user_id == owner_id()
        assert state.message.owner_id == owner_id()
        assert state.durability.lease is not None
        state.chat_cap = cap
        graph.state = state
        for name in ("on_generation_start", "on_llm_response", "on_batch_settled",
                     "on_guard_injection"):
            original = getattr(state.durability, name)

            async def record(*args, _name=name, _original=original, **kwargs):
                checkpoints.append((_name, copy.deepcopy(state.messages),
                                    state.wait_judgment_pending,
                                    state.stuck_tracker.last_fingerprint))
                return await _original(*args, **kwargs)

            setattr(state.durability, name, record)
        prepared.set()
        await release.wait()
        return state

    async def observed_run(state):
        try:
            result = await original_run(state)
            graph.results.append(result)
            if not graph.outcome.done():
                graph.outcome.set_result((True, result))
            return result
        except BaseException as error:
            graph.errors.append(type(error).__name__)
            if not graph.outcome.done():
                graph.outcome.set_result((False, error))
            raise

    runner._prepare_chat_turn = pause_prepare
    runner._run_with_guards = observed_run
    from unittest.mock import AsyncMock
    runner._run_chat_iterations = AsyncMock(wraps=runner._run_chat_iterations)
    runner._turn_recorder._save_turn_trajectory = AsyncMock()
    await _submit(graph, "Original task")
    await asyncio.wait_for(prepared.wait(), 5)
    return graph, AdmittedRunnerView(runner), graph.state, llm, checkpoints


class AdmittedRunnerView:
    """Fixture observation/control facade, never a constructed replacement runner.

    All collaborators and monkeypatches reach the real composed runner. Only
    the historical fixture's launch verbs release its existing admitted worker.
    """
    def __init__(self, runner):
        object.__setattr__(self, "runner", runner)

    def __getattr__(self, name):
        return getattr(self.runner, name)

    def __setattr__(self, name, value):
        setattr(self.runner, name, value)

    async def _run_with_guards(self, state):
        return await execute_admitted(self.runner, state)

    async def run_resumed(self, state):
        return await replay_under_new_admission(self.runner, state)


async def execute_admitted(runner, state):
    graph = runner._review_graph
    assert graph.state is state
    graph.release.set()
    try:
        ok, value = await asyncio.shield(graph.outcome)
    except asyncio.CancelledError:
        for task in list(graph.requests._tasks):
            task.cancel()
        await asyncio.gather(*list(graph.requests._tasks), return_exceptions=True)
        raise
    await asyncio.gather(*list(graph.requests._tasks), return_exceptions=True)
    row = graph.requests.get_request(graph.rid)
    assert row["ledger_generation"] is not None
    assert row["state"] not in {"running", "queued"}
    if not ok:
        # Worker intentionally catches escapes to durably publish a notice;
        # preserve the inherited core-exception observation as well.
        raise value
    return value


async def replay_under_new_admission(runner, state):
    """Reusable-object defense, not explicit resume of a terminal identity.

    The original case deliberately bypasses durable resume, to check mailbox
    replacement. Keep its old mailbox but supply a new actually admitted seal
    and lease. Terminal request fences are never reopened or monkeypatched.
    """
    graph = runner._review_graph
    results = []
    async def reuse(message, **kwargs):
        graph.requests.assert_request(message)
        state.message = message
        state._ch_id, state._req_id = message.conversation_id, message.request_id
        state._cancel = asyncio.Event()
        state.durability = await graph.requests.admit_turn(
            message, system_prompt=state.system_prompt, tools=state.tools,
            session_snapshot={"reusable_object_defense": True})
        assert state.durability.lease is not None
        result = await runner.run_resumed(state)
        results.append(result)
        return result
    graph.engine.run = reuse
    await _submit(graph, state.message.content)
    await asyncio.gather(*list(graph.requests._tasks))
    assert len(results) == 1
    return results[0]


SETUP_HUNKS = {"runtime": [
    (17, 0, "10695a02a23f1bea015841c5347938d07ec3d4b025355d0fe2d94989b42eafb7",
     "from tests.fakes import FakeLLM, FakeMessage, text_response, tool_call_response",
     "statement"),
    (25, 0, "76eed546592f7619c6ea12eb67cf08da61be9d440f30f62d13db637c719fbab8",
     "async def prepare(script, *, cap=8):\n    return await admitted_prepare(script, cap=cap)",
     "statement"),
    (56,8,"04130e76ad113aa998b57c250c24d653b09c19faaede3222f8e6f8b6e89c1142",
     "{}", "keyword_unpack"),
]}


def _paths(node, path=()):
    yield path, node
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, ast.AST):
                    yield from _paths(child, (*path, field, index))
        elif isinstance(value, ast.AST):
            yield from _paths(value, (*path, field))


def _put(tree, path, value):
    target = tree
    for part in path[:-1]:
        target = target[part] if isinstance(part, int) else getattr(target, part)
    if isinstance(path[-1], int):
        target[path[-1]] = value
    else:
        setattr(target, path[-1], value)


def adapt(stem, source, *, hunks=None):
    path, expected = SOURCES[stem]
    if hashlib.sha256(source).hexdigest() != expected:
        raise ValueError("steering frozen bytes changed")
    original = ast.parse(source, filename=path)
    tree = copy.deepcopy(original)
    approved = SETUP_HUNKS[stem]
    rules = approved if hunks is None else hunks
    if len({(r[0], r[1], r[2]) for r in rules}) != len(rules):
        raise ValueError("duplicate steering setup hunk")
    if rules != approved:
        raise ValueError("exact admitted steering hunk allowlist changed")
    replay = []
    for line, column, digest, replacement, kind in rules:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and hashlib.sha256(dump(n).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("steering hunk must match exactly once")
        node_path, node = matches[0]
        if kind == "keyword_unpack":
            # Neutral **{} removes the obsolete admin keyword, keeping the AST
            # list slot so independent reverse replay has no index adjustment.
            new = ast.keyword(arg=None, value=ast.parse(replacement, mode="eval").body)
        else:
            new = (ast.parse(replacement, mode="eval").body if kind == "expression"
                   else ast.parse(replacement).body[0])
        _put(tree, node_path, ast.copy_location(new, node))
        replay.append((node_path, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("steering assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for node_path, node in replay:
        _put(restored, node_path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("steering complete AST reverse replay failed")
    return original, tree


def load(namespace):
    output = {}
    # Parity remains blocked. Its historical event tape requires substituted
    # permission/guard/transport behavior and literal Discord owner identities.
    # Do not export a false restoration merely because three cases pass.
    for stem in ("runtime",):
        path, _sha = SOURCES[stem]
        original, tree = adapt(stem, frozen_source(path))
        module = ModuleType("frozen_review_steering_" + stem)
        module.__file__ = path
        sys.modules[module.__name__] = module
        module.__dict__.update(admitted_prepare=prepare)
        exec(compile(tree, path, "exec"), module.__dict__)
        name = "test_chat_steering_" + stem
        register_module(namespace, module, prefix="review_steering_" + stem,
                        excluded=[item["case"] for item in CORPUS_EXCLUSIONS.get(name, ())])
        output[stem] = original, tree
    return output
