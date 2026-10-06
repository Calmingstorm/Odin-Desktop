"""Full bounded-wait corpus through authenticated durable desktop admission.

Only the obsolete build/run_loop import changes. FakeMessage supplies text, not
authority; RequestService owns the real sealed task-bound execution envelope.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.config.schema import Config
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from tests.desktop_adapters.process_cases import temporary_owner
from tests.fakes import FakeLLM

SOURCE_PATH = "tests/test_bounded_process_wait.py"
SOURCE_SHA256 = "01bf1930dba107e1881744830bbae61e6492ee76fa462828a69055746d213048"
CORPUS_SELECTIONS = {"test_bounded_process_wait": None}
CORPUS_EXCLUSIONS = {}
SETUP_HUNKS = [(13, 0, "cd5a8ea320dcb05e8ea543d80d923ac3ad98095856660cccd6976ed721c37d63",
                "from tests.desktop_adapters.step8_wait import build, run_loop")]
_fixture = contextvars.ContextVar("bounded_wait_owner_fixture", default=None)


class ObservedEngine:
    """Read-through observation of unchanged engine results, never execution gates."""
    def __init__(self, engine):
        self.engine = engine
        self.results = []

    def __getattr__(self, name):
        return getattr(self.engine, name)

    async def run(self, *args, **kwargs):
        result = await self.engine.run(*args, **kwargs)
        self.results.append(result)
        return result


class Components:
    """Expose only the actual components patched at inherited executor seams."""
    def __init__(self, engine, observed, requests, transcript, journal, cid):
        self.engine, self.observed, self.requests = engine, observed, requests
        self.transcript, self.journal, self.cid = transcript, journal, cid

    @property
    def tool_executor(self):
        return self.engine.deps.tool_executor

    @property
    def tool_loop(self):
        return self.engine.runner


def build(script):
    state = _fixture.get()
    if state is None or not state.manager.is_owner(state.authority.owner_id):
        raise RuntimeError("bounded wait requires an authenticated temporary owner")
    paths = state.paths
    # A case creates at most one graph. Fail rather than share a durable profile.
    if state.graphs:
        raise RuntimeError("bounded wait case attempted a second graph")
    journal = JournalStore(paths.data_dir / "transport.sqlite3", "bounded-wait")
    events = PublicationEventJournal(journal)
    conversations = ConversationStore(journal, events)
    transcript = TranscriptStore(journal, events, conversations)
    delivery = DurableDelivery(journal, events, transcript_commit=transcript.commit)
    cfg = Config()
    cfg.openai_codex.enabled = False
    cfg.ollama.enabled = False
    cfg.openai_compatible.enabled = True
    cfg.llm_provider.model = "compat:fake-model"
    cfg.context.directory = str(paths.data_dir / "context")
    cfg.learning.enabled = False
    cfg.search.enabled = False
    cfg.browser.enabled = False
    cfg.tools.local_working_dir = str(state.workspace)
    cfg.tools.ssh_pool.enabled = False
    fake = FakeLLM(script)
    # FakeLLM's original scripted responses/call recording are untouched. Its
    # existing close method supplies only the newer provider lifecycle name.
    fake.drain_and_close = fake.close
    engine = build_engine_services(cfg, paths, state.manager, delivery=delivery,
                                   compatible_client=fake)
    observed = ObservedEngine(engine)
    requests = RequestService(journal, conversations, transcript, engine=observed,
                              permissions=state.manager, authority=state.authority,
                              delivery=delivery)
    engine.bind_requests(requests)
    cid = conversations.create()["conversation"]["id"]
    components = Components(engine, observed, requests, transcript, journal, cid)
    state.graphs.append(components)
    return components, fake


async def run_loop(bot, msg):
    # The historical fake is a transport input only. Ignore its fake owner,
    # channel and message IDs; the service allocates and seals every identity.
    response = bot.requests.submit({"client_submission_id": "inherited-case",
                                    "conversation_id": bot.cid, "text": msg.content})
    assert bot.requests.get_request(response["request_id"])["state"] == "queued"
    await bot.requests.after_commit()
    await asyncio.gather(*list(bot.requests._tasks))
    if len(bot.observed.results) != 1:
        raise RuntimeError("admitted engine did not return one original result tuple")
    result = bot.observed.results[0]
    row = bot.requests.get_request(response["request_id"])
    assert row["ledger_generation"] is not None
    assert row["state"] == ("failed" if result[2] else "completed")
    assert bot.transcript.read_conversation(bot.cid)[-1]["role"] == "assistant"
    return result


async def owner_fixture(tmp_path):
    with temporary_owner(tmp_path / "wait-owner") as state:
        state.graphs = []
        token = _fixture.set(state)
        try:
            yield state
        finally:
            try:
                for graph in state.graphs:
                    try:
                        await graph.requests.close()
                        await graph.engine.close()
                    finally:
                        graph.journal.close()
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
        raise ValueError("bounded wait frozen bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    rules = SETUP_HUNKS if hunks is None else hunks
    if len({(r[0], r[1], r[2]) for r in rules}) != len(rules):
        raise ValueError("bounded wait duplicate setup hunk")
    if rules != SETUP_HUNKS:
        raise ValueError("bounded wait exact admitted setup allowlist changed")
    replay = []
    for line, column, digest, replacement in rules:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and hashlib.sha256(dump(n).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("bounded wait setup must match exactly once")
        path, node = matches[0]
        _put(tree, path, ast.copy_location(ast.parse(replacement).body[0], node))
        replay.append((path, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("bounded wait assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for path, node in replay:
        _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("bounded wait complete AST reverse replay failed")
    return original, tree


def load(namespace):
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_bounded_wait")
    module.__file__ = SOURCE_PATH
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    module.clock.__module__ = namespace["__name__"]
    namespace["clock"] = module.clock
    register_module(namespace, module, prefix="step8_wait")
    return original, tree
