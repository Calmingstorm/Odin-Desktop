"""Fake Secret Service verifies prompt ownership and bounded shutdown."""
import asyncio
import os
import subprocess
import sys
import threading
import uuid

import pytest
import secretstorage

from src.desktop.core import CoreService
from src.desktop.secrets import ProfileSecretStore, SecretStoreError, secret_call
from tests.test_desktop_core_lifecycle import connect, profile, receive, request, send


class Bus:
    def close(self):
        pass


class Collection:
    def __init__(self):
        self.locked, self.unlock_calls = True, 0
        self.started, self.answer = threading.Event(), None
        self.values, self.relock, self.calls = {}, False, 0

    def record(self):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.calls += 1
        else:
            raise AssertionError("keyring called on event loop")

    def is_locked(self):
        self.record()
        return self.locked

    def unlock(self):
        self.record()
        self.unlock_calls += 1
        self.started.set()
        if self.answer is not None:
            self.answer.wait()
        self.locked = False
        return False

    def search_items(self, attributes):
        self.record()
        if self.relock:
            self.locked = True
            raise secretstorage.exceptions.LockedException("relocked")
        value = self.values.get(attributes["username"])
        if value is None:
            return []
        collection = self

        class Item:
            def is_locked(self):
                return collection.is_locked()

            def get_secret(self):
                collection.record()
                if collection.locked:
                    raise secretstorage.exceptions.LockedException("relocked")
                return value.encode()

        return [Item()]


@pytest.fixture
def collection(monkeypatch):
    collection = Collection()
    monkeypatch.setattr(secretstorage, "dbus_init", Bus)
    monkeypatch.setattr(secretstorage, "Collection", lambda bus: collection)
    return collection


@pytest.fixture
async def core(tmp_path, collection):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = CoreService(paths, socket_path, token_file)
    writers = []
    try:
        await service.start(read_fd)
        reader, writer, welcome = await connect(socket_path)
        writers.append(writer)
        yield service, reader, writer, welcome, socket_path, writers
    finally:
        if collection.answer is not None:
            collection.answer.set()
        for writer in writers:
            writer.close()
            await writer.wait_closed()
        await asyncio.wait_for(service.close(), 2)
        os.close(read_fd)
        os.close(write_fd)


async def test_startup_status_schema_no_unlock(core, collection):
    service, reader, writer, welcome, *_ = core
    assert "secrets.unlock" in welcome["capabilities"]
    assert welcome["event_high"] == str(service.events.high)
    assert service.management.settings._keyring_error
    for _ in range(2):
        status = await request(reader, writer, "status.get")
        assert status["result"]["first_run"]["reason"] == "keyring_unavailable"
        assert status["result"]["resource_cleanup"] == service.resource_cleanup.public()
        assert status["result"]["resource_cleanup"]["effects_undone"] is False
        schema = await request(reader, writer, "settings.schema")
        assert schema["result"]["status"]["keyring_error"]
    assert collection.unlock_calls == 0 and collection.calls > 0


async def test_unlocked_startup_shares_hydrated_request_and_management_owner(tmp_path, collection):
    collection.locked = False
    collection.values["openai_compatible.api_key"] = "private-fixture"
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = CoreService(paths, socket_path, token_file)
    try:
        await service.start(read_fd)
        settings = service.settings
        assert settings is service.management.settings
        assert settings._keyring_error is None
        assert settings.config.openai_compatible.api_key == "private-fixture"
        assert service.management.providers is service.engine.deps.llm_gateway
        assert service.management.executor is service.engine.deps.tool_executor
        assert collection.unlock_calls == 0 and collection.calls > 0
    finally:
        await service.close()
        os.close(read_fd)
        os.close(write_fd)


async def test_startup_codex_vault_and_client_build_run_off_loop():
    from types import SimpleNamespace

    from src.desktop.services import EngineServices

    client = object()
    calls = []

    def off_loop(name):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        calls.append(name)

    def read():
        off_loop("read")
        return [{"access_token": "private-fixture"}]

    def build(provider, config):
        off_loop("build")
        assert provider == "codex"
        return client

    gateway = SimpleNamespace(
        settings=SimpleNamespace(config=SimpleNamespace(openai_codex=SimpleNamespace(enabled=True))),
        codex_client=None, codex_accounts=SimpleNamespace(vault=SimpleNamespace(read=read)),
        _build=build, active_client=None,
    )
    engine = EngineServices(SimpleNamespace(llm_gateway=gateway), None)
    await engine.initialize_profile_provider()
    assert gateway.codex_client is client and calls == ["read", "build"]
    await engine.initialize_profile_provider()
    assert calls == ["read", "build"]


