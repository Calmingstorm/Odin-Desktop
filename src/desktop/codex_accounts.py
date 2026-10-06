"""Pinned Codex administration, with keyring-only provider persistence.

Retained auth/pool methods own refresh locks, rotation, quota and lifecycle.
The subclasses replace only canonical/shadow file persistence. Device polling
performs one HTTP attempt, never the retained fifteen-minute loop.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import aiohttp

from ..llm.account_key import opaque_account_key
from ..llm.codex_auth import (
    CLIENT_ID,
    DEVICE_REDIRECT_URI,
    DEVICE_TOKEN_URL,
    DEVICE_USERCODE_URL,
    DEVICE_VERIFY_URL,
    CodexAuth,
    CodexAuthPool,
    _decode_jwt_payload,
    mark_authorized_account,
    merge_authorized_account,
)
from ..llm.errors import LLMAuthError
from .secrets import SecretStoreError

METHODS = frozenset({
    "codex.accounts.list", "codex.accounts.activate", "codex.accounts.remove",
    "codex.accounts.label", "codex.accounts.refresh", "codex.login.begin", "codex.login.poll",
})
READ_METHODS = frozenset({"codex.accounts.list"})


def _error(code, message, disposition="rejected"):
    from .management import MethodError

    return MethodError(code, message, disposition)


class KeyringCodexVault:
    """One atomic keyring value containing the canonical credential records."""

    NAME = "codex_accounts"

    def __init__(self, secrets):
        self.secrets = secrets

    def read(self):
        value = self.secrets.get(self.NAME)
        if value is None:
            return []
        raw = json.loads(value)
        if not isinstance(raw, (dict, list)):
            raise ValueError("Invalid credential records")
        return raw

    def write(self, raw):
        if self.secrets.set(self.NAME, json.dumps(raw)) is not True:
            raise OSError("Credential persistence failed")


class KeyringCodexAuth(CodexAuth):
    """Retained refresh lifecycle with a generation-fenced keyring save."""

    def __init__(self, pool, slot, creds):
        super().__init__("desktop-keyring-unused")
        self.pool = pool
        self.slot = slot
        self.expected = dict(creds)
        self._credentials = dict(creds)
        self.epoch = pool.generation

    def is_configured(self):
        return bool(self.expected.get("access_token"))

    def _load(self):
        if self._credentials is None:
            self._credentials = dict(self._canonical_row())
        return self._credentials

    def _canonical_row(self):
        raw = self.pool.vault.read()
        rows = raw if isinstance(raw, list) else [raw]
        if self.epoch != self.pool.generation or self.slot >= len(rows):
            raise LLMAuthError("Codex account changed during refresh.", provider="codex")
        row = rows[self.slot]
        if not isinstance(row, dict) or not self.pool._same_credentials(row, self.expected):
            raise LLMAuthError("Codex account changed during refresh.", provider="codex")
        return row

    def _save(self, creds):
        row = self._canonical_row()
        raw = self.pool.vault.read()
        updated = dict(creds)
        if "label" in row:
            updated["label"] = row["label"]
        if isinstance(raw, list):
            raw[self.slot] = updated
        else:
            raw = updated
        self.pool.vault.write(raw)
        # Publish single-use rotations only AFTER durable keyring storage.
        self.expected = dict(updated)
        self._credentials = dict(updated)


class KeyringCodexAuthPool(CodexAuthPool):
    """Provider-compatible pool; its overridden boundary never touches files."""

    def __init__(self, vault):
        self.vault = vault
        super().__init__("desktop-keyring-unused")

    def _init_accounts(self):
        raw = self.vault.read()
        rows = raw if isinstance(raw, list) else [raw]
        previous = dict(getattr(self, "_loaded_auths", {}))
        self._generation += 1
        self._canonical_indices = []
        self._loaded_records = {}
        self._loaded_auths = {}
        for slot, creds in enumerate(rows):
            if not isinstance(creds, dict) or not creds.get("access_token"):
                continue
            auth = previous.get(slot)
            if auth is None or not self._same_credentials(creds, auth.expected):
                auth = KeyringCodexAuth(self, slot, creds)
            else:
                # An unchanged reload retains the single-use refresh lock.
                auth.epoch = self.generation
                auth.expected = dict(creds)
                if auth._credentials is not None:
                    auth._credentials = {**auth._credentials, "label": creds.get("label", "")}
            self._accounts.append(auth)
            self._canonical_indices.append(slot)
            self._loaded_auths[slot] = auth
            self._loaded_records[slot] = dict(creds)


class CodexDeviceClient:
    """Real OAuth endpoints, no long-lived session or blocking polling loop."""

    async def request_device_code(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(DEVICE_USERCODE_URL, json={"client_id": CLIENT_ID}) as response:
                if response.status != 200:
                    raise RuntimeError("Device code request failed")
                data = json.loads(await response.read())
        return {
            "device_auth_id": data["device_auth_id"], "user_code": data["user_code"],
            "interval": int(data.get("interval", 5)), "verify_url": DEVICE_VERIFY_URL,
            "expires_in": data.get("expires_in", 900),
        }

    async def poll_device_auth_once(self, device_auth_id, user_code):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(DEVICE_TOKEN_URL, json={
                "device_auth_id": device_auth_id, "user_code": user_code,
            }) as response:
                if response.status in (403, 404):
                    return None
                if response.status != 200:
                    raise RuntimeError("Device authorization check failed")
                data = json.loads(await response.read())
        return await CodexAuth.exchange_code(
            data["authorization_code"], data["code_verifier"], redirect_uri=DEVICE_REDIRECT_URI,
        )


@dataclass
class _Login:
    code: str
    interval: int
    deadline: float
    next_poll: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    credentials: dict | None = None
    done: dict | None = None


class CodexAccountsService:
    METHODS = METHODS
    READ_METHODS = READ_METHODS

    def __init__(self, settings, *, client=None, vault=None):
        self.settings = settings
        self.vault = vault if vault is not None else KeyringCodexVault(settings.secrets)
        # Startup and login.begin do not unlock or read an owner's keyring.
        self._pool: KeyringCodexAuthPool | None = None
        self.client = client if client is not None else CodexDeviceClient()
        self._logins: dict[str, _Login] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self.providers = None

    @property
    def pool(self):
        if self._pool is None:
            self._pool = KeyringCodexAuthPool(self.vault)
        return self._pool

    async def handle(self, method, params):
        if method not in METHODS:
            raise _error("method_not_found", "Unknown Codex method")
        if not isinstance(params, dict):
            raise _error("bad_request", "params must be an object")
        if self._closed:
            raise _error("unavailable", "Codex account service is closed")
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            if method == "codex.accounts.list":
                return self._list()
            if method == "codex.accounts.refresh":
                return await self._refresh(params)
            if method == "codex.login.begin":
                return await self._begin()
            if method == "codex.login.poll":
                return await self._poll(params)
            return await self._mutate(method, params)
        except Exception as exc:
            from .management import MethodError

            if isinstance(exc, MethodError):
                raise
            # Provider bodies, corrupt JSON and keyring errors may contain tokens.
            disposition = (
                "rejected" if method in READ_METHODS or method == "codex.login.begin"
                else "outcome_unknown"
            )
            if isinstance(exc, SecretStoreError):
                raise _error(
                    "keyring_unavailable", "The system keyring is locked or unavailable",
                    disposition,
                ) from None
            raise _error("unavailable", "Codex account operation failed", disposition) from None
        finally:
            self._tasks.discard(task)

    def _list(self):
        if not self.pool.account_count:
            return {"configured": False, "accounts": []}
        accounts = []
        for index, auth in enumerate(self.pool._accounts):
            creds = auth._load()
            payload = _decode_jwt_payload(creds.get("access_token", ""))
            account_id = creds.get("account_id", payload.get("chatgpt_account_id", ""))
            snapshot = self.pool.quota.snapshot_for(opaque_account_key(account_id))
            quota = ({
                "primary": (
                    snapshot.primary.to_dict()
                    if snapshot.primary and snapshot.primary.window_minutes else None
                ),
                "secondary": (
                    snapshot.secondary.to_dict()
                    if snapshot.secondary and snapshot.secondary.window_minutes else None
                ),
                "observed_at": snapshot.observed_at,
                "limit_reached_type": snapshot.limit_reached_type,
            } if snapshot is not None else None)
            expires = creds.get("expires_at", 0)
            accounts.append({
                "index": index, "label": creds.get("label", ""),
                "email": creds.get("email", payload.get("email", "unknown")),
                "account_id": account_id,
                "plan_type": creds.get("plan_type", payload.get("chatgpt_plan_type", "")),
                "expires_at": expires, "expired": time.time() >= expires,
                "rate_limited": auth.is_rate_limited(),
                "is_current": index == self.pool._current_index,
                "quota": quota,
                "limit_reached": bool(snapshot and (
                    any(window is not None and window.used_percent >= 100
                        for window in (snapshot.primary, snapshot.secondary))
                    or (snapshot.limit_reached_type and not any(
                        window is not None for window in (snapshot.primary, snapshot.secondary))))),
                "quota_check_failed": self.pool.quota_check_failure(index),
            })
        return {"configured": True, "account_count": self.pool.account_count,
                "current_index": self.pool._current_index, "accounts": accounts}

    @staticmethod
    def _index(params):
        index = params.get("index")
        if type(index) is not int or index < 0:
            raise _error("bad_request", "invalid account index")
        return index

    async def _refresh(self, params):
        # The pinned route parses its path index with int(), unlike the other
        # existing Desktop mutations. Keep that conversion for this action.
        try:
            index = int(params.get("index"))
        except (ValueError, TypeError, OverflowError):
            raise _error("bad_request", "index must be an integer") from None
        if self.providers is not None:
            client = getattr(self.providers, "codex_client", None)
            pool = getattr(client, "auth", None) if client is not None else None
        else:
            pool = self.pool
        if pool is None or not pool.account_count:
            raise _error("capability_unavailable", "codex not configured")
        if index < 0 or index >= len(pool._accounts):
            raise _error("bad_request", f"index {index} out of range")
        auth = pool._accounts[index]
        stale_token = auth._load().get("access_token")
        # Use the SAME pool and per-account refresh lock as serving traffic.
        # The retained owner settles a rotated single-use credential even if
        # the requesting task is cancelled. Never bypass it with OAuth here.
        if not await pool.force_refresh(index, stale_token):
            raise _error("unavailable", "credential refresh failed", "outcome_unknown")
        creds = auth._load()
        from ..observability.diagnostics import scrub_diagnostic

        return scrub_diagnostic({
            "status": "refreshed", "email": creds.get("email", "unknown"), "expired": False,
        })

    async def _mutate(self, method, params):
        index = self._index(params)
        if method == "codex.accounts.activate":
            try:
                await self.pool.set_active(index)
            except ValueError:
                raise _error("bad_request", "invalid account index") from None
            return {"status": "activated", "active_index": index}
        label = params.get("label", "")
        if method == "codex.accounts.label" and not isinstance(label, str):
            raise _error("bad_request", "label must be a string")
        async with self.pool._pool_lock:
            raw = self.vault.read()
            try:
                canonical = CodexAuthPool.canonical_index(raw, index)
            except ValueError:
                raise _error("bad_request", "invalid account index") from None
            rows = raw if isinstance(raw, list) else [raw]
            if method == "codex.accounts.label":
                rows[canonical]["label"] = label
                self.vault.write(rows if isinstance(raw, list) else rows[0])
                auth = self.pool._accounts[index]
                auth.expected["label"] = label
                if auth._credentials is not None:
                    auth._credentials["label"] = label
                return {"status": "updated", "label": label}
            removed = rows.pop(canonical)
            self.vault.write(rows)
            self.pool._accounts.clear()
            self.pool._manual_active_index = None
            self.pool._init_accounts()
            self.pool._current_index = min(
                self.pool._current_index, max(self.pool.account_count - 1, 0),
            )
        if self.providers is not None:
            await self.providers.reload_codex()
        return {"status": "deleted", "email": removed.get("email", "unknown")}

    async def _begin(self):
        result = await self.client.request_device_code()
        interval = max(1, int(result.get("interval", 5)))
        lifetime = float(result.get("expires_in", 900))
        auth_id, code = result["device_auth_id"], result["user_code"]
        if not isinstance(auth_id, str) or not auth_id or not isinstance(code, str) or not code:
            raise ValueError("Invalid device code")
        now = time.monotonic()
        self._logins[auth_id] = _Login(code, interval, now + lifetime, now + interval)
        return {"device_auth_id": auth_id, "user_code": code, "interval": interval,
                "verify_url": result.get("verify_url", DEVICE_VERIFY_URL)}

    async def _poll(self, params):
        auth_id, code = params.get("device_auth_id"), params.get("user_code")
        if not isinstance(auth_id, str) or not auth_id or not isinstance(code, str) or not code:
            raise _error("bad_request", "device_auth_id and user_code required")
        login = self._logins.get(auth_id)
        if login is None or login.code != code:
            raise _error("not_found", "no such login")
        save_index = params.get("save_index")
        if save_index is not None:
            try:
                save_index = int(save_index)
            except (TypeError, ValueError):
                raise _error("bad_request", "save_index must be an integer") from None
            if save_index < 0:
                raise _error("bad_request", "invalid account index")
        async with login.lock:
            if login.done is not None:
                return dict(login.done)
            if time.monotonic() >= login.deadline:
                login.credentials = None
                raise _error("expired", "The login code expired. Start again.")
            if login.credentials is None:
                if time.monotonic() < login.next_poll:
                    return {"status": "pending"}
                login.next_poll = time.monotonic() + login.interval
                login.credentials = await self.client.poll_device_auth_once(auth_id, code)
                if time.monotonic() >= login.deadline:
                    login.credentials = None
                    raise _error("expired", "The login code expired. Start again.")
                if login.credentials is None:
                    return {"status": "pending"}
            if time.monotonic() >= login.deadline:
                login.credentials = None
                raise _error("expired", "The login code expired. Start again.")
            if self._closed:
                raise _error("unavailable", "Codex account service is closed")
            creds = login.credentials
            if not isinstance(creds, dict) or not creds.get("access_token"):
                raise ValueError("Invalid credentials")
            async with self.pool._pool_lock:
                raw = self.vault.read()
                if save_index is None:
                    rows = merge_authorized_account(raw, creds)
                else:
                    rows = list(raw) if isinstance(raw, list) else [raw]
                    authorized = mark_authorized_account(creds)
                    try:
                        canonical = CodexAuthPool.canonical_index(raw, save_index)
                    except ValueError:
                        rows.append(authorized)
                    else:
                        if "label" in rows[canonical]:
                            authorized["label"] = rows[canonical]["label"]
                        rows[canonical] = authorized
                self.vault.write(rows)
                self.pool._accounts.clear()
                self.pool._manual_active_index = None
                self.pool._init_accounts()
                self.pool._current_index = min(
                    self.pool._current_index, max(self.pool.account_count - 1, 0),
                )
            if self.providers is not None:
                await self.providers.reload_codex()
            login.done = {"status": "authenticated", "email": creds.get("email", "unknown"),
                          "account_id": creds.get("account_id", "")}
            login.credentials = None
            return dict(login.done)

    async def close(self):
        """Internal lifecycle cancellation, not an invented protocol method."""
        self._closed = True
        tasks = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._logins.clear()
