"""Exact frozen replay; real desktop search transport and approved safe zip fixture.

The transport shim translates only wire names/result fields. It never implements
search, filtering, sorting, limiting or an alternate product API.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import math
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from scripts.maintenance.fixture_corpus import register_module as register_frozen_module
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationError, ConversationStore
from src.desktop.events import EventJournal
from src.desktop.requests import RequestService
from src.desktop.search import TranscriptSearch
from src.desktop.transcript import TranscriptStore
from src.sessions.manager import SessionManager
from tests.desktop_adapters.step8_conversations import _owner
from tests.desktop_adapters.step8_conversations import temporary_owner as temporary_owner

CORPUS_SELECTIONS = {"test_session_search": None, "test_attachments": None}
CORPUS_EXCLUSIONS = {
    "test_session_search": [{
        "case": "TestSessionSearchAPI.test_search_with_user_filter",
        "reviewer": "Claude, review of #35",
        "reason": (
            "Removed API identity surface: REST selects Bob from Alice/Bob messages; "
            "desktop one canonical installation owner, no multi-user participant/API "
            "identity metadata; fabricating seed identities as authority does not "
            "preserve meaning; copied engine user-provenance cases remain restored."
        ),
        "source_path": "tests/test_session_search.py",
        "source_sha256": "38aa1cce39048336ef77697cade3d9d6f964e294fa8b9daed24a50600ab0c292",
    }],
}
SUITES = {
    "test_session_search": "38aa1cce39048336ef77697cade3d9d6f964e294fa8b9daed24a50600ab0c292",
    "test_attachments": "fd45c95e1c4ea5c2d0bca39bf8809b1912194695523973ebf0d8370bc58743f6",
}
SETUP_HUNKS = {
    "tests/test_session_search.py": {
        17: ("a4c9ffaa0ad4b0d5f73d26288eb4909a6de85c114195ec40be4767111b566dfd",
             "from tests.desktop_adapters.step8_review_search_attachments import "
             "SearchClient as TestClient, SearchServer as TestServer"),
        498: ("8084b96af3bb7b2108b646f367ec931d4db85a2e652f9a12bf2d9853b39d767b",
              "def _make_bot(tmp_path):\n    return DesktopSearchFixture(tmp_path)"),
        510: ("db6f23231b534fcc9e88747ac8f437fe11d2bf8122d8e85a3f6ef608bc9b1e48",
              "def _make_app(bot):\n    return bot"),
    },
    "tests/test_attachments.py": {
        149: ("7907974429eb4882fb60a2e21090f0ccd3f7f766d4ac0ea423d058e4ea735925",
              'zf.writestr("../../escape.txt", "pwned")'),
        151: ("b9f4f63829147d494ae45062321c940e38f2294d9ea6800082b94e4c484465f3",
              'proc = AttachmentProcessor(temp_dir=str(tmp_path / "nested" / "sandbox" '
              '/ "workspace"))'),
    },
}


class DesktopSearchFixture:
    """Original seed spelling, authenticated owner and actual durable services."""
    def __init__(self, tmp_path):
        owner = _owner.get()
        if owner is None or not owner.authority.accepts(owner.context):
            raise PermissionError("authenticated temporary owner required")
        self.owner = owner
        self.sessions = SessionManager(max_history=50, max_age_hours=24,
                                       persist_dir=str(tmp_path / "seed-sessions"))
        self.store = JournalStore(tmp_path / "search" / "journal.sqlite3", "search-review")
        self.events = EventJournal(self.store)
        self.conversations = ConversationStore(self.store, self.events)
        self.transcript = TranscriptStore(self.store, self.events, self.conversations)
        self.requests = RequestService(
            self.store, self.conversations, self.transcript,
            engine=SimpleNamespace(deps=SimpleNamespace()), permissions=owner.manager,
            authority=owner.authority, delivery=SimpleNamespace())
        self.search = TranscriptSearch(self.transcript, self.events)
        self.ids, self.aliases = {}, {}

    def seed(self):
        for alias, session in self.sessions._sessions.items():
            cid = self.conversations.create(title=alias)["conversation"]["id"]
            self.ids[alias], self.aliases[cid] = cid, alias
            for message in session.messages:
                timestamp = datetime.fromtimestamp(message.timestamp, UTC).isoformat()
                if message.role == "user":
                    # Admission uses the canonical installation owner, not u1/alice/bob.
                    with patch("src.desktop.transcript.now", return_value=timestamp):
                        self.requests.submit({"client_submission_id": uuid4().hex,
                                              "conversation_id": cid, "text": message.content})
                else:
                    self.transcript.commit(cid, message.role, message.content,
                                           created_at=timestamp)

    def query(self, params):
        if not self.owner.authority.accepts(self.owner.context):
            raise PermissionError("owner expired")
        translated = {"query": params.get("q")}
        if "channel_id" in params:
            translated["conversation_id"] = self.ids.get(params["channel_id"], params["channel_id"])
        if "limit" in params:
            # Legacy REST clamped oversized limits; desktop IPC remains strict.
            translated["limit"] = min(int(params["limit"]), 50)
        # Only legacy wire conversion, never adapter-side result filtering.
        for key in ("after", "before"):
            if key in params:
                try:
                    value = float(params[key])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    translated[key] = value
        try:
            result = self.search.handle("search.query", translated)
        except ConversationError as error:
            return SearchResponse(400 if error.code == "bad_request" else 404,
                                  {"error": error.code})
        rows = [{"channel_id": self.aliases[hit["conversation_id"]],
                 "type": hit["role"], "content": hit["snippet"],
                 "timestamp": datetime.fromisoformat(hit["created_at"]).timestamp()}
                for hit in result["hits"]]
        return SearchResponse(200, {"query": translated["query"], "count": len(rows),
                                    "results": rows})


class SearchResponse:
    def __init__(self, status, data):
        self.status, self.data = status, data

    async def json(self):
        return self.data


class SearchServer:
    __test__ = False

    def __init__(self, fixture):
        self.fixture = fixture


class SearchClient:
    """Frozen HTTP client spelling, without an HTTP server or alternate route."""
    __test__ = False

    def __init__(self, server):
        self.fixture = server.fixture

    async def __aenter__(self):
        self.fixture.seed()
        return self

    async def __aexit__(self, *_):
        self.fixture.store.close()

    async def get(self, path, params=None):
        if path != "/api/sessions/search":
            raise ValueError("unadmitted transport fixture")
        return self.fixture.query(params or {})


def pinned_tree(path):
    stem = path.removeprefix("tests/").removesuffix(".py")
    if path != f"tests/{stem}.py" or stem not in SUITES:
        raise ValueError("unadmitted review suite")
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise ValueError("review frozen baseline bytes changed")
    return ast.parse(source)


def _setup_tree(path, original):
    tree, originals, seen = copy.deepcopy(original), {}, set()

    class ExactSetup(ast.NodeTransformer):
        def visit(self, node):
            line = getattr(node, "lineno", None)
            if isinstance(node, ast.stmt) and line in SETUP_HUNKS[path]:
                before, source = SETUP_HUNKS[path][line]
                if hashlib.sha256(dump(node).encode()).hexdigest() == before:
                    if line in seen:
                        raise ValueError("setup matched twice")
                    seen.add(line)
                    originals[line] = copy.deepcopy(node)
                    return ast.copy_location(ast.parse(source).body[0], node)
            return super().visit(node)

    adapted = ExactSetup().visit(tree)
    ast.fix_missing_locations(adapted)
    if seen != set(SETUP_HUNKS[path]) or corpus(original) != corpus(adapted):
        raise ValueError("setup/assertion/signature/parameter corpus drift")
    replayed = set()

    class ReverseSetup(ast.NodeTransformer):
        def visit(self, node):
            line = getattr(node, "lineno", None)
            if isinstance(node, ast.stmt) and line in originals:
                if dump(node) == dump(ast.parse(SETUP_HUNKS[path][line][1]).body[0]):
                    if line in replayed:
                        raise ValueError("reverse replay matched twice")
                    replayed.add(line)
                    return copy.deepcopy(originals[line])
            return super().visit(node)

    restored = ReverseSetup().visit(copy.deepcopy(adapted))
    if replayed != seen or dump(restored) != dump(original):
        raise ValueError("complete AST reverse replay failed")
    return adapted


def verify_adaptation(path, original, adapted):
    pinned = pinned_tree(path)
    if dump(pinned) != dump(original):
        raise ValueError("original differs from pinned baseline")
    if corpus(original) != corpus(adapted) or dump(_setup_tree(path, pinned)) != dump(adapted):
        raise ValueError("AST changed outside exact setup allowlist")
    return True


def register_module(namespace, module, *, prefix, excluded):
    """Exact executable export projection; never mutate original module or AST."""
    declared = [item["case"] for item in CORPUS_EXCLUSIONS.get(prefix, ())]
    if excluded != declared or len(set(excluded)) != len(excluded):
        raise ValueError("executable retirement differs from exact declaration")
    projection = ModuleType(module.__name__)
    projection.__dict__.update(module.__dict__)
    seen = set()
    for name, value in vars(module).items():
        if name.startswith("Test") and isinstance(value, type):
            removed = {case.split(".")[1] for case in excluded if case.split(".")[0] == name}
            if removed:
                if not removed <= set(vars(value)):
                    raise ValueError("retirement is not an original executable case")
                attrs = {key: item for key, item in vars(value).items()
                         if key not in removed and key not in ("__dict__", "__weakref__")}
                projection.__dict__[name] = type(name, value.__bases__, attrs)
                seen.update(f"{name}.{method}" for method in removed)
    if seen != set(excluded):
        raise ValueError("not all exact executable retirements matched")
    register_frozen_module(namespace, projection, prefix=prefix)


def load(namespace):
    loaded = {}
    for stem, selection in CORPUS_SELECTIONS.items():
        if selection is not None:
            raise ValueError("complete suites required")
        path = f"tests/{stem}.py"
        original = pinned_tree(path)
        adapted = _setup_tree(path, original)
        verify_adaptation(path, original, adapted)
        module = ModuleType(f"frozen_step8_review_{stem}")
        module.__dict__["DesktopSearchFixture"] = DesktopSearchFixture
        exec(compile(adapted, path, "exec"), module.__dict__)
        register_module(namespace, module, prefix=stem,
                        excluded=[item["case"] for item in CORPUS_EXCLUSIONS.get(stem, ())])
        loaded[path] = original, adapted
    return loaded
