"""Whole frozen transcript/trajectory corpora over canonical Desktop owners.

Only historical fixture setup changes. Providers and result/capture boundaries
are hermetic; AgentManager, ToolLoopRunner, TurnRecorder, RequestService and
WorkService remain the production implementations.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import contextvars
import functools
import hashlib
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source, nodes
from src.agents.manager import AgentInfo
from src.config.schema import Config, OpenAICompatibleModelProfile
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.desktop.work import WorkService
from src.observability.correlation import get_turn
from tests.desktop_adapters.tools_cases import owner_fixture

lane6_agents_lineage_state = contextvars.ContextVar("lane6_agents_lineage_transcript", default=None)
lane6_agents_lineage_hashes = {
    "test_agent_transcript_contract": "2f0980cf7385abab6fdb4d35efaca2198c2bbe1d3e35b0c5a7bc7943067fc7d0",
    "test_trajectory_completeness": "5de597c2ea6e15ea22cdcb8fa582f24ac19dfb4650505c38d3b00d063f2e203d",
}
SUITES = {
    "test_agent_transcript_contract": "2f0980cf7385abab6fdb4d35efaca2198c2bbe1d3e35b0c5a7bc7943067fc7d0",
    "test_trajectory_completeness": "5de597c2ea6e15ea22cdcb8fa582f24ac19dfb4650505c38d3b00d063f2e203d",
}
CORPUS_SELECTIONS = {"test_agent_transcript_contract": None, "test_trajectory_completeness": None}
DEFERRED_CASES = {}
lane6_agents_lineage_evidence = {}
lane6_agents_lineage_case_map = {}
lane6_agents_lineage_deferred = []


class lane6_agents_lineage_provider:
    model = "test"
    provider_name = "compat"

    async def chat_with_tools(self, **kwargs):
        raise AssertionError("No unconfigured provider generation")

    async def chat(self, **kwargs):
        return "COMPLETE"

    async def drain_and_close(self):
        pass


def lane6_agents_lineage_graph(owner):
    cfg = Config()
    cfg.openai_codex.enabled = False
    cfg.openai_compatible.enabled = True
    cfg.llm_provider.model = "compat:test"
    cfg.context.directory = str(owner.paths.data_dir / "context")
    cfg.learning.enabled = False
    cfg.browser.enabled = False
    cfg.turn_state.enabled = False
    cfg.agents.model = "compat:test"
    cfg.openai_compatible.model_profiles["test"] = OpenAICompatibleModelProfile(
        total_window_tokens=128000, max_output_tokens=4096, supports_thinking_mode=True)
    store = JournalStore(owner.paths.data_dir / "lane6_agents_lineage_journal.sqlite3", "test")
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    engine = build_engine_services(cfg, owner.paths, owner.manager, delivery=delivery,
        compatible_client=lane6_agents_lineage_provider())
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=owner.manager, authority=owner.authority, delivery=delivery)
    engine.bind_requests(requests)
    work = WorkService(store, events, authority=owner.authority, permissions=owner.manager,
        requests=requests, conversations=conversations, agents=engine.deps.agent_manager,
        tasks=engine.deps.channel_state.background_tasks, loops=engine.deps.loop_manager,
        processes=engine.deps.tool_executor._ensure_process_registry(), scheduler=engine.deps.scheduler)
    native = engine.deps.native_owners["agents"]
    native._background_admission, native._work_service = requests, work

    async def lane6_agents_lineage_publish(message, text):
        requests.assert_bound_request(message)
        await delivery.send(message.channel, text)

    native._publish_background = lane6_agents_lineage_publish
    engine.deps.background_work_ready = True
    cid = conversations.create()["conversation"]["id"]
    return SimpleNamespace(owner=owner, config=cfg, engine=engine, requests=requests,
        work=work, native=native, store=store, cid=cid, delivery=delivery,
        captured_spawn=None)


def lane6_agents_lineage_current():
    state = lane6_agents_lineage_state.get()
    if state is None:
        raise RuntimeError("Canonical lineage fixture required")
    return state


def lane6_agents_lineage_agent():
    state = lane6_agents_lineage_current()
    message = state.requests.current_bound_request()
    agent = AgentInfo(id="test", label="test", goal="run once",
        channel_id=message.conversation_id, requester_id=message.owner_id,
        requester_name="Owner", messages=[{"role": "user", "content": "run once"}])
    state.engine.deps.agent_manager._agents[agent.id] = agent
    state.work.register("agent", agent.id, message)
    return agent


def lane6_agents_lineage_gateway(client):
    state = lane6_agents_lineage_current()
    gateway = state.engine.deps.llm_gateway
    gateway.compatible_client = client
    return gateway


def lane6_agents_lineage_message():
    state = lane6_agents_lineage_current()
    return state.requests.current_bound_request()


def lane6_agents_lineage_tools(**kwargs):
    state = lane6_agents_lineage_current()
    if kwargs.get("llm_gateway") is not state.engine.deps.llm_gateway:
        raise AssertionError("The callback must use the composed gateway")
    manager = state.engine.deps.agent_manager
    spawn = manager.spawn

    def lane6_agents_lineage_capture_spawn(**inputs):
        # Launch a real manager-owned metadata/task and register it through the
        # real handler. Hold only its provider callback so the inherited replay
        # can drive the captured callback exactly once, without a second model.
        state.captured_spawn = inputs

        async def lane6_agents_lineage_held_generation(*args, **kw):
            await asyncio.Event().wait()

        return spawn(**{**inputs, "iteration_callback": lane6_agents_lineage_held_generation})

    manager.spawn = MagicMock(wraps=lane6_agents_lineage_capture_spawn)
    return state.native


def lane6_agents_lineage_recording_setup(instance, enabled=True, cap=4000):
    state = lane6_agents_lineage_current()
    state.config.observability.trajectory_user_content = enabled
    state.config.observability.max_user_content_chars = cap
    instance.config = state.config
    instance._turn_recorder = state.engine.deps.turn_recorder


def lane6_agents_lineage_loop_setup(instance, responses, tool_output="hi out", result_cap=2000):
    state = lane6_agents_lineage_current()
    cfg = state.config
    cfg.observability.loop_trace = True
    cfg.observability.trajectory_user_content = True
    cfg.observability.max_user_content_chars = 4000
    cfg.observability.max_tool_result_chars = result_cap
    cfg.tools.command_timeout_seconds = 5
    cfg.tools.max_tool_iterations_loop = 4
    instance.config = cfg
    instance._responses = list(responses)
    instance._tool_output = tool_output
    instance.saved, instance.reflected, instance.dispatched = [], [], []
    instance.lane6_agents_lineage_dispatch_owners = []
    instance.loop_manager = state.engine.deps.loop_manager
    instance._turn_recorder = state.engine.deps.turn_recorder
    instance._tool_loop_runner = state.engine.runner
    instance.audit = state.engine.deps.audit
    instance.audit.log_event = AsyncMock()
    instance.audit.log_execution = AsyncMock()

    async def lane6_agents_lineage_chat(**kwargs):
        return instance._responses.pop(0)

    instance.llm_client = lane6_agents_lineage_provider()
    instance.llm_client.chat_with_tools = lane6_agents_lineage_chat
    state.engine.deps.llm_gateway.compatible_client = instance.llm_client
    instance._turn_recorder._save_turn_trajectory = instance._save_turn_trajectory
    instance._turn_recorder._maybe_loop_reflect = instance._maybe_loop_reflect

    async def lane6_agents_lineage_dispatch(name, inputs, message, user_id, *, audit_owned_by_caller=False):
        state.requests.assert_bound_request(message)
        if user_id != message.owner_id:
            raise AssertionError("Tool dispatch lost authenticated owner")
        instance.lane6_agents_lineage_dispatch_owners.append(user_id)
        # This legacy caller spelling is capture metadata only. The production
        # runner above receives and verifies the real profile owner; the stub
        # result boundary retains the inherited observation's display label.
        return await instance._dispatch_loop_tool(name, inputs, message,
            instance.lane6_agents_lineage_caller_label,
            audit_owned_by_caller=audit_owned_by_caller)

    instance._tool_loop_runner.dispatch_loop_tool = lane6_agents_lineage_dispatch


async def lane6_agents_lineage_run_loop(instance, prompt, channel, prev_context, user_id):
    state = lane6_agents_lineage_current()
    parent = state.requests.current_bound_request()
    message = state.requests.register_background(parent, "loop_iteration", uuid4().hex, prompt)
    instance.lane6_agents_lineage_caller_label = user_id
    async with state.requests.background_execution(message):
        return await state.engine.runner.run_autonomous(prompt, message, prev_context, message.owner_id)


def lane6_agents_lineage_loop_manager():
    state = lane6_agents_lineage_current()
    manager = state.engine.deps.loop_manager

    def lane6_agents_lineage_start_loop(*, goal, channel, requester_id, requester_name,
                                      iteration_callback, **kwargs):
        parent = state.requests.current_bound_request()
        admitted = {}

        def lane6_agents_lineage_before_start(info):
            message = state.requests.register_background(parent, "loop", info.id, goal)
            admitted["message"] = message
            state.work.register("loop", info.id, message, parent_message=parent)

        @asynccontextmanager
        async def lane6_agents_lineage_execution(info):
            async with state.requests.background_execution(admitted["message"], settle=False):
                yield

        async def lane6_agents_lineage_publication(info, text):
            message = admitted["message"]
            state.requests.assert_bound_request(message)
            # Preserve the inherited capture container only, never invoke its
            # send-shaped method or treat it as authority/destination.
            channel.send_stamps.append(get_turn())
            await state.delivery.send(message.channel, text)

        def lane6_agents_lineage_settled(info):
            state.requests.settle_background(admitted["message"],
                "completed" if info.status == "completed" else "cancelled")
            state.work.refresh_all()

        return manager.start_admitted_loop(goal=goal, channel=parent.channel,
            requester_id=parent.owner_id, requester_name=parent.owner_name,
            iteration_callback=iteration_callback, before_start=lane6_agents_lineage_before_start,
            execution=lane6_agents_lineage_execution, publish=lane6_agents_lineage_publication,
            on_settled=lane6_agents_lineage_settled, **kwargs)

    manager.start_loop = lane6_agents_lineage_start_loop
    return manager


def lane6_agents_lineage_adapted_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != lane6_agents_lineage_hashes[stem]:
        raise AssertionError("Frozen suite identity changed")
    original = ast.parse(source, filename=path)
    expected = copy.deepcopy(original)
    edits = []
    bridge = __name__

    class lane6_agents_lineage_setup(ast.NodeTransformer):
        def visit_Assert(self, node):
            return node

        def visit_ImportFrom(self, node):
            if node.module == "tests.test_native_agents_tasks":
                node.module = bridge
                node.names = [ast.alias(name="lane6_agents_lineage_gateway", asname="_fake_gateway"),
                    ast.alias(name="lane6_agents_lineage_message", asname="_message"),
                    ast.alias(name="lane6_agents_lineage_tools", asname="_tools")]
                edits.append((node.lineno, "canonical_native_owner_fixture_import"))
            elif stem == "test_trajectory_completeness" and node.module == "src.tools.autonomous_loop":
                node.module = bridge
                node.names = [ast.alias(name="lane6_agents_lineage_loop_manager", asname="LoopManager")]
                edits.append((node.lineno, "canonical_admitted_loop_stamp_fixture"))
            return node

        def visit_FunctionDef(self, node):
            if stem == "test_agent_transcript_contract" and node.name == "agent":
                node.body = ast.parse(f"return {bridge}.lane6_agents_lineage_agent()".replace(
                    f"{bridge}.", "")).body
                edits.append((node.lineno, "authenticated_manager_owned_agent_fixture"))
            if node.name == "__init__" and stem == "test_trajectory_completeness":
                if node.lineno == 202:
                    node.body = [item for item in node.body if isinstance(item, (ast.Import, ast.ImportFrom, ast.ClassDef))] + ast.parse("lane6_agents_lineage_recording_setup(self, enabled, cap)").body
                    edits.append((node.lineno, "canonical_turn_recorder_setup"))
                elif node.lineno == 303:
                    node.body = [item for item in node.body if isinstance(item, (ast.Import, ast.ImportFrom, ast.ClassDef))] + ast.parse("lane6_agents_lineage_loop_setup(self, responses, tool_output, result_cap)").body
                    edits.append((node.lineno, "canonical_autonomous_runner_setup"))
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            if stem == "test_trajectory_completeness" and node.name == "_run_loop_iteration":
                node.body = ast.parse("return await lane6_agents_lineage_run_loop(self, prompt, channel, prev_context, user_id)").body
                edits.append((node.lineno, "sealed_request_autonomous_intake"))
            return self.generic_visit(node)

        def visit_Assign(self, node):
            if stem == "test_agent_transcript_contract" and node.lineno in (89, 90):
                edits.append((node.lineno, "remove_mock_manager_mutation"))
                return None
            return self.generic_visit(node)

    adapted = lane6_agents_lineage_setup().visit(copy.deepcopy(expected))
    ast.fix_missing_locations(adapted)
    if corpus(adapted) != corpus(expected):
        raise AssertionError("Retained whole-suite assertion/signature/decorator/parameter corpus changed")
    lane6_agents_lineage_evidence[path] = {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "retained_corpus_sha256": hashlib.sha256(repr(corpus(expected)).encode()).hexdigest(),
        "whole_suite": True, "original_cases": len(corpus(original)["cases"]),
        "retained_cases": len(corpus(expected)["cases"]), "setup_edits": edits,
        "exact_corpus": corpus(expected),
    }
    return adapted


def lane6_agents_lineage_bound_case(function):
    @functools.wraps(function)
    async def lane6_agents_lineage_bound(*args, **kwargs):
        state = lane6_agents_lineage_current()
        message = state.requests._register_background("task", uuid4().hex, "frozen test",
            state.cid, state.owner.authority.owner_id)
        async with state.requests.background_execution(message):
            result = function(*args, **kwargs)
            return await result if asyncio.iscoroutine(result) else result
    return lane6_agents_lineage_bound


def lane6_agents_lineage_load(namespace):
    for stem in lane6_agents_lineage_hashes:
        tree = lane6_agents_lineage_adapted_tree(stem)
        module = ModuleType(f"lane6_agents_lineage_{stem}")
        module.__file__ = str(ROOT / f"tests/{stem}.py")
        module.__dict__.update({name: value for name, value in globals().items()
                               if name.startswith("lane6_agents_lineage_")})
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        for item in tree.body:
            name = getattr(item, "name", "")
            value = getattr(module, name, None)
            if name.startswith("test_"):
                exported = f"test_lane6_agents_lineage_{stem[5:]}__{name[5:]}"
                namespace[exported] = lane6_agents_lineage_bound_case(value)
                lane6_agents_lineage_case_map[f"tests/{stem}.py::{name}"] = exported
            elif name.startswith("Test"):
                exported = f"Test_lane6_agents_lineage_{stem[5:]}_{name[4:]}"
                for member in item.body:
                    method = getattr(member, "name", "")
                    if method.startswith("test_"):
                        function = getattr(value, method)
                        setattr(value, method, lane6_agents_lineage_bound_case(function))
                        lane6_agents_lineage_case_map[f"tests/{stem}.py::{name}::{method}"] = f"{exported}::{method}"
                namespace[exported] = value


def register_module(namespace):
    lane6_agents_lineage_load(namespace)


def load(namespace):
    register_module(namespace)
