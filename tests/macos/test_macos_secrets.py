"""The Keychain backend.

The logic tests replace the native calls with recording fakes, so they touch no keychain and run
anywhere on macOS. The item tests write to a keychain, so they run only where the CI job made a
disposable one, named explicitly and kept out of the account's search list.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
import uuid

import pytest

from src.desktop.platform import macos_secrets
from src.desktop.secrets import SecretStoreError

disposable_keychain = pytest.mark.skipif(
    os.environ.get("ODIN_MACOS_DISPOSABLE_KEYCHAIN") != "1",
    reason="needs the CI job's disposable keychain",
)
REFUSED = macos_secrets.ERR_INTERACTION_NOT_ALLOWED


# --- The interaction gate --------------------------------------------------------------------


def test_an_ordinary_call_during_unlock_fails_at_once_as_pending():
    gate = macos_secrets._InteractionGate()
    gate.begin_unlock()
    try:
        with pytest.raises(SecretStoreError, match="still pending"):
            with gate.ordinary():
                pass
        with pytest.raises(SecretStoreError, match="still pending"):
            gate.begin_unlock()
    finally:
        gate.end_unlock()
    with gate.ordinary():
        pass


def test_unlock_waits_for_running_ordinary_calls():
    gate = macos_secrets._InteractionGate()
    order = []
    entered = threading.Event()

    def ordinary():
        with gate.ordinary():
            entered.set()
            time.sleep(0.3)
            order.append("ordinary done")

    worker = threading.Thread(target=ordinary)
    worker.start()
    entered.wait(5)
    gate.begin_unlock()
    order.append("unlock began")
    gate.end_unlock()
    worker.join(5)
    assert order == ["ordinary done", "unlock began"]


@pytest.mark.parametrize("status,interactive,text", [
    (macos_secrets.ERR_INTERACTION_NOT_ALLOWED, False, "requires owner interaction or is locked"),
    (macos_secrets.ERR_INTERACTION_REQUIRED, False, "requires owner interaction or is locked"),
    # A locked keychain answers a no-UI call this way (hosted macOS 26): not a Deny.
    (macos_secrets.ERR_AUTH_FAILED, False, "requires owner interaction or is locked"),
    (macos_secrets.ERR_AUTH_FAILED, True, "was denied"),
    (macos_secrets.ERR_USER_CANCELED, True, "was denied"),
    (macos_secrets.ERR_USER_CANCELED, False, "failed (OSStatus -128)"),
    (-34018, False, "failed (OSStatus -34018)"),
])
def test_keychain_statuses_stay_distinct_in_the_backend(status, interactive, text):
    assert text in str(macos_secrets._failure(status, "read", interactive=interactive))


# --- The backend's logic, over recording fakes -----------------------------------------------


class FakeSecurity:
    """The Security calls the backend makes, with the process's interaction switch recorded."""

    def __init__(self, *, locked=False, unlock_status=0, delete_status=0):
        self.interaction = False
        self.locked = locked
        self.unlock_status = unlock_status
        self.delete_status = delete_status
        self.unlocks = 0
        self.native = []  # (call, interaction allowed at that moment)

    def SecKeychainSetUserInteractionAllowed(self, allowed):  # noqa: N802 - native names
        self.interaction = bool(allowed)
        return 0

    def SecKeychainGetStatus(self, keychain, state):  # noqa: N802
        state._obj.value = 0 if self.locked else macos_secrets.UNLOCKED
        return 0

    def SecKeychainUnlock(self, keychain, length, password, use):  # noqa: N802
        self.native.append(("unlock", self.interaction))
        self.unlocks += 1
        if self.unlock_status == 0:
            self.locked = False
        return self.unlock_status

    def SecItemDelete(self, query):  # noqa: N802
        self.native.append(("delete", self.interaction))
        return self.delete_status


def _cf_object(text: str) -> int:
    return macos_secrets._cf.CFStringCreateWithCString(None, text.encode(), macos_secrets._UTF8)