async def test_retry_one_unlock_rehydrates_and_replays(core, collection):
    service, reader, writer, *_ = core
    collection.values["openai_compatible.api_key"] = "private-fixture"
    command_id = str(uuid.uuid4())
    response = await request(reader, writer, "secrets.unlock", command_id=command_id)
    assert response["ok"] and response["result"] == {"unlocked": True}
    assert collection.unlock_calls == 1
    assert service.management.settings.config.openai_compatible.api_key == "private-fixture"
    assert service.management.settings._keyring_error is None
    assert (await request(reader, writer, "secrets.unlock", command_id=command_id))["ok"]
    invalid = await request(reader, writer, "secrets.unlock", {"unexpected": True})
    assert invalid["error"]["code"] == "bad_request"
    assert collection.unlock_calls == 1


async def test_never_answer_bounded_and_concurrently_responsive(core, collection, monkeypatch):
    from src.desktop import secrets

    monkeypatch.setattr(secrets, "UNLOCK_TIMEOUT", .5)
    _, reader, writer, _, socket_path, writers = core
    collection.answer = threading.Event()
    # The app uses one socket; not merely a second responsive connection.
    other_reader, other_writer = reader, writer
    command_id = str(uuid.uuid4())
    await send(writer, {"t": "req", "id": command_id, "method": "secrets.unlock", "params": {}})
    for _ in range(100):
        if collection.started.is_set():
            break
        await asyncio.sleep(.002)
    assert collection.started.is_set()
    await send(other_writer, {"t": "ping", "n": 123})
    assert await asyncio.wait_for(receive(other_reader), .3) == {"t": "pong", "n": 123}
    status = await asyncio.wait_for(request(other_reader, other_writer, "status.get"), .3)
    assert status["result"]["first_run"]["keyring_unavailable"]
    assert (await request(other_reader, other_writer, "hosts.list"))["ok"]
    timeout = await asyncio.wait_for(receive(reader), 3)
    assert timeout["error"]["code"] == "keyring_unavailable"
    assert timeout["error"]["disposition"] == "outcome_unknown"
    repeat = await request(other_reader, other_writer, "secrets.unlock")
    assert repeat["error"]["code"] == "keyring_unavailable"
    assert collection.unlock_calls == 1
    replay = await request(other_reader, other_writer, "secrets.unlock", command_id=command_id)
    assert replay["error"]["disposition"] == "outcome_unknown"


async def test_relock_race_no_unlock(tmp_path, collection):
    paths, *_ = profile(tmp_path)
    collection.locked, collection.relock = False, True
    with pytest.raises(SecretStoreError):
        await secret_call(ProfileSecretStore(paths).get, "codex_accounts")
    assert collection.unlock_calls == 0


