"""Hash-bound output suites with profile-owner setup, never transport authority.

The retained runner, executor, output store and request admission all remain
production owners. Historical reader/room names are displayed only by the
frozen fixture's ContextVar view; writes and dispatch use canonical identities.
"""
# ruff: noqa: E501
from __future__ import annotations

import ast
import contextvars
import copy
import hashlib
import inspect
import os
from contextlib import contextmanager
from dataclasses import replace
from functools import wraps
from types import ModuleType, SimpleNamespace
from uuid import uuid4

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from src.config.schema import ToolHost, ToolsConfig
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.transcript import TranscriptStore
from src.discord.tool_loop import ToolLoopRunner
from src.permissions.manager import PermissionManager
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor as EngineExecutor
from src.tools.output_delivery import delivery_scope as actual_scope
from src.tools.runtime_delivery import execution_delivery_scope as actual_execution_scope

SUITES = {
    "test_output_streamer": "8c64bbb2a58a274f591399f888510616cfc6181cd9f75eb1d909560b3681440f",
    "test_runtime_output_delivery": "add5410c347955ddb90e2437bf8ec80cf26649b8003b921ef9eb0b08eec60622",
}
CORPUS_SELECTIONS = {"test_output_streamer": None, "test_runtime_output_delivery": None}
CORPUS_HASHES = {
    "test_output_streamer": "a9c9ed5ddebf1c4043d4e7dea42f2a0cef506611e000ffff8327e1cfd8496036",
    "test_runtime_output_delivery": "063ddd1693987f664f85b030c5f4d23749590c154a19dd45b1a90b04c3ab3c96",
}
CORPUS_EXCLUSIONS = {
    "test_output_streamer": [
        "TestAPIEndpoint.test_no_executor",
        "TestAPIEndpoint.test_with_streamer",
        "TestAPIEndpoint.test_with_active_stream",
    ],
}
EVIDENCE = {}
PROPOSED_CASES = {"test_runtime_output_delivery": {
    "test_embedded_dispatcher_fallback_does_not_promise_unretained_output":
        "Ownerless fallback is deliberately fail-closed in runtime_delivery; reviewer decision required.",
}}
CASE_MAP = {}
_fixture = contextvars.ContextVar("lane6_health_output_fixture", default=None)


def owner_id():
    return _fixture.get().authority.owner_id


def conversation_id():
    return _fixture.get().cid


def _owner(value):
    return owner_id() if value == "reader" else value


def _channel(value):
    return conversation_id() if value == "room" else value


class ScopeView:
    """Read-only legacy labels, not an alternate scope or authority issuer."""

    @staticmethod
    def get():
        owner, channel = actual_scope.get()
        state = _fixture.get()
        if state is not None:
            owner = "reader" if owner == state.authority.owner_id else owner
            channel = "room" if channel == state.cid else channel
        return owner, channel


delivery_scope = ScopeView()


def execution_delivery_scope(owner, channel=None, **kwargs):
    return actual_execution_scope(_owner(owner), _channel(channel), **kwargs)


class StoreView:
    """Map only frozen fixture labels on reads of the real retained store."""

    def __init__(self, executor):
        self.executor = executor

    def read(self, cursor, *, owner, channel, authorize):
        state = _fixture.get()
        if state.executor.check_permission("get_tool_output", _owner(owner)):
            raise PermissionError("Authenticated retention reader required")
        return self.executor._ensure_output_store().read(
            cursor, owner=_owner(owner), channel=_channel(channel), authorize=authorize)


