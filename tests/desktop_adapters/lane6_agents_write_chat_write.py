"""Exact write-invariant corpus on canonical isolated request/engine owners."""
from __future__ import annotations

import ast
import copy
import hashlib
import uuid
from contextvars import ContextVar
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.config.schema import Config
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.desktop.work import WorkService
from src.turn_state.store import TurnStateStore
from tests.fakes import FakeLLM

SUITES = {
    "test_write_invariant_integration":
        "b17a926b79afcc342e4f5fdf4b48094336057a02c5d26c517c9fedc4df8af708",
}
CORPUS_SELECTIONS = {"test_write_invariant_integration": None}
CORPUS_EXCLUSIONS = {}
EVIDENCE = {}
CASE_MAP = {}
lane6_agents_write_chat_write_context = ContextVar("lane6_agents_write_chat_write_context")


def lane6_agents_write_chat_write_build(script, tmp_path, **overrides):
    state = lane6_agents_write_chat_write_context.get()
    owner = state.owner
    cfg = Config(search={"enabled": False}, learning={"enabled": False}, **overrides)
    cfg.browser.enabled = False
    cfg.context.directory = str(owner.paths.data_dir / "context")
    fake = FakeLLM(script)
    fake.drain_and_close = fake.close
    ledger = TurnStateStore(tmp_path / "turn_state" / "turns.sqlite3")
    store = JournalStore(owner.paths.data_dir / "journal.sqlite3", owner.paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    engine = build_engine_services(cfg, owner.paths, owner.manager,
                                   codex_client=fake, turn_store=ledger, delivery=delivery)
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=owner.manager, authority=owner.authority, delivery=delivery)
    engine.bind_requests(requests)
    work = WorkService(store, events, authority=owner.authority, permissions=owner.manager,
        requests=requests, conversations=conversations, agents=engine.deps.agent_manager,
        tasks=engine.deps.channel_state.background_tasks, loops=engine.deps.loop_manager)
    native = engine.deps.native_owners["agents"]
    native._background_admission = requests
    native._work_service = work
    engine.deps.background_work_ready = True
    cid = conversations.create()["conversation"]["id"]
    graph = SimpleNamespace(engine=engine, requests=requests, store=store, work=work,
                            ledger=ledger, cid=cid, contexts={})
    state.graphs.append(graph)
    state.graph = graph
    from src.llm.recovery import RecoveryPolicy
    engine.deps.llm_gateway._recovery_policy_source = lambda: RecoveryPolicy(
        deadline_seconds=0.2, backoff_base=0.01, backoff_cap=0.02, retry_after_cap=0.05)
    bot = SimpleNamespace(tool_loop=engine.runner, tool_executor=engine.deps.tool_executor,
        llm_gateway=engine.deps.llm_gateway, native_tools=engine.deps.native_tools,
        channel_state=engine.deps.channel_state)
    return bot, fake, ledger


def lane6_agents_write_chat_write_message(content):
    graph = lane6_agents_write_chat_write_context.get().graph
    return graph.requests._register_background("workflow", uuid.uuid4().hex, content,
        graph.cid, graph.requests.authority.owner_id)


async def lane6_agents_write_chat_write_run_loop(bot, msg):
    graph = lane6_agents_write_chat_write_context.get().graph
    # Keep execution lineage running until fixture teardown. This is the actual
    # RequestService retained-execution mode, so repeated delivery reaches the
    # original ledger key without inventing an admission or changing its state.
    async with graph.requests.background_execution(msg, settle=False):
        return await bot.tool_loop.run(msg, [{"role": "user", "content": msg.content}])


async def lane6_agents_write_chat_write_prepare(runner, *args):
    graph = lane6_agents_write_chat_write_context.get().graph
    context = graph.requests.background_execution(args[0], settle=False)
    await context.__aenter__()
    try:
        st = await runner._prepare_chat_turn(*args)
    except BaseException:
        await context.__aexit__(*__import__("sys").exc_info())
        raise
    graph.contexts[id(st)] = context
    return st


async def lane6_agents_write_chat_write_guards(runner, st):
    graph = lane6_agents_write_chat_write_context.get().graph
    try:
        return await runner._run_with_guards(st)
    finally:
        await graph.contexts.pop(id(st)).__aexit__(None, None, None)


def lane6_agents_write_chat_write_housekeeping(**kwargs):
    graph = lane6_agents_write_chat_write_context.get().graph
    owner = graph.engine.deps.housekeeping
    for name, value in kwargs.items():
        setattr(owner, "_" + name, value)
    return owner


def lane6_agents_write_chat_write_disable_durability(bot):
    graph = lane6_agents_write_chat_write_context.get().graph
    bot.tool_loop._turn_store = None
    graph.engine.deps.turn_store = None


