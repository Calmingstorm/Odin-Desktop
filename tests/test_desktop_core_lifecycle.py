"""Temporary-profile core behaviour, always run behind the PID-namespace runner."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import struct
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from src.desktop.lifecycle import CoreLifetime
from src.desktop.paths import ProfilePaths


@pytest.mark.asyncio
async def test_parent_pipe_eof_is_an_orderly_shutdown_edge():
    read_fd, write_fd = os.pipe()
    lifetime = CoreLifetime()
    try:
        lifetime.watch_parent(read_fd)
        os.write(write_fd, b"parent is alive\n")
        await asyncio.sleep(0.01)
        assert lifetime.admitting
        os.close(write_fd)
        write_fd = None
        await asyncio.wait_for(lifetime.wait(), 1)
        assert lifetime.reason == "parent_eof"
        assert not lifetime.admitting
        lifetime.request_stop("runtime.shutdown")
        assert lifetime.reason == "parent_eof"
    finally:
        lifetime.close()
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


@pytest.mark.asyncio
async def test_parent_watch_cleanup_does_not_own_the_parent_descriptor():
    read_fd, write_fd = os.pipe()
    lifetime = CoreLifetime()
    try:
        lifetime.watch_parent(read_fd)
        with pytest.raises(RuntimeError, match="already watched"):
            lifetime.watch_parent(read_fd)
        lifetime.close()
        lifetime.close()
        os.write(write_fd, b"still open")
        assert os.read(read_fd, 10) == b"still open"
        assert lifetime.admitting
    finally:
        lifetime.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_parent_watch_failed_registration_retains_no_state():
    lifetime = CoreLifetime()
    with pytest.raises((OSError, ValueError)):
        lifetime.watch_parent(-1)
    lifetime.close()
    assert lifetime.admitting


def profile(root):
    paths = ProfilePaths.from_xdg("test", environ={}, home=root)
    paths.create_private()
    token_file = paths.config_dir / "ipc.token"
    token_file.write_text("ab" * 32, encoding="utf-8")
    token_file.chmod(0o600)
    socket_dir = root / "runtime"
    socket_dir.mkdir(mode=0o700)
    return paths, socket_dir / "core.sock", token_file


async def send(writer, message):
    encoded = json.dumps(message).encode()
    writer.write(struct.pack(">I", len(encoded)) + encoded)
    await writer.drain()


async def receive(reader):
    header = await asyncio.wait_for(reader.readexactly(4), 3)
    return json.loads(await asyncio.wait_for(reader.readexactly(struct.unpack(">I", header)[0]), 3))


async def connect(socket_path, *, token="ab" * 32):
    reader, writer = await asyncio.open_unix_connection(socket_path)
    await send(writer, {
        "t": "hello", "protocol": {"major": 0, "minor": 2},
        "client": {"name": "core-test", "version": "1"}, "profile_id": "test",
        "token": token, "features": [],
    })
    return reader, writer, await receive(reader)


async def request(reader, writer, method, params=None, command_id=None):
    command_id = command_id or str(uuid.uuid4())
    await send(writer, {"t": "req", "id": command_id, "method": method, "params": params or {}})
    result = await receive(reader)
    assert result["t"] == "res"
    assert result["id"] == command_id
    return result


@pytest.mark.asyncio
async def test_real_core_status_ping_events_and_shutdown_are_ordered():
    from src.desktop.core import CAPABILITIES, CoreService

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        read_fd, write_fd = os.pipe()
        service = CoreService(paths, socket_path, token_file)
        writer = None
        try:
            await service.start(read_fd)
            reader, writer, welcome = await connect(socket_path)
            assert welcome["t"] == "welcome"
            assert set(CAPABILITIES) <= set(welcome["capabilities"])
            assert "settings.set" in welcome["capabilities"]
            instance = welcome["core"]["instance_id"]
            assert str(uuid.UUID(instance)) == instance
            result = await request(reader, writer, "status.get")
            status = result["result"]
            assert status["phase"] == "ready"
            assert status["core_instance_id"] == instance
            assert status["version"] == welcome["core"]["version"]
            assert status["capabilities"] == welcome["capabilities"]
            assert status["capabilities"][:5] == list(CAPABILITIES[:5])
            assert status["capabilities"][5:] == sorted(
                (set(CAPABILITIES) | set(service.management.methods)) - set(CAPABILITIES[:5]))
            assert len(status["capabilities"]) == len(set(status["capabilities"]))
            assert status["limits"] == service.attachments.limits
            assert service.management.runtime.status()["limits"] == service.attachments.limits
            assert status["diagnostics"] == {
                "turn_durability": {"state": "on", "reason": None},
                "compatible_provider": {"state": "off", "reason": None},
            }
            assert "model" in status and "providers" in status and "summary" in status
            await send(writer, {"t": "ping", "n": 42})
            assert await receive(reader) == {"t": "pong", "n": 42}
            response = await request(reader, writer, "events.subscribe", {"after": "0"})
            assert response["ok"]
            assert response["result"]["reset_required"] is False
            ready = await receive(reader)
            assert ready["type"] == "runtime.status"
            assert ready["payload"]["phase"] == "ready"
            assert ready["payload"]["limits"] == service.attachments.limits
            assert ready["payload"]["diagnostics"] == status["diagnostics"]
            response = await request(reader, writer, "runtime.shutdown", {"reason": "test"})
            assert response["result"] == {"disposition": "accepted"}
            await asyncio.wait_for(service.lifetime.wait(), 1)
            await asyncio.wait_for(service.close(), 10)
            quiescing = await receive(reader)
            assert quiescing["type"] == "runtime.status"
            assert quiescing["payload"]["phase"] == "quiescing"
            assert int(quiescing["seq"]) > int(ready["seq"])
            assert not socket_path.exists()
            assert service.authority._runtime_lock_fd is None
            assert (paths.data_dir / "transport.sqlite3").stat().st_mode & 0o777 == 0o600
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()
            os.close(read_fd)
            os.close(write_fd)


@pytest.mark.asyncio
async def test_command_refusals_and_shutdown_receipts_survive_restart_without_reexecution():
    from src.desktop.core import CoreService

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        refused_id, shutdown_id, status_id = (str(uuid.uuid4()) for _ in range(3))
        original_refusal = None
        original_shutdown = None
        first_instance = None
        for restart in range(2):
            read_fd, write_fd = os.pipe()
            service = CoreService(paths, socket_path, token_file)
            writer = None
            try:
                await service.start(read_fd)
                reader, writer, welcome = await connect(socket_path)
                result = await request(reader, writer, "status.get", command_id=status_id)
                if not restart:
                    first_instance = result["result"]["core_instance_id"]
                else:
                    assert result["result"]["core_instance_id"] != first_instance
                refused = await request(
                    reader, writer, "runtime.shutdown", {}, refused_id,
                )
                assert refused["error"]["code"] == "bad_request"
                if not restart:
                    original_refusal = refused
                else:
                    assert refused == original_refusal
                conflict = await request(
                    reader, writer, "runtime.shutdown", {"reason": "now valid"}, refused_id,
                )
                assert conflict["error"]["code"] == "id_conflict"
                conflict_read = await request(reader, writer, "status.get", command_id=refused_id)
                assert conflict_read["error"]["code"] == "id_conflict"
                conflict_subscribe = await request(
                    reader, writer, "events.subscribe", {"after": None}, refused_id,
                )
                assert conflict_subscribe["error"]["code"] == "id_conflict"
                shutdown = await request(
                    reader, writer, "runtime.shutdown", {"reason": "test"}, shutdown_id,
                )
                if not restart:
                    original_shutdown = shutdown
                    assert not service.lifetime.admitting
                else:
                    assert shutdown == original_shutdown
                    assert service.lifetime.admitting
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                await service.close()
                os.close(read_fd)
                os.close(write_fd)


@pytest.mark.asyncio
async def test_duplicate_profile_different_socket_and_failed_start_cleanup():
    from src.desktop.core import CoreService

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        read_fd, write_fd = os.pipe()
        first = CoreService(paths, socket_path, token_file)
        duplicate = CoreService(paths, socket_path.with_name("second.sock"), token_file)
        try:
            await first.start(read_fd)
            with pytest.raises(BlockingIOError):
                await duplicate.run(read_fd)
            assert not duplicate.socket_path.exists()
            assert duplicate.authority._runtime_lock_fd is None
            assert first.authority._runtime_lock_fd is not None
            await first.close()
            replacement = CoreService(paths, socket_path, token_file)
            try:
                await replacement.start(read_fd)
                assert replacement.phase == "ready"
            finally:
                await replacement.close()
        finally:
            await duplicate.close()
            await first.close()
            os.close(read_fd)
            os.close(write_fd)


@pytest.mark.asyncio
async def test_invalid_parent_link_start_releases_journal_and_profile_lock():
    from src.desktop.core import CoreService

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        service = CoreService(paths, socket_path, token_file)
        with pytest.raises((OSError, ValueError)):
            await service.run(-1)
        assert not socket_path.exists()
        assert service.authority._runtime_lock_fd is None
        read_fd, write_fd = os.pipe()
        replacement = CoreService(paths, socket_path, token_file)
        try:
            await replacement.start(read_fd)
        finally:
            await replacement.close()
            os.close(read_fd)
            os.close(write_fd)


@pytest.mark.asyncio
async def test_unauthorized_peer_cannot_admit_shutdown():
    from src.desktop.core import CoreService

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        read_fd, write_fd = os.pipe()
        service = CoreService(paths, socket_path, token_file)
        writer = None
        try:
            await service.start(read_fd)
            reader, writer, message = await connect(socket_path, token="cd" * 32)
            assert message == {"t": "bye", "reason": "unauthorized"}
            assert await asyncio.wait_for(reader.read(), 1) == b""
            assert service.lifetime.admitting
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()
            os.close(read_fd)
            os.close(write_fd)


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_after", [0, 1])
async def test_replay_revocation_after_response_or_between_frames(monkeypatch, revoke_after):
    from src.desktop.core import CoreService
    from src.desktop.ipc import Connection
    from src.desktop.local_client import LocalClient

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        read_fd, write_fd = os.pipe()
        service = CoreService(paths, socket_path, token_file)
        original_send = Connection.send
        revoked = False
        replay_count = 0
        client = None

        async def revoke(self, frame):
            nonlocal revoked, replay_count
            await original_send(self, frame)
            if frame["t"] == "res" and revoke_after == 0:
                revoked = True
            if frame["t"] == "evt":
                replay_count += 1
                if replay_count == revoke_after:
                    revoked = True

        try:
            await service.start(read_fd)
            service.events.append("runtime.status", {}, {"phase": "ready"})
            original_accepts = service.authority.accepts
            monkeypatch.setattr(service.authority, "accepts",
                                lambda context: not revoked and original_accepts(context))
            monkeypatch.setattr(Connection, "send", revoke)
            client = await LocalClient.connect(socket_path, token_file, paths.profile_id)
            await client.request("events.subscribe", {"after": "0"})
            assert (await client.read())["t"] == "res"
            if revoke_after:
                assert (await client.read())["t"] == "evt"
            assert await client.read() == {"t": "bye", "reason": "unauthorized"}
            assert replay_count == revoke_after
            monkeypatch.setattr(service.authority, "accepts", original_accepts)
        finally:
            if client:
                await client.close()
            await service.close()
            os.close(read_fd)
            os.close(write_fd)


async def launch(paths, socket_path, token_file, root):
    environment = {
        "PATH": os.environ["PATH"], "HOME": str(root), "LANG": "C.UTF-8",
        "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
        "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(root / "runtime"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "src", "--socket", str(socket_path), "--token-file", str(token_file),
        "--profile", paths.profile_id, "--data-dir", str(paths.data_dir),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=environment,
        cwd=Path(__file__).resolve().parents[1],
    )


async def wait_connected(process, socket_path):
    # Startup now qualifies the management/provider graph before publishing IPC.
    # Use the app real-core harness's bounded eight-second startup allowance,
    # rather than making process-lifecycle assertions depend on a three-second
    # import/provisioning race when other isolated lanes are qualifying.
    deadline = asyncio.get_running_loop().time() + 8
    while asyncio.get_running_loop().time() < deadline:
        if process.returncode is not None:
            stdout, stderr = await process.communicate()
            pytest.fail(f"core exited {process.returncode}: {stdout!r} {stderr!r}")
        try:
            return await connect(socket_path)
        except (FileNotFoundError, ConnectionRefusedError):
            await asyncio.sleep(0.01)
    process.stdin.close()
    stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
    pytest.fail(
        f"core did not publish its listener within eight seconds: {stdout!r} {stderr!r}"
    )


@pytest.mark.asyncio
async def test_subprocess_parent_eof_lock_release_stale_socket_and_restart():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths, socket_path, token_file = profile(root)
        stale = socket.socket(socket.AF_UNIX)
        stale.bind(str(socket_path))
        stale.close()
        original_token = token_file.read_bytes()
        first_instance = None
        for restart in range(2):
            process = await launch(paths, socket_path, token_file, root)
            writer = None
            try:
                reader, writer, welcome = await wait_connected(process, socket_path)
                status = await request(reader, writer, "status.get")
                assert status["result"]["phase"] == "ready"
                if not restart:
                    first_instance = welcome["core"]["instance_id"]
                    second = await launch(
                        paths, socket_path.with_name("other.sock"), token_file, root,
                    )
                    try:
                        await asyncio.wait_for(second.communicate(), 10)
                        assert second.returncode != 0
                        assert not socket_path.with_name("other.sock").exists()
                    finally:
                        if second.returncode is None:
                            second.stdin.close()
                            await asyncio.wait_for(second.communicate(), 10)
                else:
                    assert welcome["core"]["instance_id"] != first_instance
                process.stdin.close()
                await asyncio.wait_for(process.communicate(), 10)
                assert process.returncode == 0
                assert not socket_path.exists()
                assert token_file.read_bytes() == original_token
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                if process.returncode is None:
                    process.stdin.close()
                    await asyncio.wait_for(process.communicate(), 10)


@pytest.mark.asyncio
async def test_validation_refusal_expiry_and_retention_reset_on_wire():
    from src.desktop.core import CoreService
    from src.desktop.events import EventJournal

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        read_fd, write_fd = os.pipe()
        service = CoreService(paths, socket_path, token_file)
        writer = None
        try:
            await service.start(read_fd)
            reader, writer, _ = await connect(socket_path)
            nonobject_id = str(uuid.uuid4())
            malformed_request = {
                "t": "req", "id": nonobject_id, "method": "runtime.shutdown", "params": [],
            }
            await send(writer, malformed_request)
            nonobject = await receive(reader)
            assert nonobject["error"]["code"] == "bad_request"
            await send(writer, malformed_request)
            assert await receive(reader) == nonobject
            invalid_id = str(uuid.uuid4())
            invalid = await request(reader, writer, "runtime.shutdown", {}, invalid_id)
            assert invalid["error"]["code"] == "bad_request"
            assert service.lifetime.admitting
            assert await request(reader, writer, "runtime.shutdown", {}, invalid_id) == invalid
            conflicting = await request(
                reader, writer, "runtime.shutdown", {"reason": "now valid"}, invalid_id,
            )
            assert conflicting["error"]["code"] == "id_conflict"
            service.commands.prune(before=10**12)
            expired = await request(reader, writer, "runtime.shutdown", {}, invalid_id)
            assert expired["error"]["code"] == "receipt_expired"
            service.events = EventJournal(service.store, max_events=2)
            for _ in range(4):
                await service._status_event()
            missing_after = await request(reader, writer, "events.subscribe")
            assert missing_after["error"]["code"] == "bad_request"
            reset = await request(reader, writer, "events.subscribe", {"after": "0"})
            assert reset["result"] == {
                "event_high": service.events.high, "reset_required": True,
            }
            await send(writer, {"t": "ping", "n": "after-reset"})
            assert await receive(reader) == {"t": "pong", "n": "after-reset"}
            await service._status_event()
            live = await receive(reader)
            assert live["seq"] == int(reset["result"]["event_high"]) + 1
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()
            os.close(read_fd)
            os.close(write_fd)


@pytest.mark.asyncio
async def test_subprocess_sigterm_exits_orderly_without_touching_other_processes():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths, socket_path, token_file = profile(root)
        process = await launch(paths, socket_path, token_file, root)
        writer = None
        try:
            reader, writer, _ = await wait_connected(process, socket_path)
            await request(reader, writer, "events.subscribe", {"after": None})
            process.send_signal(signal.SIGTERM)
            event = await receive(reader)
            assert event["type"] == "runtime.status"
            assert event["payload"]["phase"] == "quiescing"
            await asyncio.wait_for(process.communicate(), 10)
            assert process.returncode == 0
            assert not socket_path.exists()
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            if process.returncode is None:
                process.stdin.close()
                await asyncio.wait_for(process.communicate(), 10)


@pytest.mark.asyncio
async def test_parent_loss_cancels_actual_wire_subscription_stuck_during_replay(monkeypatch):
    from src.desktop.core import CoreService
    from src.desktop.ipc import Connection

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        read_fd, write_fd = os.pipe()
        service = CoreService(paths, socket_path, token_file)
        entered = asyncio.Event()
        original_send = Connection.send

        async def stalled_replay(connection, frame):
            if frame.get("t") == "evt":
                entered.set()
                await asyncio.Event().wait()
            else:
                await original_send(connection, frame)

        writer = None
        try:
            await service.start(read_fd)
            reader, writer, _ = await connect(socket_path)
            monkeypatch.setattr(Connection, "send", stalled_replay)
            subscription = await request(reader, writer, "events.subscribe", {"after": "0"})
            assert subscription["ok"]
            await asyncio.wait_for(entered.wait(), 1)
            os.close(write_fd)
            write_fd = None
            await asyncio.wait_for(service.lifetime.wait(), 1)
            await asyncio.wait_for(service.close(), 8)
            assert service.authority._runtime_lock_fd is None
            assert not socket_path.exists()
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)


@pytest.mark.asyncio
async def test_entry_can_hold_profile_owner_until_its_finalization_barrier():
    from src.desktop.core import CoreService

    with tempfile.TemporaryDirectory() as temporary:
        paths, socket_path, token_file = profile(Path(temporary))
        read_fd, write_fd = os.pipe()
        service = CoreService(paths, socket_path, token_file, release_runtime_on_close=False)
        duplicate = CoreService(paths, socket_path.with_name("second.sock"), token_file)
        try:
            await service.start(read_fd)
            await service.close()
            assert not socket_path.exists()
            with pytest.raises(BlockingIOError):
                await duplicate.run(read_fd)
            service.release_runtime()
            replacement = CoreService(paths, socket_path, token_file)
            try:
                await replacement.start(read_fd)
            finally:
                await replacement.close()
        finally:
            await service.close()
            service.release_runtime()
            await duplicate.close()
            os.close(read_fd)
            os.close(write_fd)