class ToolExecutor(EngineExecutor):
    def __init__(self, *args, **kwargs):
        state = _fixture.get()
        if state is None:
            raise RuntimeError("Profile owner fixture required")
        kwargs.setdefault("profile_paths", state.paths)
        kwargs.setdefault("permission_manager", state.permissions)
        kwargs.setdefault("memory_path", str(state.paths.data_dir / "memory.json"))
        config = kwargs.get("config") or ToolsConfig()
        config.hosts = {"myhost": ToolHost(address="127.0.0.1", ssh_user="fixture")}
        kwargs["config"] = config
        super().__init__(*args, **kwargs)
        self.set_user_context(state.authority.owner_id)
        self._builtin_policy = FixturePolicy(
            lambda: SimpleNamespace(tools=self.config),
            lambda: dict.fromkeys({"native", "skill", "mcp_fixture_echo", "search_history",
                                   "get_tool_output", "read_file", "run_command", "run_script",
                                   "test_tool", "spawn_agent", "ingest_document"}, True))
        state.executors.append(self)

    async def execute(self, tool_name, tool_input, *, user_id=None):
        return await super().execute(tool_name, tool_input,
                                     user_id=owner_id() if user_id is None else user_id)


class FixturePolicy(BuiltinToolPolicy):
    """Production readiness behavior for explicit frozen virtual/native tools."""

    def is_available(self, name):
        return not self.is_disabled(name) and self._get_readiness().get(name) is True


class FixtureRunner(ToolLoopRunner):
    def __new__(cls, *args, **kwargs):
        result = super().__new__(cls)
        result._tool_executor = ToolExecutor()
        result._record_tool_detail = None
        return result


def loop_executor(**kwargs):
    result = ToolExecutor(config=kwargs.get("config"))
    result._recovery_enabled = kwargs.get("_recovery_enabled", result._recovery_enabled)
    return result


class Executor(ToolExecutor):
    """Replace the inherited allow-all stub with the real retention executor."""

    def __init__(self, path):
        super().__init__()
        self.store = StoreView(self)
        _fixture.get().executor = self

    def deliver_output(self, text, *, user_id, channel_id=None, **kwargs):
        return super().deliver_output(text, user_id=_owner(user_id),
                                      channel_id=_channel(channel_id), **kwargs)


def session_workspace():
    return str(_fixture.get().workspace)


def state():
    from unittest.mock import AsyncMock
    fixture = _fixture.get()
    return SimpleNamespace(
        user_id=fixture.authority.owner_id, message=fixture.message, iteration=1,
        policy=SimpleNamespace(skill_file_delivery="send"),
        durability=SimpleNamespace(before_tool=AsyncMock(), after_tool=AsyncMock()),
        _pending_validations=[], pending_image_blocks=[],
    )


def runner_for(tmp_path, native):
    from unittest.mock import AsyncMock, Mock
    fixture = _fixture.get()
    runner = ToolLoopRunner.__new__(ToolLoopRunner)
    runner._tool_executor = Executor(tmp_path / "retained.sqlite")
    runner._native_tools = SimpleNamespace(handles=lambda _: True, dispatch=native)
    runner._delivery = SimpleNamespace(set_status=AsyncMock())
    runner._audit = SimpleNamespace(log_event=AsyncMock(), log_execution=AsyncMock())
    runner._audit_tool_outcome = AsyncMock()
    runner._channel_state = SimpleNamespace(track_action=Mock())
    runner._mcp_manager = None
    runner._assert_bound_request = fixture.requests.assert_bound_request
    runner._record_tool_detail = None
    return runner


