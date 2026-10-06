"""Whole frozen chat-loop corpus through authenticated desktop composition."""
from __future__ import annotations

import ast
import copy
import hashlib
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.config.schema import Config
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.desktop.work import WorkService
from src.turn_state import TurnStateStore
from tests.fakes import FakeMessage

SUITES = {"test_chat_tool_loop":
          "26ddac3a5df6fd9128e4cf18a0afd7f41590232f6389c803abbb953bf3aa6608"}
CORPUS_SELECTIONS = {"test_chat_tool_loop": None}
CORPUS_EXCLUSIONS = {"test_chat_tool_loop": [
    "TestToolFailurePaths.test_rbac_denial_returned_without_execution",
    "TestToolSurfaceAndSkills.test_api_token_allowed_tools_scope_filters",
]}
RETIRED_CASES = {"test_chat_tool_loop": {
    "TestToolFailurePaths.test_rbac_denial_returned_without_execution": {
        "reason": "Removed multi-user tier denial and literal tier-too-low assertion",
        "reviewer": "Claude, review of step 8 part 4"},
    "TestToolSurfaceAndSkills.test_api_token_allowed_tools_scope_filters": {
        "reason": "Removed bearer/API-token tool scope mutates message.allowed_tools",
        "reviewer": "Claude, review of step 8 part 4"},
}}
PROPOSED_CASES = {}
lane6_agents_write_chat_chat_path = "tests/characterization/test_chat_tool_loop.py"
lane6_agents_write_chat_chat_corpus_hash = (
    "76c08be68b5ca6c22d407ebd6854ae72e58fd201fdc683fb850e909dc28988a7")
lane6_agents_write_chat_chat_current = ContextVar(
    "lane6_agents_write_chat_chat_current", default=None)
lane6_agents_write_chat_chat_evidence = {}
lane6_agents_write_chat_chat_cases = {}
EVIDENCE = lane6_agents_write_chat_chat_evidence
CASE_MAP = lane6_agents_write_chat_chat_cases


def lane6_agents_write_chat_chat_make_bot(*, fake_llm, config_overrides=None):
    state = lane6_agents_write_chat_chat_current.get()
    paths = ProfilePaths.from_xdg("chat", home=state.root / str(len(state.graphs)), environ={})
    config = Config(**(config_overrides or {}))
    config.openai_codex.enabled = False
    config.openai_compatible.enabled = False
    config.browser.enabled = False
    config.learning.enabled = False
    config.context.directory = str(paths.data_dir / "context")
    paths.create_private()
    store = JournalStore(paths.data_dir / "chat.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    ledger = TurnStateStore(paths.data_dir / "turns.sqlite3")
    fake_llm.drain_and_close = fake_llm.close
    runtime = SimpleNamespace(native_readiness=lambda: {
        # These inherited tests inject the actual canonical handlers below.
        # Readiness narrows to concrete owners, not a policy replacement.
        "create_skill": callable(engine.deps.skill_manager.create_skill),
        "analyze_image": callable(engine.deps.native_owners["media"]._handle_analyze_image),
        "myskill": engine.deps.skill_manager.has_skill("myskill"),
    })
    engine = build_engine_services(config, paths, state.owner.manager,
        delivery=delivery, codex_client=fake_llm, turn_store=ledger, runtime_context=runtime)
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=state.owner.manager, authority=state.owner.authority, delivery=delivery)
    engine.bind_requests(requests)
    deps = engine.deps
    work = WorkService(store, events, authority=state.owner.authority,
        permissions=state.owner.manager, requests=requests, conversations=conversations,
        agents=deps.agent_manager, tasks=deps.channel_state.background_tasks,
        loops=deps.loop_manager)
    deps.native_owners["agents"]._background_admission = requests
    deps.native_owners["agents"]._work_service = work
    deps.background_work_ready = True
    cid = conversations.create()["conversation"]["id"]
    graph = SimpleNamespace(engine=engine, requests=requests, work=work, store=store,
                            cid=cid, ledger=ledger, source_messages={})
    state.graphs.append(graph)
    state.graph = graph
    return SimpleNamespace(tool_loop=engine.runner, tool_executor=deps.tool_executor,
        native_tools=deps.native_tools, media_tools=deps.native_owners["media"],
        channel_state=deps.channel_state, skill_manager=deps.skill_manager,
        prompt_builder=deps.prompt_builder, tool_catalog=deps.tool_catalog,
        turn_recorder=deps.turn_recorder, completion_classifier=deps.completion_classifier,
        llm_gateway=deps.llm_gateway)


