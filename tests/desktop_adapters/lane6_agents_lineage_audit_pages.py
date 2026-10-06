"""Frozen whole audit/page corpora using canonical desktop service ownership."""
from __future__ import annotations

import ast
import copy
import contextvars
import hashlib
import json
import uuid
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from scripts.maintenance.fixture_corpus import corpus, frozen_source, register_module
from src.agents.manager import AgentInfo
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.core import profile_config
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.desktop.work import WorkService

SUITES = {
    "test_agent_audit_parity": "24209634cb1e6bce8e0075f69fd0b2987f35b83c21d55c703c8ffb1b44222e0b",
    "test_agent_result_pages": "6e011660579a0ecf6bdd125bc0565bba6ec50e4df67b79d9e41ea94236c77c6e",
}
CORPUS_SELECTIONS = {"test_agent_audit_parity": None, "test_agent_result_pages": None}
CORPUS_EXCLUSIONS = {
    "test_agent_result_pages": ["test_byte_complete_dispatch_pages_after_eviction_and_restart"],
}
RETIRED_CASES = {
    "test_agent_result_pages.test_byte_complete_dispatch_pages_after_eviction_and_restart": {
        "reason": "Removed multi-user administrator tier: indivisible case requires admin bypass of requester/conversation binding.",
        "reviewer": "Claude, review of step 8 part 4",
        "source_sha256": "9b8600e3d5a9a60c7085b2a19347c8bbe8a3869f2f8126b01a64255337963406",
    },
}
DEFERRED_CASES = {}
lane6_agents_lineage_state = contextvars.ContextVar("lane6_agents_lineage_audit_pages_state")
lane6_agents_lineage_evidence = {}