async def test_write_delete_returned_prompt_never_executed(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from secretstorage import util

    paths, *_ = profile(tmp_path)
    prompts, wire_calls = [], []

    def wire(method, signature, *args):
        wire_calls.append(method)
        return ("/", "/native/prompt") if method == "CreateItem" else ("/native/prompt",)

    def forbidden(*args, **kwargs):
        prompts.append(True)
        raise AssertionError("only explicit unlock may execute a prompt")

    item = SimpleNamespace(is_locked=lambda: False, ensure_not_locked=lambda: None,
                           get_secret=lambda: b"old-private", _item=SimpleNamespace(call=wire))
    collection = SimpleNamespace(is_locked=lambda: False, ensure_not_locked=lambda: None,
                                 session=object(), _collection=SimpleNamespace(call=wire),
                                 search_items=lambda attrs: [item])
    monkeypatch.setattr(secretstorage, "dbus_init", Bus)
    monkeypatch.setattr(secretstorage, "Collection", lambda bus: collection)
    monkeypatch.setattr(util, "format_secret", lambda *args: ())
    monkeypatch.setattr(util, "exec_prompt", forbidden)
    store = ProfileSecretStore(paths)
    with pytest.raises(SecretStoreError):
        await secret_call(store.set, "openai_compatible.api_key", "new-private")
    with pytest.raises(SecretStoreError):
        await secret_call(store.delete, "openai_compatible.api_key")
    assert wire_calls == ["CreateItem", "Delete"] and not prompts


async def test_core_close_during_permanently_pending_prompt(core, collection, monkeypatch):
    from src.desktop import secrets

    monkeypatch.setattr(secrets, "UNLOCK_TIMEOUT", 100)
    service, _, writer, *_ = core
    collection.answer = threading.Event()
    await send(writer, {"t": "req", "id": str(uuid.uuid4()),
                        "method": "secrets.unlock", "params": {}})
    for _ in range(100):
        if collection.started.is_set():
            break
        await asyncio.sleep(.002)
    assert collection.started.is_set()
    # Unblock only in the fixture finalizer, AFTER this real close completes.
    await asyncio.wait_for(service.close(), 1)
    assert service._closed and collection.unlock_calls == 1


async def test_hydration_preserves_composed_nested_references(core, collection):
    service, reader, writer, *_ = core
    settings, executor = service.management.settings, service.management.executor
    config, email, tools = settings.config, settings.config.email, settings.config.tools
    collection.values["email.smtp.password"] = "private-mail"
    assert (await request(reader, writer, "secrets.unlock"))["ok"]
    assert settings.config is config and settings.config.email is email
    assert settings.config.tools is tools
    assert executor._app_config is config and executor._email_config is email
    assert executor._email_config.smtp.password == "private-mail"


async def test_late_native_completion_does_not_publish_worker_callback(
    core, collection, monkeypatch,
):
    from src.desktop import secrets

    monkeypatch.setattr(secrets, "UNLOCK_TIMEOUT", .03)
    service, reader, writer, *_ = core
    settings = service.management.settings
    collection.values["email.smtp.password"] = "late-private-mail"
    collection.answer = threading.Event()
    failed = await request(reader, writer, "secrets.unlock")
    assert failed["error"]["disposition"] == "outcome_unknown"
    collection.answer.set()
    for _ in range(100):
        if not settings.secrets._unlock_pending:
            break
        await asyncio.sleep(.002)
    assert not settings.secrets._unlock_pending
    assert settings.config.email.smtp.password == ""
    assert settings._keyring_error
    # A subsequent independent nonprompting read is allowed to notice the
    # unlocked service, but late worker completion itself publishes nothing.
    schema = await request(reader, writer, "settings.schema")
    assert schema["result"]["status"]["keyring_error"] is None
    assert settings.config.email.smtp.password == "late-private-mail"


async def test_repeated_cancel_cannot_release_another_dispatch_lock(core, collection, monkeypatch):
    from src.desktop import secrets

    monkeypatch.setattr(secrets, "UNLOCK_TIMEOUT", 100)
    service, _, writer, *_ = core
    collection.answer = threading.Event()
    await send(writer, {"t": "req", "id": str(uuid.uuid4()),
                        "method": "secrets.unlock", "params": {}})
    for _ in range(100):
        if collection.started.is_set():
            break
        await asyncio.sleep(.002)
    assert collection.started.is_set()
    dispatch = next(task for task in service.server._tasks
                    if task.get_coro().__name__ == "_unlock_request")
    # Another ordered request now owns serial while unlock reacquires on cancel.
    await service._serial.acquire()
    try:
        dispatch.cancel()
        await asyncio.sleep(.01)
        dispatch.cancel()
        await asyncio.sleep(.01)
        assert service._serial.locked() and not dispatch.done()
    finally:
        service._serial.release()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(dispatch, 1)
    assert not service._serial.locked()


def test_asyncio_run_exits_with_never_answer_worker(tmp_path):
    code = '''
import asyncio, threading
from pathlib import Path
from src.desktop.paths import ProfilePaths
from src.desktop import secrets
class Backend:
    def unlock(self):
        threading.Event().wait()
secrets.UNLOCK_TIMEOUT = .03
store = secrets.ProfileSecretStore(
    ProfilePaths.from_xdg(home=Path.home(), environ={}), backend=Backend(),
)
async def main():
    try:
        await store.unlock()
    except TimeoutError:
        pass
asyncio.run(main())
print("exited")
'''
    environment = dict(os.environ, HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / "config"),
                       XDG_DATA_HOME=str(tmp_path / "data"), XDG_CACHE_HOME=str(tmp_path / "cache"))
    environment.pop("DBUS_SESSION_BUS_ADDRESS", None)
    environment.pop("XDG_RUNTIME_DIR", None)
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            capture_output=True, text=True, timeout=3)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "exited"
