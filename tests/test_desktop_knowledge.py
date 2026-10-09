"""Knowledge management uses real disposable SQLite, never embedding networks."""
import asyncio
import json

import pytest

from src.desktop.knowledge import KnowledgeService
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.knowledge.importer import BulkImporter
from src.knowledge.store import IngestOutcome, KnowledgeStore


@pytest.fixture
def knowledge(tmp_path):
    paths = ProfilePaths.from_xdg("knowledge", home=tmp_path, environ={})
    paths.data_dir.mkdir(parents=True)
    store = KnowledgeStore(str(paths.data_dir / "knowledge.db"))
    assert store.available
    service = KnowledgeService(paths, store=store)
    yield service, store
    store.close()


@pytest.mark.asyncio
async def test_durable_ingest_list_search_reingest_and_restore(knowledge):
    service, store = knowledge
    assert await service.handle("knowledge.ingest", {
        "source": "doc", "content": "alpha document"}) == {
        "source": "doc", "chunks": 1}
    assert store.get_source_snapshot("doc") == "alpha document"
    listed = await service.handle("knowledge.list", {})
    assert listed[0]["source"] == "doc"
    assert listed[0]["preview"] == "alpha document"
    hits = await service.handle("knowledge.search", {"q": "alpha"})
    assert hits[0]["content"] == "alpha document"
    assert await service.handle("knowledge.reingest", {"source": "doc"}) == {
        "source": "doc", "chunks": 1, "status": "already stored, unchanged", "outcome": "unchanged"}
    await service.handle("knowledge.ingest", {"source": "doc", "content": "beta replacement"})
    versions = await service.handle("knowledge.versions", {"source": "doc"})
    assert [v["version"] for v in versions] == [2, 1]
    assert all("content" not in item for item in versions)
    assert await service.handle("knowledge.restore", {"source": "doc", "version": 1}) == {
        "status": "restored", "source": "doc", "version": 1, "chunks": 1}
    assert store.get_source_snapshot("doc") == "alpha document"
    assert await service.handle("knowledge.delete", {"source": "doc"}) == {
        "status": "deleted", "chunks_removed": 1}
    assert store.get_source_snapshot("doc") is None
    versions = await service.handle("knowledge.versions", {"source": "doc"})
    assert versions[0]["action"] == "delete"
    with pytest.raises(MethodError) as error:
        await service.handle("knowledge.restore", {
            "source": "doc", "version": versions[0]["version"]})
    assert error.value.code == "bad_request"
    await service.handle("knowledge.restore", {"source": "doc", "version": 1})
    assert store.get_source_snapshot("doc") == "alpha document"


@pytest.mark.asyncio
async def test_same_store_engine_and_persistence(knowledge):
    service, store = knowledge
    await store.ingest("tool written text", "tool-source")
    assert (await service.handle("knowledge.list", {}))[0]["source"] == "tool-source"
    await service.handle("knowledge.ingest", {"source": "management", "content": "management text"})
    reopened = KnowledgeService(service.paths)
    try:
        assert {row["source"] for row in await reopened.handle("knowledge.list", {})} == {
            "tool-source", "management"}
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_duplicate_and_near_duplicate_semantics(knowledge):
    service, store = knowledge
    await service.handle("knowledge.ingest", {"source": "a", "content": "original text"})
    duplicate = await service.handle("knowledge.ingest", {
        "source": "b", "content": "original text"})
    assert duplicate["outcome"] == "duplicate" and duplicate["duplicate_of"] == "a"
    assert store.get_source_snapshot("b") is None
    # Real overlapping chunk dedup, not the fixture's first-200-char heuristic.
    content = "a" * 18000
    await service.handle("knowledge.ingest", {"source": "long", "content": content})
    conflict = await service.handle("knowledge.ingest", {
        "source": "near", "content": content + "suffix"})
    assert conflict["outcome"] == "conflict"
    assert store.get_source_snapshot("near") is None


