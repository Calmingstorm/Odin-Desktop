"""Account lifecycle and reply recovery, using disposable credentials only.

Odin 4.14 (#652), carried to Desktop with tests/desktop_adapters/codex_setup.py. Odin's
delete-and-re-add case drives his web API; Desktop's is in tests/test_desktop_codex_accounts.py,
through the app's own account methods."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.llm import codex_auth as ca
from src.llm.account_key import opaque_account_key
from src.llm.errors import LLMRateLimitError
from src.llm.openai_codex import CodexChatClient, CodexStreamError
from tests.desktop_adapters.codex_setup import creds, setup

OLD_HEADERS = {
    "x-codex-primary-used-percent": "25",
    "x-codex-primary-window-minutes": "10080",
    "x-codex-plan-type": "pro",
}
PLUS_HEADERS = {
    "x-codex-primary-used-percent": "20",
    "x-codex-primary-window-minutes": "300",
    "x-codex-secondary-used-percent": "10",
    "x-codex-secondary-window-minutes": "10080",
    "x-codex-plan-type": "plus",
}


@pytest.fixture(autouse=True)
def isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setattr("src.llm.account_key.DEFAULT_KEY_PATH", tmp_path / "key.secret")


def mark(pool, index):
    pool.set_quota_check_failure(index, "HTTP 401")
    pool.quota.record_headers(pool._quota_key(index), OLD_HEADERS)


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("sync", [False, True])
@pytest.mark.parametrize("revision", [False, True])
async def test_same_account_in_place_replacement_immediately_recovers(
    tmp_path, single, sync, revision,
):
    path, pool, *_ = setup(tmp_path, creds("A") if single else [creds("A"), creds("B")])
    old_auth = pool.current
    assert await pool.token_for(0) == ("synthetic-A", "A")  # prime the cache
    mark(pool, 0)
    if not single:
        mark(pool, 1)
    replacement = {
        **creds("A"), "access_token": "synthetic-new-A",
        "refresh_token": "synthetic-new-refresh-A", "expires_at": 8888888888,
    }
    if revision:
        replacement = ca.mark_authorized_account(replacement)
    path.write_text(json.dumps(replacement if single else [replacement, creds("B")]))
    if sync:
        pool.reload()
    else:
        await pool.reload_async()
    assert pool.current is not old_auth
    assert await pool.token_for(0) == ("synthetic-new-A", "A")
    assert pool.quota_check_failure(0) is None  # no quota_view or process restart
    assert pool.quota.snapshot_for(opaque_account_key("A")) is None
    if not single:
        assert pool.quota_check_failure(1) == "HTTP 401"
        assert pool.quota.snapshot_for(opaque_account_key("B")) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [False, True])
async def test_shadow_replacement_with_older_expiry_becomes_authoritative(tmp_path, revision):
    path, pool, *_ = setup(tmp_path, [creds("A"), creds("B")])
    assert await pool.token_for(0) == ("synthetic-A", "A")
    mark(pool, 0)
    mark(pool, 1)
    replacement = {**creds("A"), "access_token": "synthetic-shadow-replacement",
                   "refresh_token": "synthetic-shadow-refresh", "expires_at": 8888888888}
    if revision:
        replacement = ca.mark_authorized_account(replacement)
    (tmp_path / "codex_auth_0.json").write_text(json.dumps(replacement))
    await pool.reload_async()
    assert await pool.token_for(0) == ("synthetic-shadow-replacement", "A")
    assert json.loads(path.read_text())[0] == replacement
    assert pool.quota_check_failure(0) is None
    assert pool.quota.snapshot_for(opaque_account_key("A")) is None
    assert pool.quota_check_failure(1) == "HTTP 401"


@pytest.mark.asyncio
async def test_unchanged_label_and_reorder_reload_preserve_account_state(tmp_path):
    path, pool, *_ = setup(tmp_path, [creds("A"), creds("B")])
    mark(pool, 0)
    mark(pool, 1)
    original = pool.current
    path.write_text(json.dumps([{**creds("A"), "label": "renamed"}, creds("B")]))
    await pool.reload_async()
    assert pool.current is original  # keep the single-use refresh lock
    path.write_text(json.dumps([creds("B"), creds("A")]))
    await pool.reload_async()
    assert [pool.quota_check_failure(i) for i in range(2)] == ["HTTP 401", "HTTP 401"]
    assert all(pool.quota.snapshot_for(opaque_account_key(a)) for a in ("A", "B"))


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["text", "tools", "429", "stream_failure", "empty"])
@pytest.mark.parametrize("reorder", [False, True])
async def test_reply_recovers_only_the_serving_account(tmp_path, monkeypatch, reply, reorder):
    path, pool, *_ = setup(tmp_path, [creds("A"), creds("B")])
    mark(pool, 0)
    mark(pool, 1)
    client = CodexChatClient(pool, "synthetic-model", max_retries=1)
    entered, release = asyncio.Event(), asyncio.Event()

    class Response:
        status = 429 if reply == "429" else 200
        headers = PLUS_HEADERS
        content = None

        async def __aenter__(self):
            entered.set()
            await release.wait()
            return self

        async def __aexit__(self, *args):
            pass

    session = SimpleNamespace(post=lambda *args, **kwargs: Response())
    monkeypatch.setattr(client, "_get_session", AsyncMock(return_value=session))
    monkeypatch.setattr("src.llm.openai_codex._read_error_body_bounded",
                        AsyncMock(return_value=(b'{"error":{"message":"slow down"}}', False)))

    async def reader(response):
        if reply == "stream_failure":
            raise CodexStreamError("synthetic failure")
        if reply == "tools":
            from src.llm.types import LLMResponse

            return LLMResponse(text="", tool_calls=[SimpleNamespace(name="test")])
        return "" if reply == "empty" else "healthy reply"

    task = asyncio.create_task(client._send_with_retries(
        {"model": "synthetic-model"}, reader,
        lambda result: not (result.text or result.tool_calls) if reply == "tools" else not result,
    ))
    await entered.wait()
    if reorder:
        path.write_text(json.dumps([creds("B"), creds("A")]))
        await pool.reload_async()
    release.set()
    if reply in {"429", "stream_failure"}:
        with pytest.raises(LLMRateLimitError if reply == "429" else Exception):
            await task
    else:
        await task
    a_index, b_index = (1, 0) if reorder else (0, 1)
    assert pool.quota_check_failure(b_index) == "HTTP 401"
    assert pool.quota_check_failure(a_index) == (
        None if reply in {"text", "tools"} else "HTTP 401"
    )
    snapshot = pool.quota.snapshot_for(opaque_account_key("A"))
    assert snapshot.plan_type == "plus"
    assert snapshot.primary.window_minutes == 300
    assert snapshot.secondary.window_minutes == 10080


@pytest.mark.asyncio
async def test_429_then_other_account_success_only_clears_successful_account(tmp_path, monkeypatch):
    _, pool, *_ = setup(tmp_path, [creds("A"), creds("B")])
    mark(pool, 0)
    mark(pool, 1)
    client = CodexChatClient(pool, "synthetic-model", max_retries=2)
    calls = []

    class Response:
        headers = {}
        content = None

        def __init__(self, status):
            self.status = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    def post(*args, **kwargs):
        calls.append(kwargs["headers"]["ChatGPT-Account-Id"])
        return Response(429 if len(calls) == 1 else 200)

    monkeypatch.setattr(client, "_get_session", AsyncMock(return_value=SimpleNamespace(post=post)))
    monkeypatch.setattr("src.llm.openai_codex._read_error_body_bounded",
                        AsyncMock(return_value=(b'{"error":{"message":"slow down"}}', False)))
    monkeypatch.setattr("src.llm.openai_codex.asyncio.sleep", AsyncMock())
    result = await client._send_with_retries(
        {"model": "synthetic-model"}, AsyncMock(return_value="healthy B reply"), lambda r: not r,
    )
    assert result == "healthy B reply"
    assert calls == ["A", "B"]
    assert pool.quota_check_failure(0) == "HTTP 401"
    assert pool.quota_check_failure(1) is None


@pytest.mark.asyncio
async def test_an_account_at_its_limit_is_not_a_failed_quota_check(tmp_path, monkeypatch):
    """Odin 4.18.1: an exhausted account answers the idle check with 429 and its quota."""
    from src.llm.codex_quota_check import CodexQuotaCheckService

    _path, pool, *_ = setup(tmp_path, [creds("A"), creds("B"), creds("C")])
    replies = {
        "A": (429, {**PLUS_HEADERS, "x-codex-secondary-used-percent": "100"}),
        "B": (429, {"x-codex-rate-limit-reached-type": "primary"}),
        "C": (429, PLUS_HEADERS),  # nothing exhausted: the 429 stays unexplained
    }

    class Reply:
        def __init__(self, status, headers):
            self.status, self.headers = status, headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Session:
        closed = False

        def post(self, url, *, headers, json, timeout):
            return Reply(*replies[headers["ChatGPT-Account-Id"]])

        async def close(self):
            self.closed = True

    monkeypatch.setattr("src.llm.codex_quota_check.aiohttp.ClientSession",
                        lambda **kwargs: Session())
    for index in range(3):
        pool.set_quota_check_failure(index, "HTTP 429")  # earlier checks
    await CodexQuotaCheckService(lambda: pool).check_once()
    assert [pool.quota_check_failure(index) for index in range(3)] == [None, None, "HTTP 429"]
    assert pool.quota.snapshot_for(pool._quota_key(0)).secondary.used_percent == 100


@pytest.mark.asyncio
async def test_a_stale_token_is_refreshed_and_the_quota_checked_again(tmp_path, monkeypatch):
    """An app that sat closed: its first quota check meets a rejected token."""
    from src.llm.codex_quota_check import CodexQuotaCheckService

    path, pool, *_ = setup(tmp_path, [creds("A")])
    refreshes = []

    async def token_endpoint(self, current):  # the refresh grant's answer, without the network
        refreshes.append(current["access_token"])
        self._save({**current, "access_token": "synthetic-refreshed-A",
                    "refresh_token": "synthetic-refresh-2-A"})

    monkeypatch.setattr(ca.CodexAuth, "_refresh", token_endpoint)
    exhausted = {**PLUS_HEADERS, "x-codex-secondary-used-percent": "100",
                 "x-codex-secondary-reset-after-seconds": "86400"}

    class Reply:
        def __init__(self, status, headers):
            self.status, self.headers = status, headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    seen = []

    class Session:
        closed = False

        def post(self, url, *, headers, json, timeout):
            seen.append(headers["Authorization"])
            if headers["Authorization"] == "Bearer synthetic-A":
                return Reply(401, {})
            return Reply(429, exhausted)

        async def close(self):
            self.closed = True

    monkeypatch.setattr("src.llm.codex_quota_check.aiohttp.ClientSession",
                        lambda **kwargs: Session())
    await CodexQuotaCheckService(lambda: pool).check_once()
    assert seen == ["Bearer synthetic-A", "Bearer synthetic-refreshed-A"]
    assert refreshes == ["synthetic-A"]
    assert pool.quota_check_failure(0) is None  # the limit, observed; no "Quota check failed"
    assert pool.quota.snapshot_for(pool._quota_key(0)).secondary.used_percent == 100
    assert json.loads(path.read_text())[0]["access_token"] == "synthetic-refreshed-A"


class _Vault:
    """A throwaway vault holding two disposable accounts."""

    def __init__(self):
        self.rows = [{"account_id": name, "access_token": f"synthetic-{name}",
                      "refresh_token": f"synthetic-refresh-{name}", "expires_at": 9999999999}
                     for name in ("A", "B")]
        self.writes = 0

    def read(self):
        return json.loads(json.dumps(self.rows))

    def write(self, rows):
        self.rows = json.loads(json.dumps(rows))
        self.writes += 1


class _Reply:
    def __init__(self, status, quota=None, body=None, enter=None, leave=None):
        self.status, self.headers, self.body = status, quota or {}, body
        self.enter, self.leave = enter, leave

    async def __aenter__(self):
        if self.enter:
            await self.enter()
        return self

    async def __aexit__(self, *exc):
        if self.leave:  # aiohttp awaits the connection's close here
            await self.leave()
        return False

    async def read(self):
        assert self.body is not None, "only the token endpoint's body is read"
        return json.dumps(self.body).encode()


class _Transport:
    """The token endpoint and the Codex endpoint, scripted; nothing leaves the process."""

    closed = False

    def __init__(self, quota, *, on_refresh=None):
        self.quota, self.on_refresh = list(quota), on_refresh
        self.calls, self.refreshes = [], []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        from src.llm import codex_quota_check as qc

        if url == ca.TOKEN_URL:
            self.refreshes.append(kwargs["data"])
            return _Reply(200, body={"access_token": "synthetic-refreshed-A",
                                     "refresh_token": "synthetic-rotated-refresh-A",
                                     "expires_in": 3600}, enter=self.on_refresh)
        assert url == qc.CODEX_API_URL
        self.calls.append(dict(kwargs["headers"]))
        return self.quota.pop(0)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("during", ["refresh", "response-exit-401", "response-exit-429"])
@pytest.mark.parametrize("attached", [False, True], ids=["account-service", "serving-provider"])
async def test_an_account_removed_during_its_refresh_gets_no_verdict(monkeypatch, attached, during):
    """Odin's Desktop 1.2.2 review F1 (and his Odin #667 review), adopted: an account removed
    through codex.accounts.remove while the check waits on a real refresh or on leaving the
    rejected response."""
    import socket

    import aiohttp

    from src.config.schema import Config
    from src.desktop.codex_accounts import CodexAccountsService
    from src.desktop.providers import ProviderOwner
    from src.llm import codex_quota_check as qc

    def denied(*args, **kwargs):
        raise AssertionError("no network in this test")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    config = Config()
    config.openai_codex.enabled = True
    config.openai_codex.auxiliary.enabled = False
    config.ollama.enabled = False
    config.openai_compatible.enabled = False
    accounts = CodexAccountsService(SimpleNamespace(config=config), vault=_Vault())
    providers = None
    if attached:
        providers = ProviderOwner(accounts.settings, accounts)
        accounts.providers = providers
        await providers.reload_codex()
    pool = accounts.pool
    pool.quota.record_headers(pool._quota_key(1), {
        "x-codex-secondary-used-percent": "40", "x-codex-secondary-window-minutes": "300",
        "x-codex-secondary-reset-after-seconds": "600"})
    pool.set_quota_check_failure(1, "other account sentinel")
    entered, release = asyncio.Event(), asyncio.Event()

    async def token_endpoint_await():
        entered.set()
        await release.wait()

    if during == "refresh":
        transport = _Transport([_Reply(401)], on_refresh=token_endpoint_await)
    else:
        status = int(during.rsplit("-", 1)[1])
        transport = _Transport([_Reply(status, leave=token_endpoint_await)])
    raw_refresh, refresh_targets = pool.force_refresh, []

    async def tracked_refresh(index, stale_token=None):
        refresh_targets.append(pool._accounts[index].get_account_id())
        return await raw_refresh(index, stale_token)

    pool.force_refresh = tracked_refresh
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kwargs: transport)

    def serving_pool():
        return getattr(providers.codex_client, "auth", None) if attached else pool

    check = qc.CodexQuotaCheckService(serving_pool)
    task = asyncio.create_task(check.check_once())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await accounts.handle("codex.accounts.remove", {"index": 0})  # B moves to slot 0
        release.set()
        await task
        assert len(transport.calls) == 1
        # Only A's own refresh, started before the removal; nothing for B's slot.
        assert refresh_targets == (["A"] if during == "refresh" else [])
        assert len(transport.refreshes) == (1 if during == "refresh" else 0)
        assert accounts.vault.writes == 1  # the removal only; no retired refresh is saved
        assert accounts.vault.rows[0]["account_id"] == "B"
        # The removed account's 401 must not replace B's own state.
        assert pool.quota_check_failure(0) == "other account sentinel"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await check.close()
        if providers is not None:
            await providers.close()
        await accounts.close()


@pytest.mark.asyncio
async def test_a_reload_during_the_retry_token_fetch_writes_no_verdict(tmp_path, monkeypatch):
    """The third await on the refresh path: the token fetch for the second request."""
    from src.llm.codex_quota_check import CodexQuotaCheckService

    path, pool, *_ = setup(tmp_path, [creds("A")])

    async def token_endpoint(self, current):  # a successful refresh, without the network
        self._save({**current, "access_token": "synthetic-refreshed-A"})

    monkeypatch.setattr(ca.CodexAuth, "_refresh", token_endpoint)
    raw_token_for, fetches = pool.token_for, []

    async def token_for(index):
        fetches.append(index)
        if len(fetches) == 2:  # the retry's fetch: the account set changes meanwhile
            path.write_text(json.dumps([creds("B")]))
            await pool.reload_async()
        return await raw_token_for(index)

    monkeypatch.setattr(pool, "token_for", token_for)
    calls = []

    class Session:
        closed = False

        def post(self, url, *, headers, json, timeout):
            calls.append(headers["Authorization"])
            return _Reply(401)

        async def close(self):
            self.closed = True

    monkeypatch.setattr("src.llm.codex_quota_check.aiohttp.ClientSession",
                        lambda **kwargs: Session())
    await CodexQuotaCheckService(lambda: pool).check_once()
    assert calls == ["Bearer synthetic-A"]  # no second request for the old slot
    assert pool._accounts[0].get_account_id() == "B"
    assert pool.quota_check_failure(0) is None


def test_the_shared_limit_reading_desktop_relies_on():
    """codex_quota's reading (Odin 4.18.2), which routing, the listing and the check share."""
    from src.llm.codex_quota import limit_reached, limited_windows, parse_quota_headers

    now = 1_000.0

    def snap(headers):
        return parse_quota_headers(headers, account_key="k", observed_at=now)

    named = snap({"x-codex-primary-used-percent": "20", "x-codex-primary-window-minutes": "300",
                  "x-codex-primary-reset-after-seconds": "60",
                  "x-codex-rate-limit-reached-type": "primary_window"})
    assert limited_windows(named, now) == {"primary": now + 60}
    assert limited_windows(named, now + 60) == {}  # until its reset only
    assert limit_reached(named, now) is True
    assert limit_reached(snap({"x-codex-rate-limit-reached-type": "secondary"}), now) is True
    assert limited_windows(None, now) == {} and limit_reached(None, now) is False