@pytest.fixture
def fake(monkeypatch):
    """A backend over fakes: ``reads`` scripts each _copy, ``stores`` each _store."""
    security = FakeSecurity()
    monkeypatch.setattr(macos_secrets, "_sec", security)
    monkeypatch.setattr(macos_secrets, "_gate", macos_secrets._InteractionGate())
    backend = macos_secrets.KeychainBackend.__new__(macos_secrets.KeychainBackend)
    keychain = _cf_object("stand-in keychain")
    backend._keychain = keychain
    backend._search = macos_secrets._cf.CFArrayCreate(
        None, (ctypes.c_void_p * 1)(keychain), 1, macos_secrets._ARRAY_CALLBACKS)
    backend._lock = threading.Lock()
    backend._refused, backend._generation, backend._handoff = set(), {}, {}
    reads, calls, stores = [], [], []

    def copy(service, name, *, interactive):
        calls.append(((service, name), interactive, security.interaction))
        step = reads.pop(0)
        return step() if callable(step) else step

    monkeypatch.setattr(backend, "_copy", copy)
    monkeypatch.setattr(backend, "_store", lambda service, name, value: stores.pop(0))
    yield backend, security, reads, calls, stores
    backend.__del__()


def test_ordinary_reads_never_ask_and_refusals_are_remembered(fake):
    backend, security, reads, calls, _ = fake
    reads.extend([(REFUSED, None), (macos_secrets.ERR_AUTH_FAILED, None),
                  (macos_secrets.ERR_NOT_FOUND, None), (0, "kept")])
    for name in ("a", "locked"):
        with pytest.raises(SecretStoreError, match="requires owner interaction or is locked"):
            backend.get_password("s", name)
    assert backend.get_password("s", "b") is None
    assert backend.get_password("s", "c") == "kept"
    assert [interactive for _, interactive, _ in calls] == [False] * 4
    assert not any(allowed for _, _, allowed in calls)
    assert backend._refused == {("s", "a"), ("s", "locked")}


def test_retry_repeats_only_the_refused_reads_with_interaction_then_switches_it_off(fake):
    backend, security, reads, calls, _ = fake
    security.locked = True
    with pytest.raises(SecretStoreError, match="requires owner interaction or is locked"):
        backend.get_password("s", "a")  # refused before any item call
    assert calls == [] and backend._refused == {("s", "a")}
    reads.append((0, "granted"))
    assert backend.unlock() is True
    assert security.native == [("unlock", True)]
    assert calls[-1] == (("s", "a"), True, True)  # the remembered read, interactive
    assert security.interaction is False
    assert backend._refused == set()


@pytest.mark.parametrize("call", ["write", "delete"])
def test_a_locked_keychain_refuses_writes_and_deletes_before_any_item_call(fake, call):
    backend, security, reads, calls, stores = fake
    security.locked = True
    with pytest.raises(SecretStoreError, match="requires owner interaction or is locked"):
        if call == "write":
            backend.set_password("s", "a", "v")
        else:
            backend.delete_password("s", "a")
    assert security.native == [] and stores == []  # no item call: its answer would prove nothing


def test_allow_once_hands_the_value_to_the_recovery_read_exactly_once(fake):
    backend, security, reads, calls, _ = fake
    reads.extend([(REFUSED, None), (0, "once")])
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")
    backend.unlock()
    reads.extend([(REFUSED, None), (REFUSED, None)])  # Allow Once: still refused afterwards
    assert backend.get_password("s", "a") == "once"
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")  # consumed: never served twice
    assert ("s", "a") in backend._refused  # the next Retry asks again


def test_always_allow_reads_the_keychain_itself_and_drops_the_handoff(fake):
    backend, security, reads, calls, _ = fake
    reads.extend([(REFUSED, None), (0, "from retry")])
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")
    backend.unlock()
    reads.extend([(0, "from keychain"), (REFUSED, None)])
    assert backend.get_password("s", "a") == "from keychain"
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")  # the Retry value was dropped, not kept


def test_deny_during_retry_fails_and_hands_nothing_on(fake):
    backend, security, reads, calls, _ = fake
    reads.extend([(REFUSED, None), (macos_secrets.ERR_AUTH_FAILED, None)])
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")
    with pytest.raises(SecretStoreError, match="access was denied"):
        backend.unlock()
    assert backend._handoff == {} and security.interaction is False


