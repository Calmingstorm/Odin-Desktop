"""Exact review #35 candidates, retaining incompatible assertions as failures.

Executor construction uses a canonical owner and real RequestService admission.
The callback engine tests executor middleware, not runner behaviour. No runner,
permission, readiness, governor or host guard is replaced.
"""
# ruff: noqa: E501
from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from scripts.maintenance.fixture_corpus import register_module as shared_register_module
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.transcript import TranscriptStore
from src.discord.channel_state import ChannelStateRegistry
from src.discord.tool_loop_helpers import (
    build_request_preamble as canonical_preamble,
)
from src.discord.tool_loop_helpers import (
    compute_request_id as compute_request_id,
)
from src.discord.tool_loop_helpers import (
    current_request_time as current_request_time,
)
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import EXECUTOR_HANDLERS, ToolExecutor
from tests.desktop_adapters.process_cases import _fixture, temporary_owner
from tests.desktop_adapters.step8_runner import _paths, _put

SUITES = {
    "characterization/test_executor_dispatch_parity": "652656e3e628455a90975498315f7fe4fcc329cac940e0e5ff34ac60bea43a29",
    "test_tool_loop_helpers": "a852e1e285166c02beaedc9c5c4ae113c77ffd1aec08641bcc19870b19ea5782",
}
CORPUS_SELECTIONS = {
    "test_tool_loop_helpers": None,
}
CORPUS_EXCLUSIONS = {
    "characterization/test_executor_dispatch_parity": [{
        "case": "TestMiddlewarePins.test_rbac_denial_shape_and_metrics",
        "reviewer": "Claude, review of #35",
        "reason": "Guest-tier RBAC is removed by Desktop D17; Claude, review of #35 retires only this guest denial/metrics case.",
        "source_path": "tests/characterization/test_executor_dispatch_parity.py",
        "source_sha256": "652656e3e628455a90975498315f7fe4fcc329cac940e0e5ff34ac60bea43a29",
    }],
    "test_tool_loop_helpers": [{
        "case": "TestBuildRequestPreamble.test_bot_message_block",
        "reviewer": "Claude, review of #35",
        "reason": "Multi-bot origin handling (from_another_bot=True) is removed by Desktop; Claude, review of #35 retires only bot-origin cases.",
        "source_path": "tests/test_tool_loop_helpers.py",
        "source_sha256": "a852e1e285166c02beaedc9c5c4ae113c77ffd1aec08641bcc19870b19ea5782",
    }, {
        "case": "TestBuildRequestPreamble.test_no_history_bot_turn_keeps_bot_origin_note",
        "reviewer": "Claude, review of #35",
        "reason": "Multi-bot origin handling (from_another_bot=True) is removed by Desktop; Claude, review of #35 retires only bot-origin cases.",
        "source_path": "tests/test_tool_loop_helpers.py",
        "source_sha256": "a852e1e285166c02beaedc9c5c4ae113c77ffd1aec08641bcc19870b19ea5782",
    }],
}
CORPUS_BRANCH_RETIREMENTS = {
    "test_tool_loop_helpers": [{
        "case": "TestBehaviorPreservedByRefactor.test_all_combinations_match_reference",
        "reviewer": "Claude, review of #35",
        "reason": "Multi-bot origin handling (from_another_bot=True) is removed by Desktop; Claude, review of #35 retires only bot-origin cases.",
        "source_path": "tests/test_tool_loop_helpers.py",
        "source_sha256": "a852e1e285166c02beaedc9c5c4ae113c77ffd1aec08641bcc19870b19ea5782",
        "line": 170,
        "column": 36,
        "node_sha256": "dca8f82ad2c13093e18831c63d876733f70de16f7f9f34083e01bc131bb8218e",
        "before_source": "(True, False)",
        "after_source": "(False,)",
    }],
}
SETUP_HUNKS = {
    "characterization/test_executor_dispatch_parity": [
        (75, 4, "a07c36085d26e68c5404b3e69309f6563bda30c68d0ec1cd9a7e128c3cd97ba4",
         "return desktop_executor(config=kwargs.pop('config', ToolsConfig()), **kwargs)", False),
    ],
    "test_tool_loop_helpers": [
        (6, 0, "aa75da571875e3d8f06580bed87eb6a7882d8ca859a1dd48df33087c81c51f41",
         "from tests.desktop_adapters.step8_review_helpers import build_request_preamble, compute_request_id, current_request_time", False),
        (170, 36, "dca8f82ad2c13093e18831c63d876733f70de16f7f9f34083e01bc131bb8218e", "(False,)", True),
    ],
}


def build_request_preamble(**kwargs):
    """Drop only retired false origin flag; execute the canonical pure helper."""
    origin = kwargs.pop("from_another_bot", False)
    if origin is not False:
        raise TypeError("Desktop has no bot-origin admission")
    return canonical_preamble(**kwargs)


