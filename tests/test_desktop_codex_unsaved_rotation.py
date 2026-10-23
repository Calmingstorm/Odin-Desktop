"""Odin 4.22.0 #714 and its R7 reload rule at Desktop's keyring boundary.

A refresh consumes the single-use refresh token before its rotation is saved. The rotation
outlives failed keyring writes, cache invalidation and reloads until a write succeeds, is
retried through the keyring only (never the retained file writer), and never publishes for a
removed or replaced account.
"""
import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.secrets import SecretStoreError
from src.llm import codex_auth as ca


def credential(name="a", **kwargs):
    return {"access_token": "secret-access-" + name, "refresh_token": "secret-refresh-" + name,
            "expires_at": 9999999999, "account_id": name, "email": name + "@example.test",
            "plan_type": "plus", **kwargs}


class Secrets:
    """In-memory keyring boundary whose writes can fail or be held mid-write."""

    def __init__(self, rows):
        self.values = {"codex_accounts": json.dumps(rows)}
        self.fail = False
        self.read_fail = 0  # how many of the next reads fail (a relocked keyring)
        self.writes = 0
        self.entered = threading.Event()
        self.gate = None

    def get(self, name):
        if self.read_fail:
            self.read_fail -= 1
            raise SecretStoreError("keyring locked")
        return self.values.get(name)

    def set(self, name, value):
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise SecretStoreError("keyring locked")
        self.values[name] = value
        self.writes += 1
        return True

    def rows(self):
        return json.loads(self.values["codex_accounts"])

    def put(self, rows):
        """An edit made outside this pool (no write accounting, never failing)."""
        self.values["codex_accounts"] = json.dumps(rows)


class OAuth:
    """Single-use refresh tokens: a reused one is refused, as the real endpoint does."""

    def __init__(self):
        self.consumed = []

    def session(self, **kwargs):
        transport = self

        class Response:
            def __init__(self, token):
                self.status = 400 if token in transport.consumed else 200
                transport.consumed.append(token)
                self.number = len(transport.consumed)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def read(self):
                if self.status != 200:
                    return b'{"error":"refresh_token_reused"}'
                return json.dumps({"access_token": f"rotated-access-{self.number}",
                                   "refresh_token": f"rotated-refresh-{self.number}",
                                   "expires_in": 3600}).encode()

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, **kwargs):
                assert url == ca.TOKEN_URL
                return Response(kwargs["data"]["refresh_token"])

        return Session()


@pytest.fixture
def make(monkeypatch, tmp_path):
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)  # where the pool's placeholder path would resolve
    monkeypatch.setattr("src.llm.account_key.DEFAULT_KEY_PATH", tmp_path / "key.secret")

    def prohibited(*args, **kwargs):
        raise AssertionError("file credential persistence is forbidden")

    monkeypatch.setattr("src.llm.codex_auth._atomic_write_secure", prohibited)
    oauth = OAuth()
    monkeypatch.setattr(ca.aiohttp, "ClientSession", oauth.session)
    clock = [time.time()]
    monkeypatch.setattr(ca, "time", SimpleNamespace(time=lambda: clock[0]))

    def build(rows):
        secrets = Secrets(rows)
        service = CodexAccountsService(SimpleNamespace(secrets=secrets))
        return service, secrets, oauth, clock

    yield build
    assert list(work.iterdir()) == [], "no credential file is ever written"


async def unsaved(auth, secrets):
    """Refresh an expired account while the keyring refuses the rotation's write."""
    secrets.fail = True
    with pytest.raises(SecretStoreError):
        await auth.get_access_token()


@pytest.mark.asyncio
async def test_a_rotation_outlives_failed_writes_invalidation_and_reload(make):
    service, secrets, oauth, _ = make([credential("a", expires_at=0, label="work"),
                                       credential("b")])
    pool = service.pool
    auth = pool._loaded_auths[0]
    before = secrets.rows()
    await unsaved(auth, secrets)
    assert oauth.consumed == ["secret-refresh-a"]
    assert secrets.rows() == before and secrets.writes == 0
    # Repeated failed writes: the rotation is served and never refreshed again.
    assert await auth.get_access_token() == "rotated-access-1"
    await auth.invalidate_current()
    assert await auth.get_access_token() == "rotated-access-1"
    await pool.reload_async()  # the keyring still holds the consumed predecessor
    assert pool._loaded_auths[0] is auth
    assert await pool.token_for(0) == ("rotated-access-1", "a")
    assert oauth.consumed == ["secret-refresh-a"] and secrets.writes == 0
    # Storage recovers: the next use saves the rotation at its slot with its label.
    secrets.fail = False
    assert await auth.get_access_token() == "rotated-access-1"
    saved = secrets.rows()
    assert saved[0]["refresh_token"] == "rotated-refresh-1" and saved[0]["label"] == "work"
    assert saved[1] == credential("b") and secrets.writes == 1
    assert auth._unpersisted is None and auth.expected == saved[0]
    await pool.reload_async()
    assert pool._loaded_auths[0] is auth and await auth.get_access_token() == "rotated-access-1"
    assert oauth.consumed == ["secret-refresh-a"] and secrets.writes == 1


