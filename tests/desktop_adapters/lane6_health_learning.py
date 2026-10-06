"""Exact frozen learning/recovery corpus over disposable canonical Desktop owners."""
# ruff: noqa: E501, N802
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
from contextvars import ContextVar
from functools import wraps
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source, register_module
from src.config.schema import Config
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.permissions.manager import PermissionManager

GRAPH = ContextVar("lane6_health_learning_graph")
CORPUS_SELECTIONS = {
    "test_chat_loop_recovery": None,
    "test_learning_runtime_switch": None,
    "test_learning_transport_switch": None,
}
CORPUS_EXCLUSIONS = {
    "test_chat_loop_recovery": [
        "TestEntryPointCensus.test_full_discord_run_rescues_durably",
        "TestEntryPointCensus.test_nondurable_web_run_still_rescues",
    ],
    "test_learning_runtime_switch": [
        "test_config_api_flip_drives_real_prompt_with_persisted_memory",
    ],
    "test_learning_transport_switch": [
        "test_web_physical_request_refreshes_after_provider_lock_wait",
        "test_legacy_checkpoint_resume_rebuilds_prompt_from_live_components",
    ],
}
SUITES = {
    "test_chat_loop_recovery": "13f145375ade487836f0e497ec020f9f5ef713949abbd0d4590c49a1b071e6d7",
    "test_learning_runtime_switch": "7b6e917826b8be3d19864a98f61dc5adcf295866324e60806312a4e9120e243d",
    "test_learning_transport_switch": "d0c73c09f81d9034765306690f8650c35b67478aec58ee5020915e0d2c0e7298",
}
EVIDENCE = {}
MODULES = {}
BRIDGE = "tests.desktop_adapters.lane6_health_learning"


