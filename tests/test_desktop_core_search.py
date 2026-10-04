"""Desktop bundled-search and explicit knowledge-admission contracts.

No model, native extension or network is loaded by these tests.
"""
from __future__ import annotations

import asyncio
import struct
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.knowledge import importer as importer_module
from src.knowledge.importer import BulkImporter, MAX_FILE_BYTES
from src.knowledge.store import IngestOutcome
from src.search.embedder import LocalEmbedder, MAX_INPUT_CHARS
from src.search.sqlite_vec import deserialize_vector, serialize_vector


@pytest.fixture(autouse=True)
def no_native_models_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("native/model/network access is forbidden in this suite")

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=forbidden))
    monkeypatch.setattr(importer_module.aiohttp, "ClientSession", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("src.search.sqlite_vec.load_extension", forbidden)
    monkeypatch.setattr("src.knowledge.store.load_extension", forbidden)


@pytest.fixture
def store():
    return SimpleNamespace(list_sources=lambda: [], ingest=AsyncMock(return_value=1))


def install_model_stub(monkeypatch, constructor):
    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=constructor))


def vector_model(values, texts=None):
    def embed(documents):
        if texts is not None:
            texts.extend(documents)
        return [SimpleNamespace(tolist=lambda: list(values))]

    return SimpleNamespace(embed=embed)


@pytest.mark.asyncio
async def test_embedder_without_roots_is_explicitly_unavailable():
    embedder = LocalEmbedder()
    assert "no bundled" in embedder.unavailable_reason
    assert await embedder.embed("hello") is None


@pytest.mark.asyncio
async def test_missing_bundle_never_invokes_fastembed(tmp_path):
    embedder = LocalEmbedder(model_roots=[tmp_path / "absent"])
    assert await embedder.embed("hello") is None
    assert "bundled embedding model unavailable" in embedder.unavailable_reason


def test_relative_roots_are_not_cwd_grants(store):
    with pytest.raises(ValueError, match="absolute"):
        LocalEmbedder(model_roots=["models"])
    with pytest.raises(ValueError, match="absolute"):
        BulkImporter(store, admitted_roots=[""])


@pytest.mark.asyncio
async def test_bundle_loading_is_local_cpu_worker_and_serialization_unchanged(tmp_path, monkeypatch):
    calls, texts = [], []
    main_thread = threading.get_ident()
    values = [float(i) / 384 for i in range(384)]

    def constructor(model, **kwargs):
        assert threading.get_ident() != main_thread
        calls.append((model, kwargs))
        return vector_model(values, texts)

    install_model_stub(monkeypatch, constructor)
    embedder = LocalEmbedder(model_roots=[tmp_path])
    result = await embedder.embed("a" * (MAX_INPUT_CHARS + 10))
    assert result == values
    assert embedder.DIMENSIONS == len(result) == 384
    assert serialize_vector(result) == struct.pack("384f", *values)
    assert len(deserialize_vector(serialize_vector(result), 384)) == 384
    assert texts == ["a" * MAX_INPUT_CHARS]
    assert calls == [(embedder.MODEL, {
        "specific_model_path": str(tmp_path.resolve()),
        "cache_dir": str(tmp_path.resolve()),
        "local_files_only": True,
        "cuda": False,
    })]
    assert embedder.unavailable_reason is None
    assert await embedder.embed("again") == values
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_bundle_candidates_fail_local_then_use_next(tmp_path, monkeypatch):
    bad, good = tmp_path / "bad", tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    calls = []

    def constructor(model, **kwargs):
        calls.append(kwargs)
        assert kwargs["local_files_only"] is True
        if kwargs["specific_model_path"] == str(bad):
            raise ValueError("incomplete bundle")
        return vector_model([0.0] * 384)

    install_model_stub(monkeypatch, constructor)
    embedder = LocalEmbedder(model_roots=[bad, good])
    assert await embedder.embed("hello") == [0.0] * 384
    assert len(calls) == 2
    assert embedder.unavailable_reason is None


@pytest.mark.asyncio
async def test_corrupt_bundle_is_unavailable_without_cache_fallback(tmp_path, monkeypatch):
    def constructor(model, **kwargs):
        assert kwargs["local_files_only"] is True
        raise ValueError("incomplete bundle")

    install_model_stub(monkeypatch, constructor)
    embedder = LocalEmbedder(model_roots=[tmp_path])
    assert await embedder.embed("hello") is None
    assert "incomplete bundle" in embedder.unavailable_reason


