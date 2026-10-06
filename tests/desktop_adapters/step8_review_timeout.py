"""Exact frozen timeout corpus, executed inside a real admitted request worker.

Unsupported executor capabilities remain production refusals, not fabricated
ready handlers. The four dynamic/observation matrix cases may expose that gap.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import copy
import hashlib
from functools import wraps
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from src.audit.logger import AuditLogger
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import EngineServices
from src.desktop.transcript import TranscriptStore
from src.discord.channel_state import ChannelStateRegistry
from src.discord.native_tools.registry import NativeToolDispatcher
from src.discord.tool_loop import ToolLoopDeps, ToolLoopRunner
from src.tools.builtin_policy import BuiltinToolPolicy
from src.tools.executor import ToolExecutor
from src.tools.registry import PHASE1_EXECUTOR_TOOL_NAMES
from src.tools.skill_manager import SkillManager
from src.turn_state import TurnStateStore
from tests.desktop_adapters.process_cases import temporary_owner

SOURCE_PATH = "tests/test_executor_timeout_durability.py"
SOURCE_SHA256 = "7d1ad9553f761f999f910ed7843aba30312f4cc490b22ad95d03a59245de10c2"
CORPUS_SELECTIONS = {"test_executor_timeout_durability": None}
CORPUS_EXCLUSIONS = {}
PREFIX = "step8_review_timeout"
SETUP_HUNKS = [
    (19, 0, "48f7980224a8d0229e2354231c784e02b2c76847eb26eedfe01be6db2c9594dc", "exec",
     "from tests.desktop_adapters.step8_review_timeout import OwnerExecutor as ToolExecutor"),
    (35, 23, "5e903cccd1c76c43887123512e9eae58bd35c1e73e1630524d485fc0be275ffd", "eval",
     "request_admit(store, message=_message(), system_prompt='test', tools=[], "
     "session_snapshot=None)"),
    (46, 0, "d376b5544b4c1506171da024c4a423fc2e127c8a7f948cb7b920f6c2e5e82837", "exec",
     "def _runner(executor: ToolExecutor, tools: ToolsConfig) -> ToolLoopRunner:\n"
     "    return request_runner(executor, tools)"),
    (61, 0, "541839123f063b835552f7fac5c57c101137279806d31b0e8666318450d4b55d", "exec",
     "def _state(durability: TurnDurability) -> SimpleNamespace:\n"
     "    return request_state(durability)"),
    (77, 8, "4aa1a8f86a1e442f0ca6fa212bfc8b040b8ffaa26ac1050b461ba4cd882bd114", "eval",
     "(durability.lease.key.source, durability.lease.key.channel_id, "
     "durability.lease.key.message_id, durability.lease.generation, "
     "durability.generation_seq, call_id)"),
    (171, 4, "110c6860b28ad89ccc447f1c84030b7a8e1d18ceed03fa918cd281f4c79858f7", "eval",
     "defer_close(store)"),
    (269, 4, "110c6860b28ad89ccc447f1c84030b7a8e1d18ceed03fa918cd281f4c79858f7", "eval",
     "defer_close(store)"),
]
_active = contextvars.ContextVar("step8_review_timeout_request", default=None)


def current():
    graph = _active.get()
    if graph is None or not graph.owner.manager.is_owner(graph.owner.authority.owner_id):
        raise RuntimeError("timeout adapter requires an authentic temporary owner request")
    graph.requests.assert_request(graph.message)
    return graph


class OwnerExecutor(ToolExecutor):
    """Real executor and live built-in readiness from actual phase-1 handlers."""
    def __init__(self, *args, **kwargs):
        graph = current()
        kwargs.setdefault("profile_paths", graph.owner.paths)
        kwargs.setdefault("permission_manager", graph.owner.manager)
        super().__init__(*args, **kwargs)
        self.set_builtin_policy(BuiltinToolPolicy(
            lambda: SimpleNamespace(tools=self.config),
            lambda: {name: callable(self._resolve_handler(name))
                     for name in PHASE1_EXECUTOR_TOOL_NAMES}))
        graph.owner.executors.append(self)

    async def execute(self, tool_name, tool_input, *, user_id=None):
        graph = _active.get()
        if graph is None:
            raise RuntimeError("timeout executor requires an admitted request")
        # ToolLoopRunner's retained tool child inherits publication/owner
        # scope, but cannot acquire a new request execution identity.
        graph.requests.assert_bound_request(graph.message)
        owner = graph.message.owner_id
        if user_id is not None and user_id != owner:
            raise PermissionError("foreign executor requester")
        return await super().execute(tool_name, tool_input, user_id=owner)


def request_runner(executor, tools):
    graph = current()
    skills = SkillManager(str(graph.owner.paths.data_dir / "timeout-skills"), executor)
    native = NativeToolDispatcher(
        owners={}, skill_manager=skills, tool_catalog=None,
        prompt_builder=None, channel_state=graph.engine.deps.channel_state)
    deps = ToolLoopDeps(
        get_config=lambda: SimpleNamespace(tools=tools),
        get_default_system_prompt=lambda: "test", get_context_compressor=lambda: None,
        llm_gateway=None, prompt_builder=None, tool_catalog=None,
        channel_state=graph.engine.deps.channel_state, delivery=graph.delivery,
        turn_recorder=None, completion_classifier=None, native_tools=native,
        tool_executor=executor, permissions=graph.owner.manager, skill_manager=skills,
        audit=AuditLogger(str(graph.owner.paths.data_dir / "timeout-audit.jsonl")),
        loop_manager=None, stuck_loop_tracker_cls=None,
        assert_request=graph.engine._assert_request,
        request_admission=graph.engine._admit_turn)
    return ToolLoopRunner(deps)


def request_state(durability):
    graph = current()
    return SimpleNamespace(iteration=1, _cancel=asyncio.Event(), durability=durability,
                           message=graph.message, user_id=graph.message.owner_id,
                           policy=SimpleNamespace(skill_file_delivery=False),
                           _pending_validations=[])


async def request_admit(store, *, message, system_prompt, tools, session_snapshot):
    graph = current()
    if graph.handles:
        raise RuntimeError("timeout case attempted a second fresh admission")
    graph.stores.append(store)
    graph.engine.deps.turn_store = store
    # Legacy message identifiers have no authority. Only submitted content is
    # inherited; RequestService allocated all execution/ledger identifiers.
    if message.content != graph.message.content:
        raise RuntimeError("submitted timeout content changed")
    handle = await graph.engine._admit_turn(
        graph.message, system_prompt=system_prompt, tools=tools,
        session_snapshot=session_snapshot)
    graph.handles.append(handle)
    row = graph.requests.get_request(graph.request_id)
    if (not handle.enabled or handle._store is not store or row["state"] != "running"
            or row["owner"] != graph.owner.authority.owner_id
            or row["ledger_generation"] != handle.lease.generation
            or handle.lease.key != graph.message.turn_key):
        raise RuntimeError("timeout request lacks authentic enabled ledger binding")
    return handle


def defer_close(store):
    graph = current()
    if store not in graph.stores:
        raise RuntimeError("foreign timeout store cleanup")
    # RequestService._finish must project unknown effects before SQLite closes.
    graph.deferred_closes.append(store)


class CaseObservation:
    """The inherited coroutine itself runs in RequestService's owning task."""
    def __init__(self, graph, case, args, kwargs):
        self.graph, self.case, self.args, self.kwargs = graph, case, args, kwargs
        self.deps = SimpleNamespace(turn_store=None, channel_state=ChannelStateRegistry())
        self.engine = EngineServices(self.deps, None)
        self.error = None
        self.executed = False

    async def run(self, message, **_input):
        graph = self.graph
        graph.message = message
        token = _active.set(graph)
        try:
            current()
            # The executor-only retry case has no legacy durability helper;
            # admit its request to a real temporary ledger here as well.
            if self.case.__name__ == "test_safe_tool_retry_timeout_retains_structured_uncertainty":
                store = TurnStateStore(graph.owner.paths.data_dir / "retry-turn.sqlite3")
                handle = await request_admit(store, message=message, system_prompt="test",
                                            tools=[], session_snapshot=None)
            self.executed = True
            await self.case(*self.args, **self.kwargs)
            if self.case.__name__ == "test_safe_tool_retry_timeout_retains_structured_uncertainty":
                await handle.settle_terminal(cancelled=False, is_error=True)
            return "timeout corpus complete", False, False, [], False
        except BaseException as error:
            self.error = error
            raise
        finally:
            beats = [handle._heartbeat_task for handle in graph.handles
                     if handle._heartbeat_task is not None]
            for handle in graph.handles:
                handle._stop_heartbeats()
            if beats:
                await asyncio.gather(*beats, return_exceptions=True)
            _active.reset(token)

    async def record_result(self, message, result):
        self.graph.requests.assert_request(message, allow_terminal=True)


