"""Hash-bound characterization cases on real profile-local service owners.

Only setup imports, fixture factories and observation aliases are adapted. No
assertion, test signature, decorator or parameter is edited. Cases that cannot
yet meet the frozen contract remain explicit candidates, never fake successes.
"""
# ruff: noqa: E501
from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source, register_module
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
from tests.fakes.llm import FakeLLM as FrozenFakeLLM
from tests.fakes.llm import text_response as text_response
from tests.fakes.llm import tool_call_response as tool_call_response

CORPUS_SELECTIONS = {}
SUITES = {}
SUPPORT_SUITE = {
    "test_native_skill_dispatch_pins": "b1639873c2af9332df8e0d2ac57177c39efb721e1a822b22187b9da085cabfb2",
    "test_p1_carve_semantics": "011f3a955b54720e5023ed485c4ab267ccf324d085449371dbc6196771b709dc",
    "test_p2_composition": "0195fbb4c590d4bb523f1333581456bb957c3d12049e8faf2ecc05ee4dc45f1e",
    "test_facade_contract": "5781096ed17b7dd88c88ee8047197f169e4782a4518c8e8dffdd67427be977d4",
    "test_tool_parity": "41aa806975873b2dd35cb0bc8f0c4763350f9a509c2f3c85b63f267be3f0a6c2",
}
# Detailed non-retirement blockers are published separately in candidate rows.
CORPUS_EXCLUSIONS = {
    "test_facade_contract": [{
        "case": "TestWebChatRoute.test_process_web_chat_drives_real_tool_loop",
        "reviewer": "Claude, review of step 8 part 4",
        "reason": "Removed Odin HTTP web-chat UI route and web-owned lock cache.",
        "source_path": "tests/characterization/test_facade_contract.py",
        "source_sha256": "5781096ed17b7dd88c88ee8047197f169e4782a4518c8e8dffdd67427be977d4",
    }],
    "test_native_skill_dispatch_pins": [{
        "case": "TestFileDelivery.test_file_cb_send_mode_posts_to_channel",
        "reviewer": "Claude, review of step 8 part 4",
        "reason": "Removed Discord channel.send file publication callback.",
        "source_path": "tests/characterization/test_native_skill_dispatch_pins.py",
        "source_sha256": "b1639873c2af9332df8e0d2ac57177c39efb721e1a822b22187b9da085cabfb2",
    }],
    "test_p2_composition": [{
        "case": "TestTwoStageComposition.test_scheduler_start_wires_scheduled_events_methods",
        "reviewer": "Claude, review of step 8 part 4",
        "reason": "Removed Discord OdinBot.on_ready lifecycle and guild synchronization source contract.",
        "source_path": "tests/characterization/test_p2_composition.py",
        "source_sha256": "0195fbb4c590d4bb523f1333581456bb957c3d12049e8faf2ecc05ee4dc45f1e",
    }],
}
SUPPORT_CASES = {
    "test_native_skill_dispatch_pins": {
        "TestHandlesTruthTable.test_skill_names_always_handled",
        "TestHandlesTruthTable.test_dynamic_user_skill_names_handled",
        "TestHandlesTruthTable.test_executor_routed_tools_not_handled",
        "TestSkillCrudEffects.test_crud_invalidates_and_signals_rebuild",
        "TestInvokeSkillLoudFailures.test_missing_name",
        "TestInvokeSkillLoudFailures.test_unknown_skill",
        "TestInvokeSkillLoudFailures.test_non_dict_input",
        "TestInvokeSkillLoudFailures.test_missing_required_fields_fail_loudly",
        "TestInvokeSkillLoudFailures.test_complete_input_executes_with_callbacks",
        "TestFileDelivery.test_list_skills_empty_message",
    },
    "test_p1_carve_semantics": {
        "TestCarveMutationSemantics.test_caller_history_list_not_mutated",
    },
    "test_p2_composition": {
        "TestTwoStageComposition.test_services_and_components_handles",
        "TestTwoStageComposition.test_channel_state_lives_in_services",
        "TestTwoStageComposition.test_gateway_owns_the_llm_surface",
        "TestAuxiliaryFlatHandle.test_flat_handle_follows_gateway_swaps",
        "test_usage_rollup_wired_to_real_savers_and_paths",
    },
    "test_facade_contract": {
        "TestPositiveSurface.test_config_is_replaceable",
        "TestLateBoundAbsent.test_late_bound_names_absent_on_fresh_bot",
        "TestNegativeContract.test_no_retired_spellings_in_src",
        "TestNegativeContract.test_no_string_based_retired_lookups_in_src",
        "TestNegativeContract.test_no_string_based_retired_lookups_in_tests",
        "TestNegativeContract.test_no_retired_spellings_in_tests",
        "TestNegativeContract.test_no_bot_private_access_in_src",
    },
    # PR48 review 1 restores the complete parity suite in tests/test_tool_parity.py.
    "test_tool_parity": set(),
}
_scope = ContextVar("step8_characterization_fixture")


