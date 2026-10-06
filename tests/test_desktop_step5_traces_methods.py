"""Real named reads and keyring-only refresh settlement, without live state."""
import ast
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.management import MethodError
from src.desktop.trajectories import TrajectoriesService
from src.llm import codex_auth as ca
from src.trajectories.saver import TrajectorySaver
from tests.desktop_adapters import step5_traces
from tests.desktop_adapters.step5_traces import EVIDENCE, adapted_tree


class Secrets:
    def __init__(self, rows):
        self.value = json.dumps(rows)

    def get(self, name):
        assert name == "codex_accounts"
        return self.value

    def set(self, name, value):
        assert name == "codex_accounts"
        self.value = value
        return True


def _account(account="A"):
    return {"account_id": account, "access_token": f"synthetic-{account}",
            "refresh_token": "synthetic-refresh", "expires_at": 9999999999,
            "email": "owner@example.invalid"}


def _service(rows):
    secrets = Secrets(rows)
    return CodexAccountsService(SimpleNamespace(secrets=secrets)), secrets


class Transport:
    def __init__(self):
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.calls = 0

    def session(self, **kwargs):
        owner = self

        class Response:
            status = 200

            async def __aenter__(self):
                owner.calls += 1
                owner.entered.set()
                await owner.release.wait()
                return self

            async def __aexit__(self, *args):
                pass

            async def read(self):
                return json.dumps({"access_token": "synthetic-next-token",
                                   "refresh_token": "synthetic-next-refresh",
                                   "expires_in": 3600}).encode()

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, **kwargs):
                assert url == ca.TOKEN_URL
                assert kwargs["data"]["grant_type"] == "refresh_token"
                return Response()
        return Session()


async def test_named_selected_filters_limit_utf8_and_scrub_without_truncation(tmp_path):
    saver = TrajectorySaver(str(tmp_path))
    match = {"message_id": "selected", "channel_id": "c", "user_id": "u",
             "tools_used": ["wanted"], "is_error": True,
             "final_response": "会話" * 6000, "access_token": "synthetic-private"}
    unrelated = {"message_id": "unrelated", "tools_used": ["other"]}
    (tmp_path / "today.jsonl").write_bytes((json.dumps(match, ensure_ascii=False)
        + "\ninvalid\n" + json.dumps(unrelated) + "\n").encode())
    service = TrajectoriesService(saver=saver)
    filters = {"channel_id": "c", "user_id": "u", "tool_name": "wanted", "errors_only": True,
               "limit": 1}
    result = await service.handle("trajectories.read", {"filename": "today.jsonl", **filters})
    assert result["count"] == 1
    assert result["entries"][0]["message_id"] == "selected"
    assert result["entries"][0]["final_response"] == match["final_response"]
    assert "synthetic-private" not in json.dumps(result)
    assert (await service.handle("trajectories.search", filters))["results"] == result["entries"]
    selected = await service.handle("trajectories.message", {"message_id": "selected"})
    assert selected["entry"] == result["entries"][0]
    assert await service.handle("trajectories.list", {}) == {"files": ["today.jsonl"], "count": 0}


@pytest.mark.parametrize("name", ["not.txt", "bad..jsonl", "a/b.jsonl", "a\\b.jsonl"])
async def test_named_path_guards(tmp_path, name):
    service = TrajectoriesService(saver=TrajectorySaver(str(tmp_path)))
    with pytest.raises(MethodError, match="invalid filename"):
        await service.handle("trajectories.read", {"filename": name})


async def test_named_symlink_escape_read_only_construction_and_relocation(tmp_path):
    root, outside = tmp_path / "profile", tmp_path / "outside.jsonl"
    target = [root / "trajectories"]
    service = TrajectoriesService(get_directory=lambda: target[0])
    assert not root.exists()
    assert await service.handle("trajectories.list", {}) == {"files": [], "count": 0}
    assert not root.exists()
    service.saver.directory.mkdir(parents=True)
    outside.write_text('{"message_id":"private"}\n')
    (service.saver.directory / "escape.jsonl").symlink_to(outside)
    with pytest.raises(MethodError, match="invalid filename"):
        await service.handle("trajectories.read", {"filename": "escape.jsonl"})
    target[0] = tmp_path / "relocated"
    assert await service.handle("trajectories.list", {}) == {"files": [], "count": 0}
    assert service.saver.directory == target[0]
    assert not target[0].exists()


