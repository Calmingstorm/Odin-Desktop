"""Real IPC and retained runner, with a harmless deterministic provider."""
from __future__ import annotations

import asyncio
import base64
import os
import uuid
from types import SimpleNamespace

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.core import CoreService, _CoreEvents, _PublicationStore, profile_config
from src.desktop.delivery import ArtifactPost, DurableDelivery
from src.discord.tool_loop import ToolLoopRunner
from src.llm.types import LLMResponse
from tests.test_desktop_core_lifecycle import connect, profile, receive, request


class Provider:
    model = "test"
    provider_name = "compat"

    def __init__(self, *, blocked=False, artifact=False):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not blocked:
            self.release.set()
        self.calls = 0
        self.closed = False
        self.core = None
        self.artifact = artifact

    async def chat_with_tools(self, **_kwargs):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        if self.artifact and self.calls == 1:
            row = self.core.store.connection.execute(
                "SELECT request_id,conversation_id FROM desktop_requests WHERE state='running'"
            ).fetchone()
            message = self.core.requests.fetch_request(row["conversation_id"], row["request_id"])
            await self.core.delivery.send(message, "A retained file", files=[ArtifactPost(
                b"harmless binary\x00\xff", "proof.bin", "application/octet-stream",
                tool="read_file")])
        return LLMResponse(text=f"Guarded answer {self.calls}.")

    async def chat(self, **_kwargs):
        return "COMPLETE"

    async def drain_and_close(self):
        self.closed = True


def configured(paths):
    cfg = profile_config(paths)
    cfg.openai_codex.enabled = False
    cfg.openai_compatible.enabled = True
    cfg.llm_provider.model = "compat:test"
    cfg.browser.enabled = False
    cfg.learning.enabled = False
    return cfg


def service(paths, socket_path, token_file, provider):
    core = CoreService(paths, socket_path, token_file, config_provider=configured,
                       runtime_provider=lambda *_args: SimpleNamespace(compatible_client=provider))
    provider.core = core
    return core


async def settled(core):
    async def wait():
        while core.requests._tasks:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 5)


