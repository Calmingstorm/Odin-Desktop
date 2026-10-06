"""Real admitted foreground requests delegate durable task-owned destinations."""
from __future__ import annotations

import asyncio
import os

import pytest

from src.llm.types import LLMResponse
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, service, settled


class DelegatingProvider(Provider):
    def __init__(self):
        super().__init__()
        self.child_started = asyncio.Event()
        self.child_release = asyncio.Event()
        self.child = None
        self.child_task = None

    async def chat_with_tools(self, **_kwargs):
        self.calls += 1
        parent = self.core.requests.current_bound_request()
        self.child = self.core.requests.register_background(
            parent, "task", "test-task", "Read status")

        async def run_child():
            async with self.core.requests.background_execution(self.child):
                self.core.requests.assert_request(self.child)
                self.child_started.set()
                await self.child_release.wait()
                await self.core.delivery.send(self.child.channel, "Stored task result")

        self.child_task = asyncio.create_task(run_child())
        await self.child_started.wait()
        return LLMResponse(text="Delegated.")


@pytest.mark.asyncio
async def test_background_destination_survives_foreground_settlement_and_cannot_replay(
        tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = DelegatingProvider()
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        created = await request(reader, writer, "conversations.create")
        cid = created["result"]["conversation"]["id"]
        admitted = await request(reader, writer, "submission.send", {
            "client_submission_id": "delegate", "conversation_id": cid, "text": "Delegate status"})
        rid = admitted["result"]["request_id"]
        await asyncio.wait_for(provider.child_started.wait(), 5)
        async with asyncio.timeout(5):
            while core.requests.get_request(rid)["state"] == "running":
                await asyncio.sleep(.01)
        assert core.requests.get_request(rid)["state"] == "completed"
        with pytest.raises(PermissionError):
            core.requests.register_background(provider.child, "task", "forged", "Status")
        with pytest.raises(PermissionError):
            core.requests.assert_request(provider.child)
        provider.child_release.set()
        await settled(core)
        assert core.requests.get_request(provider.child.request_id)["state"] == "completed"
        assert core.transcript.list(cid)["items"][-1]["text"] == "Stored task result"
        with pytest.raises(PermissionError):
            async with core.requests.background_execution(provider.child):
                pytest.fail("A settled background run was replayed")
    finally:
        provider.child_release.set()
        if writer:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
