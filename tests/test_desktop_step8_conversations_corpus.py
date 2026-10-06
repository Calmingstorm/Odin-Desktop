"""Complete inherited step2 suites and independent loader/provenance checks."""
import ast
import copy
import os

import pytest

from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters import step8_conversations as adapter
from tests.desktop_adapters.step8_conversations import load


@pytest.fixture(autouse=True)
def _authentic_temporary_conversation_owner(tmp_path):
    with adapter.temporary_owner(tmp_path / "owner"):
        yield


_loaded = load(globals())


def test_step8_conversations_complete_frozen_corpus():
    assert adapter.CORPUS_EXCLUSIONS == {}
    assert all(selection is None for selection in adapter.CORPUS_SELECTIONS.values())
    for path, (original, adapted) in _loaded.items():
        assert corpus(original) == corpus(adapted)
        assert adapter.verify_adaptation(path, original, adapted)
        for symbol, _, _ in corpus(original)["cases"]:
            parts = symbol.split(".")
            name = f"test_{path.split('/')[-1][:-3]}_{parts[0][5:]}"
            assert callable(globals()[name])


@pytest.mark.parametrize("path", list(adapter.SETUP_HUNKS))
def test_step8_conversations_loader_rejects_source_digest_drift(path, monkeypatch):
    monkeypatch.setattr(adapter, "frozen_source", lambda _: b"pass\n")
    with pytest.raises(ValueError, match="baseline bytes"):
        adapter.pinned_tree(path)


def test_step8_conversations_loader_rejects_unadmitted_suite():
    with pytest.raises(ValueError, match="unadmitted"):
        adapter.pinned_tree("tests/test_not_admitted.py")


@pytest.mark.parametrize("path", list(adapter.SETUP_HUNKS))
def test_step8_conversations_loader_rejects_setup_hash_drift(path):
    original, _ = _loaded[path]
    broken = copy.deepcopy(original)
    line = next(iter(adapter.SETUP_HUNKS[path]))
    target = next(node for node in ast.walk(broken)
                  if isinstance(node, ast.stmt) and getattr(node, "lineno", None) == line)
    target.lineno += 10000
    with pytest.raises(ValueError, match="corpus drift"):
        adapter._setup_tree(path, broken)


@pytest.mark.parametrize("kind", ["assertion", "signature", "decorator", "parameter", "behavior"])
def test_step8_conversations_loader_rejects_nonsetup_ast_changes(kind):
    path = "tests/test_channel_cursor_campaign.py"
    original, adapted = _loaded[path]
    broken = copy.deepcopy(adapted)
    case = next(node for node in broken.body
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"))
    if kind == "assertion":
        assertion = next(node for node in ast.walk(case) if isinstance(node, ast.Assert))
        assertion.test = ast.Constant(value=True)
    elif kind == "signature":
        case.args.args.append(ast.arg(arg="invented"))
    elif kind == "decorator":
        case.decorator_list.append(ast.Name(id="invented", ctx=ast.Load()))
    elif kind == "parameter":
        case.decorator_list.append(ast.parse(
            "pytest.mark.parametrize('value', [1, 2])", mode="eval").body)
    else:
        case.body.insert(0, ast.parse("invented_behavior = True").body[0])
        assert corpus(original) == corpus(broken)
    with pytest.raises(ValueError, match="allowlist"):
        adapter.verify_adaptation(path, original, broken)


def test_step8_conversations_owner_is_authentic_and_closed():
    state = adapter._owner.get()
    message = adapter.desktop_message("m1")
    assert state.authority.accepts(state.context)
    assert state.manager.is_owner(message.owner_id)
    assert state.context.owner_uid == os.geteuid()
    assert message.conversation_id == "42"
    assert message.created_at.timestamp() == 100.0
    with pytest.raises(PermissionError):
        state.authority.authenticate_local(peer_uid=os.geteuid() + 1)
    token = adapter._owner.set(None)
    try:
        with pytest.raises(PermissionError, match="authenticated"):
            adapter.desktop_message("unbound")
    finally:
        adapter._owner.reset(token)
