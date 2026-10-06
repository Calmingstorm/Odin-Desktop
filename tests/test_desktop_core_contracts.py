"""Narrow missing seam pins, not a replacement for the existing contract suites.

Use real temporary-profile CoreService, IPC and the retained guarded runner.
Only the provider is deterministic and harmless. Run with run-phase1-tests.py.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

import pytest

from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, service, settled


@asynccontextmanager
async def running_core(paths, socket_path, token_file, provider):
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _welcome = await connect(socket_path)
        yield core, reader, writer
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        provider.release.set()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


async def wait_for_calls(provider, count):
    async def wait():
        while provider.calls < count:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 5)


@pytest.mark.asyncio
async def test_foreground_ownership_is_per_conversation_not_per_profile(tmp_path):
    """Section 1.5: a blocked owner serializes its thread, not other threads."""
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider(blocked=True)
    async with running_core(paths, socket_path, token_file, provider) as (core, reader, writer):
        conversations = []
        for title in ("First thread", "Independent thread"):
            created = await request(reader, writer, "conversations.create", {"title": title})
            assert created["ok"]
            conversations.append(created["result"]["conversation"]["id"])
        first_cid, second_cid = conversations
        first = await request(reader, writer, "submission.send", {
            "client_submission_id": "first-owner", "conversation_id": first_cid,
            "text": "Wait for a harmless deterministic result"})
        await wait_for_calls(provider, 1)
        queued = await request(reader, writer, "submission.send", {
            "client_submission_id": "first-followup", "conversation_id": first_cid,
            "text": "A separate follow-up, not steering"})
        independent = await request(reader, writer, "submission.send", {
            "client_submission_id": "second-owner", "conversation_id": second_cid,
            "text": "Run independently of the first conversation"})
        assert first["ok"] and queued["ok"] and independent["ok"]
        await wait_for_calls(provider, 2)

        first_snapshot = await request(reader, writer, "conversation.snapshot", {
            "conversation_id": first_cid})
        second_snapshot = await request(reader, writer, "conversation.snapshot", {
            "conversation_id": second_cid})
        assert first_snapshot["result"]["running"]["request_id"] == first["result"]["request_id"]
        assert [row["request_id"] for row in first_snapshot["result"]["queued"]] == [
            queued["result"]["request_id"]]
        assert second_snapshot["result"]["running"]["request_id"] == (
            independent["result"]["request_id"])
        assert second_snapshot["result"]["queued"] == []
        assert provider.calls == 2
        assert not provider.release.is_set()
        # Pending user messages are visible, but no provider candidate is yet a final.
        assert all(message["role"] != "assistant" for snapshot in (first_snapshot, second_snapshot)
                   for message in snapshot["result"]["messages"]["items"])

        provider.release.set()
        await settled(core)
        assert provider.calls == 3
        for cid, expected in ((first_cid, 2), (second_cid, 1)):
            snapshot = await request(reader, writer, "conversation.snapshot", {
                "conversation_id": cid})
            assert snapshot["result"]["running"] is None
            assert snapshot["result"]["queued"] == []
            assert len([m for m in snapshot["result"]["messages"]["items"]
                        if m["role"] == "assistant"]) == expected


@pytest.mark.asyncio
async def test_deleted_destination_submission_identity_survives_core_restart(tmp_path):
    """Section 1.4: visible deletion/restart cannot admit a forgotten ID again.

    This does NOT certify body-free tombstones: the current canonical binding
    still retains submitted text. That separate privacy gap is listed in the map.
    """
    paths, socket_path, token_file = profile(tmp_path)
    first_receipt = None
    original = None
    for restart in range(2):
        provider = Provider()
        async with running_core(paths, socket_path, token_file, provider) as (core, reader, writer):
            if not restart:
                created = await request(reader, writer, "conversations.create")
                cid = created["result"]["conversation"]["id"]
                original = {"client_submission_id": "lifetime-id", "conversation_id": cid,
                            "text": "A harmless visible input that will be deleted"}
                accepted = await request(reader, writer, "submission.send", original)
                assert accepted["ok"]
                first_receipt = accepted["result"]
                await settled(core)
                assert provider.calls == 1
                current = await request(reader, writer, "conversations.list")
                revision = next(item["rev"] for item in current["result"]["items"]
                                if item["id"] == cid)
                deleted = await request(reader, writer, "conversations.delete", {
                    "id": cid, "expected_rev": revision})
                assert deleted["ok"]
                row = core.requests.get_request(first_receipt["request_id"])
                assert row["text"] == "" and json.loads(row["attachments"]) == []

            before = provider.calls
            # New transport command IDs force domain deduplication, not a cached RPC.
            duplicate = await request(reader, writer, "submission.send", original)
            assert duplicate["ok"] and duplicate["result"] == first_receipt
            conflict = await request(reader, writer, "submission.send", {
                **original, "text": "Changed input must not become a second execution"})
            assert conflict["error"]["code"] == "id_conflict"
            replacement = await request(reader, writer, "conversations.create")
            replacement_cid = replacement["result"]["conversation"]["id"]
            retargeted = await request(reader, writer, "submission.send", {
                **original, "conversation_id": replacement_cid})
            assert retargeted["error"]["code"] == "id_conflict"
            await settled(core)
            assert provider.calls == before
            snapshot = await request(reader, writer, "conversation.snapshot", {
                "conversation_id": replacement_cid})
            assert snapshot["result"]["messages"]["items"] == []
            assert snapshot["result"]["running"] is None
            assert snapshot["result"]["queued"] == []