@pytest.mark.asyncio
async def test_ipc_dedup_queue_disconnect_guarded_delivery_artifact_and_restart(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider(blocked=True, artifact=True)
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        assert isinstance(core.engine.runner, ToolLoopRunner)
        reader, writer, welcome = await connect(socket_path)
        assert "submission.send" in welcome["capabilities"]
        assert "control.stop" in welcome["capabilities"]
        created = await request(reader, writer, "conversations.create", {})
        cid = created["result"]["conversation"]["id"]
        params = {"client_submission_id": "dedup", "conversation_id": cid, "text": "First"}
        command_id = str(uuid.uuid4())
        first = await request(reader, writer, "submission.send", params, command_id)
        await asyncio.wait_for(provider.entered.wait(), 2)
        assert await request(reader, writer, "submission.send", params, command_id) == first
        duplicate = await request(reader, writer, "submission.send", params)
        assert duplicate["result"] == first["result"]
        queued = await request(reader, writer, "submission.send", {
            "client_submission_id": "queued", "conversation_id": cid, "text": "Second"})
        snapshot = await request(reader, writer, "conversation.snapshot", {"conversation_id": cid})
        assert snapshot["result"]["running"]["request_id"] == first["result"]["request_id"]
        assert snapshot["result"]["queued"][0]["request_id"] == queued["result"]["request_id"]
        writer.close()
        await writer.wait_closed()
        writer = None
        provider.release.set()
        await settled(core)
        reader, writer, _ = await connect(socket_path)
        snapshot = await request(reader, writer, "conversation.snapshot", {"conversation_id": cid})
        messages = snapshot["result"]["messages"]["items"]
        assert [m["text"] for m in messages if m["role"] == "assistant"] == [
            "Guarded answer 1.", "Guarded answer 2."]
        assert provider.calls == 2
        notification = core.delivery.notifications.pending()[0]
        acknowledgement = await request(reader, writer, "notifications.ack", {
            "dedupe_key": notification["dedupe_key"], "outcome": "shown"})
        assert acknowledgement["result"] == {"disposition": "recorded"}
        artifact = next(m["artifacts"][0] for m in messages if m.get("artifacts"))
        ref = artifact["ref"]
        got = await request(reader, writer, "artifacts.read", {
            "ref": ref, "offset": 0, "length": 64})
        assert base64.b64decode(got["result"]["data_b64"]) == b"harmless binary\x00\xff"
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        provider.release.set()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
    assert provider.closed
    next_provider = Provider()
    core = service(paths, socket_path, token_file, next_provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        assert await request(reader, writer, "submission.send", params, command_id) == first
        await settled(core)
        assert next_provider.calls == 0
        got = await request(reader, writer, "artifacts.read", {
            "ref": ref, "offset": 0, "length": 64})
        assert got["ok"]
        read_id = str(uuid.uuid4())
        assert (await request(reader, writer, "artifacts.read", {
            "ref": ref, "offset": 0, "length": 1}, read_id))["ok"]
        core.config.tools.disabled_tools.append("read_file")
        saved = await request(reader, writer, "artifacts.read", {
            "ref": ref, "offset": 0, "length": 1}, read_id)
        assert saved["ok"]
        assert base64.b64decode(saved["result"]["data_b64"]) == b"h"
        assert core.store.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (read_id,)
        ).fetchone()[0] == 0
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_ipc_chunk_offset_idempotent_without_command_receipt(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    core = service(paths, socket_path, token_file, Provider())
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        failed = await request(reader, writer, "attachments.begin", {
            "client_attachment_id": "missing", "conversation_id": "missing",
            "name": "a.txt", "mime": "text/plain", "size": 1})
        assert failed["error"]["code"] == "not_found"
        created = await request(reader, writer, "conversations.create")
        cid = created["result"]["conversation"]["id"]
        begun = await request(reader, writer, "attachments.begin", {
            "client_attachment_id": "a", "conversation_id": cid,
            "name": "a.txt", "mime": "text/plain", "size": 1})
        params = {"upload_id": begun["result"]["upload_id"], "offset": 0, "data_b64": "YQ=="}
        ident = str(uuid.uuid4())
        first = await request(reader, writer, "attachments.chunk", params, ident)
        assert (await request(reader, writer, "attachments.chunk", params, ident)) == first
        assert first["result"] == {"received": 1}
        assert core.store.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (ident,)
        ).fetchone()[0] == 0
        status = await request(reader, writer, "status.get")
        assert status["result"]["limits"]["chunk_bytes"] == begun["result"]["chunk_bytes"]
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_worker_events_replay_live_no_gap_with_zero_replay_retention(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider(blocked=True)
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writers = []
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        writers.append(writer)
        events_reader, events_writer, _ = await connect(socket_path)
        writers.append(events_writer)
        subscribed = await request(events_reader, events_writer, "events.subscribe", {
            "after": None})
        high = int(subscribed["result"]["event_high"])
        core.events.max_events = 0
        created = await request(reader, writer, "conversations.create")
        cid = created["result"]["conversation"]["id"]
        await request(reader, writer, "submission.send", {
            "client_submission_id": "event", "conversation_id": cid, "text": "Hello"})
        await provider.entered.wait()
        provider.release.set()
        await settled(core)
        frames = []
        while len(frames) < int(core.events.high) - high:
            frames.append(await receive(events_reader))
        assert [f["seq"] for f in frames] == list(range(high + 1, int(core.events.high) + 1))
        kinds = [frame["type"] for frame in frames]
        assert "request.started" in kinds and "request.completed" in kinds
        assert kinds.count("message.committed") == 2
    finally:
        provider.release.set()
        for writer in writers:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_management_commit_flushes_pending_worker_events_in_sequence(tmp_path, monkeypatch):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider(blocked=True)
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writers = []
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        writers.append(writer)
        created = await request(reader, writer, "conversations.create")
        cid = created["result"]["conversation"]["id"]
        await request(reader, writer, "submission.send", {
            "client_submission_id": "management-interleave", "conversation_id": cid,
            "text": "Hello"})
        await asyncio.wait_for(provider.entered.wait(), 2)
        events_reader, events_writer, _ = await connect(socket_path)
        writers.append(events_writer)
        subscribed = await request(events_reader, events_writer, "events.subscribe", {
            "after": None})
        high = int(subscribed["result"]["event_high"])
        schema = await request(reader, writer, "settings.schema")
        original_invoke = core.management.invoke

        async def interleave(method, params):
            if method == "settings.set":
                # Dispatch holds _serial across this management await. Actual request
                # workers commit their results while the ordered publisher is waiting.
                assert core._serial.locked()
                provider.release.set()
                await settled(core)
                assert int(core.events.high) > high
                assert core._published_seq <= high
            return await original_invoke(method, params)

        monkeypatch.setattr(core.management, "invoke", interleave)
        saved = await request(reader, writer, "settings.set", {
            "expected_revision": schema["result"]["revision"],
            "changes": [{"path": "tools.command_shell", "value": "sh"}]})
        assert saved["ok"]
        final_high = int(core.events.high)
        frames = []
        for _ in range(final_high - high):
            frames.append(await asyncio.wait_for(receive(events_reader), 2))
        assert [frame["seq"] for frame in frames] == list(range(high + 1, final_high + 1))
        assert frames[-1]["type"] == "settings.changed"
        assert "request.completed" in [frame["type"] for frame in frames]
    finally:
        provider.release.set()
        for writer in writers:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


def test_committed_publication_capture_discards_transaction_and_savepoint_rollbacks(tmp_path):
    wakes = []
    store = _PublicationStore(tmp_path / "journal.sqlite3", "test",
                              committed=lambda: wakes.append(1))
    events = _CoreEvents(store, max_events=0)
    DurableDelivery(store, events, transcript_commit=lambda **_kwargs: None)

    def frames():
        return [row[0] for row in store.connection.execute(
            "SELECT kind FROM desktop_delivery_outbox ORDER BY event_seq")]

    try:
        with pytest.raises(ValueError), store.transaction():
            events.append("rolled_back", {"kind": "test", "id": "1"}, {})
            raise ValueError("harmless rollback")
        assert frames() == []
        with store.transaction() as db:
            db.execute("SAVEPOINT refused")
            events.append("savepoint_rollback", {"kind": "test", "id": "1"}, {})
            db.execute("ROLLBACK TO refused")
            db.execute("RELEASE refused")
        assert frames() == []
        with store.transaction():
            events.append("first", {"kind": "test", "id": "1"}, {})
            db = store.connection
            db.execute("SAVEPOINT refused")
            events.append("second_rolledback", {"kind": "test", "id": "2"}, {})
            db.execute("ROLLBACK TO refused")
            db.execute("RELEASE refused")
            events.append("committed", {"kind": "test", "id": "1"}, {})
        assert frames() == ["first", "committed"]
        assert wakes
        assert events.between("0") == []
    finally:
        store.close()


def test_default_config_storage_paths_bound_to_selected_profile(tmp_path):
    from src.desktop.ssh_sockets import socket_directory

    paths, _socket_path, _token_file = profile(tmp_path)
    cfg = profile_config(paths)
    assert cfg.context.directory == str(paths.data_dir / "context")
    assert cfg.sessions.persist_directory == str(paths.data_dir / "sessions")
    assert cfg.tools.ssh_pool.socket_dir == socket_directory(paths)
    assert cfg.openai_codex.credentials_path == str(paths.secrets_dir / "codex_auth.json")
    assert cfg.attachments.temp_directory == str(paths.cache_dir / "attachments")
    assert not cfg.openai_compatible.api_key


@pytest.mark.asyncio
async def test_request_cleanup_failure_preserves_graph_storage_and_profile_owner(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    original_close = None
    try:
        await core.start(read_fd)
        original_close = core.requests.close

        async def cannot_retire():
            raise RuntimeError("Execution still alive")

        core.requests.close = cannot_retire
        with pytest.raises(RuntimeError, match="Execution still alive"):
            await core.close()
        assert not provider.closed
        assert not core.store._closed
        assert core.phase == "quiescing"
        contender = OwnerAuthority(paths, app_bootstrap=True)
        with pytest.raises(Exception):
            contender.acquire_runtime()
    finally:
        if original_close is not None:
            await original_close()
        if core.engine is not None:
            await core.engine.close()
        if core.store is not None:
            core.store.close()
        core.release_runtime()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_engine_cleanup_failure_records_unknown_without_releasing_graph_owner(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    core = service(paths, socket_path, token_file, Provider())
    read_fd, write_fd = os.pipe()
    try:
        await core.start(read_fd)
        original_close = core.engine.close
        closed = []
        original_management_close = core.management.close

        async def cannot_finish():
            await original_close()
            raise RuntimeError("Engine cleanup unverified")

        async def management_close():
            closed.append("management")
            await original_management_close()

        core.engine.close = cannot_finish
        core.management.close = management_close
        with pytest.raises(RuntimeError, match="Engine cleanup unverified"):
            await core.close()
        assert closed == ["management"]
        assert core.resource_cleanup.public()["state"] == "unknown"
        assert core.resource_cleanup.public()["reconciliation_required"]
        assert not core.store._closed
        contender = OwnerAuthority(paths, app_bootstrap=True)
        with pytest.raises(Exception):
            contender.acquire_runtime()
    finally:
        if core.store is not None:
            core.store.close()
        core.release_runtime()
        os.close(read_fd)
        os.close(write_fd)
