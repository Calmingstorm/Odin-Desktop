"""Whole frozen agent corpora with authentic profile-local engine ownership."""

from __future__ import annotations

import ast
import contextvars
import copy
import hashlib
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from src.agents.manager import AgentManager as RetainedAgentManager
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.core import profile_config
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.desktop.work import WorkService

lane6_agents_core_state = contextvars.ContextVar("lane6_agents_core_state")
SUITES = {
    "test_agent_auto_dynamic": "24ab02cd772b8267386db861f39bab27428f7e3b0c1ed541506eca55433180da",
    "test_agent_completion_classifier": (
        "c73d509c079d20da613b9e4be74343a1457de09e493a9598aa70727a8f7d71d2"
    ),
    "test_agent_model_admission": (
        "363fbda2fdfcf2c11c902bb6b13e95429ea60807ee7e3e099db0b929d789874b"
    ),
    "test_agent_parent_activity": (
        "0cbcea1b9673a4fa3f4a96fc899a591460df576dea6afc08706a305d6093ea02"
    ),
    "test_agent_repetition": "d8166c9a8d1075476c31f4d614f3683d407acbca5824b2badd57d12aecdd0ac0",
    "test_agent_stream_progress": (
        "7290cc68cc3ae1dbb08b27de4f1254f50d043af6a9004ba8e95d711c8caa6e84"
    ),
    "test_agent_wait_budget": "97c566d0fb3fc48a0e9c947d81b1f6832249c1b1097f22c94e0d2992cd1b5719",
    "test_nested_agents": "456360eb249056add8aec170277b0f0d30247552c1bfcdf127a827c9c0566554",
}
lane6_agents_core_hashes = SUITES
lane6_agents_core_corpus_hashes = {
    "test_agent_auto_dynamic": "9cd39bf7e9b32cc08acdce0dc6409e724b1557b1c9c57d673f2388d7289215ff",
    "test_agent_completion_classifier": (
        "6f2a3e9c207f120ae161ee2825ba4f39e171111b056ad83d3c1287ce52a15fa5"
    ),
    "test_agent_model_admission": (
        "0bba2c7ff6582ba7d5704ac92f63ef09bd8252588b5476471f5dd65ef9aa6354"
    ),
    "test_agent_parent_activity": (
        "65d4f49215f9824b53edab0619b650c5482998e8131d31172a9ec6406983e32d"
    ),
    "test_agent_repetition": "15192ecb85e6eee0563b839858790ed007b4832c6848aa66bbba8f0a7212c9c8",
    "test_agent_stream_progress": (
        "74455f7c0c4a168113dc0681d347fa071672bfd3311e1b1216a850a80d3874be"
    ),
    "test_agent_wait_budget": "7a7be083cdc79ac27222cee7cd066c7e43c556b055948f071b91f0d75117ef76",
    "test_nested_agents": "86eaa8663033c96315aff007738996113e99eb640d3a75a71924289b2085e6ff",
}
CORPUS_SELECTIONS = {
    "test_agent_auto_dynamic": None,
    "test_agent_completion_classifier": None,
    "test_agent_model_admission": None,
    "test_agent_parent_activity": None,
    "test_agent_repetition": None,
    "test_agent_stream_progress": None,
    "test_agent_wait_budget": None,
    "test_nested_agents": None,
}
lane6_agents_core_retired = {
    "test_agent_completion_classifier": {
        "test_iteration_cap_failure_visible_to_wait_results_and_agents_api": (
            "Inseparable mixed wait visibility plus removed HTTP agent-list/detail listener case; "
            "retained failed wait visibility covered by lane6_agents_core supplement"
        ),
    },
    "test_nested_agents": {
        "TestRestApi.test_list_agents_includes_depth": "Removed HTTP listener setup_api contract",
    },
}
lane6_agents_core_evidence = {}
lane6_agents_core_cases = {}
CORPUS_EXCLUSIONS = {
    "test_agent_completion_classifier": [
        "test_iteration_cap_failure_visible_to_wait_results_and_agents_api"
    ],
    "test_nested_agents": ["TestRestApi.test_list_agents_includes_depth"],
}
lane6_agents_core_deferred = {}
RETIRED_CASES = {
    "test_agent_completion_classifier": {
        "test_iteration_cap_failure_visible_to_wait_results_and_agents_api": {
            "source_sha256": "c73d509c079d20da613b9e4be74343a1457de09e493a9598aa70727a8f7d71d2",
            "reason": (
                "Inseparable removed HTTP agent-list/detail listener assertion corpus; "
                "retained failed wait visibility separately supplemented"
            ),
            "reviewer": "Claude, review of step 8 part 4",
        },
    },
    "test_nested_agents": {
        "TestRestApi.test_list_agents_includes_depth": {
            "source_sha256": "456360eb249056add8aec170277b0f0d30247552c1bfcdf127a827c9c0566554",
            "reason": "Removed setup_api HTTP listener contract",
            "reviewer": "Claude, review of step 8 part 4",
        },
    },
}


