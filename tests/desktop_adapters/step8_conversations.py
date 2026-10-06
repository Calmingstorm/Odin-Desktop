"""Complete frozen step2 suites with authentic admitted-message setup only."""
from __future__ import annotations

import ast
import contextvars
import copy
import hashlib
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from src.permissions.manager import PermissionManager

_owner = contextvars.ContextVar("step8_conversation_owner", default=None)


@contextmanager
def temporary_owner(tmp_path):
    if os.geteuid() == 0:
        raise RuntimeError("use isolated non-root odin runner")
    paths = ProfilePaths.from_xdg(environ={
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }, home=tmp_path)
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    request_token = manager.set_request_owner(context)
    owner_token = _owner.set(SimpleNamespace(paths=paths, authority=authority,
                                            manager=manager, context=context))
    try:
        if not manager.is_owner(authority.owner_id) or not authority.accepts(context):
            raise RuntimeError("authentic temporary conversation owner unavailable")
        yield _owner.get()
    finally:
        _owner.reset(owner_token)
        manager.reset_request_owner(request_token)
        authority.release_runtime()


def desktop_message(identity, content="body", *, conversation_id="42", timestamp=100.0):
    state = _owner.get()
    if state is None or not state.authority.accepts(state.context):
        raise PermissionError("no authenticated temporary conversation owner")
    return SimpleNamespace(id=identity, content=content, conversation_id=conversation_id,
                           owner_id=state.authority.owner_id, participant="tester",
                           role="user", created_at=datetime.fromtimestamp(timestamp, UTC),
                           attachments=[])


CORPUS_SELECTIONS = {
    "test_channel_cursor_campaign": None,
    "test_pr341_b10_channel_consistency": None,
    "test_pr341_b7_channel_reconciliation": None,
    "test_search_history_source_priority": None,
}
CORPUS_EXCLUSIONS = {}
SUITES = {
    "test_channel_cursor_campaign": (
        "67b01211656e00656f447046057f931569ee8fd0bf76b112e3c396f0b0e0ca49"
    ),
    "test_pr341_b10_channel_consistency": (
        "248a1ccf33f4723e0b5f453fefb65a7364ad8fd5b17dde34c96c49313ffc26d2"
    ),
    "test_pr341_b7_channel_reconciliation": (
        "2e1bdd838c6204107963186f2f28dabc40868ffef0911305d45980d38ed109af"
    ),
    "test_search_history_source_priority": (
        "f017dfb328b626e378ed045123c89b439f1f9c9db8def4f113f1ae5a01ed2bb5"
    ),
}
# Exact locations and complete before-node hashes. No removal hunks.
SETUP_HUNKS = {
    "tests/test_channel_cursor_campaign.py": {
        12: ("4cd35a1004787776e81e087c9867ad90bdd858d5cd79f86cf3492d14ee42ca66",
             "return desktop_message(identity, content)"),
    },
    "tests/test_pr341_b10_channel_consistency.py": {
        13: ("3908a9d63775bff0cfe25c0d26ed100173600fd22fe4b0ae317f1543430d7d02",
             "from tests.desktop_adapters.step8_conversations import desktop_message as message"),
    },
    "tests/test_pr341_b7_channel_reconciliation.py": {
        10: ("3908a9d63775bff0cfe25c0d26ed100173600fd22fe4b0ae317f1543430d7d02",
             "from tests.desktop_adapters.step8_conversations import desktop_message as message"),
    },
    "tests/test_search_history_source_priority.py": {
        255: ("6742991fc737d2e366b1008759c129cdecb8d574cc777a7bb0f119117460c0a7",
              'message = desktop_message("12345", f"Fresh marker {marker}", '
              'conversation_id="scratch", timestamp=datetime.now(UTC).timestamp())'),
    },
}


def pinned_tree(path):
    stem = path.removeprefix("tests/").removesuffix(".py")
    if path != f"tests/{stem}.py" or stem not in SUITES:
        raise ValueError("unadmitted step2 suite")
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise ValueError("step2 frozen baseline bytes changed")
    return ast.parse(source)


def _setup_tree(path, original):
    tree = copy.deepcopy(original)
    seen, originals = set(), {}

    class ExactSetup(ast.NodeTransformer):
        def visit(self, node):
            line = getattr(node, "lineno", None)
            if line not in SETUP_HUNKS[path] or not isinstance(node, ast.stmt):
                return super().visit(node)
            expected, replacement = SETUP_HUNKS[path][line]
            if hashlib.sha256(dump(node).encode()).hexdigest() != expected:
                return super().visit(node)
            if line in seen:
                raise ValueError("step2 setup matched twice")
            seen.add(line)
            originals[line] = copy.deepcopy(node)
            return ast.copy_location(ast.parse(replacement).body[0], node)

    adapted = ExactSetup().visit(tree)
    ast.fix_missing_locations(adapted)
    if seen != set(SETUP_HUNKS[path]) or corpus(original) != corpus(adapted):
        raise ValueError("step2 setup/assertion/signature/parameter corpus drift")
    restored, replayed = copy.deepcopy(adapted), set()

    class ReverseSetup(ast.NodeTransformer):
        def visit(self, node):
            line = getattr(node, "lineno", None)
            if line in originals and isinstance(node, ast.stmt):
                replacement = ast.parse(SETUP_HUNKS[path][line][1]).body[0]
                if dump(node) == dump(replacement):
                    if line in replayed:
                        raise ValueError("step2 reverse replay matched twice")
                    replayed.add(line)
                    return copy.deepcopy(originals[line])
            return super().visit(node)

    restored = ReverseSetup().visit(restored)
    if replayed != seen or dump(restored) != dump(original):
        raise ValueError("step2 complete AST reverse replay failed")
    return adapted


def verify_adaptation(path, original, adapted):
    pinned = pinned_tree(path)
    if dump(pinned) != dump(original):
        raise ValueError("original AST differs from pinned baseline")
    expected = _setup_tree(path, pinned)
    if corpus(original) != corpus(adapted) or dump(expected) != dump(adapted):
        raise ValueError("AST changed outside exact setup allowlist")
    return True


def load(namespace):
    loaded = {}
    for stem, selected in CORPUS_SELECTIONS.items():
        if selected is not None or CORPUS_EXCLUSIONS:
            raise ValueError("only complete step2 suites are admitted")
        path = f"tests/{stem}.py"
        original = pinned_tree(path)
        adapted = _setup_tree(path, original)
        verify_adaptation(path, original, adapted)
        module = ModuleType(f"frozen_step8_{stem}")
        module.__dict__["desktop_message"] = desktop_message
        exec(compile(adapted, path, "exec"), module.__dict__)
        if stem == "test_search_history_source_priority":
            namespace["history"] = module.history
        register_module(namespace, module, prefix=stem)
        loaded[path] = (original, adapted)
    return loaded