@pytest.mark.asyncio
async def test_reingest_requires_full_snapshot(knowledge, monkeypatch):
    service, store = knowledge
    await store.ingest("current document", "doc")
    monkeypatch.setattr(store, "get_source_snapshot", lambda source: None)
    with pytest.raises(MethodError) as error:
        await service.handle("knowledge.reingest", {"source": "doc"})
    assert error.value.code == "conflict"


@pytest.mark.asyncio
async def test_ingest_label_does_not_import_and_import_is_explicit(knowledge, tmp_path):
    _, store = knowledge
    document = tmp_path / "import.txt"
    document.write_text("explicit imported document")
    paths = ProfilePaths.from_xdg("knowledge", home=tmp_path, environ={})
    importer = BulkImporter(store, admitted_roots=[tmp_path])
    service = KnowledgeService(paths, store=store, importer=importer)
    await service.handle("knowledge.ingest", {
        "source": str(document), "content": "literal content"})
    assert store.get_source_snapshot(str(document)) == "literal content"
    result = await service.handle("knowledge.import", {
        "items": [{"type": "file", "path": str(document)}]})
    assert result["succeeded"] == 1 and result["failed"] == 0
    assert store.get_source_snapshot(document.as_uri()) == "explicit imported document"
    service.close()  # injected engine remains graph-owned
    assert store.available


@pytest.mark.asyncio
async def test_no_success_before_commit(knowledge, monkeypatch):
    service, store = knowledge
    started = asyncio.Event()
    release = asyncio.Event()
    original = store.ingest
    async def gated(*args, **kwargs):
        started.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(store, "ingest", gated)
    pending = asyncio.create_task(service.handle("knowledge.ingest", {
        "source": "doc", "content": "text"}))
    await started.wait()
    assert not pending.done() and store.get_source_snapshot("doc") is None
    release.set()
    assert await pending == {"source": "doc", "chunks": 1}
    assert store.get_source_snapshot("doc") == "text"


@pytest.mark.asyncio
async def test_failure_zero_and_secrets_never_success_or_leak(knowledge, monkeypatch):
    service, store = knowledge
    secret = "password=example-sensitive-value"
    await store.ingest(secret, "doc")
    assert secret not in json.dumps(await service.handle("knowledge.list", {}))
    assert secret not in json.dumps(await service.handle("knowledge.search", {"q": "password"}))
    async def failed(*args, **kwargs):
        return IngestOutcome(0, "failure")
    monkeypatch.setattr(store, "ingest", failed)
    with pytest.raises(MethodError) as error:
        await service.handle("knowledge.ingest", {"source": "new", "content": "text"})
    assert error.value.code == "internal_error"
    async def raised(*args, **kwargs):
        raise OSError(secret)
    monkeypatch.setattr(store, "ingest", raised)
    with pytest.raises(MethodError) as error:
        await service.handle("knowledge.ingest", {"source": "new", "content": "text"})
    assert secret not in str(error.value)
    assert error.value.disposition == "outcome_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params", [
    ("knowledge.ingest", {"source": "doc", "content": ""}),
    ("knowledge.ingest", {"source": "x" * 101, "content": "text"}),
    ("knowledge.ingest", {"source": "doc", "content": "x" * 500001}),
    ("knowledge.search", {}), ("knowledge.search", {"q": "\x00"}),
    ("knowledge.reingest", {"source": "absent"}),
    ("knowledge.delete", {"source": "absent"}),
    ("knowledge.restore", {"source": "doc", "version": 1}),
    ("knowledge.restore", {"source": "doc", "version": True}),
    ("knowledge.import", {"items": []}), ("knowledge.list", []), ("unknown", {}),
])
async def test_validation_and_missing(knowledge, method, params):
    with pytest.raises(MethodError):
        await knowledge[0].handle(method, params)


@pytest.mark.asyncio
async def test_limit_fallback_clamp_and_unavailable(knowledge, monkeypatch):
    service, store = knowledge
    seen = []
    async def search(query, embedder=None, limit=10):
        seen.append(limit)
        return []
    monkeypatch.setattr(store, "search_hybrid", search)
    for limit in ("bad", 0, 100):
        assert await service.handle("knowledge.search", {"q": "text", "limit": limit}) == []
    assert seen == [10, 1, 50]
    store.close()
    with pytest.raises(MethodError) as error:
        await service.handle("knowledge.list", {})
    assert error.value.code == "unavailable"


