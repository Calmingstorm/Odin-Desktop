"""Named Knowledge/learning methods against isolated retained stores."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.desktop.knowledge import METHODS, READ_METHODS, KnowledgeService
from src.desktop.learned_context import LearnedContextService
from src.desktop.management import MethodError
from src.knowledge.store import KnowledgeStore
from src.learning.reflector import ConversationReflector


@pytest.fixture
def knowledge(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    service = KnowledgeService(SimpleNamespace(data_dir=tmp_path), store=store)
    yield service
    store.close()


async def test_chunks_versions_diff_duplicate_merge_real_store(knowledge):
    store = knowledge.store
    await store.ingest("first version body", "a.md", dedup=False)
    await store.ingest("second version body", "a.md", dedup=False)
    await store.ingest("second version body", "copy.md", dedup=False)
    chunks = await knowledge.handle("knowledge.chunks", {"source": "a.md"})
    assert len(chunks) >= 1
    version = await knowledge.handle("knowledge.version", {"source": "a.md", "version": 1})
    assert version["content"] == "first version body"
    diff = await knowledge.handle("knowledge.diff", {"source": "a.md", "v1": 1, "v2": 2})
    assert diff["from_version"] == 1 and diff["to_version"] == 2
    assert "first version body" in diff["diff"] and "second version body" in diff["diff"]
    duplicates = await knowledge.handle("knowledge.duplicates", {})
    assert duplicates["exact"]
    result = await knowledge.handle("knowledge.merge", {
        "keep_source": " a.md ", "remove_source": " copy.md "})
    assert result["kept"] == "a.md" and result["chunks_removed"] >= 1
    assert not store.get_source_chunks("copy.md")
    assert "knowledge.merge" not in READ_METHODS
    assert {"knowledge.chunks", "knowledge.duplicates",
            "knowledge.version", "knowledge.diff"} <= READ_METHODS
    assert READ_METHODS <= METHODS


@pytest.mark.parametrize("method,params,message", [
    ("knowledge.chunks", {"source": "missing"}, "source not found or empty"),
    ("knowledge.version", {"source": "missing", "version": 1}, "version not found"),
    ("knowledge.diff", {"source": "missing", "v1": 1, "v2": 2}, "one or both versions not found"),
    ("knowledge.merge", {"keep_source": "missing", "remove_source": "also"},
     "keep_source not found or nothing to merge"),
])
async def test_missing_results_are_truthful(knowledge, method, params, message):
    with pytest.raises(MethodError) as failure:
        await knowledge.handle(method, params)
    assert failure.value.code == "not_found" and failure.value.message == message


@pytest.mark.parametrize("threshold,expected", [("oops", .5), (2, 2), (-1, -1)])
async def test_duplicate_threshold_fallback_without_extra_bounds(
        knowledge, threshold, expected, monkeypatch):
    received = []
    monkeypatch.setattr(knowledge.store, "find_near_duplicates",
                        lambda value: received.append(value) or [])
    assert await knowledge.handle("knowledge.duplicates", {"threshold": threshold}) == {
        "exact": [], "near": []}
    assert received == [expected]


@pytest.mark.parametrize("version", [True, -1, "1", None])
async def test_version_typed_boundary(knowledge, version):
    with pytest.raises(MethodError) as failure:
        await knowledge.handle("knowledge.version", {"source": "a", "version": version})
    assert failure.value.code == "bad_request"


async def test_disabled_learning_real_retained_store_and_reopen(tmp_path):
    path = tmp_path / "learned.json"
    original = json.dumps({"version": 2, "last_reflection": None, "entries": [
        {"key": "a", "content": "Old lesson", "category": "operational"},
        {"key": "b", "content": "Remove lesson", "category": "correction"},
    ]})
    path.write_text(original)
    reflector = ConversationReflector(str(path), enabled=False)
    service = LearnedContextService(SimpleNamespace(data_dir=tmp_path), reflector=reflector)
    assert (await service.handle("learned.list", {}))["count"] == 2
    assert path.read_text() == original
    assert reflector.get_prompt_section() == ""
    for params in ({"key": "a"}, {"key": "a", "content": None},
                   {"key": "a", "category": 3}):
        with pytest.raises(MethodError):
            await service.handle("learned.update", params)
    assert path.read_text() == original
    updated = await service.handle("learned.update", {
        "key": "a", "content": "", "category": "preference"})
    assert updated["content"] == "" and updated["category"] == "preference"
    assert await service.handle("learned.delete", {"key": "b"}) == {
        "status": "deleted", "key": "b"}
    reopened = LearnedContextService(SimpleNamespace(data_dir=tmp_path))
    assert (await reopened.handle("learned.list", {}))["count"] == 1
    assert reopened.reflector.get_prompt_section() == ""


async def test_runtime_reflector_getter_prioritizes_actual_lock_and_store(tmp_path):
    current = [None]
    service = LearnedContextService(SimpleNamespace(data_dir=tmp_path),
                                    reflector_getter=lambda: current[0])
    fallback = service.reflector
    current[0] = ConversationReflector(str(tmp_path / "runtime-learned.json"), enabled=False)
    assert service.reflector is current[0] and service.reflector is not fallback
    assert (await service.handle("learned.list", {}))["count"] == 0


async def test_merge_removes_retained_full_document_snapshot(knowledge):
    await knowledge.store.ingest("keep body", "keep", dedup=False)
    await knowledge.store.ingest("remove body", "remove", dedup=False)
    result = await knowledge.handle("knowledge.merge", {
        "keep_source": "keep", "remove_source": "remove"})
    assert result["chunks_removed"] >= 1
    assert knowledge.store.get_source_snapshot("remove") is None


async def test_new_method_outputs_scrubbed_without_changing_retained_data(knowledge, tmp_path):
    from src.llm.secret_scrubber import scrub_output_secrets

    content = "credential sk-" + "A" * 48
    assert scrub_output_secrets(content) != content
    await knowledge.store.ingest(content, "secret.md", dedup=False)
    chunks = await knowledge.handle("knowledge.chunks", {"source": "secret.md"})
    version = await knowledge.handle("knowledge.version", {"source": "secret.md", "version": 1})
    assert content not in json.dumps(chunks)
    assert version["content"] == scrub_output_secrets(content)
    assert knowledge.store.get_source_snapshot("secret.md") == content
    path = tmp_path / "learned.json"
    path.write_text(json.dumps({"version": 2, "last_reflection": None, "entries": [
        {"key": "s", "content": content, "category": "fact"},
    ]}))
    service = LearnedContextService(SimpleNamespace(data_dir=tmp_path))
    listing = await service.handle("learned.list", {})
    assert content not in json.dumps(listing)
    assert service.reflector.get_all_entries()[0]["content"] == content


async def test_learned_mutation_failure_is_unknown_not_invented_success(tmp_path, monkeypatch):
    reflector = ConversationReflector(str(tmp_path / "learned.json"), enabled=False)
    service = LearnedContextService(None, reflector=reflector)

    async def failed(key):
        raise RuntimeError("private backend detail")

    monkeypatch.setattr(reflector, "delete_entry_async", failed)
    with pytest.raises(MethodError) as error:
        await service.handle("learned.delete", {"key": "a"})
    assert error.value.code == "internal_error"
    assert error.value.disposition == "outcome_unknown"
    assert "private backend detail" not in error.value.message


def test_whole_adapter_static_association_and_exact_reversal():
    from pathlib import Path

    from scripts.maintenance.phase2_suites import _full_adapter
    from tests.desktop_adapters.step5_knowledge_corpus import SUITES, transformed_source

    root = Path(__file__).resolve().parents[1]
    for name, digest in SUITES.items():
        assert _full_adapter(root, "tests/test_desktop_step5_knowledge_corpus.py",
                             f"tests/{name}.py", digest)
        assert transformed_source(name)