class FakeLLM(FrozenFakeLLM):
    async def drain_and_close(self):
        await self.close()


class BotView:
    """Read aliases of canonical owners, never fabricated runtime components."""

    def __init__(self, engine, requests):
        self.services = engine.deps
        self.components = engine.deps
        self.requests = requests
        self.channel_state = engine.deps.channel_state
        self.llm_gateway = engine.deps.llm_gateway
        self.tool_catalog = engine.deps.tool_catalog
        self.scheduling_tools = engine.deps.native_tools.owners["scheduling"]
        self.tool_loop = RunnerView(engine, requests)

    @property
    def config(self):
        return self.services.get_config()

    @config.setter
    def config(self, value):
        # The fixture owns an explicitly replaceable get_config provider.
        self.services.get_config = lambda: value

    @property
    def auxiliary_llm_client(self):
        return self.llm_gateway.auxiliary_llm_client

    @property
    def usage_rollup(self):
        return self.services.usage_rollup

    @property
    def trajectory_saver(self):
        return self.services.trajectory_saver

    @property
    def agent_trajectory_saver(self):
        return self.services.agent_trajectory_saver

    @property
    def audit(self):
        return self.services.audit


class RunnerView:
    def __init__(self, engine, requests):
        self.engine, self.requests = engine, requests

    async def run(self, envelope, history):
        captured = []
        original = self.engine.run

        async def run_bound(message, **kwargs):
            # Durable admission remains RequestService's real worker and owner.
            envelope.channel = message.channel
            try:
                result = await self.engine.runner.run(message, history)
            except Exception as error:
                captured.append(error)
                raise
            captured.append(result)
            return result

        self.engine.run = run_bound
        authority = self.requests.authority
        owner_binding = self.requests.permissions.set_request_owner(
            authority.authenticate_local(peer_uid=authority.owner_uid))
        try:
            cid = self.requests.conversations.create()["conversation"]["id"]
            self.requests.submit({"client_submission_id": "fixture-turn",
                                  "conversation_id": cid, "text": "Convert the time"})
            await self.requests.after_commit()
            import asyncio
            await asyncio.gather(*self.requests._tasks)
            if len(captured) != 1:
                raise AssertionError("canonical request worker did not run exactly once")
            if isinstance(captured[0], Exception):
                raise captured[0]
            return captured[0]
        finally:
            self.engine.run = original
            self.requests.permissions.reset_request_owner(owner_binding)


def make_bot(fake_llm=None, config_overrides=None):
    state = _scope.get()
    paths = ProfilePaths.from_xdg(f"characterization-{len(state.graphs)}",
                                 home=state.root, environ={})
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    store = JournalStore(paths.data_dir / "transport.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    cfg = Config(**(config_overrides or {}))
    cfg.openai_codex.enabled = False
    cfg.openai_compatible.enabled = True
    cfg.llm_provider.model = "compat:characterization"
    cfg.learning.enabled = False
    cfg.browser.enabled = False
    cfg.context.directory = str(paths.data_dir / "context")
    cfg.attachments.temp_directory = str(paths.cache_dir / "attachments")
    runtime = SimpleNamespace(get_config=lambda: cfg)
    engine = build_engine_services(cfg, paths, permissions, delivery=delivery,
        compatible_client=fake_llm or FakeLLM([]), runtime_context=runtime)
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=permissions, authority=authority, delivery=delivery)
    engine.bind_requests(requests)
    state.graphs.append((engine, requests, store, authority, permissions))
    return BotView(engine, requests)


