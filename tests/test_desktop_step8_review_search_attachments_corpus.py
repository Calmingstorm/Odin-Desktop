"""Complete inherited search/attachment cases, provenance and safe-fixture proof."""
import ast
import copy
import os
import zipfile

import pytest

from scripts.maintenance.fixture_corpus import corpus
from src.discord.attachments import AttachmentProcessor
from tests.desktop_adapters import step8_review_search_attachments as adapter
from tests.desktop_adapters.step8_review_search_attachments import load


@pytest.fixture(autouse=True)
def _canonical_owner(tmp_path_factory):
    # The original cleanup tests own every directory beneath their tmp_path.
    # Authority scaffolding is separate so it cannot change cleanup counts.
    with adapter.temporary_owner(tmp_path_factory.mktemp("review-search-owner")):
        yield


_loaded = load(globals())


def test_review_search_attachments_complete_frozen_corpus():
    assert set(adapter.CORPUS_EXCLUSIONS) == {"test_session_search"}
    assert [item["case"] for item in adapter.CORPUS_EXCLUSIONS["test_session_search"]] == [
        "TestSessionSearchAPI.test_search_with_user_filter"]
    assert all(selection is None for selection in adapter.CORPUS_SELECTIONS.values())
    for path, (original, adapted) in _loaded.items():
        assert corpus(original) == corpus(adapted)
        assert adapter.verify_adaptation(path, original, adapted)
        for symbol, _, _ in corpus(original)["cases"]:
            classname, method = symbol.split(".")
            imported = globals()[f"Test_{path.split('/')[-1][:-3]}_{classname[4:]}"]
            if symbol in [
                item["case"]
                for item in adapter.CORPUS_EXCLUSIONS.get(path.split('/')[-1][:-3], ())
            ]:
                assert not hasattr(imported, method)
                continue
            assert callable(getattr(imported, method))


def test_review_loader_rejects_unadmitted_suite():
    with pytest.raises(ValueError, match="unadmitted"):
        adapter.pinned_tree("tests/test_not_admitted.py")


@pytest.mark.parametrize("path", list(adapter.SETUP_HUNKS))
def test_review_loader_rejects_baseline_hash_drift(path, monkeypatch):
    monkeypatch.setattr(adapter, "frozen_source", lambda _: b"pass\n")
    with pytest.raises(ValueError, match="baseline bytes"):
        adapter.pinned_tree(path)


@pytest.mark.parametrize("path", list(adapter.SETUP_HUNKS))
def test_review_loader_rejects_setup_hash_drift(path):
    original, _ = _loaded[path]
    broken = copy.deepcopy(original)
    target = next(
        node for node in ast.walk(broken)
        if isinstance(node, ast.stmt) and node.lineno == next(iter(adapter.SETUP_HUNKS[path]))
    )
    target.lineno += 10000
    with pytest.raises(ValueError, match="corpus drift"):
        adapter._setup_tree(path, broken)