def test_lazy_constructor_never_opens_store_or_embedder(tmp_path):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    service = KnowledgeService(paths)
    assert service._store is None and service._importer is None
    assert not paths.data_dir.exists()


def test_importer_must_share_engine(knowledge, tmp_path):
    service, store = knowledge
    other = KnowledgeStore(str(tmp_path / "other.db"))
    try:
        with pytest.raises(ValueError, match="same knowledge store"):
            KnowledgeService(service.paths, store=store, importer=BulkImporter(other))
        assert KnowledgeService(service.paths, importer=BulkImporter(store)).store is store
    finally:
        other.close()


@pytest.mark.asyncio
async def test_existing_source_label_is_exact_not_trimmed(knowledge):
    service, store = knowledge
    await store.ingest("literal source text", " padded source ")
    assert await service.handle("knowledge.delete", {"source": " padded source "}) == {
        "status": "deleted", "chunks_removed": 1}


@pytest.mark.asyncio
async def test_injected_fake_embedder_uses_real_store_without_network(knowledge):
    original, store = knowledge
    class Embedder:
        def __init__(self):
            self.inputs = []

        async def embed(self, text):
            self.inputs.append(text)
            return [1.0] + [0.0] * 383

    embedder = Embedder()
    service = KnowledgeService(original.paths, store=store,
                               importer=BulkImporter(store, embedder))
    assert service.embedder is embedder
    await service.handle("knowledge.ingest", {"source": "vector", "content": "test document"})
    assert store.get_source_snapshot("vector") == "test document"
    hits = await service.handle("knowledge.search", {"q": "document"})
    assert hits[0]["source"] == "vector"
    assert embedder.inputs == (["test document", "document"] if store._has_vec else [])


@pytest.mark.asyncio
async def test_failed_restore_never_reports_success(knowledge, monkeypatch):
    service, store = knowledge
    await store.ingest("saved version", "doc")
    async def failed(*args, **kwargs):
        return IngestOutcome(1, "failure")
    monkeypatch.setattr(store, "restore_version", failed)
    with pytest.raises(MethodError) as error:
        await service.handle("knowledge.restore", {"source": "doc", "version": 1})
    assert error.value.code == "internal_error"


class _TopicEmbedder:
    """Deterministic vectors by topic, so a paraphrase with no shared words still matches."""

    TOPICS = (("kiwi", "fruit", "weekday", "release"), ("standup", "meeting", "daily"))

    def __init__(self):
        self.unavailable_reason = None

    async def embed(self, text):
        lowered = text.lower()
        vector = [0.0] * 384
        for index, words in enumerate(self.TOPICS):
            vector[index] = float(sum(word in lowered for word in words))
        vector[383] = 0.1
        return vector


async def _composed_core(tmp_path, monkeypatch, *, roots=(), search=True, runtime=None,
                         files=None):
    import os
    from types import SimpleNamespace

    from src.desktop.core import CoreService, profile_config
    from src.search import bundled_models
    from tests.test_desktop_core_lifecycle import profile
    from tests.test_desktop_engine_services import Provider
    from tests.test_desktop_management_core import TemporaryKeyring

    monkeypatch.setattr(bundled_models, "bundled_model_roots", lambda: tuple(roots))
    paths, socket_path, token_file = files or profile(tmp_path)
    config = profile_config(paths)
    config.openai_codex.enabled = False
    config.llm_provider.model = "compat:test"
    config.openai_compatible.enabled = True
    config.learning.enabled = False
    config.browser.enabled = False
    config.search.enabled = search
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, config_provider=lambda _: config,
        runtime_provider=lambda *_: SimpleNamespace(
            compatible_client=Provider([]), **(runtime or {})),
        secret_backend=TemporaryKeyring())
    await core.start(read_fd)

    async def close():
        await core.close()
        os.close(read_fd)
        os.close(write_fd)

    close.files = (paths, socket_path, token_file)
    return core, paths, close


