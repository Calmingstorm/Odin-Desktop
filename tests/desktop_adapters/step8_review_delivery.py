"""Frozen delivery review corpus on actual authenticated Desktop owners.

The embedded ownerless runtime fallback is not a Desktop consumer. Substitute
an authenticated, composed executor whose retention quota is exhausted, keeping
the complete failed-retention assertion and parameter corpus. No delivery,
authorization, readiness, scrubber, or storage method is replaced.
"""
from __future__ import annotations

import ast
import contextvars
import copy
import hashlib
from contextlib import asynccontextmanager
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.config.schema import Config, ToolHost
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.tools.output_retention import OutputStore
from tests.desktop_adapters.process_cases import temporary_owner
from tests.fakes import FakeLLM

SOURCE_PATH = "tests/test_delivery_review_regressions.py"
SOURCE_SHA256 = "bc0ddcfe244eeee48507dd6a5a16b333f18b421415b3fc1f1f1f856b340ae018"
CORPUS_SELECTIONS = {"test_delivery_review_regressions": None}
CORPUS_EXCLUSIONS = {}
_fixture = contextvars.ContextVar("review_delivery_owner", default=None)

# Every change is an exact setup/call-site contract. All assertions, signatures,
# decorators and parameter values are untouched, including runtime and disabled.
SETUP_HUNKS = [
    (14, 0, "8dce3e2a05cc244e733c19f4bc147ac405041272953870af6f871eadf49345ce",
     "from tests.desktop_adapters.step8_review_delivery import "
     "executor, owner_id, runtime_failure_executor"),
    (34, 8, "d7ddec0f3cb30c35d687ce4d405495ac7d42b0307d7448e9dce50e790316fed4",
     "ex._app_config.tools.disabled_tools = ['get_tool_output']"),
    (37, 17, "cdcdf99b1505ebae3de5a1c671bf32cdabe3e4fde8e3343af6d7258daa4ba0dc",
     "deliver_runtime_output(runtime_failure_executor(tmp_path), body, "
     "tool_name='search_history', tool_input={}, user_id=owner_id())"),
    (35, 84, "7ed9d3ff0ecb5e0185214cc16df64abe796357eb389d0941d265b4ccf20363c3",
     "user_id=owner_id()"),
    (66, 80, "7ed9d3ff0ecb5e0185214cc16df64abe796357eb389d0941d265b4ccf20363c3",
     "user_id=owner_id()"),
    (85, 32, "7ed9d3ff0ecb5e0185214cc16df64abe796357eb389d0941d265b4ccf20363c3",
     "user_id=owner_id()"),
    (141, 30, "7ed9d3ff0ecb5e0185214cc16df64abe796357eb389d0941d265b4ccf20363c3",
     "user_id=owner_id()"),
    (143, 71, "7ed9d3ff0ecb5e0185214cc16df64abe796357eb389d0941d265b4ccf20363c3",
     "user_id=owner_id()"),
    (150, 36, "7ed9d3ff0ecb5e0185214cc16df64abe796357eb389d0941d265b4ccf20363c3",
     "user_id=owner_id()"),
]


def owner_id():
    state = _fixture.get()
    if state is None or not state.manager.is_owner(state.authority.owner_id):
        raise RuntimeError("delivery corpus requires an authenticated temporary owner")
    return state.authority.owner_id


def executor(tmp_path):
    owner_id()
    state = _fixture.get()
    if state.graphs:
        raise RuntimeError("delivery corpus allows one composed graph per case")
    paths = state.paths
    journal = JournalStore(paths.data_dir / "delivery.sqlite3", "review-delivery")
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
    cfg.tools.hosts = {"testhost": ToolHost(address="127.0.0.1", ssh_user="odin")}
    fake = FakeLLM([])
    fake.drain_and_close = fake.close
    engine = build_engine_services(cfg, paths, state.manager, delivery=delivery,
                                   compatible_client=fake)
    requests = RequestService(journal, conversations, transcript, engine=engine,
                              permissions=state.manager, authority=state.authority,
                              delivery=delivery)
    engine.bind_requests(requests)
    state.graphs.append((engine, requests, journal, transcript, conversations, cfg))
    ex = engine.deps.tool_executor
    ex.set_user_context(owner_id())
    state.executors.append(ex)
    return ex


def runtime_failure_executor(tmp_path):
    ex = executor(tmp_path)
    ex._output_store = OutputStore(tmp_path / "runtime-failed.sqlite3", global_bytes=1)
    return ex


@asynccontextmanager
async def owner_fixture(tmp_path):
    with temporary_owner(tmp_path / "delivery-owner") as state:
        state.graphs = []
        token = _fixture.set(state)
        try:
            yield state
        finally:
            try:
                for engine, requests, journal, *_ in state.graphs:
                    try:
                        await requests.close()
                        await engine.close()
                    finally:
                        journal.close()
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


def _replacement(source, node):
    if isinstance(node, ast.keyword):
        return ast.parse(f"f({source})", mode="eval").body.keywords[0]
    if isinstance(node, ast.expr):
        return ast.parse(source, mode="eval").body
    return ast.parse(source).body[0]


def adapt(source, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("delivery frozen bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    rules = SETUP_HUNKS if hunks is None else hunks
    if len({(r[0], r[1], r[2]) for r in rules}) != len(rules):
        raise ValueError("delivery duplicate setup hunk")
    if rules != SETUP_HUNKS:
        raise ValueError("delivery exact setup allowlist changed")
    replay = []
    for line, column, digest, replacement in rules:
        matches = [(p, n) for p, n in _paths(original)
                   if getattr(n, "lineno", None) == line
                   and getattr(n, "col_offset", None) == column
                   and hashlib.sha256(dump(n).encode()).hexdigest() == digest]
        if len(matches) != 1:
            raise ValueError("delivery setup must match exactly once")
        path, node = matches[0]
        _put(tree, path, ast.copy_location(_replacement(replacement, node), node))
        replay.append((path, node))
    ast.fix_missing_locations(tree)
    if corpus(original) != corpus(tree):
        raise ValueError("delivery assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for path, node in replay:
        _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("delivery complete AST reverse replay failed")
    return original, tree


def load(namespace):
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_review_delivery")
    module.__file__ = SOURCE_PATH
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    register_module(namespace, module, prefix="step8_review_delivery")
    return original, tree