def lane6_agents_write_chat_chat_message(content, **kwargs):
    graph = lane6_agents_write_chat_chat_current.get().graph
    message = graph.requests._register_background("workflow", uuid.uuid4().hex, content,
        graph.cid, graph.requests.authority.owner_id)
    if "channel" in kwargs or "id" in kwargs:
        source = FakeMessage(content, **kwargs)
        graph.source_messages[id(source)] = (source, message)
        state = graph.engine.deps.channel_state
        if not isinstance(state.cancel_events, lane6_agents_write_chat_chat_source_channels):
            state.cancel_events = lane6_agents_write_chat_chat_source_channels(
                state.cancel_events, str(source.channel.id), graph.cid)
        return source
    return message


class lane6_agents_write_chat_chat_source_channels(MutableMapping):  # noqa: N801
    """Source-local observation alias of the canonical owner's actual Events."""

    def __init__(self, events, source_id, conversation_id):
        self.events = events
        self.source_id = source_id
        self.conversation_id = conversation_id

    def _key(self, key):
        return self.conversation_id if key == self.source_id else key

    def __getitem__(self, key):
        return self.events[self._key(key)]

    def __setitem__(self, key, value):
        self.events[self._key(key)] = value

    def __delitem__(self, key):
        del self.events[self._key(key)]

    def __iter__(self):
        return iter(self.events)

    def __len__(self):
        return len(self.events)


class lane6_agents_write_chat_chat_source_kill_observer(MagicMock):  # noqa: N801
    """Observe original fixture identity only after canonical request validation.

    This is the inherited injected kill observer, not production cancellation.
    The real manager cancellation supplement remains separately exercised.
    """

    def __call__(self, request_id):
        graph = lane6_agents_write_chat_chat_current.get().graph
        matches = [(source, message) for source, message in graph.source_messages.values()
                   if message.request_id == request_id]
        if len(matches) != 1:
            raise AssertionError("Kill observer requires the exact mapped request UUID")
        source, message = matches[0]
        graph.requests.assert_request(message)
        return super().__call__(str(source.id))


def lane6_agents_write_chat_chat_cid():
    return lane6_agents_write_chat_chat_current.get().graph.cid


async def lane6_agents_write_chat_chat_run_loop(bot, msg, history=None):
    graph = lane6_agents_write_chat_chat_current.get().graph
    canonical = graph.source_messages[id(msg)][1] if id(msg) in graph.source_messages else msg
    async with graph.requests.background_execution(canonical, settle=False):
        return await bot.tool_loop.run(canonical, history if history is not None else [
            {"role": "user", "content": msg.content}])


