"""State commands exercise the same primitives and locks as actual tools."""
import asyncio
import json

import pytest

from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.state import METHODS, READ_METHODS, StateService
from src.tools.executor import ToolExecutor


@pytest.fixture
def state(tmp_path):
    paths = ProfilePaths.from_xdg("state", home=tmp_path, environ={})
    executor = ToolExecutor(memory_path=str(paths.data_dir / "memory.json"), profile_paths=paths)
    return StateService(paths, "owner", memory=executor, lists=executor), executor


@pytest.mark.asyncio
async def test_tool_and_management_share_memory_and_prompt(state):
    service, executor = state
    assert service.memory is executor
    assert service.lists is executor.state_tools
    await executor.state_tools._handle_memory_manage(
        {"action": "save", "key": "tool", "value": "tool value"}, user_id="owner")
    assert await service.handle("memory.get", {"scope": "user_owner", "key": "tool"}) == {
        "scope": "user_owner", "key": "tool", "value": "tool value"}
    assert await service.handle("memory.set", {"scope": "global", "key": "count", "value": 42}) == {
        "status": "saved", "scope": "global", "key": "count"}
    assert executor._load_memory_for_user("owner") == {"tool": "tool value", "count": "42"}
    assert await service.handle("memory.list", {}) == {
        "global": {"keys": ["count"], "count": 1},
        "user_owner": {"keys": ["tool"], "count": 1}}
    assert await service.handle("memory.get", {"scope": "global"}) == {
        "scope": "global", "entries": {"count": "42"}}
    reopened = StateService(service.paths, "owner")
    assert (await reopened.handle("memory.get", {"scope": "global"}))["entries"] == {"count": "42"}


@pytest.mark.asyncio
async def test_fresh_authorized_scopes_are_discoverable_without_creation(state, monkeypatch):
    service, executor = state
    path = service.paths.data_dir / "memory.json"
    assert not path.exists()

    def unexpected_save(data):
        pytest.fail("Reading absent scopes must not persist memory")

    monkeypatch.setattr(executor, "_save_all_memory", unexpected_save)
    assert await service.handle("memory.list", {"owner_id": "other"}) == {
        "global": {"keys": [], "count": 0},
        "user_owner": {"keys": [], "count": 0},
    }
    for scope in ("global", "user_owner"):
        assert await service.handle("memory.get", {"scope": scope}) == {
            "scope": scope, "entries": {},
        }
    with pytest.raises(MethodError) as error:
        await service.handle("memory.get", {"scope": "user_other"})
    assert error.value.code == "forbidden"
    assert not path.exists()


@pytest.mark.asyncio
async def test_absent_personal_scope_reads_leave_existing_memory_unchanged(state):
    service, executor = state
    executor._save_all_memory({"global": {"existing": "value"}})
    path = service.paths.data_dir / "memory.json"
    before = path.read_bytes()
    assert await service.handle("memory.list", {}) == {
        "global": {"keys": ["existing"], "count": 1},
        "user_owner": {"keys": [], "count": 0},
    }
    assert await service.handle("memory.get", {"scope": "user_owner"}) == {
        "scope": "user_owner", "entries": {},
    }
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_profile_writes_leave_alongside_state_untouched(tmp_path):
    sentinel = tmp_path / "alongside-memory.json"
    sentinel.write_text('{"global":{"other":"untouched"}}')
    paths = ProfilePaths.from_xdg("new", home=tmp_path, environ={})
    service = StateService(paths, "owner")
    await service.handle("memory.set", {"scope": "global", "key": "new", "value": "fresh"})
    assert sentinel.read_text() == '{"global":{"other":"untouched"}}'
    assert service.memory._load_all_memory() == {"global": {"new": "fresh"}}


@pytest.mark.asyncio
async def test_scope_is_owner_bound_not_params(state):
    service, executor = state
    executor._save_all_memory({"global": {}, "user_owner": {}, "user_other": {"hidden": "private"}})
    assert "user_other" not in await service.handle("memory.list", {"owner_id": "other"})
    for method in ("memory.get", "memory.set", "memory.delete"):
        with pytest.raises(MethodError) as error:
            await service.handle(method, {"scope": "user_other", "key": "hidden", "value": "x"})
        assert error.value.code == "forbidden"
    assert executor._load_all_memory()["user_other"] == {"hidden": "private"}