@pytest.fixture(autouse=True)
def characterization_owner(tmp_path):
    state = SimpleNamespace(root=tmp_path, graphs=[])
    binding = _scope.set(state)
    try:
        yield
    finally:
        async def cleanup(engine, requests):
            # Frozen pointer-swap pin assigns an inert sentinel, not a provider.
            auxiliary = engine.deps.llm_gateway.auxiliary_llm_client
            if auxiliary is not None and not hasattr(auxiliary, "drain_and_close"):
                engine.deps.llm_gateway.auxiliary_llm_client = None
            await requests.close()
            await engine.close()

        for engine, requests, store, authority, permissions in reversed(state.graphs):
            asyncio.run(cleanup(engine, requests))
            store.close()
            authority.release_runtime()
        _scope.reset(binding)


class FixtureImports(ast.NodeTransformer):
    def visit_Assert(self, node):
        return node

    def visit_ImportFrom(self, node):
        if node.module == "tests.fakes":
            node.module = __name__
        elif node.module == "src.discord.wiring":
            node.module = __name__
        elif node.module == "src.discord.client":
            node.module = __name__
        elif node.level and node.module == "test_executor_dispatch_parity":
            return None  # pure frozen constants are populated below, no old bot import
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "Config":
            # Exact obsolete constructor-only fixtures, never real tier policy.
            node.keywords = [keyword for keyword in node.keywords
                             if keyword.arg not in {"discord", "permissions"}]
        return node


BotServices = SimpleNamespace
BotComponents = SimpleNamespace


def OdinBot(config):  # noqa: N802 - exact archived constructor import
    return make_bot(config_overrides=config.model_dump())


class FakeMessage:
    def __init__(self, content):
        self.content = content
        self.channel = None


def adapted_tree(name):
    path = f"tests/characterization/{name}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUPPORT_SUITE[name]:
        raise AssertionError("frozen characterization source hash changed")
    original = ast.parse(source, filename=path)
    adapted = ast.fix_missing_locations(FixtureImports().visit(copy.deepcopy(original)))
    if corpus(original) != corpus(adapted):
        raise AssertionError("characterization assertions/signatures/decorators/parameters changed")
    return original, adapted


def _select(tree, retained):
    tree = copy.deepcopy(tree)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            node.body = [method for method in node.body if not (
                isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                and method.name.startswith("test_")
                and f"{node.name}.{method.name}" not in retained)] or [ast.Pass()]
    tree.body = [node for node in tree.body if not (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_") and node.name not in retained)]
    return ast.fix_missing_locations(tree)


def load_support(namespace):
    # Dispatch truth-table constants are exact archived literals, not a shadow
    # registry invented by the adapter.
    support_path = "tests/characterization/test_executor_dispatch_parity.py"
    support_source = frozen_source(support_path)
    if hashlib.sha256(support_source).hexdigest() != (
            "652656e3e628455a90975498315f7fe4fcc329cac940e0e5ff34ac60bea43a29"):
        raise AssertionError("frozen dispatch helper source hash changed")
    support = ast.parse(support_source)
    constants = {}
    for node in support.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                {"EXECUTOR_ROUTED", "NATIVE_REGISTERED", "SKILL_TOOLS"} for t in node.targets):
            exec(compile(ast.Module(body=[node], type_ignores=[]), support_path, "exec"), constants)
    for name in SUPPORT_SUITE:
        original, adapted = adapted_tree(name)
        module = ModuleType(f"step8_characterization_{name}")
        module.__file__ = str(Path(__file__).parents[1] / "characterization" / f"{name}.py")
        module.__dict__.update(constants)
        exec(compile(_select(adapted, SUPPORT_CASES[name]), module.__file__, "exec"), module.__dict__)
        # Exact module-local fixtures retain original bodies and signatures.
        for value in vars(module).values():
            if isinstance(value, type) and value.__module__ == module.__name__:
                for fixture_name in ("bot", "_isolated_cwd"):
                    if fixture_name in vars(module):
                        setattr(value, fixture_name, staticmethod(vars(module)[fixture_name]))
        register_module(namespace, module, prefix=name)