def test_a_write_or_delete_after_retry_voids_its_value(fake):
    backend, security, reads, calls, stores = fake
    reads.extend([(REFUSED, None), (REFUSED, None), (0, "a1"), (0, "b1")])
    for name in ("a", "b"):
        with pytest.raises(SecretStoreError):
            backend.get_password("s", name)
    backend.unlock()
    stores.append(0)
    backend.set_password("s", "a", "a2")
    backend.delete_password("s", "b")
    reads.extend([(REFUSED, None), (REFUSED, None)])
    for name in ("a", "b"):
        with pytest.raises(SecretStoreError):
            backend.get_password("s", name)  # no stale Retry value after a change


def test_the_handoff_expires(fake, monkeypatch):
    backend, security, reads, calls, _ = fake
    reads.extend([(REFUSED, None), (0, "late")])
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")
    backend.unlock()
    now = time.monotonic()
    monkeypatch.setattr(macos_secrets.time, "monotonic",
                        lambda: now + macos_secrets.HANDOFF_SECONDS + 1)
    reads.append((REFUSED, None))
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")


def test_a_late_retry_starts_no_further_prompt_and_publishes_nothing(fake, monkeypatch):
    backend, security, reads, calls, _ = fake
    reads.extend([(REFUSED, None), (REFUSED, None)])
    for name in ("a", "b"):
        with pytest.raises(SecretStoreError):
            backend.get_password("s", name)
    monkeypatch.setattr(macos_secrets, "UNLOCK_TIMEOUT", 0.2)

    def slow_answer():
        time.sleep(0.4)  # the owner answers after the store has stopped waiting
        return 0, "late"

    reads.append(slow_answer)
    with pytest.raises(SecretStoreError, match="after its deadline"):
        backend.unlock()
    assert [key for key, interactive, _ in calls if interactive] == [("s", "a")]  # b never asked
    assert backend._handoff == {} and security.interaction is False


def test_ordinary_calls_fail_fast_while_a_retry_prompt_is_pending(fake):
    backend, security, reads, calls, stores = fake
    reads.append((REFUSED, None))
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")
    asked, answer = threading.Event(), threading.Event()

    def pending_prompt():
        asked.set()
        answer.wait(10)
        return 0, "v"

    reads.append(pending_prompt)
    retry = threading.Thread(target=backend.unlock)
    retry.start()
    try:
        assert asked.wait(5)
        before = list(calls), list(security.native)
        for attempt in (lambda: backend.get_password("s", "x"),
                        lambda: backend.set_password("s", "x", "v"),
                        lambda: backend.delete_password("s", "x")):
            started = time.monotonic()
            with pytest.raises(SecretStoreError, match="still pending"):
                attempt()
            assert time.monotonic() - started < 1
        assert (list(calls), list(security.native)) == before  # nothing reached the keychain
        with pytest.raises(SecretStoreError, match="still pending"):
            backend.unlock()  # a duplicate Retry
    finally:
        answer.set()
        retry.join(10)
    assert security.interaction is False
    stores.append(0)
    backend.set_password("s", "x", "after")  # ordinary calls work again


@pytest.mark.parametrize("failure", ["unlock refused", "read raises"])
def test_every_way_out_of_retry_switches_interaction_off(fake, failure):
    backend, security, reads, calls, stores = fake
    reads.append((REFUSED, None))
    with pytest.raises(SecretStoreError):
        backend.get_password("s", "a")
    if failure == "unlock refused":
        security.locked, security.unlock_status = True, macos_secrets.ERR_USER_CANCELED
        expected = SecretStoreError
    else:
        def broken():
            raise RuntimeError("native failure")

        reads.append(broken)
        expected = RuntimeError
    with pytest.raises(expected):
        backend.unlock()
    assert security.interaction is False
    security.locked = False  # the owner unlocks it some other way
    stores.append(0)
    backend.set_password("s", "x", "v")  # the gate reopened


