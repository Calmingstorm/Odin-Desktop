"""Real dbus-next behaviour on a throwaway bus inside the PID runner."""
import asyncio
import subprocess
from pathlib import Path

import pytest
from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus

from src.desktop.session_end import CLIENT, SessionEndMonitor
from tests.desktop_fixtures.private_session_manager import CLIENT_PATH, NAME, PATH, Client, Manager


@pytest.fixture
def bus_address(monkeypatch):
    daemon = subprocess.Popen([
        "dbus-daemon", "--nofork", "--print-address=1", "--config-file=" + str(
            Path(__file__).parent / "desktop_fixtures/private-session.conf")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    address = daemon.stdout.readline().strip()
    assert address.startswith("unix:")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    try:
        yield address
    finally:
        daemon.terminate()
        daemon.wait(timeout=5)
        daemon.stdout.close()
        daemon.stderr.close()


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("member", ["EndSession", "Stop"])
async def test_cancel_runs_and_end_once_ack_after_cleanup(bus_address, member):
    bus = await MessageBus(bus_address=bus_address).connect()
    client, manager = Client(), Manager()
    bus.export(PATH, manager)
    bus.export(CLIENT_PATH, client)
    await bus.request_name(NAME)
    ends = []

    async def end():
        ends.append(True)

    monitor = SessionEndMonitor(end)
    monitor.start()
    try:
        await monitor.startup
        assert monitor.client_path == CLIENT_PATH
        assert manager.clients == [["odin-desktop", ""]]
        client.QueryEndSession(0)
        await until(lambda: len(client.responses) == 1)
        client.CancelEndSession()
        await asyncio.sleep(0.05)
        assert ends == []
        # Other senders and paths cannot end the app.
        monitor._signal(Message(message_type=MessageType.SIGNAL, sender=":other",
                                path=CLIENT_PATH, interface=CLIENT, member="Stop"))
        monitor._signal(Message(message_type=MessageType.SIGNAL, sender=bus.unique_name,
                                path="/Other", interface=CLIENT, member="Stop"))
        assert ends == []
        getattr(client, member)(*([0] if member == "EndSession" else []))
        await until(lambda: ends)
        client.EndSession(0)
        await asyncio.sleep(0.05)
        assert ends == [True]
        assert len(client.responses) == 1  # not yet done persisting app receipt
        await monitor.close()
        assert client.responses == [[True, ""], [True, ""]]
        assert not monitor.tasks
    finally:
        await monitor.close()
        bus.disconnect()


@pytest.mark.asyncio
async def test_missing_manager_fails_open_without_activating_service(bus_address):
    monitor = SessionEndMonitor(lambda: None)
    monitor.start()
    await monitor.startup
    assert monitor.bus is None
    assert monitor.client_path is None
    await monitor.close()


@pytest.mark.asyncio
async def test_missing_bus_does_not_start(monkeypatch):
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monitor = SessionEndMonitor(lambda: None)
    monitor.start()
    assert monitor.startup is None
    await monitor.close()


@pytest.mark.asyncio
async def test_end_response_is_bounded_even_if_parent_never_finishes(bus_address, monkeypatch):
    bus = await MessageBus(bus_address=bus_address).connect()
    client = Client()
    bus.export(PATH, Manager())
    bus.export(CLIENT_PATH, client)
    await bus.request_name(NAME)
    monitor = SessionEndMonitor(lambda: asyncio.sleep(0))
    monitor.start()
    try:
        await monitor.startup
        # Shorten only the test's parent wait, leaving real D-Bus calls intact.
        original = asyncio.wait_for

        async def shortened(awaitable, timeout):
            return await original(awaitable, min(timeout, 0.1))

        monkeypatch.setattr("src.desktop.session_end.asyncio.wait_for", shortened)
        client.EndSession(0)
        await until(lambda: len(client.responses) == 1)
        assert monitor.ending
    finally:
        await monitor.close()
        bus.disconnect()