def make_graph(tmp_path):
    paths = ProfilePaths.from_xdg("lane6-learning", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    owner_token = permissions.set_request_owner(
        authority.authenticate_local(peer_uid=authority.owner_uid))
    store = JournalStore(paths.data_dir / "transport.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    config = Config()
    config.openai_codex.enabled = False
    config.browser.enabled = False
    config.learning.enabled = False
    config.context.directory = str(paths.data_dir / "context")
    config.attachments.temp_directory = str(paths.cache_dir / "attachments")
    config_holder = SimpleNamespace(config=config)
    runtime_context = SimpleNamespace(get_config=lambda: config_holder.config)
    engine = build_engine_services(config, paths, permissions, delivery=delivery,
                                   runtime_context=runtime_context)
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=permissions, authority=authority, delivery=delivery)
    engine.bind_requests(requests)
    cid = conversations.create()["conversation"]["id"]
    message = requests._register_background("loop", "learning-fixture", "learned", cid,
                                           authority.owner_id)
    return SimpleNamespace(paths=paths, authority=authority, permissions=permissions,
        owner_token=owner_token, store=store, engine=engine, requests=requests,
        message=message, config=config, config_holder=config_holder)


def owner_id():
    return GRAPH.get().authority.owner_id


def admitted_message():
    return GRAPH.get().message


def prompt_builder(tmp_path, live):
    from src.discord.prompts import PromptBuilder
    from src.learning.reflector import ConversationReflector

    graph = GRAPH.get()
    path = tmp_path / "learned.json"
    path.write_text(json.dumps({"version": 2, "last_reflection": None, "entries": [
        {"key": "runtime_lesson", "category": "operational", "content": "learned value"}
    ]}))
    memory_path = tmp_path / "memory.json"
    memory_path.write_text(json.dumps({"global": {"manual_note": "memory value"}}))
    executor = graph.engine.deps.tool_executor
    executor._memory_path = memory_path
    config = graph.config.model_copy(deep=True)
    config.learning = live
    return PromptBuilder(get_config=lambda: config,
        context_loader=graph.engine.deps.context_loader,
        reflector=ConversationReflector(str(path), enabled=True),
        skill_manager=None, tool_executor=executor,
        channel_state=graph.engine.deps.channel_state, get_codex_client=lambda: None)


def census_runner(gw, *, config=None, recorder=None):
    module = MODULES["test_chat_loop_recovery"]
    runner, saved, cleared = module._original_census_runner(gw, config=config, recorder=recorder)
    return runner, saved, cleared


_census_runner = census_runner


def make_bot(*, fake_llm=None):
    graph = GRAPH.get()
    runner = graph.engine.runner
    gateway = graph.engine.deps.llm_gateway
    if fake_llm is not None:
        fake_llm.drain_and_close = fake_llm.close
    gateway.codex_client = fake_llm
    graph.config.openai_codex.enabled = True
    return SimpleNamespace(tool_loop=runner, prompt_builder=graph.engine.deps.prompt_builder,
                           llm_gateway=gateway)


def FakeMessage(content):
    # The durable request envelope, not an owner-shaped Discord fixture.
    return admitted_message()


def transport_tools(**overrides):
    graph = GRAPH.get()
    tools = graph.engine.deps.native_owners["agents"]
    for key, value in overrides.items():
        setattr(tools, "_" + key, value)
    from unittest.mock import MagicMock

    from src.desktop.work import WorkService
    tools._agent_manager = MagicMock()
    manager = tools._agent_manager
    # Capture callbacks without launching autonomous work; ownership and work
    # admission still execute their real services against an immutable record.
    record = SimpleNamespace(requester_id=owner_id(), channel_id=graph.message.conversation_id,
        created_at="learning-fixture-generation", status="running", label="x",
        _task=MagicMock(), iteration_count=0, tools_used=[], results=[])
    manager._agents = {"agent-1": record}
    tools._background_admission = graph.requests
    async def publish(message, text, kind=None):
        graph.requests.assert_bound_request(message)
        return await graph.engine.deps.delivery.send(message.channel, text)
    tools._publish_background = publish
    tools._work_service = WorkService(graph.store, graph.requests.events,
        authority=graph.authority, permissions=graph.permissions, requests=graph.requests,
        conversations=graph.requests.conversations, agents=manager)
    graph.config.agents.model = "gpt-5.6-sol"
    return tools


def adapted_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise ValueError("Frozen source identity changed")
    original = ast.parse(source, filename=path)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit(self, node):
            before = ast.dump(node, include_attributes=False)
            result = super().visit(node)
            after = (ast.dump(result, include_attributes=False) if isinstance(result, ast.AST)
                     else json.dumps([ast.dump(n, include_attributes=False) for n in result or []]))
            if before != after and isinstance(node, (ast.ImportFrom, ast.Call, ast.Constant, ast.Lambda)):
                edits.append({"line": node.lineno, "before_ast_sha256": hashlib.sha256(before.encode()).hexdigest(),
                              "after_ast_sha256": hashlib.sha256(after.encode()).hexdigest(),
                              "after_ast": after})
            return result

        def visit_Assert(self, node):
            return node

        def visit_ImportFrom(self, node):
            if node.module == "tests.test_chat_loop_recovery":
                node.module = BRIDGE
            elif node.module == "tests.test_native_agents_tasks":
                return [
                    ast.copy_location(ast.ImportFrom(module=BRIDGE, names=[
                        ast.alias(name="transport_tools", asname="_tools"),
                        ast.alias(name="admitted_message", asname="_message")], level=0), node),
                    ast.copy_location(ast.ImportFrom(module=node.module, names=[
                        ast.alias(name="_fake_gateway")], level=0), node)]
            elif node.module == "tests.test_resume_admission":
                return None
            elif node.module == "tests.fakes":
                return [ast.copy_location(ast.ImportFrom(module="tests.fakes.llm", names=[
                    alias for alias in node.names if alias.name in {
                        "FakeLLM", "text_response", "tool_call_response"}], level=0), node),
                    ast.copy_location(ast.ImportFrom(module=BRIDGE, names=[
                        ast.alias(name="FakeMessage"), ast.alias(name="make_bot")], level=0), node)]
            elif node.module == "src.web.api.config_admin":
                return None
            return node

        def visit_FunctionDef(self, node):
            if node.name == "_prompt_builder":
                edits.append((node.lineno, "canonical_executor_prompt_fixture"))
                return ast.copy_location(ast.ImportFrom(module=BRIDGE,
                    names=[ast.alias(name="prompt_builder", asname="_prompt_builder")], level=0), node)
            return self.generic_visit(node)

        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "Config":
                node.keywords = [k for k in node.keywords if k.arg != "discord"]
            if isinstance(node.func, ast.Name) and node.func.id == "ToolLoopDeps":
                node.keywords = [k for k in node.keywords if k.arg != "channel_config"]
                node.keywords.extend([
                    ast.keyword(arg="assert_request", value=ast.parse(
                        "GRAPH.get().engine._assert_request", mode="eval").body),
                    ast.keyword(arg="request_admission", value=ast.parse(
                        "GRAPH.get().engine._admit_turn", mode="eval").body)])
                for keyword in node.keywords:
                    if keyword.arg in {"tool_executor", "native_tools", "permissions",
                                       "skill_manager", "audit", "loop_manager"}:
                        keyword.value = ast.parse(
                            f"GRAPH.get().engine.deps.{keyword.arg}", mode="eval").body
            if isinstance(node.func, ast.Name) and node.func.id == "_ChatTurn":
                for keyword in node.keywords:
                    if keyword.arg == "message":
                        keyword.value = ast.parse("admitted_message()", mode="eval").body
            if isinstance(node.func, ast.Attribute) and node.func.attr == "run_autonomous":
                node.args[1] = ast.Call(func=ast.Name(id="admitted_message", ctx=ast.Load()), args=[], keywords=[])
            if isinstance(node.func, ast.Name) and node.func.id == "_message":
                node.keywords = []
            return node

        def visit_Lambda(self, node):
            self.generic_visit(node)
            if node.args.vararg and node.args.kwarg is None:
                node.args.kwarg = ast.arg(arg="_setup_kwargs")
            return node

        def visit_Constant(self, node):
            if node.value in ("u1", "u"):
                return ast.copy_location(ast.Call(func=ast.Name(id="owner_id", ctx=ast.Load()), args=[], keywords=[]), node)
            return node

    adapted = Setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if corpus(original) != corpus(adapted):
        raise ValueError("Assertion/signature/decorator/parameter AST changed")
    EVIDENCE[path] = {"source_sha256": SUITES[stem], "whole_suite": True,
        "exact_corpus": corpus(original), "setup_edits": edits}
    return adapted


def load(namespace):
    for stem in SUITES:
        module = ModuleType("lane6_health_learning_" + stem)
        module.__file__ = str(ROOT / f"tests/{stem}.py")
        module.__dict__.update(GRAPH=GRAPH, owner_id=owner_id, admitted_message=admitted_message)
        tree = adapted_tree(stem)
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        MODULES[stem] = module
        if stem == "test_chat_loop_recovery":
            module._original_census_runner = module._census_runner
            globals().update(_Gateway=module._Gateway, _chat_config=module._chat_config)
            original_runner = module._runner
            def runner(gateway, factory=original_runner):
                fixture = factory(gateway)
                result = GRAPH.get().engine.runner
                for attribute in ("_channel_state", "_llm_gateway", "_prompt_builder",
                                  "_get_config", "_get_context_compressor",
                                  "_get_compression_stats", "errors_seen", "_llm_error_done"):
                    setattr(result, attribute, getattr(fixture, attribute))
                return result
            module._runner = runner
        for symbol in CORPUS_EXCLUSIONS.get(stem, ()):
            parts = symbol.split(".")
            if len(parts) == 1:
                delattr(module, parts[0])
            else:
                delattr(getattr(module, parts[0]), parts[1])
        def bound(fn):
            @wraps(fn)
            async def execute(*args, **kwargs):
                graph = GRAPH.get()
                async with graph.requests.background_execution(graph.message):
                    return await fn(*args, **kwargs)
            return execute
        for key, value in list(vars(module).items()):
            if key.startswith("test_") and inspect.iscoroutinefunction(value):
                setattr(module, key, bound(value))
            elif key.startswith("Test") and isinstance(value, type):
                for method, fn in list(vars(value).items()):
                    if method.startswith("test_") and inspect.iscoroutinefunction(fn):
                        setattr(value, method, bound(fn))
        register_module(namespace, module, prefix=stem, full_class_name=True)
