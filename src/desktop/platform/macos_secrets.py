"""The profile's secrets in the login Keychain, as generic passwords (Security.framework).

Targeting: every call names one keychain, the login keychain at
~/Library/Keychains/login.keychain-db (tests inject a disposable one). Reads, updates and deletes
search only it (kSecMatchSearchList) and adds go only to it (kSecUseKeychain); the account's
default keychain and search list are never consulted or changed. A missing keychain is unavailable:
nothing here creates one, and unlock() never does.

Prompts: as with Linux's Secret Service backend, ordinary reads, writes and deletes never prompt.
User interaction is switched off for the process when this module loads, and every ordinary query
also asks for no authentication UI. Only unlock(), the owner's Retry, allows interaction, inside a
window no ordinary call overlaps: one that arrives meanwhile fails at once as pending, unlock()
waits for running ones first, and every path out of the window switches interaction off again.

Retry: a read refused without UI (a locked keychain, or an item whose access list does not name
this binary) is remembered. unlock() unlocks the keychain when it is locked, then repeats
exactly the remembered reads with interaction allowed, until the store's unlock deadline; after it,
no further prompt starts and nothing is published. A value read there is handed, once and for a
short window, to the next ordinary read of that item that is refused again, unless the item was
written or deleted since: "Allow Once" authorizes that one retrieval, so the recovery read after
Retry uses it instead of failing. Nothing else is kept.

Locked: every ordinary call first checks the named keychain's lock state and is refused while it is
locked, without an item call. On a locked keychain a write or delete can report success or "not
found" without happening (hosted macOS 26), so such an answer would prove nothing.

Failures: a missing item reads as None. Every other failure is a SecretStoreError, which the store
reports as it does on Linux, without native diagnostics. There is no file fallback.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import threading
import time
from pathlib import Path

from ..secrets import UNLOCK_TIMEOUT, SecretStoreError

if sys.platform != "darwin":
    raise ImportError("the Keychain backend is macOS-only")

_cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
_sec = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")

_UTF8 = 0x08000100
ERR_SUCCESS = 0
ERR_NOT_FOUND = -25300
ERR_DUPLICATE = -25299
ERR_NO_SUCH_KEYCHAIN = -25294
ERR_INTERACTION_NOT_ALLOWED = -25308
ERR_INTERACTION_REQUIRED = -25315
ERR_AUTH_FAILED = -25293
ERR_USER_CANCELED = -128
UNLOCKED = 1  # kSecUnlockStateStatus
HANDOFF_SECONDS = 30.0
LOGIN_KEYCHAIN = Path("Library") / "Keychains" / "login.keychain-db"

_cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
_cf.CFStringCreateWithCString.restype = ctypes.c_void_p
_cf.CFDataCreate.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long]
_cf.CFDataCreate.restype = ctypes.c_void_p
_cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
_cf.CFDataGetLength.restype = ctypes.c_long
_cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
_cf.CFDataGetBytePtr.restype = ctypes.c_void_p
_cf.CFDictionaryCreate.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_long,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_cf.CFDictionaryCreate.restype = ctypes.c_void_p
_cf.CFArrayCreate.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_long,
    ctypes.c_void_p,
]
_cf.CFArrayCreate.restype = ctypes.c_void_p
_cf.CFRelease.argtypes = [ctypes.c_void_p]
_cf.CFRelease.restype = None
for _name in ("SecItemCopyMatching", "SecItemAdd"):
    getattr(_sec, _name).argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    getattr(_sec, _name).restype = ctypes.c_int32
_sec.SecItemUpdate.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_sec.SecItemUpdate.restype = ctypes.c_int32
_sec.SecItemDelete.argtypes = [ctypes.c_void_p]
_sec.SecItemDelete.restype = ctypes.c_int32
_sec.SecKeychainSetUserInteractionAllowed.argtypes = [ctypes.c_bool]
_sec.SecKeychainSetUserInteractionAllowed.restype = ctypes.c_int32
_sec.SecKeychainOpen.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
_sec.SecKeychainOpen.restype = ctypes.c_int32
_sec.SecKeychainGetStatus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
_sec.SecKeychainGetStatus.restype = ctypes.c_int32
_sec.SecKeychainUnlock.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_bool]
_sec.SecKeychainUnlock.restype = ctypes.c_int32


def _constant(library, name: str) -> int:
    return ctypes.c_void_p.in_dll(library, name).value


_KEY_CALLBACKS = ctypes.addressof(ctypes.c_void_p.in_dll(_cf, "kCFTypeDictionaryKeyCallBacks"))
_VALUE_CALLBACKS = ctypes.addressof(ctypes.c_void_p.in_dll(_cf, "kCFTypeDictionaryValueCallBacks"))
_ARRAY_CALLBACKS = ctypes.addressof(ctypes.c_void_p.in_dll(_cf, "kCFTypeArrayCallBacks"))
_TRUE = _constant(_cf, "kCFBooleanTrue")
_K = {
    name: _constant(_sec, name)
    for name in (
        "kSecClass",
        "kSecClassGenericPassword",
        "kSecAttrService",
        "kSecAttrAccount",
        "kSecAttrLabel",
        "kSecValueData",
        "kSecReturnData",
        "kSecMatchLimit",
        "kSecMatchLimitOne",
        "kSecMatchSearchList",
        "kSecUseKeychain",
        "kSecUseAuthenticationUI",
        "kSecUseAuthenticationUIFail",
    )
}
# What an ordinary (no-UI) call gets from a locked keychain or an item that would need the owner:
# macOS 26 answers a locked keychain with errSecAuthFailed. No dialog was shown, so it is never a
# Deny here; only an answer during Retry's interactive reads can be the owner's denial.
_REFUSED_WITHOUT_UI = (ERR_INTERACTION_NOT_ALLOWED, ERR_INTERACTION_REQUIRED, ERR_AUTH_FAILED)


class _InteractionGate:
    """Process-wide: no ordinary call overlaps unlock()'s window of allowed interaction."""

    def __init__(self):
        self._condition = threading.Condition()
        self._active = 0
        self._unlocking = False

    @contextlib.contextmanager
    def ordinary(self):
        with self._condition:
            if self._unlocking:
                raise SecretStoreError("Profile keyring unlock is still pending")
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def begin_unlock(self):
        with self._condition:
            if self._unlocking:
                raise SecretStoreError("Profile keyring unlock is still pending")
            self._unlocking = True
            self._condition.wait_for(lambda: self._active == 0)

    def end_unlock(self):
        with self._condition:
            self._unlocking = False
            self._condition.notify_all()


