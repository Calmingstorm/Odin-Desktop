"""Exercise retained CRUD/read boundaries with inert stores and private paths."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.desktop.learned_context import LearnedContextService
from src.desktop.management import MethodError
from src.desktop.trajectories import TrajectoriesService


def reflector():
    return SimpleNamespace(get_all_entries=Mock(return_value=[{"key": "fixture"}]),
        get_metadata=Mock(return_value={"enabled": False}),
        delete_entry_async=AsyncMock(return_value=True),
        update_entry_async=AsyncMock(return_value={"key": "fixture", "content": "new"}))


@pytest.mark.asyncio
async def test_learned_crud_uses_shared_runtime_reflector_and_async_write_seams(tmp_path):
    current = reflector()
    service = LearnedContextService(SimpleNamespace(data_dir=tmp_path),
                                    reflector_getter=lambda: current)
    assert await service.handle("learned.list", {}) == {
        "entries": [{"key": "fixture"}], "enabled": False}
    assert await service.handle("learned.update", {"key": "fixture", "content": "new"}) == {
        "key": "fixture", "content": "new"}
    current.update_entry_async.assert_awaited_once_with("fixture", content="new", category=None)
    assert await service.handle("learned.delete", {"key": "fixture"}) == {
        "status": "deleted", "key": "fixture"}
    current.delete_entry_async.assert_awaited_once_with("fixture")
    replacement = reflector()
    current = replacement
    assert service.reflector is replacement


def test_standalone_reflector_is_cached_and_generation_disabled(tmp_path, monkeypatch):
    instance = reflector()
    constructor = Mock(return_value=instance)
    monkeypatch.setattr("src.learning.reflector.ConversationReflector", constructor)
    learning = SimpleNamespace(max_entries=20, consolidation_target=10, injection_token_budget=500)
    service = LearnedContextService(SimpleNamespace(data_dir=tmp_path),
        reflector_getter=lambda: None, learning_getter=lambda: learning)
    assert service.reflector is instance and service.reflector is instance
    constructor.assert_called_once_with(str(tmp_path / "learned.json"), enabled=False,
        max_entries=20, consolidation_target=10, injection_token_budget=500)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params", [
    ("unknown", {}), ("learned.list", []), ("learned.delete", {"key": ""}),
    ("learned.update", {"key": 1}), ("learned.update", {"key": "fixture"}),
    ("learned.update", {"key": "fixture", "content": 1}),
    ("learned.update", {"key": "fixture", "category": None}),
])
async def test_learned_validation_does_not_write(method, params):
    store = reflector()
    service = LearnedContextService(None, reflector=store)
    with pytest.raises(MethodError):
        await service.handle(method, params)
    store.delete_entry_async.assert_not_awaited()
    store.update_entry_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["learned.delete", "learned.update"])
async def test_missing_learned_entry_is_not_success(method):
    store = reflector()
    store.delete_entry_async.return_value = False
    store.update_entry_async.return_value = None
    with pytest.raises(MethodError, match="entry not found"):
        await LearnedContextService(None, reflector=store).handle(
            method, {"key": "missing", "content": "new"})


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["learned.list", "learned.update"])
async def test_learned_failure_scrubs_sensitive_exception(method):
    store = reflector()
    store.get_all_entries.side_effect = RuntimeError("fixture sensitive exception")
    store.update_entry_async.side_effect = RuntimeError("fixture sensitive exception")
    with pytest.raises(MethodError, match="learned-context operation failed") as error:
        await LearnedContextService(None, reflector=store).handle(
            method, {"key": "fixture", "content": "new"})
    assert "sensitive" not in str(error.value)


def saver(tmp_path):
    return SimpleNamespace(directory=tmp_path, count=3,
        list_files=AsyncMock(return_value=["trace.jsonl"]),
        find_by_message_id=AsyncMock(return_value={"id": "message"}),
        search=AsyncMock(return_value=[{"id": "match"}]),
        read_file=AsyncMock(return_value=[{"id": "entry"}]))


def test_trajectory_reader_rebinds_without_creating_directories(tmp_path):
    directory = tmp_path / "absent"
    runtime = saver(directory)
    service = TrajectoriesService(get_directory=lambda: directory, saver_getter=lambda: runtime)
    assert service.saver is runtime
    runtime.directory = tmp_path / "old"
    reader = service.saver
    assert reader.directory == directory and reader.count == 0
    assert service.saver is reader and not directory.exists()
    directory = tmp_path / "replacement"
    assert service.saver is not reader
    assert service.saver.directory == directory and not directory.exists()
    assert TrajectoriesService().saver is None
    profile_service = TrajectoriesService(SimpleNamespace(data_dir=tmp_path))
    assert profile_service.saver.directory == tmp_path / "trajectories"


@pytest.mark.asyncio
async def test_trajectory_read_routes_bound_limits_and_filters(tmp_path):
    store = saver(tmp_path)
    service = TrajectoriesService(saver=store)
    # L12 (1.0.5): count is the number of files listed. The writer's own counter (3 here)
    # counts its writes, and the profile reader never writes, so it always showed 0.
    assert await service.handle("trajectories.list", {}) == {"files": ["trace.jsonl"], "count": 1}
    assert await service.handle("trajectories.message", {"message_id": "message"}) == {
        "entry": {"id": "message"}}
    store.find_by_message_id.assert_awaited_once_with("message")
    assert await service.handle("trajectories.search", {
        "limit": 99999, "channel_id": "channel", "errors_only": "TRUE"}) == {
            "results": [{"id": "match"}], "count": 1}
    store.search.assert_awaited_once_with(channel_id="channel", user_id=None,
        tool_name=None, errors_only=True, limit=500)
    assert await service.handle("trajectories.read", {
        "filename": "trace.jsonl", "limit": "invalid", "user_id": "user", "errors_only": 1,
        "channel_id": ""}) == {"entries": [{"id": "entry"}], "count": 1}
    store.read_file.assert_awaited_once_with("trace.jsonl", limit=100,
                                            user_id="user", errors_only=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["", "../trace.jsonl", "nested/trace.jsonl",
                                       "nested\\trace.jsonl", "trace.txt", 1])
async def test_trajectory_selected_file_rejects_unsafe_names(tmp_path, filename):
    store = saver(tmp_path)
    with pytest.raises(MethodError):
        await TrajectoriesService(saver=store).handle("trajectories.read", {"filename": filename})
    store.read_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_trajectory_selected_file_cannot_escape_via_symlink(tmp_path):
    directory = tmp_path / "traces"
    directory.mkdir()
    (directory / "trace.jsonl").symlink_to(tmp_path / "outside.jsonl")
    store = saver(directory)
    with pytest.raises(MethodError, match="invalid filename"):
        await TrajectoriesService(saver=store).handle(
            "trajectories.read", {"filename": "trace.jsonl"})
    store.read_file.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params", [
    ("unknown", {}), ("trajectories.list", []),
    ("trajectories.message", {"message_id": 1}),
    ("trajectories.search", {"tool_name": False}),
])
async def test_trajectory_validation_fails_before_read(tmp_path, method, params):
    store = saver(tmp_path)
    with pytest.raises(MethodError):
        await TrajectoriesService(saver=store).handle(method, params)
    store.list_files.assert_not_awaited()
    store.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_trajectory_missing_capability_entry_and_scrubbed_store_failure(tmp_path):
    with pytest.raises(MethodError, match="trajectory saving not available"):
        await TrajectoriesService().handle("trajectories.list", {})
    store = saver(tmp_path)
    store.find_by_message_id.return_value = None
    service = TrajectoriesService(saver=store)
    with pytest.raises(MethodError, match="trajectory not found"):
        await service.handle("trajectories.message", {"message_id": "missing"})
    store.list_files.side_effect = OSError("fixture sensitive path")
    with pytest.raises(MethodError, match="Trajectory read is unavailable") as error:
        await service.handle("trajectories.list", {})
    assert "sensitive" not in str(error.value)
