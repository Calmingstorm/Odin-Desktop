"""Bounded optional session helper paths with no real desktop bus or pipe."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.desktop import session_end as module


@pytest.mark.asyncio
async def test_end_callback_and_response_failures_do_not_delay_finished_exit(monkeypatch):
    callback = AsyncMock(side_effect=RuntimeError("fixture callback failed"))
    monitor = module.SessionEndMonitor(callback)
    monitor.finished.set()
    monitor.owner = ":fixture"
    monitor.client_path = "/fixture"
    call = AsyncMock(side_effect=RuntimeError("fixture bus failed"))
    monkeypatch.setattr(monitor, "_call", call)
    await monitor._end()
    callback.assert_awaited_once()
    call.assert_awaited_once_with(":fixture", "/fixture", module.CLIENT,
                                 "EndSessionResponse", "bs", [True, ""])


@pytest.mark.asyncio
async def test_helper_no_registered_manager_closes_without_reading_parent_pipe(monkeypatch):
    monitor = SimpleNamespace(start=Mock(), startup=None, client_path=None, close=AsyncMock())
    monkeypatch.setattr(module, "SessionEndMonitor", Mock(return_value=monitor))
    connect = AsyncMock(side_effect=AssertionError("must not read pipe"))
    monkeypatch.setattr(asyncio.get_running_loop(), "connect_read_pipe", connect)
    await module.run()
    monitor.start.assert_called_once()
    monitor.close.assert_awaited_once()
    connect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("read_fails", [False, True])
async def test_registered_helper_reads_parent_pipe_and_always_closes(
        monkeypatch, capsys, read_fails):
    monitor = SimpleNamespace(start=Mock(), startup=asyncio.sleep(0),
                             client_path="/fixture", close=AsyncMock())
    constructor = Mock(return_value=monitor)
    monkeypatch.setattr(module, "SessionEndMonitor", constructor)
    reader = SimpleNamespace(read=AsyncMock(side_effect=OSError("fixture pipe closed")
                                            if read_fails else None))
    reader_constructor = Mock(return_value=reader)
    protocol = object()
    protocol_constructor = Mock(return_value=protocol)
    monkeypatch.setattr(module.asyncio, "StreamReader", reader_constructor)
    monkeypatch.setattr(module.asyncio, "StreamReaderProtocol", protocol_constructor)
    transport = SimpleNamespace(close=Mock())
    connect = AsyncMock(return_value=(transport, None))
    monkeypatch.setattr(asyncio.get_running_loop(), "connect_read_pipe", connect)
    if read_fails:
        with pytest.raises(OSError, match="fixture pipe closed"):
            await module.run()
    else:
        await module.run()
    monitor.start.assert_called_once()
    reader.read.assert_awaited_once()
    monitor.close.assert_awaited_once()
    transport.close.assert_called_once()
    assert connect.await_args.args[0]() is protocol
    assert connect.await_args.args[1] is module.sys.stdin
    protocol_constructor.assert_called_once_with(reader)
    await constructor.call_args.args[0]()
    assert capsys.readouterr().out == "session-ending\n"