def lane6_agents_write_chat_chat_tree():
    source = frozen_source(lane6_agents_write_chat_chat_path)
    if hashlib.sha256(source).hexdigest() != SUITES["test_chat_tool_loop"]:
        raise AssertionError("Frozen whole chat source hash changed")
    original = ast.parse(source, filename=lane6_agents_write_chat_chat_path)
    if (hashlib.sha256(repr(corpus(original)).encode()).hexdigest()
            != lane6_agents_write_chat_chat_corpus_hash):
        raise AssertionError("Frozen whole chat corpus hash changed")
    edits = []

    class lane6_agents_write_chat_chat_setup(ast.NodeTransformer):  # noqa: N801
        def visit_ImportFrom(self, node):
            if node.module != "tests.fakes":
                return node
            swapped = [a for a in node.names if a.name in {"FakeMessage", "make_bot"}]
            retained = [a for a in node.names if a not in swapped]
            edits.append({"line": node.lineno, "operation": "canonical_owner_factory"})
            return [ast.copy_location(ast.ImportFrom(module=__name__, names=[ast.alias(
                name="lane6_agents_write_chat_chat_message" if a.name == "FakeMessage"
                else "lane6_agents_write_chat_chat_make_bot", asname=a.asname or a.name)
                for a in swapped], level=0), node), ast.copy_location(ast.ImportFrom(
                    module="tests.fakes", names=retained, level=0), node)]

        def visit_AsyncFunctionDef(self, node):
            if node.name == "run_loop":
                edits.append({"line": node.lineno, "operation": "bound_real_request_runner"})
                return ast.copy_location(ast.ImportFrom(module=__name__, names=[ast.alias(
                    name="lane6_agents_write_chat_chat_run_loop", asname="run_loop")],
                    level=0), node)
            return self.generic_visit(node)

        def visit_Assert(self, node):
            return node

        def visit_Call(self, node):
            if (getattr(node, "lineno", None) == 624 and ast.unparse(node) ==
                    "MagicMock(return_value=['a1', 'a2'])"):
                edits.append({"line": node.lineno, "operation":
                              "canonical_request_to_source_identity_observer"})
                node.func = ast.Name(id="lane6_agents_write_chat_chat_source_kill_observer",
                                     ctx=ast.Load())
            return self.generic_visit(node)

        def visit_Subscript(self, node):
            # Only setup mutations are rebound. Assertion literals stay exact.
            if (isinstance(node.value, ast.Attribute) and node.value.attr == "cancel_events"
                    and isinstance(node.slice, ast.Constant) and node.slice.value == "99"):
                edits.append({"line": node.lineno, "operation": "canonical_cancel_destination"})
                node.slice = ast.Call(func=ast.Name(
                    id="lane6_agents_write_chat_chat_cid", ctx=ast.Load()), args=[], keywords=[])
            return self.generic_visit(node)

    adapted = lane6_agents_write_chat_chat_setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if corpus(original) != corpus(adapted):
        raise AssertionError("Chat assertions/signatures/decorators/parameters changed")
    lane6_agents_write_chat_chat_evidence[lane6_agents_write_chat_chat_path] = {
        "source_sha256": SUITES["test_chat_tool_loop"],
        "corpus_sha256": lane6_agents_write_chat_chat_corpus_hash,
        "whole_suite": True, "setup_edits": edits}
    return adapted


def register_module(namespace, suite="test_chat_tool_loop"):
    if suite not in SUITES:
        raise ValueError("Unadmitted frozen chat suite")
    tree = lane6_agents_write_chat_chat_tree()
    module = ModuleType("lane6_agents_write_chat_chat_frozen")
    module.__file__ = lane6_agents_write_chat_chat_path
    module.lane6_agents_write_chat_chat_cid = lane6_agents_write_chat_chat_cid
    module.lane6_agents_write_chat_chat_source_kill_observer = (
        lane6_agents_write_chat_chat_source_kill_observer)
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            cls = getattr(module, node.name)
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    dotted = f"{node.name}.{child.name}"
                    if dotted in CORPUS_EXCLUSIONS[suite]:
                        delattr(cls, child.name)
                    else:
                        lane6_agents_write_chat_chat_cases[dotted] = (
                            f"{node.name}::{child.name}")
            namespace[node.name] = cls
        elif getattr(node, "name", "") == "_isolated_cwd":
            namespace["lane6_agents_write_chat_chat_isolated_cwd"] = getattr(module, node.name)


def load(namespace, suite="test_chat_tool_loop"):
    register_module(namespace, suite)
