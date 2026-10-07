"""Profile credentials in the Linux keyring, never in a fallback vault file."""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from contextlib import closing
from contextvars import ContextVar

from .paths import ProfilePaths


class SecretStoreError(RuntimeError):
    """The keyring is unavailable, locked, or rejected an operation."""


class StartupSecretCalls:
    """Retain startup worker settlement without weakening transactional callers."""

    def __init__(self):
        self.pending = set()
        self.errors = set()
        self.started = False
        self.active = True

    def track(self, future):
        self.started = True
        self.pending.add(future)

        def settled(done):
            self.pending.discard(done)
            if not done.cancelled() and (error := done.exception()) is not None:
                self.errors.add(type(error).__name__)

        future.add_done_callback(settled)

    async def settle(self, timeout):
        if self.pending:
            await asyncio.wait(self.pending, timeout=timeout)

    def outcome(self):
        if self.pending or self.errors:
            return {"state": "unknown", "pending": len(self.pending),
                    "error_types": sorted(self.errors)}
        return {"state": "released" if self.started else "not_started"}


startup_secret_calls: ContextVar[StartupSecretCalls | None] = ContextVar(
    "startup_secret_calls", default=None,
)


async def secret_call(function, *args, **kwargs):
    """Daemon I/O, settled before cancellation reaches transaction rollback.

    Never use the loop's executor: a never-answer native prompt must not make
    asyncio.run hang joining its default executor during process shutdown.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    startup = startup_secret_calls.get()
    if startup is not None and not startup.active:
        startup = None
    if startup is not None:
        startup.track(future)

    def deliver(value, error):
        if not future.done():
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(value)

    def run():
        try:
            value, error = function(*args, **kwargs), None
        except BaseException as exc:
            value, error = None, exc
        try:
            loop.call_soon_threadsafe(deliver, value, error)
        except RuntimeError:
            pass

    threading.Thread(target=run, name="desktop-secret", daemon=True).start()
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(future)
            if cancelled:
                raise asyncio.CancelledError
            return result
        except asyncio.CancelledError:
            if startup is not None:
                # Only the explicitly supervised startup scope may retire its
                # await. The daemon and its eventual outcome remain accounted
                # for; ordinary transaction rollback still waits for settlement.
                raise
            if future.done():
                if not future.cancelled():
                    # Settlement failure wins over cancellation. Merely
                    # retrieving it would let rollback callers mistake an
                    # uncertain vault effect for successful restoration.
                    future.result()
                raise
            cancelled = True


UNLOCK_TIMEOUT = 10.0


class _SecretServiceBackend:
    """Direct existing collection access, never Keyring's automatic unlock.

    A relock after the check raises LockedException instead of prompting.
    Missing default collections are not created (creation also prompts).
    Every operation owns its connection, so workers never share a D-Bus socket.
    """

    def _call(self, operation):
        import secretstorage

        with closing(secretstorage.dbus_init()) as bus:
            collection = secretstorage.Collection(bus)
            if collection.is_locked():
                raise SecretStoreError("Profile keyring is locked")
            return operation(collection)

    @staticmethod
    def _query(service, name):
        return {"service": service, "username": name}

    def get_password(self, service, name):
        def read(collection):
            for item in collection.search_items(self._query(service, name)):
                if item.is_locked():
                    raise SecretStoreError("Profile credential is locked")
                return item.get_secret().decode("utf-8")
            return None
        return self._call(read)

    def set_password(self, service, name, value):
        def write(collection):
            # Collection.create_item executes a returned native prompt. Use
            # its wire operation, never exec_prompt, even if relocking races
            # the locked-state check. Only secrets.unlock may call Prompt.
            from secretstorage.defines import SS_PREFIX
            from secretstorage.util import format_secret, open_session

            collection.ensure_not_locked()
            if not collection.session:
                collection.session = open_session(collection.connection)
            properties = {
                SS_PREFIX + "Item.Label": ("s", f"Password for '{name}' on '{service}'"),
                SS_PREFIX + "Item.Attributes": ("a{ss}", self._query(service, name)
                                                | {"application": "Python keyring library"}),
            }
            item, prompt = collection._collection.call(
                "CreateItem", "a{sv}(oayays)b", properties,
                format_secret(collection.session, value.encode("utf-8"), "text/plain"), True,
            )
            if prompt != "/" or item == "/":
                raise SecretStoreError("Profile keyring write requires owner interaction")
        return self._call(write)

    def delete_password(self, service, name):
        def delete(collection):
            for item in collection.search_items(self._query(service, name)):
                if item.is_locked():
                    raise SecretStoreError("Profile credential is locked")
                # Item.delete also executes prompts. Never start them here.
                item.ensure_not_locked()
                prompt, = item._item.call("Delete", "")
                if prompt != "/":
                    raise SecretStoreError("Profile keyring deletion requires owner interaction")
                return
        return self._call(delete)

    def unlock(self):
        import secretstorage

        with closing(secretstorage.dbus_init()) as bus:
            collection = secretstorage.Collection(bus)
            if collection.is_locked():
                # Bound the caller, not SecretStorage's prompt receiver. Its
                # timeout does not Dismiss the native prompt; keeping this
                # daemon waiting retains the duplicate-prompt guard until the
                # user actually accepts/dismisses (or the connection fails).
                collection.unlock()
            if collection.is_locked():
                raise SecretStoreError("Profile keyring remains locked")
            return True


class ProfileSecretStore:
    """Lazy Secret Service adapter with an injectable isolated-test backend."""

    def __init__(self, paths: ProfilePaths, *, backend=None):
        self.paths = paths
        identity = str(paths.config_dir.absolute()).encode("utf-8")
        self.namespace = (
            f"odin-desktop:{paths.profile_id}:{hashlib.sha256(identity).hexdigest()[:24]}"
        )
        self.durability_degraded = False
        self._backend = backend
        self._unlock_guard = threading.Lock()
        self._unlock_pending = False

    def _name(self, name):
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,511}", name
        ):
            raise ValueError("invalid secret identifier")
        return name

    def _adapter(self):
        if self._backend is None:
            try:
                self._backend = _SecretServiceBackend()
            except Exception:
                raise SecretStoreError("Profile keyring is unavailable") from None
        return self._backend

    async def unlock(self):
        """Explicit Retry only; bounded wait and at most one outstanding prompt.

        A timeout/cancel does not prove the native prompt's outcome. A late
        worker never rehydrates configuration and suppresses duplicate prompts
        until it finishes. It is a daemon, not an executor shutdown dependency.
        """
        with self._unlock_guard:
            if self._unlock_pending:
                raise SecretStoreError("Profile keyring unlock is still pending")
            self._unlock_pending = True

        def attempt():
            try:
                backend = self._adapter()
                hook = getattr(backend, "unlock", None)
                if hook is not None:
                    if hook() is not True:
                        raise SecretStoreError("Profile keyring unlock failed")
                else:
                    backend.get_password(self.namespace, "codex_accounts")
                return True
            finally:
                with self._unlock_guard:
                    self._unlock_pending = False

        # Unlock is abandonable, unlike transactional writes. Do not wrap a
        # cancellation-settled secret_call in a Task: asyncio.run gathers all
        # cancelled tasks at exit, which would wait forever for this prompt.
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def deliver(value, error):
            if not future.done():
                if error is None:
                    future.set_result(value)
                else:
                    future.set_exception(SecretStoreError(
                        "Profile keyring is unavailable or locked",
                    ))

        def run():
            try:
                value, error = attempt(), None
            except Exception as exc:
                value, error = None, exc
            try:
                loop.call_soon_threadsafe(deliver, value, error)
            except RuntimeError:
                pass

        threading.Thread(target=run, name="desktop-secret-unlock", daemon=True).start()
        try:
            return await asyncio.wait_for(future, UNLOCK_TIMEOUT)
        except (TimeoutError, asyncio.CancelledError):
            raise
        except Exception:
            raise SecretStoreError("Profile keyring is unavailable or locked") from None

    def set(self, name, value) -> bool:
        name = self._name(name)
        if not isinstance(value, str) or len(value.encode("utf-8")) > 65536:
            raise ValueError("secret must be a bounded string")
        try:
            self._adapter().set_password(self.namespace, name, value)
        except Exception:
            raise SecretStoreError(
                "Profile keyring could not store the credential (unavailable or locked)"
            ) from None
        return True

    def get(self, name):
        name = self._name(name)
        try:
            value = self._adapter().get_password(self.namespace, name)
            if value is not None and not isinstance(value, str):
                raise TypeError
            return value
        except Exception:
            raise SecretStoreError(
                "Profile keyring could not read the credential (unavailable or locked)"
            ) from None

    def delete(self, name) -> bool:
        name = self._name(name)
        try:
            adapter = self._adapter()
            if adapter.get_password(self.namespace, name) is not None:
                adapter.delete_password(self.namespace, name)
        except Exception:
            raise SecretStoreError(
                "Profile keyring could not clear the credential (unavailable or locked)"
            ) from None
        return True

    clear = delete
