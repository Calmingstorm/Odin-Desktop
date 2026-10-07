"""Real startup stop edges, inside the repository's self-isolating runner."""
import asyncio
import json
import os
import signal
import threading

import pytest

from src.desktop import lifecycle
from src.desktop.core import CoreService
from src.desktop.resource_cleanup import ResourceCleanupError
from tests.test_desktop_core_lifecycle import profile


@pytest.mark.asyncio
@pytest.mark.parametrize("hydration", [1, 2])
@pytest.mark.parametrize("settles", [False, True])
async def test_sigterm_retires_withheld_startup_truthfully(
    tmp_path, monkeypatch, hydration, settles,
):
    from src.desktop.settings import SettingsService

    entered, release = threading.Event(), threading.Event()
    original = SettingsService.hydrate_secrets
    calls = 0

    def withheld(settings):
        nonlocal calls
        calls += 1
        if calls == hydration:
            entered.set()
            release.wait(20)
        return original(settings)

    monkeypatch.setattr(SettingsService, "hydrate_secrets", withheld)
    monkeypatch.setattr(lifecycle, "PARENT_EXIT_GRACE_SECONDS", 0.01)
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = CoreService(paths, socket_path, token_file)
    task = asyncio.create_task(service.run(read_fd))
    try:
        async with asyncio.timeout(15):
            while not entered.is_set():
                await asyncio.sleep(0.01)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(service.lifetime.wait(), 1)
        if settles:
            asyncio.get_running_loop().call_later(0.05, release.set)
            assert await asyncio.wait_for(asyncio.shield(task), 3) == 0
        else:
            with pytest.raises(ResourceCleanupError):
                await asyncio.wait_for(asyncio.shield(task), 3)
        evidence = json.loads((paths.data_dir / "resource-cleanup.json").read_text())
        assert service.lifetime.reason == "sigterm"
        assert service.server is None
        assert evidence["state"] == ("complete" if settles else "unknown")
        assert evidence["resources"]["startup_secrets"]["state"] == (
            "released" if settles else "unknown")
        assert (service.authority._runtime_lock_fd is None) is settles
        assert service._close_complete is settles
        if hydration == 1:
            assert evidence["resources"]["computer"] == {"state": "not_started"}
            assert evidence["resources"]["processes"] == {"state": "not_started"}
    finally:
        release.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), 20)
        except ResourceCleanupError:
            pass
        await asyncio.sleep(0.1)
        service.release_runtime()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_parent_eof_cancels_async_startup_without_starting_engine(tmp_path):
    entered = asyncio.Event()

    async def config(paths):
        entered.set()
        await asyncio.Event().wait()

    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = CoreService(paths, socket_path, token_file, config_provider=config)
    task = asyncio.create_task(service.run(read_fd))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        os.close(write_fd)
        write_fd = None
        assert await asyncio.wait_for(task, 2) == 0
        evidence = json.loads((paths.data_dir / "resource-cleanup.json").read_text())
        assert evidence["state"] == "complete"
        assert evidence["resources"]["startup_secrets"] == {"state": "not_started"}
        assert service.engine is None
        assert service.authority._runtime_lock_fd is None
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


@pytest.mark.asyncio
async def test_cancellation_resistant_startup_retains_ownership_and_store(tmp_path, monkeypatch):
    from src.desktop import core
    from src.desktop.core import profile_config

    monkeypatch.setattr(core, "STARTUP_SETTLE_SECONDS", 0.05)
    entered, release = asyncio.Event(), asyncio.Event()

    async def config(paths):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
            raise
        return profile_config(paths)

    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = CoreService(paths, socket_path, token_file, config_provider=config)
    task = asyncio.create_task(service.run(read_fd))
    try:
        await entered.wait()
        service.lifetime.request_stop("test_stop")
        with pytest.raises(ResourceCleanupError):
            await asyncio.wait_for(task, 1)
        assert service.authority._runtime_lock_fd is not None
        assert service.store.connection.execute("SELECT 1").fetchone()[0] == 1
        evidence = json.loads((paths.data_dir / "resource-cleanup.json").read_text())
        assert evidence["state"] == "unknown"
        assert evidence["resources"]["startup"]["state"] == "unknown"
        assert not service._close_complete
    finally:
        release.set()
        await asyncio.sleep(0.1)
        service.store.close()
        service.release_runtime()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_late_secret_error_is_retained_and_inactive_scope_keeps_transaction_barrier():
    from src.desktop.secrets import StartupSecretCalls, secret_call, startup_secret_calls

    started, release = threading.Event(), threading.Event()

    def worker():
        started.set()
        release.wait(5)
        raise ValueError("not retained in evidence")

    calls = StartupSecretCalls()
    token = startup_secret_calls.set(calls)
    try:
        task = asyncio.create_task(secret_call(worker))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls.outcome()["state"] == "unknown"
        release.set()
        await calls.settle(1)
        await asyncio.sleep(0)
        assert calls.outcome() == {"state": "unknown", "pending": 0,
                                   "error_types": ["ValueError"]}
        calls.active = False
        started.clear()
        release.clear()
        task = asyncio.create_task(secret_call(worker))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        release.set()
        with pytest.raises(ValueError):
            await task
    finally:
        release.set()
        startup_secret_calls.reset(token)