async def test_named_limits_and_missing_capability(tmp_path):
    saver = TrajectorySaver(str(tmp_path))
    saver.search = AsyncMock(return_value=[])
    saver.read_file = AsyncMock(return_value=[])
    service = TrajectoriesService(saver=saver)
    for value, expected in [("bad", 50), (None, 50), (0, 1), (1000, 500)]:
        await service.handle("trajectories.search", {"limit": value})
        assert saver.search.call_args.kwargs["limit"] == expected
    for value, expected in [("bad", 100), (None, 100), (0, 1), (1000, 500)]:
        await service.handle("trajectories.read", {"filename": "today.jsonl", "limit": value})
        assert saver.read_file.call_args.kwargs["limit"] == expected
    with pytest.raises(MethodError) as failure:
        await TrajectoriesService().handle("trajectories.list", {})
    assert failure.value.code == "capability_unavailable"
    with pytest.raises(MethodError) as missing:
        await service.handle("trajectories.message", {"message_id": "missing"})
    assert missing.value.code == "not_found"


async def test_keyring_named_admin_and_serving_share_single_use_refresh(tmp_path, monkeypatch):
    service, secrets = _service([_account()])
    transport = Transport()
    monkeypatch.setattr(ca.aiohttp, "ClientSession", transport.session)
    pool = service.pool
    original = pool.force_refresh
    admitted = asyncio.Event()

    async def observed(index, stale_token=None):
        admitted.set()
        return await original(index, stale_token)

    serving = asyncio.create_task(pool.force_refresh(0, "synthetic-A"))
    await transport.entered.wait()
    monkeypatch.setattr(pool, "force_refresh", observed)
    admin = asyncio.create_task(service.handle("codex.accounts.refresh", {"index": "0"}))
    await admitted.wait()
    transport.release.set()
    assert await serving
    assert await admin == {
        "status": "refreshed", "email": "owner@example.invalid", "expired": False,
    }
    assert transport.calls == 1
    assert json.loads(secrets.value)[0]["refresh_token"] == "synthetic-next-refresh"
    assert list(tmp_path.iterdir()) == []
    assert "codex.accounts.refresh" in service.METHODS
    assert "codex.accounts.refresh" not in service.READ_METHODS


async def test_keyring_cancelled_admin_settles_rotation(monkeypatch):
    service, secrets = _service([_account()])
    transport = Transport()
    monkeypatch.setattr(ca.aiohttp, "ClientSession", transport.session)
    admin = asyncio.create_task(service.handle("codex.accounts.refresh", {"index": 0}))
    await transport.entered.wait()
    admin.cancel()
    await asyncio.sleep(0)
    assert not admin.done()
    transport.release.set()
    with pytest.raises(asyncio.CancelledError):
        await admin
    assert json.loads(secrets.value)[0]["refresh_token"] == "synthetic-next-refresh"
    assert service.pool._accounts[0]._load()["refresh_token"] == "synthetic-next-refresh"


@pytest.mark.parametrize("mutation", ["remove", "reorder", "reauth"])
async def test_keyring_retired_refresh_cannot_publish(monkeypatch, mutation):
    service, secrets = _service([_account(), _account("B")])
    transport = Transport()
    monkeypatch.setattr(ca.aiohttp, "ClientSession", transport.session)
    admin = asyncio.create_task(service.handle("codex.accounts.refresh", {"index": 0}))
    await transport.entered.wait()
    if mutation == "remove":
        await service.handle("codex.accounts.remove", {"index": 0})
    else:
        rows = [_account("B"), _account()] if mutation == "reorder" else [
            {**_account(), "access_token": "synthetic-new-auth"}, _account("B")]
        service.vault.write(rows)
        await service.pool.reload_async()
    before = secrets.value
    transport.release.set()
    with pytest.raises(MethodError, match="credential refresh failed"):
        await admin
    assert secrets.value == before