@pytest.mark.asyncio
async def test_a_cleared_cache_serves_the_unsaved_rotation_not_the_consumed_record(make):
    service, secrets, oauth, _ = make([credential("a", expires_at=0)])
    auth = service.pool._loaded_auths[0]
    await unsaved(auth, secrets)
    auth._credentials = None  # however the cache is dropped, the keyring's record is spent
    assert await auth.get_access_token() == "rotated-access-1"
    assert oauth.consumed == ["secret-refresh-a"] and secrets.writes == 0


@pytest.mark.asyncio
async def test_an_unsaved_rotation_refreshes_with_its_own_token_and_the_newest_is_saved(make):
    service, secrets, oauth, clock = make([credential("a", expires_at=0)])
    auth = service.pool._loaded_auths[0]
    await unsaved(auth, secrets)
    clock[0] += 7200  # the unsaved rotation expires before any write succeeds
    with pytest.raises(SecretStoreError):
        await auth.get_access_token()
    assert oauth.consumed == ["secret-refresh-a", "rotated-refresh-1"]
    secrets.fail = False
    assert await auth.get_access_token() == "rotated-access-2"
    assert secrets.rows()[0]["refresh_token"] == "rotated-refresh-2" and secrets.writes == 1
    assert oauth.consumed == ["secret-refresh-a", "rotated-refresh-1"]