class ExecutorAdmission:
    """Real RequestService callback engine for tool-layer characterization."""
    def __init__(self, state, identity):
        self.deps = SimpleNamespace(turn_store=None, channel_state=ChannelStateRegistry())
        self.journal = JournalStore(state.paths.data_dir / f"dispatch-{identity}.sqlite3", "dispatch")
        events = PublicationEventJournal(self.journal)
        conversations = ConversationStore(self.journal, events)
        transcript = TranscriptStore(self.journal, events, conversations)
        delivery = DurableDelivery(self.journal, events, transcript_commit=transcript.commit)
        self.requests = RequestService(self.journal, conversations, transcript,
                                       engine=self, permissions=state.manager,
                                       authority=state.authority, delivery=delivery)
        self.pending = {}
        self.serial = 0
        self.conversations = conversations

    async def run(self, message, **_kwargs):
        self.requests.assert_request(message)
        callback, future = self.pending.pop(message.content)
        try:
            future.set_result(await callback(message))
        except Exception as error:
            future.set_exception(error)
        return ("Executor characterization settled", False, False, [], False)

    async def record_result(self, _message, _result):
        pass

    async def call(self, callback):
        self.serial += 1
        identity = str(self.serial)
        future = asyncio.get_running_loop().create_future()
        self.pending[identity] = (callback, future)
        cid = self.conversations.create()["conversation"]["id"]
        accepted = self.requests.submit({"client_submission_id": identity,
                                        "conversation_id": cid, "text": identity})
        await self.requests.after_commit()
        try:
            return await future
        finally:
            await asyncio.gather(*list(self.requests._tasks))
            row = self.requests.get_request(accepted["request_id"])
            if row["state"] != "completed":
                raise RuntimeError("executor characterization admission did not settle")


def desktop_executor(*, config, **kwargs):
    state = _fixture.get()
    if state is None or not state.manager.is_owner(state.authority.owner_id):
        raise RuntimeError("dispatch characterization requires authentic temporary owner")
    if "permission_manager" in kwargs:
        raise ValueError("retired guest permission fixture is not admitted")
    config = config.model_copy(deep=True)
    config.local_working_dir = str(state.workspace)
    config.audit_log_path = str(state.paths.data_dir / "audit.jsonl")
    config.ssh_pool.enabled = False
    config.recovery.enabled = False
    config.branch_freshness.enabled = False
    executor = ToolExecutor(config=config, profile_paths=state.paths,
                            permission_manager=state.manager,
                            memory_path=str(state.paths.data_dir / "memory.json"), **kwargs)
    executor.set_builtin_policy(BuiltinToolPolicy(
        lambda: SimpleNamespace(tools=executor.config),
        lambda: {name: callable(executor._resolve_handler(name)) for name in EXECUTOR_HANDLERS},
    ))
    admission = ExecutorAdmission(state, len(state.admissions))
    state.admissions.append(admission)
    state.executors.append(executor)
    canonical_execute = executor.execute

    async def admitted_execute(tool_name, tool_input, *, user_id=None):
        async def callback(message):
            # Explicit non-owner IDs are NOT translated into invented authority.
            return await canonical_execute(tool_name, tool_input,
                                           user_id=message.owner_id if user_id is None else user_id)
        return await admission.call(callback)

    executor.execute = admitted_execute
    return executor


@asynccontextmanager
async def owner_fixture(tmp_path):
    with temporary_owner(tmp_path / "dispatch-owner") as state:
        state.admissions = []
        try:
            yield state
        finally:
            for admission in state.admissions:
                await admission.requests.close()
                admission.journal.close()


def adapt(stem, source, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise ValueError("review helper frozen bytes changed")
    original = ast.parse(source)
    tree = copy.deepcopy(original)
    rules = SETUP_HUNKS[stem] if hunks is None else hunks
    if len({(r[0], r[1], r[2]) for r in rules}) != len(rules):
        raise ValueError("review helper duplicate setup hunk")
    if rules != SETUP_HUNKS[stem]:
        raise ValueError("review helper exact admitted allowlist changed")
    replay = []
    for line, column, digest, replacement, expression in rules:
        matches = [(path, node) for path, node in _paths(original)
                   if getattr(node, "lineno", None) == line
                   and getattr(node, "col_offset", None) == column
                   and hashlib.sha256(dump(node).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("review helper setup must match exactly once")
        path, node = matches[0]
        replacement_node = (ast.parse(replacement, mode="eval").body if expression
                            else ast.parse(replacement).body[0])
        _put(tree, path, ast.copy_location(replacement_node, node))
        replay.append((path, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("review helper assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for path, node in replay:
        _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("review helper complete AST reverse replay failed")
    return original, tree


def register_module(namespace, module, *, prefix=None, excluded=()):
    """Project only declared retirements at discovery, retaining frozen ASTs."""
    exposed = ModuleType(module.__name__ + "_exposed")
    exposed.__dict__.update(module.__dict__)
    excluded = set(excluded)
    for name in {case for case in excluded if "." not in case}:
        del exposed.__dict__[name]
    for cls_name in {case.split(".")[0] for case in excluded if "." in case}:
        cls = getattr(module, cls_name)
        attrs = {key: value for key, value in vars(cls).items()
                 if key not in {"__dict__", "__weakref__"}
                 and f"{cls_name}.{key}" not in excluded}
        setattr(exposed, cls_name, type(cls_name, cls.__bases__, attrs))
    shared_register_module(namespace, exposed, prefix=prefix)


def load(namespace, *, include_dispatch=False):
    loaded = {}
    for stem in SUITES:
        path = f"tests/{stem}.py"
        original, tree = adapt(stem, frozen_source(path))
        module = ModuleType("review_helpers_" + stem.replace("/", "_"))
        module.__file__ = str(Path(__file__).resolve().parents[2] / path)
        module.__package__ = "tests.characterization" if stem.startswith("characterization/") else "tests"
        module.__dict__["desktop_executor"] = desktop_executor
        exec(compile(tree, path, "exec"), module.__dict__)
        if not stem.startswith("characterization/") or include_dispatch:
            register_module(namespace, module, prefix="review_" + stem.split("/")[-1],
                            excluded=[item["case"] for item in CORPUS_EXCLUSIONS.get(stem, ())])
        loaded[path] = (original, tree)
    return loaded