async def _knowledge_health(core):
    result = await core.management.invoke("health.get", {})
    assert result["ok"], result
    return next(item for item in result["result"]["components"] if item["name"] == "knowledge")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["bundled", "source checkout", "search off"])
async def test_packaged_core_composes_the_bundled_embedder_and_full_text_index(
        tmp_path, monkeypatch, case):
    """L17 (1.0.5): the packaged core never built an embedder (the bundled model sat
    unused) nor a full-text index, so knowledge search was literal and health still
    claimed vector search. Odin's wiring builds both while search is on."""
    from src.search.embedder import LocalEmbedder

    root = tmp_path / "bundle" / "models" / "bge-small-en-v1.5"
    core, paths, close = await _composed_core(
        tmp_path, monkeypatch, roots=(root,) if case == "bundled" else (),
        search=case != "search off")
    try:
        deps = core.engine.deps
        fts = deps.knowledge_fts
        if case == "bundled":
            assert isinstance(deps.embedder, LocalEmbedder)
            assert deps.embedder._model_roots == (root,)
        else:
            assert deps.embedder is None
        assert core.management.knowledge.embedder is deps.embedder
        if case == "search off":
            assert fts is None and deps.knowledge_store._fts is None
        else:
            assert deps.knowledge_store._fts is fts and fts.available
            assert (paths.data_dir / "fts.db").is_file()
        component = await _knowledge_health(core)
        semantic = case == "bundled" and deps.knowledge_store._has_vec
        assert component["metadata"]["vector_search"] is semantic
        assert ("vector + FTS" if semantic else "FTS only") in component["detail"]
        if case == "bundled":
            # The test bundle has no model: the failed lazy load is reported, not hidden.
            assert await deps.embedder.embed("probe") is None
            assert "bundled embedding model unavailable" in deps.embedder.unavailable_reason
            component = await _knowledge_health(core)
            assert component["metadata"]["vector_search"] is False
            assert "FTS only" in component["detail"]
    finally:
        await close()
    if fts is not None:
        assert not fts.available


@pytest.mark.asyncio
async def test_composed_knowledge_search_finds_a_paraphrase_through_the_embedder(
        tmp_path, monkeypatch):
    """The composed store, management service and embedder rank meaning, not only words."""
    core, _, close = await _composed_core(
        tmp_path, monkeypatch, runtime={"embedder": _TopicEmbedder()})
    try:
        if not core.engine.deps.knowledge_store._has_vec:
            pytest.skip("sqlite-vec is not loadable here")
        service = core.management.knowledge
        for source, content in (("kiwi.md", "The kiwi project ships every Tuesday morning."),
                                ("standup.md", "Our standup is at 9 in the small room.")):
            await service.handle("knowledge.ingest", {"source": source, "content": content})
        hits = await service.handle(
            "knowledge.search", {"q": "which weekday does the fruit release go out"})
        assert hits[0]["source"] == "kiwi.md"
        hits = await service.handle("knowledge.search", {"q": "daily meeting"})
        assert hits[0]["source"] == "standup.md"
        hits = await service.handle("knowledge.search", {"q": "Tuesday"})
        assert hits[0]["source"] == "kiwi.md"
    finally:
        await close()


@pytest.mark.asyncio
async def test_startup_indexes_knowledge_stored_without_full_text_rows(tmp_path, monkeypatch):
    """Chunks stored before 1.0.5 had no full-text rows; startup adds them, as Odin's boot."""
    core, paths, close = await _composed_core(tmp_path, monkeypatch)
    await close()
    before = KnowledgeStore(str(paths.data_dir / "knowledge.db"))
    await before.ingest("Quarterly zebra inventory notes", "zebra.md")
    before.close()
    core, _, close = await _composed_core(tmp_path, monkeypatch, files=close.files)
    try:
        hits = core.engine.deps.knowledge_fts.search_knowledge("zebra")
        assert [row["source"] for row in hits] == ["zebra.md"]
    finally:
        await close()
