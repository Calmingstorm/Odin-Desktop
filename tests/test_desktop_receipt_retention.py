"""Capability refusal is cheap; served command identities survive retention."""
import asyncio
import os
import uuid

import pytest

from src.desktop import core
from src.desktop.commands import CommandJournal, JournalStorageError, JournalStore, response_error
from tests.test_desktop_core_lifecycle import connect, profile, receive, request, send

UNAVAILABLE = (
    "work.list", "search.query", "notifications.ack",
    "conversations.create", "conversations.update", "submission.send", "control.stop",
    "control.steer", "conversations.list", "messages.list", "conversation.snapshot",
    "unknown.method",
    "messages.around", "artifacts.read", "reports.page", "tool.detail", "tool.output",
    "skills.list", "skills.get", "skills.config.get", "mcp.list", "mcp.status", "mcp.tools",
    "schedules.list", "schedules.history", "schedules.validate_cron", "computer.status",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", UNAVAILABLE)
async def test_unavailable_method_never_reserves_even_invalid_or_quiescing(tmp_path, method):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = core.CoreService(paths, socket_path, token_file)
    writer = None
    try:
        await service.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        statements = []
        service.store.connection.set_trace_callback(statements.append)
        command_id = str(uuid.uuid4())
        first = await request(reader, writer, method, {}, command_id)
        assert first["error"]["code"] == "capability_unavailable"
        await send(writer, {"t": "req", "id": command_id, "method": method, "params": []})
        assert await receive(reader) == first
        service.lifetime.request_stop("test")
        second = await request(reader, writer, method, {"changed": True}, command_id)
        assert second == first
        assert service.store.connection.execute(
            "SELECT count(*) FROM command_receipts").fetchone()[0] == 0
        assert not any(sql.startswith(("BEGIN", "INSERT", "UPDATE", "DELETE"))
                       for sql in statements)
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await service.close()
        os.close(read_fd)
        os.close(write_fd)


def test_protocol_reads_are_classified_including_stream_control():
    assert {
        "status.get", "events.subscribe", "conversations.list", "messages.list",
        "conversation.snapshot", "usage.get", "work.list", "settings.schema", "search.query",
        "messages.around", "artifacts.read", "reports.page", "tool.detail", "tool.output",
        "codex.accounts.list", "models.agents.get", "models.discover", "personality.get",
        "tools.list", "tools.timeouts.get", "skills.list", "skills.get", "skills.config.get",
        "mcp.list", "mcp.status", "mcp.tools", "webhooks.outbound.list",
        "hosts.list", "hosts.references", "schedules.list", "schedules.history",
        "schedules.validate_cron", "memory.list", "memory.get", "lists.list", "lists.get",
        "knowledge.list", "knowledge.search", "knowledge.versions", "audit.query",
        "audit.verify", "health.get", "logs.search", "turn_state.list", "computer.status",
    } <= core.READ_METHODS
    assert "notifications.ack" not in core.READ_METHODS
    assert "runtime.shutdown" not in core.READ_METHODS


def test_identity_lookup_is_read_only(tmp_path):
    store = JournalStore(tmp_path / "journal" / "transport.sqlite3", "test")
    try:
        commands = CommandJournal(store)
        commands.execute("bound", "runtime.shutdown", {},
                         lambda: response_error("bad_request", "Missing reason"))
        statements = []
        store.connection.set_trace_callback(statements.append)
        assert commands.check("fresh", "status.get", {}) is None
        assert commands.check("bound", "usage.get", {})["error"]["code"] == "id_conflict"
        assert not any(sql.startswith(("BEGIN", "COMMIT", "INSERT", "UPDATE", "DELETE"))
                       for sql in statements)
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("on_start", [False, True])
async def test_scheduled_prune_keeps_unknown_pending_and_tombstone_bindings(
        tmp_path, monkeypatch, on_start):
    monkeypatch.setattr(core, "RECEIPT_PRUNE_INTERVAL", 0.01, raising=False)
    monkeypatch.setattr(core, "RECEIPT_RETENTION", 60, raising=False)
    paths, socket_path, token_file = profile(tmp_path)
    ids = {name: str(uuid.uuid4()) for name in ("known", "unknown", "pending", "legacy")}
    unknown = response_error("internal", "Unresolved outcome", "outcome_unknown")
    legacy = response_error("capability_unavailable", "Old durable refusal")

    def seed(service):
        service.commands.execute(ids["known"], "runtime.shutdown", {},
                                 lambda: response_error("bad_request", "Missing reason"))
        service.commands.execute(ids["unknown"], "runtime.shutdown", {}, lambda: unknown)

        def interrupted():
            raise RuntimeError("Harmless stub failure")

        service.commands.execute(ids["pending"], "runtime.shutdown", {}, interrupted)
        service.commands.execute(ids["legacy"], "notifications.ack", {}, lambda: legacy)
        with service.store.transaction() as db:
            db.execute("UPDATE command_receipts SET finished_at=1 WHERE state='final'")

    read_fd, write_fd = os.pipe()
    service = core.CoreService(paths, socket_path, token_file)
    writer = None
    task = None
    try:
        await service.start(read_fd)
        seed(service)
        if on_start:
            await service.close()
            service = core.CoreService(paths, socket_path, token_file)
            await service.start(read_fd)
            assert service.store.connection.execute(
                "SELECT state FROM command_receipts WHERE command_id=?",
                (ids["known"],)).fetchone()[0] == "expired"
        async with asyncio.timeout(1):
            while service.store.connection.execute(
                    "SELECT state FROM command_receipts WHERE command_id=?",
                    (ids["known"],)).fetchone()[0] != "expired":
                await asyncio.sleep(0.01)
        task = service._receipt_pruner
        rows = {row["command_id"]: dict(row) for row in service.store.connection.execute(
            "SELECT * FROM command_receipts")}
        assert rows[ids["known"]]["response"] is None
        assert rows[ids["legacy"]]["response"] is None
        assert rows[ids["unknown"]]["state"] == "final"
        assert rows[ids["unknown"]]["unknown_outcome"] == 1
        assert rows[ids["pending"]]["state"] == "pending"
        await service.close()
        assert task.done()
        service = core.CoreService(paths, socket_path, token_file)
        await service.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        for name in ("known", "legacy"):
            method = "notifications.ack" if name == "legacy" else "runtime.shutdown"
            expired = await request(reader, writer, method, {}, ids[name])
            assert expired["error"]["code"] == "receipt_expired"
            assert expired["error"]["disposition"] == "outcome_unknown"
        assert (await request(reader, writer, "runtime.shutdown", {}, ids["unknown"])) == {
            "t": "res", "id": ids["unknown"], **unknown,
        }
        pending = await request(reader, writer, "runtime.shutdown", {}, ids["pending"])
        assert pending["error"]["disposition"] == "outcome_unknown"
        for command_id in ids.values():
            for method in ("usage.get", "events.subscribe", "unknown.method", "runtime.shutdown"):
                conflict = await request(reader, writer, method, {"reason": "changed"}, command_id)
                assert conflict["error"]["code"] == "id_conflict"
        assert service.lifetime.admitting
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await service.close()
        if task is not None:
            assert task.done()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_busy_shutdown_refusal_remains_final_after_restart(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    command_id = str(uuid.uuid4())
    original = None
    for restart in range(2):
        read_fd, write_fd = os.pipe()
        service = core.CoreService(paths, socket_path, token_file)
        writer = None
        try:
            await service.start(read_fd)
            reader, writer, _ = await connect(socket_path)
            if not restart:
                service.lifetime.request_stop("test")
            answer = await request(
                reader, writer, "runtime.shutdown", {"reason": "test"}, command_id,
            )
            assert answer["error"]["code"] == "busy"
            if restart:
                assert answer == original
                assert service.lifetime.admitting
            original = answer
            conflict = await request(reader, writer, "notifications.ack", {}, command_id)
            assert conflict["error"]["code"] == "id_conflict"
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await service.close()
            os.close(read_fd)
            os.close(write_fd)


@pytest.mark.asyncio
async def test_preexisting_unavailable_receipt_still_replays_and_conflicts(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = core.CoreService(paths, socket_path, token_file)
    writer = None
    command_id = str(uuid.uuid4())
    old_refusal = response_error("capability_unavailable", "Original durable refusal")
    try:
        await service.start(read_fd)
        service.commands.execute(command_id, "conversations.create", {"title": "old"},
                                 lambda: old_refusal)
        await service.close()
        service = core.CoreService(paths, socket_path, token_file)
        await service.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        answer = await request(reader, writer, "conversations.create", {"title": "old"}, command_id)
        assert answer == {
            "t": "res", "id": command_id, **old_refusal,
        }
        for method in ("conversations.create", "usage.get", "runtime.shutdown"):
            conflict = await request(reader, writer, method, {"reason": "changed"}, command_id)
            assert conflict["error"]["code"] == "id_conflict"
        assert service.store.connection.execute(
            "SELECT count(*) FROM command_receipts").fetchone()[0] == 1
        assert service.lifetime.admitting
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await service.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_periodic_prune_storage_failure_stops_admission_and_cleans_task(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(core, "RECEIPT_PRUNE_INTERVAL", 0.01)
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    service = core.CoreService(paths, socket_path, token_file)
    try:
        await service.start(read_fd)

        def unavailable(before):
            raise JournalStorageError()

        monkeypatch.setattr(service.commands, "prune", unavailable)
        await asyncio.wait_for(service.lifetime.wait(), 1)
        assert service.lifetime.reason == "storage_unavailable"
        assert not service.lifetime.admitting
        await service.close()
        assert service._receipt_pruner.done()
        assert service.authority._runtime_lock_fd is None
    finally:
        await service.close()
        os.close(read_fd)
        os.close(write_fd)