async def run_admitted_case(case, *args, **kwargs):
    tmp_path = kwargs.get("tmp_path", args[0] if args else None)
    if tmp_path is None:
        raise RuntimeError("timeout corpus requires its original temporary fixture")
    with temporary_owner(tmp_path / "timeout-owner") as owner:
        journal = JournalStore(owner.paths.data_dir / "timeout-requests.sqlite3", "timeout-corpus")
        events = PublicationEventJournal(journal)
        conversations = ConversationStore(journal, events)
        transcript = TranscriptStore(journal, events, conversations)
        delivery = DurableDelivery(journal, events, transcript_commit=transcript.commit)
        graph = SimpleNamespace(owner=owner, stores=[], handles=[], deferred_closes=[],
                                journal=journal, delivery=delivery, message=None)
        observation = CaseObservation(graph, case, args, kwargs)
        graph.engine = observation.engine
        requests = RequestService(journal, conversations, transcript, engine=observation,
                                  permissions=owner.manager, authority=owner.authority,
                                  delivery=delivery)
        graph.requests = requests
        observation.engine.bind_requests(requests)
        cid = conversations.create()["conversation"]["id"]
        response = requests.submit({"client_submission_id": "timeout-corpus",
                                    "conversation_id": cid,
                                    "text": "exercise executor timeout durability"})
        graph.request_id = response["request_id"]
        try:
            if requests.get_request(graph.request_id)["state"] != "queued":
                raise RuntimeError("timeout request was not durably queued")
            await requests.after_commit()
            tasks = list(requests._tasks)
            await asyncio.wait_for(asyncio.gather(*tasks), 30)
            if observation.error is not None:
                raise observation.error
            if not observation.executed:
                raise RuntimeError("timeout corpus was not executed")
            return graph
        finally:
            await requests.close()
            for handle in graph.handles:
                handle._stop_heartbeats()
            for store in graph.stores:
                store.close()
            journal.close()


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