def lane6_agents_lineage_graph(script=None):
    state = lane6_agents_lineage_state.get()
    paths = state.owner.paths
    root = paths.data_dir / ("audit-pages-" + str(len(state.graphs)))
    root.mkdir()
    store = JournalStore(root / "journal.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    cfg = profile_config(paths)
    cfg.openai_codex.enabled = False
    cfg.ollama.enabled = False
    cfg.openai_compatible.enabled = False
    cfg.browser.enabled = False
    cfg.learning.enabled = False
    cfg.turn_state.enabled = False
    cfg.context.directory = str(root / "context")
    provider = None
    if script is not None:
        from tests.fakes.llm import FakeLLM
        from src.config.schema import OpenAICompatibleModelProfile

        provider = FakeLLM(script, model="fixture")
        provider.drain_and_close = provider.close
        cfg.openai_compatible.enabled = True
        cfg.llm_provider.model = "compat:fixture"
        cfg.openai_compatible.model_profiles["fixture"] = OpenAICompatibleModelProfile(
            total_window_tokens=131072, max_output_tokens=4096)
    engine = build_engine_services(cfg, paths, state.owner.manager, delivery=delivery,
                                   compatible_client=provider)
    requests = RequestService(store, conversations, transcript, engine=engine,
                              permissions=state.owner.manager, authority=state.owner.authority,
                              delivery=delivery)
    engine.bind_requests(requests)
    work = WorkService(store, events, authority=state.owner.authority,
                       permissions=state.owner.manager, requests=requests,
                       conversations=conversations, agents=engine.deps.agent_manager,
                       tasks=engine.deps.channel_state.background_tasks)
    native = engine.deps.native_owners["agents"]
    native._background_admission = requests
    native._work_service = work
    async def lane6_agents_lineage_publish(message, text, kind=None):
        requests.assert_bound_request(message)
        return await delivery.send(message.channel, text)

    native._publish_background = lane6_agents_lineage_publish
    engine.deps.background_work_ready = True
    engine.deps.tool_catalog.invalidate()
    cid = conversations.create()["conversation"]["id"]
    graph = SimpleNamespace(engine=engine, requests=requests, work=work, store=store,
                            cid=cid, owner_id=state.owner.authority.owner_id, provider=provider)
    state.graphs.append(graph)
    state.managers[id(work.agents)] = graph
    return graph


def lane6_agents_lineage_owner_id():
    return lane6_agents_lineage_state.get().owner.authority.owner_id


def lane6_agents_lineage_build(script, **overrides):
    graph = lane6_agents_lineage_graph(script)
    return SimpleNamespace(tool_loop=graph.engine.runner, graph=graph), graph.provider


async def lane6_agents_lineage_run_iteration(bot, prompt="do the loop work", prev=None,
                                           user_id="4242"):
    graph = bot.graph
    message = graph.requests._register_background(
        "loop_iteration", uuid.uuid4().hex, prompt, graph.cid, graph.owner_id)
    async with graph.requests.background_execution(message):
        return await bot.tool_loop.run_autonomous(prompt, message, prev, graph.owner_id)


def lane6_agents_lineage_manager():
    return lane6_agents_lineage_graph().work.agents


def lane6_agents_lineage_harness(tmp_path, result="ok", error=None):
    from src.audit.logger import AuditLogger

    graph = lane6_agents_lineage_graph()
    runner = graph.engine.runner
    runner._audit = AuditLogger(str(tmp_path / "audit.jsonl"))
    runner.dispatch_loop_tool_inner = AsyncMock(return_value=result, side_effect=error)
    message = graph.requests._register_background(
        "agent", "audit-worker", "test", graph.cid, graph.owner_id)
    agent = AgentInfo(id="a", label="worker " + "x" * 300, goal="test",
                      channel_id=graph.cid, requester_id=graph.owner_id,
                      requester_name="User", parent_id="p", root_id="root", turn_id="origin")
    agent.iteration_count = 3
    graph.work.agents._agents[agent.id] = agent
    return runner, message, agent


async def lane6_agents_lineage_finish(manager, saver, text):
    import asyncio

    graph = lane6_agents_lineage_state.get().managers[id(manager)]
    root = graph.requests._register_background(
        "workflow", uuid.uuid4().hex, "result page fixture", graph.cid, graph.owner_id)
    child = None

    async def lane6_agents_lineage_iteration(*args, **kwargs):
        async with graph.requests.background_execution(child):
            return {"text": text, "tool_calls": [], "stop_reason": "end_turn"}

    async with graph.requests.background_execution(root):
        aid = manager.spawn(label="worker", goal="test", channel_id=graph.cid,
                            requester_id=graph.owner_id, requester_name="user",
                            trajectory_saver=saver,
                            iteration_callback=lane6_agents_lineage_iteration,
                            tool_executor_callback=AsyncMock())
        child = graph.requests.register_background(root, "agent", aid, "test")
        graph.work.register("agent", aid, child, parent_message=root)
    await manager._agents[aid]._task
    cleanup = manager._cleanup_tasks.pop(aid)
    cleanup.cancel()
    await asyncio.gather(cleanup, return_exceptions=True)
    return aid


def lane6_agents_lineage_dispatcher(tmp_path, manager, saver):
    graph = lane6_agents_lineage_state.get().managers[id(manager)]
    native = graph.engine.deps.native_owners["agents"]
    native._agent_trajectory_saver = saver

    async def lane6_agents_lineage_call(name, inp, uid="7", cid=42):
        owner = graph.owner_id if uid == "7" else uid
        destination = graph.cid if cid == 42 else str(cid)
        result_id = inp.get("agent_id") or next(iter(inp.get("agent_ids", [])), None)
        if cid == 42 and result_id:
            snapshot = await native._load_agent_result(result_id)
            if snapshot is not None:
                destination = snapshot["channel_id"]
        from src.tools.runtime_delivery import execution_delivery_scope
        admission = next((item for item in lane6_agents_lineage_state.get().graphs
                          if item.cid == destination), graph)
        if destination != admission.cid:
            destination = admission.cid
            return await native._handle_get_agent_results(inp, user_id=owner, channel_id="foreign-conversation")
        message = admission.requests._register_background(
            "workflow", uuid.uuid4().hex, "read result page", destination, graph.owner_id)
        async with admission.requests.background_execution(message):
            with execution_delivery_scope(owner, destination):
                out, _ = await graph.engine.deps.native_tools.dispatch(
                    name, inp, message=message, user_id=owner, skill_file_delivery="stage")
        from src.tools.result_validator import ToolResult

        return out.output if isinstance(out, ToolResult) else out

    return lane6_agents_lineage_call


def lane6_agents_lineage_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise ValueError("Frozen audit/page hash changed")
    original = ast.parse(source, filename=path)
    bridge = "tests.desktop_adapters.lane6_agents_lineage_audit_pages"
    edits = []

    class lane6_agents_lineage_setup(ast.NodeTransformer):
        def visit_Assert(self, node):
            return node

        def visit_FunctionDef(self, node):
            helpers = {"harness": "lane6_agents_lineage_harness",
                       "dispatcher": "lane6_agents_lineage_dispatcher"}
            if node.name in helpers:
                replacement = ast.parse(
                    f"from {bridge} import {helpers[node.name]} as {node.name}").body[0]
                edits.append((node, replacement))
                return ast.copy_location(replacement, node)
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            if node.name == "finish":
                replacement = ast.parse(
                    f"from {bridge} import lane6_agents_lineage_finish as finish").body[0]
                edits.append((node, replacement))
                return ast.copy_location(replacement, node)
            return self.generic_visit(node)

        def visit_ImportFrom(self, node):
            if node.module == "tests.characterization.test_autonomous_loop":
                replacement = ast.parse(
                    f"from {bridge} import lane6_agents_lineage_build as build, "
                    "lane6_agents_lineage_run_iteration as run_iteration").body[0]
            elif node.module == "src.agents.manager" and stem == "test_agent_result_pages":
                replacement = ast.parse(
                    f"from {bridge} import lane6_agents_lineage_manager as AgentManager").body[0]
            elif node.module == "src.permissions.manager" or node.module == "tests.test_native_agents_tasks":
                replacement = ast.Pass()
            else:
                return node
            edits.append((node, replacement))
            return ast.copy_location(replacement, node)

        def visit_Constant(self, node):
            if stem == "test_agent_audit_parity" and node.value == "u":
                replacement = ast.parse("lane6_agents_lineage_owner_id()", mode="eval").body
                edits.append((node, replacement))
                return ast.copy_location(replacement, node)
            return node

    tree = lane6_agents_lineage_setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(tree)
    if corpus(tree) != corpus(original):
        raise ValueError("Frozen assertions/signatures/decorators/parameters changed")
    lane6_agents_lineage_evidence[stem] = {
        "path": path, "inherited_sha256": SUITES[stem],
        "corpus_sha256": hashlib.sha256(json.dumps(corpus(original)).encode()).hexdigest(),
        "setup_hunks": [{"line": before.lineno,
                         "before_sha256": hashlib.sha256(ast.dump(before).encode()).hexdigest(),
                         "after_sha256": hashlib.sha256(ast.dump(after).encode()).hexdigest(),
                         "before_source": ast.unparse(before), "after_source": ast.unparse(after)}
                        for before, after in edits],
    }
    return tree


def lane6_agents_lineage_load(namespace):
    for stem in SUITES:
        module = ModuleType("lane6_agents_lineage_" + stem)
        module.__file__ = f"tests/{stem}.py"
        module.lane6_agents_lineage_owner_id = lane6_agents_lineage_owner_id
        exec(compile(lane6_agents_lineage_tree(stem), module.__file__, "exec"), module.__dict__)
        deferred = [key.split(".", 1)[1] for key in DEFERRED_CASES if key.startswith(stem + ".")]
        for case in [*CORPUS_EXCLUSIONS.get(stem, []), *deferred]:
            del module.__dict__[case]
        register_module(namespace, module, prefix="lane6_agents_lineage_" + stem)


load = lane6_agents_lineage_load