def lane6_agents_core_owner_id():
    return lane6_agents_core_state.get().owner.authority.owner_id


def lane6_agents_core_engine():
    state = lane6_agents_core_state.get()
    paths = ProfilePaths.from_xdg("engine", home=state.root / str(len(state.engines)), environ={})
    config = profile_config(paths)
    config.openai_codex.enabled = False
    config.ollama.enabled = False
    config.openai_compatible.enabled = False
    config.browser.enabled = False
    config.learning.enabled = False
    config.turn_state.enabled = False
    config.context.directory = str(paths.data_dir / "context")
    store = JournalStore(paths.data_dir / "journal.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    engine = build_engine_services(config, paths, state.owner.manager, delivery=delivery)
    requests = RequestService(
        store,
        conversations,
        transcript,
        engine=engine,
        permissions=state.owner.manager,
        authority=state.owner.authority,
        delivery=delivery,
    )
    engine.bind_requests(requests)
    work = WorkService(
        store,
        events,
        authority=state.owner.authority,
        permissions=state.owner.manager,
        requests=requests,
        conversations=conversations,
        agents=engine.deps.agent_manager,
        tasks=engine.deps.channel_state.background_tasks,
    )
    native = engine.deps.native_owners["agents"]
    native._background_admission = requests
    native._work_service = work

    async def publish(message, text, kind=None):
        requests.assert_bound_request(message)
        return await delivery.send(message.channel, text)

    native._publish_background = publish
    engine.deps.background_work_ready = True
    engine.lane6_agents_core_store = store
    engine.lane6_agents_core_work = work
    state.engines.append(engine)
    return engine


def lane6_agents_core_manager(*args, **kwargs):
    engine = lane6_agents_core_engine()
    if args or kwargs:
        manager = RetainedAgentManager(*args, **kwargs)
        manager.set_completion_classifier(engine.deps.completion_classifier)
        engine.deps.agent_manager = manager
        engine.deps.native_owners["agents"]._agent_manager = manager
        engine.lane6_agents_core_work.agents = manager
    return engine.deps.agent_manager


def lane6_agents_core_tools(**overrides):
    """Keep inherited external observation/fault seams on the actual native owner."""
    engine = lane6_agents_core_engine()
    native = engine.deps.native_owners["agents"]
    for name, value in overrides.items():
        attribute = "_" + name
        if not hasattr(native, attribute):
            raise AssertionError(f"Unreviewed native setup seam: {name}")
        setattr(native, attribute, value)
        if name == "agent_manager":
            engine.deps.agent_manager = value
            engine.lane6_agents_core_work.agents = value
    return native


def lane6_agents_core_composition(config):
    engine = lane6_agents_core_engine()
    return SimpleNamespace(
        agent_manager=engine.deps.agent_manager,
        completion_classifier=engine.deps.completion_classifier,
        llm_gateway=engine.deps.llm_gateway,
    )


def lane6_agents_core_model_tools(**overrides):
    engine = lane6_agents_core_state.get().model_engine
    native = engine.deps.native_owners["agents"]
    for name, value in overrides.items():
        setattr(native, "_" + name, value)
    # Observe calls, never replace the return value or the retained admission.
    manager = engine.deps.agent_manager
    manager.spawn = Mock(wraps=manager.spawn)
    retained_spawn = native._handle_spawn_agent

    async def admitted_spawn(message, inp):
        if engine.requests.get_request(message.request_id)["state"] == "running":
            engine.requests.assert_bound_request(message)
            return await retained_spawn(message, inp)
        if engine.requests.get_request(message.request_id)["state"] != "admitted":
            raise AssertionError("Admission fixture may only execute once")
        async with engine.requests.background_execution(message):
            return await retained_spawn(message, inp)

    native._handle_spawn_agent = admitted_spawn
    return native


def lane6_agents_core_message(*args, **kwargs):
    return lane6_agents_core_state.get().model_message


def lane6_agents_core_channel():
    return lane6_agents_core_message().conversation_id


def lane6_agents_core_scheduled_handlers(**overrides):
    from src.discord.scheduled_events import (
        ScheduledEventHandlers,
        ScheduledEventsDeps,
        _scheduled_execution,
    )

    state = lane6_agents_core_state.get()
    engine = state.model_engine
    deps = engine.deps
    callback = overrides["tool_loop"].dispatch_loop_tool_inner

    async def dispatch(message, name, inp):
        engine.requests.assert_bound_request(message)
        return await callback(name, inp, message, message.owner_id)

    class Lane6AgentsCoreScheduledOwner(ScheduledEventHandlers):
        async def _execute_scheduled_tool(self, *args, **kwargs):
            async with engine.requests.background_execution(state.model_message):
                token = _scheduled_execution.set((self, state.model_message))
                try:
                    return await super()._execute_scheduled_tool(*args, **kwargs)
                finally:
                    _scheduled_execution.reset(token)

    return Lane6AgentsCoreScheduledOwner(
        ScheduledEventsDeps(
            get_config=deps.get_config,
            tool_executor=deps.tool_executor,
            audit=deps.audit,
            llm_gateway=deps.llm_gateway,
            tool_loop=engine.runner,
            agent_task_tools=deps.native_owners["agents"],
            dispatch_tool=dispatch,
        )
    )


def lane6_agents_core_agent():
    from src.agents.manager import AgentInfo

    return AgentInfo(
        id="test",
        label="test",
        goal="run once",
        channel_id="c",
        requester_id=lane6_agents_core_owner_id(),
        requester_name="Owner",
        messages=[{"role": "user", "content": "run once"}],
    )


def lane6_agents_core_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != lane6_agents_core_hashes[stem]:
        raise AssertionError("Frozen agent suite hash changed")
    original = ast.parse(source, filename=path)
    if (
        hashlib.sha256(repr(corpus(original)).encode()).hexdigest()
        != lane6_agents_core_corpus_hashes[stem]
    ):
        raise AssertionError("Frozen agent suite corpus hash changed")
    retired = lane6_agents_core_retired.get(stem, {})
    edits = []
    bridge = "tests.desktop_adapters.lane6_agents_core"

    class Setup(ast.NodeTransformer):
        def __init__(self):
            self.scope = []

        def visit_Assert(self, node):
            return node

        def visit_ClassDef(self, node):
            self.scope.append(node.name)
            result = self.generic_visit(node)
            self.scope.pop()
            return result

        def visit_FunctionDef(self, node):
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            return self.visit_FunctionDef(node)

        def visit_ImportFrom(self, node):
            if (
                stem == "test_agent_model_admission"
                and node.module == "tests.test_native_agents_tasks"
            ):
                edits.append((node.lineno, "sealed_model_admission_helpers"))
                names = {
                    "_tools": "lane6_agents_core_model_tools",
                    "_message": "lane6_agents_core_message",
                }
                swapped = [
                    ast.alias(name=names[a.name], asname=a.asname or a.name)
                    for a in node.names
                    if a.name in names
                ]
                others = [a for a in node.names if a.name not in names]
                return [
                    ast.copy_location(ast.ImportFrom(module=bridge, names=swapped, level=0), node),
                    ast.copy_location(
                        ast.ImportFrom(module=node.module, names=others, level=0), node
                    ),
                ]
            if (
                stem == "test_agent_model_admission"
                and node.module == "tests.test_scheduled_events"
            ):
                edits.append((node.lineno, "real_scheduled_owner_admission_helpers"))
                node.module = bridge
                node.names = [
                    ast.alias(
                        name={
                            "_channel": "lane6_agents_core_channel",
                            "_handlers": "lane6_agents_core_scheduled_handlers",
                        }[a.name],
                        asname=a.asname or a.name,
                    )
                    for a in node.names
                ]
            if node.module == "src.agents.manager":
                aliases = [a for a in node.names if a.name == "AgentManager"]
                if aliases:
                    retained = [a for a in node.names if a not in aliases]
                    edits.append((node.lineno, "canonical_composition_manager_import"))
                    result = [
                        ast.copy_location(
                            ast.ImportFrom(
                                module=bridge,
                                names=[
                                    ast.alias(
                                        name="lane6_agents_core_manager", asname="AgentManager"
                                    )
                                ],
                                level=0,
                            ),
                            node,
                        )
                    ]
                    if retained:
                        result.append(
                            ast.copy_location(
                                ast.ImportFrom(module=node.module, names=retained, level=0), node
                            )
                        )
                    return result
            if node.module == "tests.test_agent_transcript_contract":
                if all(a.name == "agent" for a in node.names):
                    edits.append((node.lineno, "authentic_owner_agent_fixture"))
                    node.module = bridge
                    node.names = [
                        ast.alias(name="lane6_agents_core_agent", asname=a.asname or "agent")
                        for a in node.names
                    ]
            if node.module == "tests.test_native_agents_tasks":
                aliases = [a for a in node.names if a.name == "_tools"]
                if aliases:
                    edits.append((node.lineno, "canonical_native_owner_fixture"))
                    others = [a for a in node.names if a not in aliases]
                    result = [
                        ast.copy_location(
                            ast.ImportFrom(
                                module=bridge,
                                names=[ast.alias(name="lane6_agents_core_tools", asname="_tools")],
                                level=0,
                            ),
                            node,
                        )
                    ]
                    if others:
                        result.append(
                            ast.copy_location(
                                ast.ImportFrom(module=node.module, names=others, level=0), node
                            )
                        )
                    return result
            if node.module == "src.discord.client":
                if [a.name for a in node.names] != ["OdinBot"]:
                    raise AssertionError("Unexpected removed composition import")
                edits.append((node.lineno, "desktop_composition_fixture"))
                node.module = bridge
                node.names = [ast.alias(name="lane6_agents_core_composition", asname="OdinBot")]
            if node.module == "src.tools":
                for alias in node.names:
                    if alias.name == "get_tool_definitions":
                        edits.append((node.lineno, "static_documentation_catalog"))
                        alias.name, alias.asname = (
                            "get_documentation_tool_definitions",
                            "get_tool_definitions",
                        )
                        node.module = "src.tools.registry"
            return node

        def visit_Assign(self, node):
            if stem == "test_agent_model_admission":
                targets = [ast.unparse(t) for t in node.targets]
                if targets in (
                    ["tools._agent_manager.spawn.return_value"],
                    ["tools._agent_manager._agents"],
                ):
                    edits.append((node.lineno, "remove_mock_only_manager_setup"))
                    return None
            return self.generic_visit(node)

        def visit_Call(self, node):
            self.generic_visit(node)
            if (
                stem == "test_agent_model_admission"
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_execute_scheduled_tool"
            ):
                if not isinstance(node.args[-1], ast.Constant) or node.args[-1].value != "7":
                    raise AssertionError("Unexpected inherited schedule actor setup")
                edits.append((node.lineno, "authentic_schedule_actor"))
                node.args[-1] = ast.Call(
                    func=ast.Name(id="lane6_agents_core_owner_id", ctx=ast.Load()),
                    args=[],
                    keywords=[],
                )
            if isinstance(node.func, ast.Name) and node.func.id == "Config":
                for keyword in list(node.keywords):
                    if keyword.arg == "discord":
                        node.keywords.remove(keyword)
                        edits.append((node.lineno, "removed_inert_discord_config"))
            for keyword in node.keywords:
                if keyword.arg == "requester_id" and isinstance(keyword.value, ast.Constant):
                    edits.append((node.lineno, "authentic_owner_requester"))
                    keyword.value = ast.Call(
                        func=ast.Name(id="lane6_agents_core_owner_id", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    )
            return node

    adapted = Setup().visit(copy.deepcopy(original))

    # Keep the entire frozen corpus, including retired cases, before export.
    class Projection(ast.NodeTransformer):
        def __init__(self):
            self.scope = []

        def visit_ClassDef(self, node):
            self.scope.append(node.name)
            result = self.generic_visit(node)
            self.scope.pop()
            return result

        def visit_FunctionDef(self, node):
            if ".".join([*self.scope, node.name]) in retired:
                return None
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            return self.visit_FunctionDef(node)

    expected = Projection().visit(copy.deepcopy(original))
    if corpus(adapted) != corpus(original):
        raise AssertionError("Frozen agent assertions/signatures/decorators/parameters changed")
    ast.fix_missing_locations(adapted)
    lane6_agents_core_evidence[path] = {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "retained_corpus_sha256": hashlib.sha256(repr(corpus(expected)).encode()).hexdigest(),
        "whole_suite": True,
        "setup_edits": edits,
        "retired_cases": [
            {
                "original": f"{path}::{symbol.replace('.', '::')}",
                "reason": reason,
                "reviewer": "Claude, review of step 8 part 4",
            }
            for symbol, reason in retired.items()
        ],
    }
    return adapted


def register_module(namespace, stem):
    lane6_agents_core_load(namespace, [stem])


def load(namespace):
    for stem in SUITES:
        register_module(namespace, stem)


def lane6_agents_core_load(namespace, stems=None):
    for stem in stems or lane6_agents_core_hashes:
        tree = lane6_agents_core_tree(stem)
        if stem in lane6_agents_core_deferred:
            continue
        module = ModuleType(f"lane6_agents_core_{stem}")
        module.__file__ = str(ROOT / f"tests/{stem}.py")
        module.lane6_agents_core_owner_id = lane6_agents_core_owner_id
        exec(compile(tree, module.__file__, "exec"), module.__dict__)
        for node in tree.body:
            name = getattr(node, "name", "")
            if name.startswith("test_"):
                if name in lane6_agents_core_retired.get(stem, {}):
                    continue
                target = f"test_lane6_agents_core_{stem}_{name[5:]}"
                namespace[target] = getattr(module, name)
                lane6_agents_core_cases[f"tests/{stem}.py::{name}"] = target
            elif name.startswith("Test"):
                target = f"Test_lane6_agents_core_{stem}_{name[4:]}"
                namespace[target] = getattr(module, name)
                for child in node.body:
                    if getattr(child, "name", "").startswith("test_"):
                        if f"{name}.{child.name}" in lane6_agents_core_retired.get(stem, {}):
                            delattr(namespace[target], child.name)
                            continue
                        lane6_agents_core_cases[f"tests/{stem}.py::{name}::{child.name}"] = (
                            f"{target}::{child.name}"
                        )