def adapt(source, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("timeout frozen bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    rules = SETUP_HUNKS if hunks is None else hunks
    if len({r[:3] for r in rules}) != len(rules):
        raise ValueError("timeout duplicate setup hunk")
    if rules != SETUP_HUNKS:
        raise ValueError("timeout exact admitted setup allowlist changed")
    replay = []
    for line, column, digest, mode, replacement in rules:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and hashlib.sha256(dump(n).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("timeout setup must match exactly once")
        path, node = matches[0]
        replacement_tree = ast.parse(replacement, mode=mode)
        adapted = replacement_tree.body if mode == "eval" else replacement_tree.body[0]
        _put(tree, path, ast.copy_location(adapted, node))
        replay.append((path, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("timeout assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for path, node in replay:
        _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("timeout complete AST reverse replay failed")
    return original, tree


def admitted(case):
    @wraps(case)
    async def wrapped(*args, **kwargs):
        return await run_admitted_case(case, *args, **kwargs)
    return wrapped


def load(namespace):
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_review_timeout")
    module.__file__ = SOURCE_PATH
    module.__dict__.update(request_admit=request_admit, request_runner=request_runner,
                           request_state=request_state, defer_close=defer_close)
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    for name, case in list(vars(module).items()):
        if name.startswith("test_") and callable(case):
            wrapped = admitted(case)
            wrapped.__module__ = namespace["__name__"]
            namespace[f"test_{PREFIX}_{name[5:]}"] = wrapped
    return original, tree