async def test_keyring_refresh_failed_storage_keeps_old_credentials(monkeypatch):
    service, secrets = _service([_account()])
    transport = Transport()
    monkeypatch.setattr(ca.aiohttp, "ClientSession", transport.session)
    original = secrets.value
    secrets.set = lambda *args: False
    transport.release.set()
    with pytest.raises(MethodError) as failure:
        await service.handle("codex.accounts.refresh", {"index": 0})
    assert failure.value.disposition == "outcome_unknown"
    assert secrets.value == original
    assert service.pool._accounts[0]._load()["access_token"] == "synthetic-A"


async def test_named_refresh_validation_and_secret_failure(monkeypatch):
    service, _ = _service([])
    with pytest.raises(MethodError) as failure:
        await service.handle("codex.accounts.refresh", {"index": 0})
    assert failure.value.code == "capability_unavailable"
    service, _ = _service([_account()])
    for index in (None, "bad", -1, 1):
        with pytest.raises(MethodError) as failure:
            await service.handle("codex.accounts.refresh", {"index": index})
        assert failure.value.code == "bad_request"
    monkeypatch.setattr(service.pool, "force_refresh", AsyncMock(
        side_effect=RuntimeError("Bearer synthetic-private")))
    with pytest.raises(MethodError) as failure:
        await service.handle("codex.accounts.refresh", {"index": 0})
    assert "synthetic-private" not in str(failure.value)


async def test_refresh_requires_configured_serving_pool_when_gateway_composed():
    service, _ = _service([_account()])
    service.providers = SimpleNamespace(codex_client=None)
    with pytest.raises(MethodError) as failure:
        await service.handle("codex.accounts.refresh", {"index": 0})
    assert failure.value.code == "capability_unavailable"
    assert service._pool is None


def test_whole_frozen_source_assertions_decorators_and_parameters_preserved():
    for stem in ("test_trajectories", "test_webui_selected_trace_filters",
                 "test_codex_account_mutation_regressions"):
        adapted_tree(stem)
        evidence = EVIDENCE[f"tests/{stem}.py"]
        assert evidence["whole_suite"] is True
        assert evidence["full_assert_parameter_ast_preserved_before_projection"] is True


async def test_keyring_unchanged_reload_and_label_keep_refresh_owner(monkeypatch):
    service, secrets = _service([_account()])
    transport = Transport()
    monkeypatch.setattr(ca.aiohttp, "ClientSession", transport.session)
    auth = service.pool._accounts[0]
    admin = asyncio.create_task(service.handle("codex.accounts.refresh", {"index": 0}))
    await transport.entered.wait()
    await service.pool.reload_async()
    assert service.pool._accounts[0] is auth
    await service.handle("codex.accounts.label", {"index": 0, "label": "owner label"})
    transport.release.set()
    assert (await admin)["status"] == "refreshed"
    assert json.loads(secrets.value)[0]["label"] == "owner label"
    assert transport.calls == 1


async def test_named_trajectory_errors_scrub_backend_secrets(tmp_path):
    saver = TrajectorySaver(str(tmp_path))
    saver.list_files = AsyncMock(side_effect=RuntimeError("Bearer synthetic-private"))
    service = TrajectoriesService(saver=saver)
    with pytest.raises(MethodError) as failure:
        await service.handle("trajectories.list", {})
    assert failure.value.code == "unavailable"
    assert "synthetic-private" not in str(failure.value)
    for method, params, code in [("trajectories.other", {}, "method_not_found"),
                                 ("trajectories.list", [], "bad_request"),
                                 ("trajectories.read", {"filename": 1}, "bad_request")]:
        with pytest.raises(MethodError) as failure:
            await service.handle(method, params)
        assert failure.value.code == code