def test_queries_name_the_keychain_and_ask_for_no_ui(fake):
    backend = fake[0]
    get = macos_secrets._cf.CFDictionaryGetValue
    get.argtypes, get.restype = [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_void_p
    contains = macos_secrets._cf.CFDictionaryContainsKey
    contains.argtypes, contains.restype = [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_bool
    K = macos_secrets._K  # noqa: N806
    with macos_secrets._Owned() as owned:
        ordinary = backend._query(owned, "s", "n")
        assert get(ordinary, K["kSecMatchSearchList"]) == backend._search
        assert get(ordinary, K["kSecUseAuthenticationUI"]) == K["kSecUseAuthenticationUIFail"]
        interactive = backend._query(owned, "s", "n", interactive=True)
        assert get(interactive, K["kSecMatchSearchList"]) == backend._search
        assert not contains(interactive, K["kSecUseAuthenticationUI"])


def test_a_missing_keychain_is_unavailable_and_never_created(tmp_path):
    missing = tmp_path / "absent.keychain-db"
    with pytest.raises(SecretStoreError, match="unavailable"):
        macos_secrets.KeychainBackend(missing)
    assert not missing.exists()


def test_the_default_is_the_login_keychain_of_this_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # a home without one: unavailable, not created
    with pytest.raises(SecretStoreError, match="unavailable"):
        macos_secrets.KeychainBackend()
    assert not (tmp_path / "Library").exists()


# --- Real items in the CI job's disposable keychain ------------------------------------------


def _search_state():
    def run(*arguments):
        return subprocess.run(["security", *arguments], capture_output=True, text=True,
                              check=True).stdout

    return run("list-keychains", "-d", "user"), run("default-keychain", "-d", "user")


@pytest.fixture
def keychain():
    path = os.environ["ODIN_MACOS_DISPOSABLE_KEYCHAIN_PATH"]
    before = _search_state()
    assert path not in before[0]  # explicitly named, not found through the search list
    backend = macos_secrets.KeychainBackend(path)
    service = f"odin-desktop-test:{uuid.uuid4().hex}"
    yield backend, service, path
    for name in ("token", "other"):
        backend.delete_password(service, name)
    assert _search_state() == before  # nothing changed the account's keychain settings


@disposable_keychain
def test_a_round_trip_and_a_missing_item(keychain):
    backend, service, _ = keychain
    assert backend.get_password(service, "token") is None
    backend.set_password(service, "token", "first → ✓")
    assert backend.get_password(service, "token") == "first → ✓"
    backend.set_password(service, "token", "second")
    assert backend.get_password(service, "token") == "second"
    assert backend.get_password(service, "other") is None
    backend.delete_password(service, "token")
    assert backend.get_password(service, "token") is None
    backend.delete_password(service, "token")  # deleting a missing item is not an error


@disposable_keychain
def test_items_land_only_in_the_named_keychain(keychain):
    backend, service, path = keychain
    backend.set_password(service, "token", "here")
    found = subprocess.run(["security", "find-generic-password", "-s", service, "-a", "token",
                            path], capture_output=True, text=True)
    assert found.returncode == 0, found.stderr
    elsewhere = subprocess.run(["security", "find-generic-password", "-s", service, "-a", "token"],
                               capture_output=True, text=True)
    assert elsewhere.returncode != 0  # not in any keychain of the search list


@disposable_keychain
def test_a_locked_keychain_refuses_every_ordinary_call_without_a_prompt(keychain):
    backend, service, path = keychain
    backend.set_password(service, "token", "kept")
    subprocess.run(["security", "lock-keychain", path], check=True)
    try:
        for attempt in (lambda: backend.get_password(service, "token"),
                        lambda: backend.set_password(service, "token", "changed"),
                        lambda: backend.delete_password(service, "token")):
            started = time.monotonic()
            with pytest.raises(SecretStoreError, match="requires owner interaction or is locked"):
                attempt()
            assert time.monotonic() - started < 10  # an error, never a waiting dialog
        assert (service, "token") in backend._refused
    finally:
        password = os.environ["ODIN_MACOS_DISPOSABLE_KEYCHAIN_PASSWORD"]
        subprocess.run(["security", "unlock-keychain", "-p", password, path], check=True)
    # The owner's Retry with the keychain open again: the remembered read succeeds and clears.
    assert backend.unlock() is True
    assert backend._refused == set()
    assert backend.get_password(service, "token") == "kept"
