"""Entire pinned heartbeat corpus through real, task-owned request admission.

The observing engine boundary performs admission, then waits while the inherited
case exercises its real store/handle. No heartbeat or authority method is mocked.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import copy
import hashlib
import sqlite3
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.desktop.commands import JournalStorageError, JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import EngineServices
from src.desktop.transcript import TranscriptStore
from src.discord.channel_state import ChannelStateRegistry
from src.turn_state.store import TurnStateUnavailableError
from tests.desktop_adapters.process_cases import temporary_owner

SOURCE_PATH = "tests/test_turn_durability_heartbeat.py"
SOURCE_SHA256 = "e7595d33ed5660a9055e372a36bc98606df1b61f5c6f8aa8153cb727f440a04c"
CORPUS_SELECTIONS = {"test_turn_durability_heartbeat": None}
CORPUS_EXCLUSIONS = {}
SETUP_HUNKS = [
    (45, 19, "30ffb29be8a68a455b7162d5d0360bb153a23b8495217c1b20fc6ae40078f39b",
     "request_admit(store, message=FakeMsg(), system_prompt='s', tools=[], session_snapshot=None)"),
    (155, 19, "30ffb29be8a68a455b7162d5d0360bb153a23b8495217c1b20fc6ae40078f39b",
     "request_admit(store, message=FakeMsg(), system_prompt='s', tools=[], session_snapshot=None)"),
]
_fixture = contextvars.ContextVar("heartbeat_owner_fixture", default=None)


class AdmissionObservation:
    """Observe the real engine admission seam without generating an LLM turn.

    RequestService owns submit, persisted state, seal, worker task and binding.
    EngineServices._admit_turn and RequestService.admit_turn are both unchanged.
    Holding this operation open lets the parent case inspect the production beat.
    """
    def __init__(self, store, **admission):
        self.deps = SimpleNamespace(turn_store=store, channel_state=ChannelStateRegistry())
        self.engine = EngineServices(self.deps, None)
        self.ready = asyncio.get_running_loop().create_future()
        self.release = asyncio.Event()
        self.admission = admission
        self.message = None
        self.handle = None

    async def run(self, message, **_input):
        try:
            self.message = message
            self.handle = await self.engine._admit_turn(message, **self.admission)
            self.ready.set_result(self.handle)
        except BaseException as error:
            if not self.ready.done():
                self.ready.set_exception(error)
            raise
        # No test changes the timer or heartbeat task here. The real task-bound
        # request remains running until the case is done and teardown cancels it.
        await self.release.wait()
        raise RuntimeError("heartbeat observation must be cancelled, not replayed")


async def request_admit(store, *, message, system_prompt, tools, session_snapshot):
    state = _fixture.get()
    if state is None or not state.manager.is_owner(state.authority.owner_id):
        raise RuntimeError("heartbeat admission requires an authenticated temporary owner")
    journal = JournalStore(state.paths.data_dir / f"heartbeat-{len(state.graphs)}.sqlite3",
                           "heartbeat-corpus")
    events = PublicationEventJournal(journal)
    conversations = ConversationStore(journal, events)
    transcript = TranscriptStore(journal, events, conversations)
    delivery = DurableDelivery(journal, events, transcript_commit=transcript.commit)
    observation = AdmissionObservation(store, system_prompt=system_prompt, tools=tools,
                                       session_snapshot=session_snapshot)
    requests = RequestService(journal, conversations, transcript, engine=observation,
                              permissions=state.manager, authority=state.authority,
                              delivery=delivery)
    observation.engine.bind_requests(requests)
    cid = conversations.create()["conversation"]["id"]
    graph = SimpleNamespace(journal=journal, requests=requests, observation=observation,
                            store=store, cid=cid, tasks=[])
    state.graphs.append(graph)
    # Legacy message identifiers/author have no authority. Its content alone is
    # submitted, with all execution identities allocated by RequestService.
    response = requests.submit({"client_submission_id": "heartbeat-observation",
                                "conversation_id": cid, "text": message.content})
    graph.request_id = response["request_id"]
    if requests.get_request(graph.request_id)["state"] != "queued":
        raise RuntimeError("heartbeat request was not persisted queued")
    await requests.after_commit()
    graph.tasks = list(requests._tasks)
    handle = await asyncio.wait_for(asyncio.shield(observation.ready), timeout=5)
    row = requests.get_request(graph.request_id)
    if row["state"] != "running" or row["owner"] != state.authority.owner_id:
        raise RuntimeError("heartbeat request lacks authentic running owner binding")
    if handle.enabled and (handle._store is not store or
                           row["ledger_generation"] != handle.lease.generation):
        raise RuntimeError("heartbeat admission changed the supplied store or ledger binding")
    return handle


@asynccontextmanager
async def owner_fixture(tmp_path):
    with temporary_owner(tmp_path / "heartbeat-owner") as state:
        state.graphs = []
        token = _fixture.set(state)
        try:
            yield state
        finally:
            try:
                for graph in state.graphs:
                    handle = graph.observation.handle
                    beat = handle._heartbeat_task if handle is not None else None
                    if handle is not None:
                        handle._stop_heartbeats()
                    if beat is not None:
                        beat_results = await asyncio.gather(beat, return_exceptions=True)
                        for result in beat_results:
                            if (isinstance(result, BaseException)
                                    and not isinstance(result, asyncio.CancelledError)):
                                raise RuntimeError("Unexpected heartbeat task failure") from result
                    closed_connection = False
                    if graph.store._conn is not None:
                        try:
                            graph.store._conn.execute("SELECT 1")
                        except sqlite3.ProgrammingError as error:
                            if str(error) != "Cannot operate on a closed database.":
                                raise
                            closed_connection = True
                    # Store-death cases intentionally destroy the ledger. The
                    # actual request cancellation can then report the same store
                    # failure in terminal projection; retrieve it, never repair
                    # or replace the tested ledger just to make cleanup green.
                    for task in graph.tasks:
                        task.cancel()
                    graph.cleanup_results = await asyncio.gather(
                        *graph.tasks, return_exceptions=True)
                    unexpected = []
                    for result in graph.cleanup_results:
                        if isinstance(result, asyncio.CancelledError):
                            continue
                        if (isinstance(result, TurnStateUnavailableError)
                                and not graph.store.available):
                            continue
                        if (isinstance(result, sqlite3.ProgrammingError)
                                and closed_connection
                                and str(result) == "Cannot operate on a closed database."):
                            continue
                        if isinstance(result, JournalStorageError) and closed_connection:
                            # JournalStore.transaction wraps this known closed-
                            # ledger SQLite error during _finish projection. Only
                            # this proven dead-ledger case is expected. Confirm
                            # the actual request journal itself is still healthy.
                            graph.journal.connection.execute("SELECT 1").fetchone()
                            continue
                        if isinstance(result, BaseException):
                            unexpected.append(result)
                    await graph.requests.close()
                    graph.store.close()
                    graph.journal.close()
                    if unexpected:
                        raise RuntimeError(
                            "Unexpected heartbeat request cleanup failure") from unexpected[0]
            finally:
                _fixture.reset(token)


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
        raise ValueError("heartbeat frozen bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    rules = SETUP_HUNKS if hunks is None else hunks
    if len({(r[0], r[1], r[2]) for r in rules}) != len(rules):
        raise ValueError("heartbeat duplicate setup hunk")
    if rules != SETUP_HUNKS:
        raise ValueError("heartbeat exact admitted setup allowlist changed")
    replay = []
    for line, column, digest, replacement in rules:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and hashlib.sha256(dump(n).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("heartbeat setup must match exactly once")
        path, node = matches[0]
        _put(tree, path, ast.copy_location(ast.parse(replacement, mode="eval").body, node))
        replay.append((path, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("heartbeat assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for path, node in replay:
        _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("heartbeat complete AST reverse replay failed")
    return original, tree


def load(namespace):
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_heartbeat")
    module.__file__ = SOURCE_PATH
    module.__dict__["request_admit"] = request_admit
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    module._fast_beats.__module__ = namespace["__name__"]
    namespace["_fast_beats"] = module._fast_beats
    register_module(namespace, module, prefix="step8_heartbeat")
    return original, tree