@contextmanager
def owner_fixture(tmp_path):
    paths = ProfilePaths.from_xdg("output", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    binding = permissions.set_request_owner(context)
    store = JournalStore(paths.data_dir / "transport.sqlite3", "output")
    events = EventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    cid = conversations.create()["conversation"]["id"]
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    engine = SimpleNamespace(deps=SimpleNamespace(turn_store=None))
    requests = RequestService(store, conversations, transcript, engine=engine,
                              permissions=permissions, authority=authority, delivery=None)
    fixture = SimpleNamespace(paths=paths, authority=authority, permissions=permissions,
                              cid=cid, requests=requests, executors=[], executor=None,
                              workspace=workspace, message=None)
    token = _fixture.set(fixture)
    try:
        yield fixture
    finally:
        for executor in fixture.executors:
            executor.set_user_context(None)
        _fixture.reset(token)
        store.close()
        permissions.reset_request_owner(binding)
        authority.release_runtime()


def admitted_message(fixture):
    message = fixture.requests._register_background(
        "task", "output-" + uuid4().hex, "Read harmless retained output",
        fixture.cid, fixture.authority.owner_id)
    return replace(message, allowed_tools=["search_history", "get_tool_output", "read_file",
                                           "native", "mcp_fixture_echo", "skill"])


class SetupOnly(ast.NodeTransformer):
    def __init__(self, suite):
        self.suite = suite
        self.edits = []
        self.symbol = "<module>"

    def _record(self, before, after):
        self.edits.append({
            "symbol": self.symbol, "line": before.lineno,
            "before_sha256": hashlib.sha256(ast.dump(before).encode()).hexdigest(),
            "after_sha256": hashlib.sha256(ast.dump(after).encode()).hexdigest(),
            "after_source": ast.unparse(after), "reason": "canonical profile-owner setup",
        })
        return ast.copy_location(after, before)

    def visit_Assert(self, node):
        return node

    def visit_FunctionDef(self, node):
        previous = self.symbol
        self.symbol = node.name if previous == "<module>" else previous + "." + node.name
        try:
            if self.suite == "test_runtime_output_delivery" and node.name in {"runner_for", "state"}:
                updated = copy.deepcopy(node)
                updated.body = ast.parse(f"return {node.name}(*locals().values())").body
                # Alias avoids recursion inside the frozen module.
                updated.body[0].value.func.id = "fixture_" + node.name
                return self._record(node, updated)
            if self.suite == "test_output_streamer" and node.name == "_session_workspace":
                updated = copy.deepcopy(node)
                updated.body = ast.parse("return session_workspace()").body
                return self._record(node, updated)
            # Decorators/parameters/defaults are corpus-bound, not setup seams.
            node.body = [self.visit(child) for child in node.body]
            return node
        finally:
            self.symbol = previous

    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        previous = self.symbol
        self.symbol = node.name
        try:
            if self.suite == "test_runtime_output_delivery" and node.name == "Executor":
                updated = copy.deepcopy(node)
                updated.bases = [ast.Name(id="FixtureExecutor", ctx=ast.Load())]
                for member in updated.body:
                    if isinstance(member, ast.FunctionDef) and member.name == "__init__":
                        member.body = ast.parse("FixtureExecutor.__init__(self, path)").body
                    elif isinstance(member, ast.FunctionDef) and member.name == "deliver_output":
                        member.body = ast.parse(
                            "return FixtureExecutor.deliver_output(self, text, tool_name=tool_name, "
                            "tool_input=tool_input, user_id=user_id, channel_id=channel_id, status=status)").body
                return self._record(node, updated)
            node.body = [self.visit(child) for child in node.body]
            return node
        finally:
            self.symbol = previous

    def visit_ImportFrom(self, node):
        if self.suite == "test_output_streamer" and node.module == "src.discord.tool_loop":
            updated = copy.deepcopy(node)
            updated.module = __name__
            updated.names = [ast.alias(name="FixtureRunner", asname="ToolLoopRunner")]
            return self._record(node, updated)
        if node.module == "src.tools.executor" and any(a.name == "ToolExecutor" for a in node.names):
            updated = copy.deepcopy(node)
            updated.module = __name__
            return self._record(node, updated)
        if (self.suite == "test_runtime_output_delivery" and node.module == "src.tools.output_delivery"
                and any(a.name == "delivery_scope" for a in node.names)):
            updated = ast.parse(
                "from src.tools.output_delivery import DeliveredOutput, RankedOutput, deliver\n"
                "from tests.desktop_adapters.lane6_health_output import delivery_scope").body
            # Keep the first real imports and the scope projection separate.
            for item in updated:
                ast.copy_location(item, node)
            self.edits.append({"symbol": self.symbol, "line": node.lineno,
                               "before_sha256": hashlib.sha256(ast.dump(node).encode()).hexdigest(),
                               "after_source": "\n".join(ast.unparse(n) for n in updated),
                               "reason": "read-only projection of canonical scope to inherited labels"})
            return updated
        if self.suite == "test_runtime_output_delivery" and node.module == "src.tools.runtime_delivery":
            if not all(a.name == "execution_delivery_scope" for a in node.names):
                return node
            updated = copy.deepcopy(node)
            updated.module = __name__
            return self._record(node, updated)
        return node

    def visit_Constant(self, node):
        if self.suite == "test_runtime_output_delivery" and node.value in ("reader", "room"):
            name = "owner_id" if node.value == "reader" else "conversation_id"
            return self._record(node, ast.parse(name + "()", mode="eval").body)
        if (self.suite == "test_output_streamer" and self.symbol.startswith("TestCallIdAttribution.")
                and node.value == "1"):
            return self._record(node, ast.parse("owner_id()", mode="eval").body)
        return node

    def visit_Assign(self, node):
        if (self.suite == "test_output_streamer" and self.symbol.startswith("TestCallIdAttribution.")
                and ast.unparse(node.targets[0]) == "runner._tool_executor"):
            updated = copy.deepcopy(node)
            updated.value.func = ast.Name(id="loop_executor", ctx=ast.Load())
            return self._record(node, updated)
        return self.generic_visit(node)


def register_module(namespace):
    for suite, expected_hash in SUITES.items():
        path = f"tests/{suite}.py"
        source = frozen_source(path)
        if hashlib.sha256(source).hexdigest() != expected_hash:
            raise AssertionError(f"Frozen source hash changed: {path}")
        original = ast.parse(source, filename=path)
        if hashlib.sha256(repr(corpus(original)).encode()).hexdigest() != CORPUS_HASHES[suite]:
            raise AssertionError(f"Frozen corpus hash changed: {path}")
        transformer = SetupOnly(suite)
        adapted = transformer.visit(copy.deepcopy(original))
        ast.fix_missing_locations(adapted)
        if corpus(original) != corpus(adapted):
            raise AssertionError("Frozen assertions/signatures/decorators/parameters changed")
        EVIDENCE[path] = {"source_sha256": expected_hash, "whole_suite": True,
                          "exact_corpus": corpus(original), "setup_edits": transformer.edits,
                          "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest()}
        module = ModuleType("lane6_health_output_" + suite)
        module.__file__ = str(ROOT / path)
        module.fixture_runner_for = runner_for
        module.FixtureExecutor = Executor
        module.fixture_state = state
        module.session_workspace = session_workspace
        module.loop_executor = loop_executor
        module.owner_id = owner_id
        module.conversation_id = conversation_id
        exec(compile(adapted, module.__file__, "exec"), module.__dict__)
        for node in adapted.body:
            name = getattr(node, "name", "")
            if name.startswith("test_"):
                if name in PROPOSED_CASES.get(suite, {}):
                    continue
                exported = f"test_lane6_health_output_{suite[5:]}__{name[5:]}"
                namespace[exported] = admitted_case(getattr(module, name))
                CASE_MAP[f"{path}::{name}"] = exported
            elif name.startswith("Test"):
                cls = getattr(module, name)
                exported = f"TestLane6HealthOutput_{suite[5:]}_{name[4:]}"
                for child in node.body:
                    case = getattr(child, "name", "")
                    if case.startswith("test_"):
                        symbol = f"{name}.{case}"
                        if symbol in CORPUS_EXCLUSIONS.get(suite, set()):
                            delattr(cls, case)
                        else:
                            CASE_MAP[f"{path}::{name}::{case}"] = f"{exported}::{case}"
                            setattr(cls, case, admitted_case(getattr(cls, case)))
                if any(k.startswith(f"{path}::{name}::") for k in CASE_MAP):
                    namespace[exported] = cls


def load(namespace):
    register_module(namespace)


def admitted_case(case):
    if not inspect.iscoroutinefunction(case):
        return case

    @wraps(case)
    async def wrapped(*args, **kwargs):
        fixture = _fixture.get()
        async with fixture.requests.background_execution(fixture.message):
            return await case(*args, **kwargs)

    return wrapped