@pytest.mark.asyncio
async def test_bulk_validation_atomic_and_duplicate_count(state):
    service, executor = state
    await service.handle("memory.set", {"scope": "global", "key": "one", "value": ""})
    for bad in ({"scope": "user_other", "key": "hidden"}, None, {"scope": "global", "key": 3}):
        with pytest.raises(MethodError):
            await service.handle("memory.bulk_delete", {
                "entries": [{"scope": "global", "key": "one"}, bad]})
        assert executor._load_all_memory()["global"] == {"one": ""}
    assert await service.handle("memory.bulk_delete", {"entries": [
        {"scope": "global", "key": "one"}, {"scope": "global", "key": "one"},
        {"scope": "global", "key": "absent"}]}) == {"status": "deleted", "count": 1}


@pytest.mark.asyncio
async def test_list_tool_write_management_read_delete(state):
    service, executor = state
    await executor.state_tools._handle_manage_list({
        "action": "add", "list_name": "Shopping", "items": ["paper"], "owner": "personal"},
        user_id="owner")
    result = await service.handle("lists.get", {"name": " Shopping "})
    assert result["name"] == "shopping"
    assert result["items"][0]["name"] == "paper"
    listed = await service.handle("lists.list", {})
    assert listed == {"items": [{"name": "shopping", "count": 1,
                                 "updated_at": result["items"][0]["added_at"]}]}
    assert await service.handle("lists.delete", {"name": "shopping"}) == {
        "status": "deleted", "name": "shopping"}
    assert executor.state_tools._load_lists_for_write() == {}


@pytest.mark.asyncio
async def test_concurrent_memory_writes_keep_all_values(state):
    service, executor = state
    async def tool_write(index):
        return await executor.state_tools._handle_memory_manage(
            {"action": "save", "scope": "global", "key": f"t{index}", "value": "value"},
            user_id="owner")
    await asyncio.gather(*(service.handle("memory.set", {
        "scope": "global", "key": f"m{i}", "value": "value"}) for i in range(20)),
        *(tool_write(i) for i in range(20)))
    assert len(executor._load_all_memory()["global"]) == 40


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["memory", "lists"])
async def test_corrupt_store_never_overwritten(state, kind):
    service, _ = state
    path = service.paths.data_dir / f"{kind}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json")
    for method, params in ((f"{kind}.list", {}),
                           ("memory.set", {"scope": "global", "key": "x", "value": "y"})
                           if kind == "memory" else ("lists.delete", {"name": "x"})):
        with pytest.raises(MethodError):
            await service.handle(method, params)
        assert path.read_text() == "not valid json"


@pytest.mark.asyncio
async def test_scrubs_read_values_and_storage_failure(state, monkeypatch):
    service, executor = state
    secret = "password=example-sensitive-value"
    await service.handle("memory.set", {"scope": "global", "key": "note", "value": secret})
    assert secret not in json.dumps(await service.handle("memory.get", {"scope": "global"}))
    def fail(data):
        raise OSError(secret)
    monkeypatch.setattr(executor, "_save_all_memory", fail)
    with pytest.raises(MethodError) as error:
        await service.handle("memory.set", {"scope": "global", "key": "new", "value": "x"})
    assert secret not in str(error.value)
    assert error.value.disposition == "outcome_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params", [
    ("memory.set", {"scope": "global", "key": "x"}),
    ("memory.get", {"scope": "global", "key": "absent"}),
    ("memory.delete", {"scope": "global", "key": "absent"}),
    ("lists.get", {"name": "absent"}), ("lists.delete", {"name": "absent"}),
    ("memory.bulk_delete", {"entries": []}), ("memory.get", {}),
    ("invalid", {}), ("memory.list", []),
])
async def test_invalid_and_missing_are_errors(state, method, params):
    with pytest.raises(MethodError):
        await state[0].handle(method, params)


def test_method_classification_and_lazy_profile(tmp_path):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    service = StateService(paths, "owner")
    assert service._memory is None and service._lists is None
    assert not paths.data_dir.exists()
    assert READ_METHODS < METHODS