@pytest.mark.asyncio
async def test_a_reorder_keeps_the_unsaved_rotation_and_saves_it_at_the_new_slot(make):
    service, secrets, oauth, _ = make([credential("a", expires_at=0), credential("b")])
    pool = service.pool
    auth = pool._loaded_auths[0]
    await unsaved(auth, secrets)
    rows = secrets.rows()
    secrets.put([rows[1], rows[0]])
    await pool.reload_async()
    assert pool._loaded_auths[1] is auth and auth.slot == 1
    secrets.fail = False
    assert await pool.token_for(1) == ("rotated-access-1", "a")
    saved = secrets.rows()
    assert [row["account_id"] for row in saved] == ["b", "a"]
    assert saved[0] == rows[1] and saved[1]["refresh_token"] == "rotated-refresh-1"
    assert oauth.consumed == ["secret-refresh-a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["removed", "replaced"])
async def test_a_removed_or_replaced_account_never_publishes_its_unsaved_rotation(make, change):
    service, secrets, oauth, _ = make([credential("a", expires_at=0), credential("b")])
    pool = service.pool
    auth = pool._loaded_auths[0]
    await unsaved(auth, secrets)
    secrets.fail = False
    if change == "removed":
        await service.handle("codex.accounts.remove", {"index": 0})
        expected = [credential("b")]
    else:  # a fresh login of the same account starts a new refresh chain
        expected = [credential("a", access_token="relogin", refresh_token="relogin-r"),
                    credential("b")]
        secrets.put(expected)
        await pool.reload_async()
        assert pool._loaded_auths[0] is not auth
    writes = secrets.writes
    # The retired auth's retry is refused by its guard; nothing is resurrected.
    await auth.get_access_token()
    assert secrets.rows() == expected and secrets.writes == writes
    assert auth._unpersisted is not None
    assert oauth.consumed == ["secret-refresh-a"]


@pytest.mark.asyncio
async def test_a_cancelled_retry_still_settles_its_keyring_write(make):
    service, secrets, oauth, _ = make([credential("a", expires_at=0)])
    auth = service.pool._loaded_auths[0]
    await unsaved(auth, secrets)
    secrets.fail = False
    secrets.entered.clear()
    secrets.gate = threading.Event()
    retry = asyncio.create_task(auth.get_access_token())
    assert await asyncio.to_thread(secrets.entered.wait, 5)
    retry.cancel()
    await asyncio.sleep(0.05)
    assert not retry.done()  # the write settles before cancellation is delivered
    secrets.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(retry, 5)
    assert secrets.rows()[0]["refresh_token"] == "rotated-refresh-1"
    assert auth._unpersisted is None and auth.expected["refresh_token"] == "rotated-refresh-1"
    secrets.gate = None
    assert await auth.get_access_token() == "rotated-access-1"
    assert oauth.consumed == ["secret-refresh-a"] and secrets.writes == 1


def test_the_retained_file_retry_is_never_reached():
    from src.desktop.codex_accounts import KeyringCodexAuth

    auth = KeyringCodexAuth.__new__(KeyringCodexAuth)
    auth._unpersisted = credential("a")
    auth._retry_unpersisted()  # a no-op: the keyring retry replaces it
    with pytest.raises(RuntimeError, match="keyring only"):
        auth._persist(credential("a"))


@pytest.mark.asyncio
async def test_a_rotation_the_keyring_could_not_check_is_quarantined_then_adopted(make):
    """Odin's review R1: the keyring relocked during the refresh, so the identity check's
    read failed with the old token already spent. The rotation is held in quarantine:
    never served or saved while unverified, and the spent token is never offered again."""
    service, secrets, oauth, _ = make([credential("a", expires_at=0, label="work")])
    pool = service.pool
    auth = pool._loaded_auths[0]
    secrets.read_fail = 1  # the first read after the refresh: the identity check's
    with pytest.raises(SecretStoreError):
        await auth.get_access_token()
    assert oauth.consumed == ["secret-refresh-a"] and secrets.writes == 0
    assert auth._quarantined is not None and auth._unpersisted is None
    secrets.read_fail = 10**6  # still locked: refused as such, no second refresh
    with pytest.raises(SecretStoreError):
        await pool.token_for(0)
    assert await auth.force_refresh("secret-access-a") is False
    assert oauth.consumed == ["secret-refresh-a"] and secrets.writes == 0
    secrets.read_fail = 0  # unlocked again: checked against the same fences, then saved
    assert await pool.token_for(0) == ("rotated-access-1", "a")
    saved = secrets.rows()[0]
    assert saved["refresh_token"] == "rotated-refresh-1" and saved["label"] == "work"
    assert auth._quarantined is None and auth._unpersisted is None and secrets.writes == 1
    assert oauth.consumed == ["secret-refresh-a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["removed", "replaced"])
async def test_a_quarantined_rotation_of_a_changed_account_is_dropped(make, change):
    service, secrets, oauth, _ = make([credential("a", expires_at=0), credential("b")])
    pool = service.pool
    auth = pool._loaded_auths[0]
    secrets.read_fail = 1
    with pytest.raises(SecretStoreError):
        await auth.get_access_token()
    if change == "removed":
        await service.handle("codex.accounts.remove", {"index": 0})
        expected = [credential("b")]
    else:
        expected = [credential("a", access_token="relogin", refresh_token="relogin-r"),
                    credential("b")]
        secrets.put(expected)
        await pool.reload_async()
    writes = secrets.writes
    await auth._retry_unsaved()  # the retired auth's check refuses: dropped
    assert auth._quarantined is None and auth._unpersisted is None
    assert secrets.rows() == expected and secrets.writes == writes


@pytest.mark.asyncio
async def test_a_label_edit_while_a_rotation_is_unsaved_survives_reloads(make):
    """Odin's review C1: a reload serves the unsaved rotation; a later label edit must not
    be hidden by the rotation's older label at the next reload."""
    service, secrets, oauth, _ = make([credential("a", expires_at=0, label="old")])
    pool = service.pool
    await unsaved(pool._loaded_auths[0], secrets)
    secrets.fail = False
    await pool.reload_async()
    await service.handle("codex.accounts.label", {"index": 0, "label": "new-label"})

    def listed():
        return [row.get("label") for row in service._list()["accounts"]]

    assert listed() == ["new-label"]
    await pool.reload_async()
    assert listed() == ["new-label"] and secrets.rows()[0]["label"] == "new-label"
    assert await pool.token_for(0) == ("rotated-access-1", "a")
    saved = secrets.rows()[0]
    assert saved["label"] == "new-label" and saved["refresh_token"] == "rotated-refresh-1"
    assert oauth.consumed == ["secret-refresh-a"]
