"""Fixture waits stay bounded without replaying a command or changing contracts."""
from __future__ import annotations

import asyncio
import json
import struct
from types import SimpleNamespace

import pytest

from tests import test_desktop_core_lifecycle as harness


@pytest.mark.asyncio
async def test_receipt_has_one_fifteen_second_budget_for_the_complete_frame(monkeypatch):
    budgets = []
    original_timeout = asyncio.timeout

    def recorded_timeout(seconds):
        budgets.append(seconds)
        return original_timeout(seconds)

    monkeypatch.setattr(harness.asyncio, "timeout", recorded_timeout)
    encoded = json.dumps({"t": "res", "id": "one", "ok": True}).encode()
    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack(">I", len(encoded)) + encoded)
    assert await harness.receive(reader) == {"t": "res", "id": "one", "ok": True}
    assert budgets == [15]


@pytest.mark.asyncio
async def test_receipt_expiry_still_raises_without_a_second_read(monkeypatch):
    monkeypatch.setattr(harness, "CORE_RECEIPT_WAIT_SECONDS", 0.01)
    calls = []

    class Reader:
        async def readexactly(self, count):
            calls.append(count)
            await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await harness.receive(Reader())
    assert calls == [4]


@pytest.mark.asyncio
async def test_startup_has_one_twenty_five_second_budget(monkeypatch):
    budgets = []
    calls = []
    original_timeout = asyncio.timeout

    def recorded_timeout(seconds):
        budgets.append(seconds)
        return original_timeout(seconds)

    async def connect(path):
        calls.append(path)
        return "reader", "writer", {"t": "welcome"}

    monkeypatch.setattr(harness.asyncio, "timeout", recorded_timeout)
    monkeypatch.setattr(harness, "connect", connect)
    assert await harness.wait_connected(SimpleNamespace(returncode=None), "socket") == (
        "reader", "writer", {"t": "welcome"})
    assert budgets == [25]
    assert calls == ["socket"]


@pytest.mark.asyncio
async def test_startup_deadline_bounds_a_stalled_connect_without_relaunch(monkeypatch):
    monkeypatch.setattr(harness, "CORE_STARTUP_WAIT_SECONDS", 0.01)
    calls = []

    async def connect(path):
        calls.append(path)
        await asyncio.Event().wait()

    monkeypatch.setattr(harness, "connect", connect)
    with pytest.raises(pytest.fail.Exception, match="core did not publish its listener"):
        await harness.wait_connected(SimpleNamespace(returncode=None), "socket")
    assert calls == ["socket"]


@pytest.mark.asyncio
async def test_startup_exited_process_still_fails_immediately(monkeypatch):
    calls = []

    async def communicate():
        calls.append("communicate")
        return b"output", b"failed"

    async def connect(path):
        pytest.fail("An exited process must not be connected or relaunched")

    monkeypatch.setattr(harness, "connect", connect)
    with pytest.raises(pytest.fail.Exception, match="core exited 7"):
        await harness.wait_connected(
            SimpleNamespace(returncode=7, communicate=communicate), "socket")
    assert calls == ["communicate"]


@pytest.mark.asyncio
async def test_request_sends_once_and_preserves_response_identity_on_expiry(monkeypatch):
    calls = []

    async def send(writer, message):
        calls.append(message)

    async def receive(reader):
        raise TimeoutError

    monkeypatch.setattr(harness, "send", send)
    monkeypatch.setattr(harness, "receive", receive)
    with pytest.raises(TimeoutError):
        await harness.request("reader", "writer", "tools.set_enabled",
                              {"name": "run_command", "enabled": False}, "same-id")
    assert calls == [{"t": "req", "id": "same-id", "method": "tools.set_enabled",
                      "params": {"name": "run_command", "enabled": False}}]
