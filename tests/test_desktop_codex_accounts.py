"""No login, network or real keyring. Exercise retained provider composition."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from src.desktop.codex_accounts import (
    METHODS,
    READ_METHODS,
    CodexAccountsService,
    CodexDeviceClient,
)
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore
from src.llm.account_key import opaque_account_key
from src.llm.codex_auth import CodexAuth, CodexAuthPool
from src.llm.errors import LLMAuthError


def credential(name="a", **kwargs):
    return {"access_token": "secret-access-" + name, "refresh_token": "secret-refresh-" + name,
            "expires_at": 9999999999, "account_id": name, "email": name + "@example.test",
            "plan_type": "plus", **kwargs}


class Secrets:
    """Throwaway injectable keyring boundary, including locked/failure behaviour."""

    def __init__(self):
        self.values = {}
        self.fail = False
        self.writes = 0

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        if self.fail:
            raise OSError("keyring locked secret-access-a")
        self.values[name] = value
        self.writes += 1
        return True


class Device:
    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls = 0

    async def request_device_code(self):
        return {"device_auth_id": "dev", "user_code": "CODE", "interval": 5,
                "verify_url": "https://example.test/device", "expires_in": 900}

    async def poll_device_auth_once(self, auth_id, code):
        assert (auth_id, code) == ("dev", "CODE")
        self.calls += 1
        result = self.answers.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def make_service(monkeypatch):
    # Catch any accidental use of retained canonical/shadow file operations.
    def prohibited(*args, **kwargs):
        raise AssertionError("file credential persistence is forbidden")

    monkeypatch.setattr("src.llm.codex_auth._atomic_write_secure", prohibited)
    monkeypatch.setattr("src.llm.codex_auth.aiohttp.ClientSession", prohibited)
    clock = [1000.0]
    monkeypatch.setattr("src.desktop.codex_accounts.time.monotonic", lambda: clock[0])

    def make(rows=None, device=None):
        secrets = Secrets()
        if rows is not None:
            secrets.values["codex_accounts"] = json.dumps(rows)
        settings = SimpleNamespace(secrets=secrets)
        service = CodexAccountsService(settings, client=device or Device())
        return service, secrets, clock

    return make


@pytest.mark.asyncio
async def test_list_shape_real_pool_and_empty(make_service):
    service, _, _ = make_service()
    assert await service.handle("codex.accounts.list", {}) == {"configured": False, "accounts": []}
    service, _, _ = make_service([credential(label="Primary")])
    assert isinstance(service.pool, CodexAuthPool)
    result = await service.handle("codex.accounts.list", {})
    assert result["configured"] and result["account_count"] == 1
    account = result["accounts"][0]
    assert account == {"index": 0, "label": "Primary", "email": "a@example.test", "account_id": "a",
                       "plan_type": "plus", "expires_at": 9999999999, "expired": False,
                       "rate_limited": False, "is_current": True, "quota": None,
                       "limit_reached": False, "quota_check_failed": None}
    assert "secret-" not in json.dumps(result)
    assert await service.pool.acquire() == ("secret-access-a", "a", 0)
    assert READ_METHODS == {"codex.accounts.list"}
    assert "codex.login.cancel" not in METHODS


@pytest.mark.asyncio
async def test_mutations_valid_slot_mapping_and_durable_order(make_service):
    service, secrets, _ = make_service([{"unusable": True}, credential(), credential("b")])
    await service.handle("codex.accounts.activate", {"index": 1})
    assert service.pool._current_index == 1
    auth = service.pool._accounts[0]
    lock = auth._refresh_lock
    assert await service.handle("codex.accounts.label", {"index": 0, "label": "new"}) == {
        "status": "updated", "label": "new"}
    assert service.pool._accounts[0] is auth and auth._refresh_lock is lock
    assert json.loads(secrets.values["codex_accounts"])[1]["label"] == "new"
    # Metadata change cannot retire or lose an in-flight token refresh.
    auth._save(credential(access_token="rotated", refresh_token="rotated-refresh"))
    assert auth._load()["label"] == "new"
    assert json.loads(secrets.values["codex_accounts"])[1]["access_token"] == "rotated"
    assert await service.handle("codex.accounts.remove", {"index": 0}) == {
        "status": "deleted", "email": "a@example.test"}
    assert (await service.handle("codex.accounts.list", {}))["accounts"][0]["account_id"] == "b"
    with pytest.raises(LLMAuthError):
        auth._save(credential(access_token="stale"))
    assert "stale" not in secrets.values["codex_accounts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [True, -1, "0", None, 999])
async def test_invalid_indices_no_mutation(make_service, index):
    service, secrets, _ = make_service([credential()])
    before = dict(secrets.values)
    for method in ("codex.accounts.activate", "codex.accounts.label", "codex.accounts.remove"):
        with pytest.raises(MethodError) as exc:
            await service.handle(method, {"index": index})
        assert exc.value.code == "bad_request"
    assert secrets.values == before


@pytest.mark.asyncio
async def test_failed_keyring_write_does_not_acknowledge_or_publish(make_service):
    service, secrets, _ = make_service([credential(label="old")])
    before = dict(secrets.values)
    secrets.fail = True
    for method in ("codex.accounts.label", "codex.accounts.remove"):
        with pytest.raises(MethodError) as exc:
            await service.handle(method, {"index": 0, "label": "new"})
        assert "secret-access" not in str(exc.value)
    auth = service.pool.current
    with pytest.raises(OSError):
        auth._save(credential(access_token="rotation"))
    assert auth._load()["access_token"] == "secret-access-a"
    assert secrets.values == before
    assert auth._load()["label"] == "old"


@pytest.mark.asyncio
async def test_device_once_interval_expiry_and_durable_retry(make_service):
    device = Device([None, credential()])
    service, secrets, clock = make_service(device=device)
    begin = await service.handle("codex.login.begin", {})
    assert set(begin) == {"device_auth_id", "user_code", "interval", "verify_url"}
    assert await service.handle("codex.login.poll", begin) == {"status": "pending"}
    assert device.calls == 0
    clock[0] += 5
    assert await service.handle("codex.login.poll", begin) == {"status": "pending"}
    assert device.calls == 1
    answer = await service.handle("codex.login.poll", {**begin, "interval": 0})
    assert answer == {"status": "pending"}
    assert device.calls == 1
    clock[0] += 5
    secrets.fail = True
    with pytest.raises(MethodError):
        await service.handle("codex.login.poll", begin)
    assert device.calls == 2 and service.pool.account_count == 0
    secrets.fail = False
    result = await service.handle("codex.login.poll", begin)
    assert result == {"status": "authenticated", "email": "a@example.test", "account_id": "a"}
    assert device.calls == 2 and secrets.writes == 1
    assert await service.handle("codex.login.poll", begin) == result
    assert device.calls == 2 and secrets.writes == 1
    clock[0] += 1000
    assert await service.handle("codex.login.poll", begin) == result
    assert "secret-" not in json.dumps(result)


@pytest.mark.asyncio
async def test_unknown_code_expiry_error_scrub_and_corruption(make_service):
    service, secrets, clock = make_service(device=Device([RuntimeError("secret-refresh-a")]))
    begin = await service.handle("codex.login.begin", {})
    with pytest.raises(MethodError) as exc:
        await service.handle("codex.login.poll", {**begin, "user_code": "wrong"})
    assert exc.value.code == "not_found"
    clock[0] += 5
    with pytest.raises(MethodError) as exc:
        await service.handle("codex.login.poll", begin)
    assert "secret-" not in str(exc.value)
    clock[0] += 900
    with pytest.raises(MethodError) as exc:
        await service.handle("codex.login.poll", begin)
    assert exc.value.code == "expired"
    assert secrets.writes == 0
    secrets.values["codex_accounts"] = '"secret-corrupt-record"'
    with pytest.raises(MethodError):
        await service.handle("codex.accounts.remove", {"index": 0})
    assert secrets.values["codex_accounts"] == '"secret-corrupt-record"'


@pytest.mark.asyncio
@pytest.mark.parametrize("save_index", [None, 0, 9])
async def test_login_merge_reauth_labels_and_missing_slot_append(make_service, save_index):
    service, secrets, clock = make_service(
        [credential(label="keep")], Device([credential(access_token="new")]),
    )
    old_auth = service.pool.current
    begin = await service.handle("codex.login.begin", {})
    clock[0] += 5
    await service.handle("codex.login.poll", {**begin, "save_index": save_index})
    rows = json.loads(secrets.values["codex_accounts"])
    if save_index == 9:
        assert len(rows) == 2
    else:
        assert len(rows) == 1 and rows[0]["label"] == "keep"
        assert rows[0]["_authorization_revision"]
        with pytest.raises(LLMAuthError):
            old_auth._save(credential(access_token="stale"))


@pytest.mark.asyncio
async def test_close_cancels_inflight_login_without_store_write(make_service):
    entered = asyncio.Event()

    class SlowDevice(Device):
        async def poll_device_auth_once(self, *args):
            entered.set()
            await asyncio.Event().wait()

    service, secrets, clock = make_service(device=SlowDevice())
    begin = await service.handle("codex.login.begin", {})
    clock[0] += 5
    task = asyncio.create_task(service.handle("codex.login.poll", begin))
    await entered.wait()
    await service.close()
    assert task.cancelled()
    assert not service._logins and secrets.writes == 0
    with pytest.raises(MethodError):
        await service.handle("codex.accounts.list", {})


@pytest.mark.asyncio
async def test_retained_refresh_lock_and_unchanged_reload(make_service, monkeypatch):
    service, secrets, _ = make_service([credential(expires_at=0)])
    auth = service.pool.current
    calls = []

    async def refresh(creds):
        calls.append(creds["refresh_token"])
        await asyncio.sleep(0)
        auth._save(credential(access_token="rotated", refresh_token="rotated-r"))

    monkeypatch.setattr(auth, "_refresh", refresh)
    tokens = await asyncio.gather(auth.get_access_token(), auth.get_access_token())
    assert tokens == ["rotated", "rotated"]
    assert len(calls) == 1
    await service.pool.reload_async()
    assert service.pool.current is auth
    await auth.invalidate_current()
    assert auth._load()["refresh_token"] == "rotated-r"
    assert json.loads(secrets.values["codex_accounts"])[0]["refresh_token"] == "rotated-r"


@pytest.mark.asyncio
async def test_real_device_transport_one_request_and_exchange(monkeypatch):
    requests = []
    statuses = [404, 200, 200]

    class Response:
        async def __aenter__(self):
            self.status = statuses.pop(0)
            return self

        async def __aexit__(self, *args):
            pass

        async def read(self):
            return json.dumps({
                "authorization_code": "private-code", "code_verifier": "private-verifier",
                "device_auth_id": "dev", "user_code": "CODE", "interval": 7,
            }).encode()

    class Session:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def post(self, url, **kwargs):
            requests.append((url, kwargs))
            return Response()

    async def exchange(code, verifier, redirect_uri):
        assert code == "private-code" and verifier == "private-verifier"
        assert redirect_uri.endswith("/deviceauth/callback")
        return credential()

    monkeypatch.setattr("src.desktop.codex_accounts.aiohttp.ClientSession", Session)
    monkeypatch.setattr(CodexAuth, "exchange_code", exchange)
    device = CodexDeviceClient()
    assert await device.poll_device_auth_once("dev", "CODE") is None
    assert len(requests) == 1
    assert await device.poll_device_auth_once("dev", "CODE") == credential()
    assert len(requests) == 2
    begin = await device.request_device_code()
    assert begin["interval"] == 7 and begin["expires_in"] == 900
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_actual_secret_store_temp_backend_and_alongside_sentinel(tmp_path, monkeypatch):
    class Backend:
        def __init__(self):
            self.values = {}

        def get_password(self, service, name):
            return self.values.get((service, name))

        def set_password(self, service, name, value):
            self.values[service, name] = value

        def delete_password(self, service, name):
            self.values.pop((service, name), None)

    monkeypatch.setenv("HOME", str(tmp_path))
    paths = ProfilePaths.from_xdg("codex-test", environ={}, home=tmp_path)
    backend = Backend()
    secrets = ProfileSecretStore(paths, backend=backend)
    secrets.set("codex_accounts", json.dumps([credential()]))
    sentinel = tmp_path / "alongside.txt"
    sentinel.write_text("unchanged")
    service = CodexAccountsService(SimpleNamespace(secrets=secrets), client=Device())
    await service.handle("codex.accounts.label", {"index": 0, "label": "Saved"})
    restored = CodexAccountsService(SimpleNamespace(secrets=secrets), client=Device())
    assert (await restored.handle("codex.accounts.list", {}))["accounts"][0]["label"] == "Saved"
    assert sentinel.read_text() == "unchanged"
    # Retained account_key may establish non-token HMAC material for quota keys.
    # Neither canonical credentials nor per-account shadow token files exist.
    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("codex_auth*"))


@pytest.mark.asyncio
async def test_lazy_locked_keyring_does_not_block_constructor_or_begin():
    class Locked(Secrets):
        def get(self, name):
            raise OSError("secret-keyring-message")

    service = CodexAccountsService(SimpleNamespace(secrets=Locked()), client=Device())
    assert service._pool is None
    assert (await service.handle("codex.login.begin", {}))["device_auth_id"] == "dev"
    with pytest.raises(MethodError) as exc:
        await service.handle("codex.accounts.list", {})
    assert exc.value.code == "unavailable" and "secret-" not in str(exc.value)


@pytest.mark.asyncio
async def test_quota_status_and_manual_activation_reuse_retained_policy(make_service):
    service, _, _ = make_service([credential(), credential("b")])
    key = opaque_account_key("b")
    service.pool.quota.record_headers(key, {
        "x-codex-primary-used-percent": "100", "x-codex-primary-window-minutes": "60",
        "x-codex-primary-reset-after-seconds": "600",
    })
    service.pool.set_quota_check_failure(1, "unavailable")
    listing = await service.handle("codex.accounts.list", {})
    row = listing["accounts"][1]
    assert row["quota"]["primary"]["used_percent"] == 100 and row["limit_reached"]
    assert row["quota_check_failed"] == "unavailable"
    await service.handle("codex.accounts.activate", {"index": 1})
    assert await service.pool.acquire() == ("secret-access-b", "b", 1)


@pytest.mark.asyncio
async def test_concurrent_polls_do_not_exchange_or_persist_twice(make_service):
    device = Device([credential()])
    service, secrets, clock = make_service(device=device)
    begin = await service.handle("codex.login.begin", {})
    clock[0] += 5
    results = await asyncio.gather(*(
        service.handle("codex.login.poll", begin) for _ in range(4)
    ))
    assert all(result == results[0] for result in results)
    assert device.calls == 1 and secrets.writes == 1