@pytest.mark.parametrize("kind", ["assertion", "signature", "decorator", "parameter", "behavior"])
def test_review_loader_rejects_nonsetup_ast_drift(kind):
    path = "tests/test_attachments.py"
    original, adapted = _loaded[path]
    broken = copy.deepcopy(adapted)
    case = next(node for node in ast.walk(broken)
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"))
    if kind == "assertion":
        next(node for node in ast.walk(case) if isinstance(node, ast.Assert)).test = (
            ast.Constant(True)
        )
    elif kind == "signature":
        case.args.args.append(ast.arg(arg="invented"))
    elif kind == "decorator":
        case.decorator_list.append(ast.Name(id="invented", ctx=ast.Load()))
    elif kind == "parameter":
        case.decorator_list.append(
            ast.parse("pytest.mark.parametrize('v', [1, 2])", mode="eval").body
        )
    else:
        case.body.insert(0, ast.parse("invented = True").body[0])
        assert corpus(original) == corpus(broken)
    with pytest.raises(ValueError, match="allowlist"):
        adapter.verify_adaptation(path, original, broken)


def test_review_search_admission_uses_actual_canonical_owner(tmp_path):
    fixture = adapter.DesktopSearchFixture(tmp_path)
    try:
        cid = fixture.conversations.create()["conversation"]["id"]
        response = fixture.requests.submit({"client_submission_id": "seed", "conversation_id": cid,
                                            "text": "canonical searchable marker"})
        request = fixture.requests.get_request(response["request_id"])
        state = adapter._owner.get()
        assert request["owner"] == state.authority.owner_id
        assert state.context.owner_uid == os.geteuid()
        assert state.authority.accepts(state.context)
        assert (
            fixture.search.handle("search.query", {"query": "searchable"})["hits"][0]["message_id"]
            == response["message_id"]
        )
        with pytest.raises(PermissionError):
            state.authority.authenticate_local(peer_uid=os.geteuid() + 1)
    finally:
        fixture.store.close()


def test_review_safe_zip_fixture_preserves_original_containment_property(tmp_path):
    extraction = (
        tmp_path / "nested" / "sandbox" / "workspace" / "ch1" / "msg1" / "evil.zip.extracted"
    )
    member = "../../escape.txt"
    # Even naive join/write without traversal rejection stays within tmp_path.
    broken_destination = (extraction / member).resolve()
    assert broken_destination.is_relative_to(tmp_path.resolve())
    assert not broken_destination.is_relative_to(extraction.resolve())
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(member, "pwned")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}
    manifest, ok = AttachmentProcessor(temp_dir=str(tmp_path))._extract_zip(archive, extraction)
    assert not ok
    assert any("BLOCKED" in entry for entry in manifest)
    assert not broken_destination.exists()
    # No archive member landed anywhere outside extraction, not just at one guessed path.
    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_review_transport_does_not_implement_product_search(tmp_path, monkeypatch):
    fixture = adapter.DesktopSearchFixture(tmp_path)
    calls = []
    try:
        def observe(method, params):
            calls.append((method, params))
            return {"hits": [], "next_cursor": None, "watermark": "0"}
        monkeypatch.setattr(fixture.search, "handle", observe)
        fixture.ids["ch1"] = "actual-conversation"
        response = fixture.query({"q": "marker", "channel_id": "ch1", "user_id": "bob",
                                  "after": "1700000000", "before": "1700000010", "limit": "100"})
        assert response.status == 200
        assert calls == [(
            "search.query", {"query": "marker", "conversation_id": "actual-conversation",
                             "after": 1700000000.0,
                             "before": 1700000010.0, "limit": 50})]
        assert response.data["results"] == []
    finally:
        fixture.store.close()


def test_review_search_time_role_filters_before_paging_and_inclusive(tmp_path):
    fixture = adapter.DesktopSearchFixture(tmp_path)
    try:
        cid = fixture.conversations.create()["conversation"]["id"]
        for timestamp, role in [
            (100, "user"), (200, "assistant"), (300, "assistant"), (400, "user")
        ]:
            fixture.transcript.commit(
                cid, role, "needle", created_at=adapter.datetime.fromtimestamp(
                    timestamp, adapter.UTC).isoformat())
        query = {"query": "needle", "after": 200, "before": 300, "role": "assistant", "limit": 1}
        first = fixture.search.handle("search.query", query)
        assert len(first["hits"]) == 1
        assert adapter.datetime.fromisoformat(first["hits"][0]["created_at"]).timestamp() == 300
        assert first["next_cursor"] == "1"
        second = fixture.search.handle("search.query", {**query, "cursor": first["next_cursor"]})
        assert adapter.datetime.fromisoformat(second["hits"][0]["created_at"]).timestamp() == 200
        assert second["next_cursor"] is None
        assert fixture.search.query({**query, "after": 301})["hits"] == []
        assert len(fixture.search.query({"query": "needle", "unused": "unchanged"})["hits"]) == 4
    finally:
        fixture.store.close()


@pytest.mark.parametrize("change", [
    {"after": True}, {"after": "100"}, {"before": float("nan")},
    {"before": float("inf")}, {"after": []}, {"role": "bob"}, {"role": False},
    {"limit": 51}, {"limit": 100},
])
def test_review_search_filter_validation_preserves_strict_ipc(tmp_path, change):
    fixture = adapter.DesktopSearchFixture(tmp_path)
    try:
        with pytest.raises(adapter.ConversationError) as error:
            fixture.search.handle("search.query", {"query": "needle", **change})
        assert error.value.code == "bad_request"
    finally:
        fixture.store.close()


def test_review_legacy_limit_clamp_reaches_real_fifty_cap(tmp_path):
    fixture = adapter.DesktopSearchFixture(tmp_path)
    try:
        cid = fixture.conversations.create()["conversation"]["id"]
        fixture.aliases[cid] = "ch1"
        for number in range(55):
            fixture.transcript.commit(cid, "user", f"needle {number}")
        result = fixture.query({"q": "needle", "limit": "100"})
        assert result.status == 200
        assert result.data["count"] == 50
        assert len(result.data["results"]) == 50
        assert fixture.search.query({"query": "needle", "limit": 50})["next_cursor"] == "50"
    finally:
        fixture.store.close()