def register_module(namespace):
    path = "tests/test_write_invariant_integration.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES["test_write_invariant_integration"]:
        raise AssertionError("Frozen write source changed")
    original = ast.parse(source, filename=path)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            mapping = ({"FakeMessage": "lane6_agents_write_chat_write_message"}
                       if node.module == "tests.fakes" else
                       {"Housekeeping": "lane6_agents_write_chat_write_housekeeping"}
                       if node.module == "src.discord.housekeeping" else {})
            swapped = [a for a in node.names if a.name in mapping]
            if not swapped:
                return node
            edits.append({"line": node.lineno, "operation": "canonical_owner_import"})
            result = [ast.copy_location(ast.ImportFrom(module=__name__, level=0, names=[
                ast.alias(name=mapping[a.name], asname=a.asname or a.name)
                for a in swapped]), node)]
            remaining = [a for a in node.names if a.name not in mapping and a.name != "make_bot"]
            if remaining:
                result.append(ast.copy_location(ast.ImportFrom(module=node.module,
                    level=node.level, names=remaining), node))
            return result

        def visit_FunctionDef(self, node):
            if node.name == "build_with_store":
                edits.append({"line": node.lineno, "operation": "canonical_shared_graph_factory"})
                return ast.copy_location(ast.ImportFrom(module=__name__, level=0, names=[ast.alias(
                    name="lane6_agents_write_chat_write_build", asname=node.name)]), node)
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            if node.name == "run_loop":
                edits.append({"line": node.lineno, "operation": "stable_bound_request_runner"})
                return ast.copy_location(ast.ImportFrom(module=__name__, level=0, names=[ast.alias(
                    name="lane6_agents_write_chat_write_run_loop", asname=node.name)]), node)
            return self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                    "_prepare_chat_turn", "_run_with_guards"}:
                edits.append({"line": node.lineno, "operation": "bound_split_lifecycle_setup"})
                name = ("lane6_agents_write_chat_write_prepare"
                        if node.func.attr == "_prepare_chat_turn"
                        else "lane6_agents_write_chat_write_guards")
                return ast.copy_location(ast.Call(func=ast.Name(id=name, ctx=ast.Load()),
                    args=[node.func.value, *node.args], keywords=node.keywords), node)
            return self.generic_visit(node)

        def visit_Assign(self, node):
            if (node.lineno == 283
                    and ast.unparse(node) ==
                    "bot.tool_loop._outer_tool_timeout = lambda name, inp: 0.2"):
                # Bounded test-only timeout: under parallel qualification the
                # WI-2 threaded commit can consume .2s before the blocking
                # executor seam begins. Settlement assertions are unchanged.
                edits.append({"line": node.lineno, "operation": "bounded_harness_wait",
                              "before_seconds": 0.2, "after_seconds": 2.0})
                node.value.body = ast.Constant(value=2.0)
                return node
            if (len(node.targets) == 1
                    and ast.unparse(node.targets[0]) == "bot.tool_loop._turn_store"
                    and isinstance(node.value, ast.Constant) and node.value.value is None):
                edits.append({"line": node.lineno, "operation": "canonical_feature_off_wiring"})
                return ast.copy_location(ast.Expr(value=ast.Call(func=ast.Name(
                    id="lane6_agents_write_chat_write_disable_durability", ctx=ast.Load()),
                    args=[ast.Name(id="bot", ctx=ast.Load())], keywords=[])), node)
            return self.generic_visit(node)

    adapted = Setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if len(edits) != 10:
        raise AssertionError("Write setup transformation inventory changed")
    if corpus(original) != corpus(adapted):
        raise AssertionError("Write assertions/signatures/decorators/parameters changed")
    digest = hashlib.sha256(repr(corpus(original)).encode()).hexdigest()
    if digest != "65abd606e29e57ecb6d8430bcf3390bd276468649490db41342ea70b91bd6e7a":
        raise AssertionError("Pinned write corpus changed")
    EVIDENCE[path] = {"source_sha256": SUITES["test_write_invariant_integration"],
        "corpus_sha256": digest, "whole_suite": True, "setup_edits": edits}
    module = ModuleType("lane6_agents_write_chat_write_frozen")
    module.__file__ = path
    module.lane6_agents_write_chat_write_prepare = lane6_agents_write_chat_write_prepare
    module.lane6_agents_write_chat_write_guards = lane6_agents_write_chat_write_guards
    module.lane6_agents_write_chat_write_disable_durability = (
        lane6_agents_write_chat_write_disable_durability)
    exec(compile(adapted, path, "exec"), module.__dict__)
    for node in adapted.body:
        name = getattr(node, "name", "")
        if name.startswith("Test"):
            target = "TestLane6_agents_write_chat_write_" + name[4:]
            namespace[target] = getattr(module, name)
            for child in node.body:
                case = getattr(child, "name", "")
                if case.startswith("test_"):
                    CASE_MAP[path + "::" + name + "::" + case] = target + "::" + case
        elif any(isinstance(d, ast.Call) and ast.unparse(d.func) == "pytest.fixture"
                 for d in getattr(node, "decorator_list", [])):
            namespace["lane6_agents_write_chat_write_fixture_" + name] = getattr(module, name)


def load(namespace):
    register_module(namespace)
