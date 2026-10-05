"""Real local transport and restart proofs for the durable conversation graph."""
import os
import uuid

import pytest

from src.desktop.core import CoreService
from tests.test_desktop_core_lifecycle import connect, profile, receive, request


@pytest.mark.asyncio
async def test_conversation_admission_receipt_and_transcript_survive_core_restart(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    command_id = str(uuid.uuid4())
    created = None
    for restart in range(2):
        read_fd, write_fd = os.pipe()
        core = CoreService(paths, socket_path, token_file)
        writer = None
        try:
            await core.start(read_fd)
            reader, writer, welcome = await connect(socket_path)
            assert "conversations.create" in welcome["capabilities"]
            answer = await request(
                reader, writer, "conversations.create", {"title": "Durable"}, command_id)
            assert answer["ok"]
            if not restart:
                created = answer
                cid = answer["result"]["conversation"]["id"]
                core.transcript.commit(cid, "user", "a visible fact", client_submission_id="seed")
                core.transcript.commit(cid, "assistant", "a guarded reply")
            else:
                assert answer == created
                cid = answer["result"]["conversation"]["id"]
            listing = await request(reader, writer, "conversations.list")
            assert len(listing["result"]["items"]) == 1
            snapshot = await request(
                reader, writer, "conversation.snapshot", {"conversation_id": cid})
            assert [m["text"] for m in snapshot["result"]["messages"]["items"]] == [
                "a visible fact", "a guarded reply"]
            assert snapshot["result"]["watermark"] == core.events.high
            assert snapshot["result"]["unresolved"] == []
            assert core.store.connection.execute(
                "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
                (command_id,)).fetchone()[0] == 1
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await core.close()
            os.close(read_fd)
            os.close(write_fd)


@pytest.mark.asyncio
async def test_snapshot_then_subscription_replays_exact_committed_tail(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file)
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        created = await request(reader, writer, "conversations.create", {})
        cid = created["result"]["conversation"]["id"]
        snapshot = await request(reader, writer, "conversation.snapshot", {"conversation_id": cid})
        watermark = snapshot["result"]["watermark"]
        message = core.transcript.commit(cid, "assistant", "tail committed after the snapshot")
        subscription = await request(reader, writer, "events.subscribe", {"after": watermark})
        assert not subscription["result"]["reset_required"]
        tail = [await receive(reader) for _ in core.events.between(watermark)]
        assert tail == core.events.between(watermark)
        assert tail[0]["payload"]["message"] == message
        assert int(tail[0]["cursor"]) > int(watermark)
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_invalid_domain_command_is_a_durable_refusal_not_an_unknown_outcome(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file)
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        command_id = str(uuid.uuid4())
        first = await request(reader, writer, "conversations.delete",
                              {"id": "missing", "expected_rev": 1}, command_id)
        assert first["error"]["code"] == "not_found"
        assert first["error"]["disposition"] != "outcome_unknown"
        again = await request(reader, writer, "conversations.delete",
                              {"id": "missing", "expected_rev": 1}, command_id)
        assert again == first
        search = await request(reader, writer, "search.query", {"query": " ", "limit": 5})
        assert search["error"]["code"] == "bad_request"
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
