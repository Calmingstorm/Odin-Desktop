"""Odin 4.22.0 (PR #729) in Desktop: Odin's new Codex auth cases, verbatim.

Desktop keeps tests/test_codex_auth.py byte for byte as Odin v4.13.0 wrote it. Odin
4.22.0's cases for a rotation whose write failed (#714) and its reload rule (R7) run here
on the file-backed auth Desktop carries; tests/test_desktop_codex_unsaved_rotation.py runs
the same rules through Desktop's keyring pool.
"""
from __future__ import annotations

import json

import pytest

from src.llm import codex_auth as ca
from src.llm.codex_auth import CodexAuth, CodexAuthPool
from tests.test_codex_auth import _creds, _FakeResp, _FakeSession  # noqa: F401


class TestRefreshTransport:
    def _auth(self, tmp_path, creds):
        p = tmp_path / "creds.json"
        p.write_text(json.dumps(creds))
        return CodexAuth(str(p))

    @pytest.mark.asyncio
    async def test_failed_credential_write_keeps_the_rotated_refresh_token(
        self, tmp_path, monkeypatch
    ):
        # The token endpoint consumed r1 and returned r2. A failed write (a full
        # disk) must not drop r2 and send the burned r1 on the next refresh.
        _FakeSession.response = _FakeResp(
            200, json.dumps({"access_token": "new-access", "refresh_token": "r2",
                             "expires_in": 3600}).encode())
        monkeypatch.setattr(ca.aiohttp, "ClientSession", _FakeSession)
        a = self._auth(tmp_path, _creds(access="old", refresh="r1", expires_at=0))
        real_write = ca._atomic_write_secure
        failures = {"left": 1}

        def flaky(path, content):
            if failures["left"]:
                failures["left"] -= 1
                raise OSError(28, "No space left on device")
            return real_write(path, content)

        monkeypatch.setattr(ca, "_atomic_write_secure", flaky)
        with pytest.raises(OSError):
            await a.get_access_token()
        assert a._credentials["refresh_token"] == "r2"
        await a.invalidate_current()  # the newer unsaved tokens outlive a cache drop
        assert a._credentials["refresh_token"] == "r2"
        posts_before = _FakeSession.last
        # The next request serves the new token and saves it, without refreshing.
        assert await a.get_access_token() == "new-access"
        assert _FakeSession.last is posts_before
        saved = json.loads((tmp_path / "creds.json").read_text())
        assert saved["refresh_token"] == "r2" and a._unpersisted is None

    @pytest.mark.asyncio
    async def test_unsaved_credentials_of_a_retired_account_are_never_published(
        self, tmp_path, monkeypatch
    ):
        a = self._auth(tmp_path, _creds(refresh="r1"))
        a._credentials = a._unpersisted = _creds(refresh="r2")
        a.save_guard = lambda: False
        a._retry_unpersisted()
        saved = json.loads((tmp_path / "creds.json").read_text())
        assert saved["refresh_token"] == "r1" and a._unpersisted is not None


class TestUnsavedRotationAcrossReload:
    """A rotation whose write failed is newer than the file: its refresh
    token is the live one. A pool reload (an account edit, another account's
    deletion) re-read the file's record, so the next refresh sent the used
    token and the account failed (PR #729 review R7)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fmt", ["single", "list"])
    async def test_a_reload_keeps_serving_the_unsaved_rotation(self, tmp_path, monkeypatch, fmt):
        path = tmp_path / "codex_auth.json"
        old = _creds(access="old", refresh="r1", expires_at=0, account_id="acct-1")
        path.write_text(json.dumps(old if fmt == "single" else [old]))
        pool = CodexAuthPool(str(path))
        auth = pool._accounts[0]
        real_write = ca._atomic_write_secure

        def full_disk(path, content):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(ca, "_atomic_write_secure", full_disk)
        with pytest.raises(OSError):
            auth._save(_creds(access="new", refresh="r2", account_id="acct-1"))
        monkeypatch.setattr(ca, "_atomic_write_secure", real_write)
        await pool.reload_async()
        assert pool._accounts[0] is auth  # the same refresh chain keeps its auth

        async def burned(_record):
            raise AssertionError("refreshed with the used refresh token")

        monkeypatch.setattr(auth, "_refresh", burned)
        assert await auth.get_access_token() == "new"
        assert json.loads(auth._path.read_text())["refresh_token"] == "r2"
        assert auth._unpersisted is None and auth._credentials["refresh_token"] == "r2"
        if fmt == "list":
            assert json.loads(path.read_text())[0]["refresh_token"] == "r2"

    def test_a_retried_save_does_not_replace_a_newer_cache(self, tmp_path):
        a = CodexAuth(str(tmp_path / "creds.json"))
        newer = _creds(refresh="r3", expires_at=9_999_999_999)
        a._credentials = newer
        a._unpersisted = _creds(refresh="r2", expires_at=1_000)
        a._retry_unpersisted()
        assert a._credentials is newer and a._unpersisted is None