@pytest.mark.asyncio
async def test_first_load_remains_single_flight_after_cancellation(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def constructor(model, **kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5), "test failed to release the model loader"
        return vector_model([0.0] * 384)

    install_model_stub(monkeypatch, constructor)
    embedder = LocalEmbedder(model_roots=[tmp_path])
    first = asyncio.create_task(embedder.embed("first"))
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(embedder.embed("second"))
        await asyncio.sleep(0.02)
        assert len(calls) == 1
    finally:
        release.set()
        if not first.done():
            await first
    assert await second == [0.0] * 384
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_local_import_default_is_fail_closed(tmp_path, store):
    path = tmp_path / "doc.md"
    path.write_text("admission must be explicit", encoding="utf-8")
    importer = BulkImporter(store)
    file_result = await importer.import_file(str(path))
    directory_result = await importer.import_directory(str(tmp_path))
    assert file_result.status == directory_result[0].status == "error"
    assert "none admitted" in file_result.error
    store.ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_roots_and_canonical_file_identity(tmp_path, store):
    root = tmp_path / "admitted"
    root.mkdir()
    path = root / "doc.md"
    path.write_text("canonical source", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    importer = BulkImporter(store, admitted_roots=[alias])
    single = await importer.import_file(str(alias / "doc.md"))
    directory = await importer.import_directory(str(root))
    assert single.status == directory[0].status == "ok"
    assert single.source == directory[0].source == path.resolve().as_uri()
    assert store.ingest.await_args.args == ("canonical source", path.as_uri())


@pytest.mark.asyncio
async def test_symlink_escape_and_prefix_sibling_are_denied(tmp_path, store):
    root = tmp_path / "admitted"
    sibling = tmp_path / "admitted-other"
    root.mkdir()
    sibling.mkdir()
    outside = sibling / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    escape = root / "escape.md"
    escape.symlink_to(outside)
    importer = BulkImporter(store, admitted_roots=[root])
    assert (await importer.import_file(str(outside))).status == "error"
    assert (await importer.import_file(str(escape))).status == "error"
    results = await importer.import_directory(str(root))
    assert results[0].status == "skipped"
    assert results[0].error == "no files matched pattern"
    store.ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_directory_scope_does_not_expand_to_other_admitted_root(tmp_path, store):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    outside = second / "doc.md"
    outside.write_text("other admitted directory", encoding="utf-8")
    (first / "alias.md").symlink_to(outside)
    importer = BulkImporter(store, admitted_roots=[first, second])
    result = await importer.import_directory(str(first))
    assert result[0].status == "skipped"
    store.ingest.assert_not_awaited()
    assert (await importer.import_file(str(outside))).status == "ok"


@pytest.mark.asyncio
async def test_file_size_fence_is_preserved(tmp_path, store):
    path = tmp_path / "large.md"
    path.write_bytes(b"a" * (MAX_FILE_BYTES + 1))
    importer = BulkImporter(store, admitted_roots=[tmp_path])
    result = await importer.import_file(str(path))
    assert result.status == "skipped"
    assert "too large" in result.error
    store.ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_stat_growth_size_fence_is_preserved(tmp_path, store, monkeypatch):
    path = tmp_path / "growing.md"
    path.write_text("small", encoding="utf-8")
    importer = BulkImporter(store, admitted_roots=[tmp_path])
    monkeypatch.setattr(importer, "_read_file_bytes", lambda path: b"a" * (MAX_FILE_BYTES + 1))
    result = await importer.import_file(str(path))
    assert result.status == "skipped"
    assert "too large" in result.error
    store.ingest.assert_not_awaited()


@pytest.mark.parametrize("outcome,count,status,note", [
    ("stored", 2, "ok", ""),
    ("unchanged", 2, "ok", "already stored, unchanged"),
    ("duplicate", 0, "skipped", "identical content already stored"),
    ("conflict", 0, "skipped", "near-duplicate content already stored"),
    ("failure", 0, "error", ""),
])
@pytest.mark.asyncio
async def test_admitted_import_preserves_typed_dedup_outcomes(tmp_path, store, outcome, count, status, note):
    path = tmp_path / "doc.md"
    path.write_text("typed store result", encoding="utf-8")
    store.ingest.return_value = IngestOutcome(count, outcome, "existing")
    importer = BulkImporter(store, admitted_roots=[tmp_path])
    result = await importer.import_file(str(path))
    assert result.status == status
    assert result.outcome == outcome
    assert result.note.startswith(note)
    assert bool(result.error) == (outcome == "failure")