def _frozen_file_setup(tmp_path, rows, monkeypatch):
    """Execute the unchanged frozen setup with its admitted constructor seam."""
    services = []

    def constructed(*args, **kwargs):
        service = CodexAccountsService(*args, **kwargs)
        services.append(service)
        return service

    monkeypatch.setattr(step5_traces, "CodexAccountsService", constructed)
    tree = adapted_tree("test_codex_account_mutation_regressions")
    namespace = {"_FileFixturePool": step5_traces._FileFixturePool}
    exec(compile(ast.fix_missing_locations(tree),
                 "tests/test_codex_account_mutation_regressions.py", "exec"), namespace)
    result = namespace["setup"](tmp_path, rows)
    assert len(services) == 1
    return (*result, services[0])


@pytest.mark.parametrize("single_format", [False, True])
async def test_file_fixture_keeps_actual_pool_service_locks_and_reload_owner(
    tmp_path, monkeypatch, single_format,
):
    rows = _account() if single_format else [_account()]
    path, pool, bot, _, _, service = _frozen_file_setup(tmp_path, rows, monkeypatch)
    assert type(service) is CodexAccountsService
    assert isinstance(pool, ca.CodexAuthPool)
    assert await service.get_pool() is pool is bot.llm_gateway.codex_client.auth
    assert type(pool).reload_async is ca.CodexAuthPool.reload_async
    assert type(pool).force_refresh is ca.CodexAuthPool.force_refresh
    auth = pool._accounts[0]
    lock = auth._refresh_lock
    assert type(auth) is ca.CodexAuth
    assert auth.expected is pool._loaded_records[0]
    generation = pool.generation
    async with pool._pool_lock:
        reloading = asyncio.create_task(pool.reload_async())
        await asyncio.sleep(0)
        assert not reloading.done()
        assert pool.generation == generation
    assert await reloading == 1
    assert pool.generation == generation + 1
    assert pool._accounts[0] is auth
    assert auth._refresh_lock is lock
    assert auth.expected is pool._loaded_records[0]
    assert auth.save_guard()
    assert json.loads(path.read_text()) == rows
    with pytest.raises(RuntimeError, match="requires the pool lock"):
        pool._reload_accounts(rows)


@pytest.mark.parametrize("operation", ["delete", "reauth"])
async def test_file_fixture_named_mutation_reloads_durable_canonical_under_lock(
    tmp_path, monkeypatch, operation,
):
    path, pool, bot, app, _, service = _frozen_file_setup(
        tmp_path, [_account(), None, _account("B")], monkeypatch)
    old = pool._accounts[1]
    seen = []
    original_reload = pool._reload_accounts

    def observed_reload(raw=None):
        assert pool._pool_lock.locked()
        assert json.loads(path.read_text()) == raw
        seen.append(raw)
        original_reload(raw)

    monkeypatch.setattr(pool, "_reload_accounts", observed_reload)
    async with step5_traces.TestClient(step5_traces.TestServer(app)) as client:
        if operation == "delete":
            response = await client.delete("/api/codex/account/1")
        else:
            monkeypatch.setattr(ca.CodexAuth, "poll_device_auth", AsyncMock(
                return_value={**_account("B"), "access_token": "synthetic-new-B"}))
            response = await client.post("/api/codex/device-poll", json={
                "device_auth_id": "fixture", "user_code": "fixture", "save_index": 1})
    assert response.status == 200
    assert (await response.json())["status"] == (
        "deleted" if operation == "delete" else "authenticated")
    assert len(seen) == 1
    assert await service.get_pool() is pool
    assert pool._canonical_indices == ([0] if operation == "delete" else [0, 2])
    assert pool._accounts[0].get_account_id() == "A"
    assert not old.save_guard()
    if operation == "reauth":
        replacement = pool._accounts[1]
        assert replacement is not old
        assert replacement.expected is pool._loaded_records[2]
        assert replacement._load()["access_token"] == "synthetic-new-B"
        assert json.loads((tmp_path / "codex_auth_2.json").read_text()) == seen[0][2]
        assert replacement.save_guard()
    bot.llm_gateway.reload_codex.assert_awaited_once_with()