_gate = _InteractionGate()
# Off for the whole process from the first use on; only unlock() switches it on, inside its window.
_sec.SecKeychainSetUserInteractionAllowed(False)


class _Owned:
    """CoreFoundation objects created for one call, released together."""

    def __init__(self):
        self.objects: list[int] = []

    def keep(self, value):
        if not value:
            raise SecretStoreError("Profile keyring call could not be prepared")
        self.objects.append(value)
        return value

    def string(self, text: str) -> int:
        return self.keep(_cf.CFStringCreateWithCString(None, text.encode("utf-8"), _UTF8))

    def data(self, value: bytes) -> int:
        return self.keep(_cf.CFDataCreate(None, value, len(value)))

    def dictionary(self, pairs: dict[int, int]) -> int:
        keys = (ctypes.c_void_p * len(pairs))(*pairs.keys())
        values = (ctypes.c_void_p * len(pairs))(*pairs.values())
        return self.keep(
            _cf.CFDictionaryCreate(None, keys, values, len(pairs), _KEY_CALLBACKS, _VALUE_CALLBACKS)
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for value in reversed(self.objects):
            _cf.CFRelease(value)


def _failure(status: int, action: str, *, interactive: bool = False) -> SecretStoreError:
    if interactive and status in (ERR_AUTH_FAILED, ERR_USER_CANCELED):
        return SecretStoreError(f"Profile keyring {action} was denied")
    if status in _REFUSED_WITHOUT_UI:
        return SecretStoreError(f"Profile keyring {action} requires owner interaction or is locked")
    return SecretStoreError(f"Profile keyring {action} failed (OSStatus {status})")


class KeychainBackend:
    """Generic passwords in one named keychain, keyed by the profile's service and the name."""

    def __init__(self, keychain_path: str | os.PathLike | None = None):
        path = Path(keychain_path) if keychain_path is not None else Path.home() / LOGIN_KEYCHAIN
        keychain = ctypes.c_void_p()
        if _sec.SecKeychainOpen(os.fsencode(path), ctypes.byref(keychain)) != ERR_SUCCESS:
            raise SecretStoreError("Profile keyring is unavailable")
        state = ctypes.c_uint32()
        # A missing keychain fails here (errSecNoSuchKeychain): it is never created.
        if not keychain.value or _sec.SecKeychainGetStatus(
            keychain, ctypes.byref(state)
        ) != ERR_SUCCESS:
            if keychain.value:
                _cf.CFRelease(keychain)
            raise SecretStoreError("Profile keyring is unavailable")
        search = _cf.CFArrayCreate(
            None, (ctypes.c_void_p * 1)(keychain.value), 1, _ARRAY_CALLBACKS
        )
        if not search:
            _cf.CFRelease(keychain)
            raise SecretStoreError("Profile keyring is unavailable")
        self._keychain = keychain.value
        self._search = search
        self._lock = threading.Lock()  # guards the three maps below
        self._refused: set[tuple[str, str]] = set()
        self._generation: dict[tuple[str, str], int] = {}
        self._handoff: dict[tuple[str, str], tuple[str, int, float]] = {}

    def __del__(self):
        for name in ("_search", "_keychain"):
            value = getattr(self, name, None)
            if value:
                _cf.CFRelease(value)
                setattr(self, name, None)

    def _query(
        self, owned: _Owned, service: str, name: str, *, interactive: bool = False, **extra: int
    ) -> int:
        pairs = {
            _K["kSecClass"]: _K["kSecClassGenericPassword"],
            _K["kSecAttrService"]: owned.string(service),
            _K["kSecAttrAccount"]: owned.string(name),
            _K["kSecMatchSearchList"]: self._search,
        }
        if not interactive:
            pairs[_K["kSecUseAuthenticationUI"]] = _K["kSecUseAuthenticationUIFail"]
        pairs.update({_K[key]: value for key, value in extra.items()})
        return owned.dictionary(pairs)

    def _copy(self, service: str, name: str, *, interactive: bool) -> tuple[int, str | None]:
        with _Owned() as owned:
            query = self._query(
                owned,
                service,
                name,
                interactive=interactive,
                kSecReturnData=_TRUE,
                kSecMatchLimit=_K["kSecMatchLimitOne"],
            )
            result = ctypes.c_void_p()
            status = _sec.SecItemCopyMatching(query, ctypes.byref(result))
            if status != ERR_SUCCESS:
                return status, None
            owned.keep(result.value)
            length = _cf.CFDataGetLength(result.value)
            data = ctypes.string_at(_cf.CFDataGetBytePtr(result.value), length)
            return status, data.decode("utf-8")

    def _note(self, key: tuple[str, str], status: int, *, changed: bool = False) -> None:
        with self._lock:
            if changed:
                self._generation[key] = self._generation.get(key, 0) + 1
                self._handoff.pop(key, None)
            if status in _REFUSED_WITHOUT_UI:
                self._refused.add(key)
            elif status in (ERR_SUCCESS, ERR_NOT_FOUND):
                self._refused.discard(key)

    def _refuse_if_locked(self, key: tuple[str, str] | None, action: str) -> None:
        """Ordinary calls never touch a locked keychain: there, a write or delete can report
        success or "not found" without happening (hosted macOS 26), so its answer proves nothing.
        A refused read is remembered for Retry."""
        state = ctypes.c_uint32()
        if _sec.SecKeychainGetStatus(self._keychain, ctypes.byref(state)) != ERR_SUCCESS:
            raise SecretStoreError("Profile keyring is unavailable")
        if not state.value & UNLOCKED:
            if key is not None:
                self._note(key, ERR_INTERACTION_NOT_ALLOWED)
            raise _failure(ERR_INTERACTION_NOT_ALLOWED, action)

    def _take_handoff(self, key: tuple[str, str]) -> str | None:
        with self._lock:
            entry = self._handoff.pop(key, None)
            if entry is None:
                return None
            value, generation, expires = entry
            if time.monotonic() > expires or self._generation.get(key, 0) != generation:
                return None
            return value

    def get_password(self, service: str, name: str) -> str | None:
        key = (service, name)
        with _gate.ordinary():
            try:
                self._refuse_if_locked(key, "read")
            except SecretStoreError:
                handed = self._take_handoff(key)
                if handed is not None:
                    return handed
                raise
            status, value = self._copy(service, name, interactive=False)
        self._note(key, status)
        if status in _REFUSED_WITHOUT_UI:
            handed = self._take_handoff(key)
            if handed is not None:
                return handed
        elif status == ERR_SUCCESS:
            with self._lock:
                self._handoff.pop(key, None)  # the keychain's own answer replaces it
        if status == ERR_NOT_FOUND:
            return None
        if status != ERR_SUCCESS:
            raise _failure(status, "read")
        return value

    def set_password(self, service: str, name: str, value: str) -> None:
        with _gate.ordinary():
            self._refuse_if_locked(None, "write")
            status = self._store(service, name, value)
        self._note((service, name), status, changed=True)
        if status != ERR_SUCCESS:
            raise _failure(status, "write")

    def _store(self, service: str, name: str, value: str) -> int:
        with _Owned() as owned:
            secret = owned.data(value.encode("utf-8"))
            query = self._query(owned, service, name)
            status = _sec.SecItemUpdate(query, owned.dictionary({_K["kSecValueData"]: secret}))
            if status == ERR_NOT_FOUND:
                label = owned.string(f"Password for '{name}' on '{service}'")
                attributes = owned.dictionary(
                    {
                        _K["kSecClass"]: _K["kSecClassGenericPassword"],
                        _K["kSecAttrService"]: owned.string(service),
                        _K["kSecAttrAccount"]: owned.string(name),
                        _K["kSecAttrLabel"]: label,
                        _K["kSecValueData"]: secret,
                        _K["kSecUseKeychain"]: self._keychain,
                        _K["kSecUseAuthenticationUI"]: _K["kSecUseAuthenticationUIFail"],
                    }
                )
                status = _sec.SecItemAdd(attributes, None)
                if status == ERR_DUPLICATE:  # created concurrently: update it instead
                    status = _sec.SecItemUpdate(
                        query, owned.dictionary({_K["kSecValueData"]: secret})
                    )
            return status

    def delete_password(self, service: str, name: str) -> None:
        with _gate.ordinary(), _Owned() as owned:
            self._refuse_if_locked(None, "deletion")
            status = _sec.SecItemDelete(self._query(owned, service, name))
        self._note((service, name), status, changed=True)
        if status not in (ERR_SUCCESS, ERR_NOT_FOUND):
            raise _failure(status, "deletion")

    def unlock(self) -> bool:
        """The owner's Retry: the only call that may show a system dialog.

        It unlocks the keychain when it is locked, then repeats the reads that were refused for
        interaction, with interaction allowed, so the system can ask the owner for access. After
        the store's unlock deadline it starts no further prompt and hands nothing on.
        """
        deadline = time.monotonic() + UNLOCK_TIMEOUT
        _gate.begin_unlock()
        try:
            _sec.SecKeychainSetUserInteractionAllowed(True)
            try:
                read = self._unlock_with_interaction(deadline)
            finally:
                _sec.SecKeychainSetUserInteractionAllowed(False)
        finally:
            _gate.end_unlock()
        if time.monotonic() > deadline:
            raise SecretStoreError("Profile keyring unlock finished after its deadline")
        expires = time.monotonic() + HANDOFF_SECONDS
        with self._lock:
            for key, (value, generation) in read.items():
                if self._generation.get(key, 0) == generation:
                    self._handoff[key] = (value, generation, expires)
        return True

    def _unlock_with_interaction(self, deadline: float) -> dict:
        state = ctypes.c_uint32()
        if _sec.SecKeychainGetStatus(self._keychain, ctypes.byref(state)) != ERR_SUCCESS:
            raise SecretStoreError("Profile keyring is unavailable")
        if not state.value & UNLOCKED:
            if _sec.SecKeychainUnlock(self._keychain, 0, None, False) != ERR_SUCCESS:
                raise SecretStoreError("Profile keyring remains locked")
        with self._lock:
            pending = sorted(self._refused)
            generations = {key: self._generation.get(key, 0) for key in pending}
        read = {}
        for key in pending:
            if time.monotonic() > deadline:
                break  # the Retry's authority has expired: no further prompt
            status, value = self._copy(*key, interactive=True)
            self._note(key, status)
            if status == ERR_SUCCESS:
                read[key] = (value, generations[key])
            elif status != ERR_NOT_FOUND:
                raise _failure(status, "access", interactive=True)
        return read
