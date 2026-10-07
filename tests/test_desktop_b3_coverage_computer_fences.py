"""Pure computer admission refusal paths; no native backend or display input."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.computer.models import ComputerError
from src.desktop.computer_binding import ComputerForegroundBinding, bind_foreground


def binding():
    requests = SimpleNamespace(assert_request=Mock(),
        binding=Mock(return_value=None), is_background=Mock(return_value=False))
    controller = SimpleNamespace(finish_turn=AsyncMock(), enabled=True, _recoveries={})
    config = SimpleNamespace(computer=SimpleNamespace(enabled=True))
    return ComputerForegroundBinding(requests, controller=controller, config=config), requests


def test_no_publication_cannot_create_backend():
    computer, _ = binding()
    with pytest.raises(ComputerError, match="desktop_x11_backend_unavailable"):
        computer._backend()


@pytest.mark.asyncio
async def test_queued_or_absent_request_cannot_acquire_foreground_identity():
    computer, requests = binding()
    message = SimpleNamespace(conversation_id="cid", request_id="rid", generation=1,
                              owner_id="owner")
    for row in (None, {"state": "queued"}):
        requests.binding.return_value = row
        with pytest.raises(PermissionError, match="Foreground request is not running"):
            computer.enter_request(message)
    assert computer._requests.get() is None and computer._active_requests == {}


@pytest.mark.asyncio
async def test_retiring_unbound_request_cannot_call_cleanup():
    computer, _ = binding()
    with pytest.raises(PermissionError, match="Only the admitted root"):
        await computer.leave_request(None)
    computer.controller.finish_turn.assert_not_awaited()


def test_foreground_composition_requires_started_management_owner():
    service = SimpleNamespace(_started=False, _closed=False, controller=object())
    with pytest.raises(RuntimeError, match="started before binding"):
        bind_foreground(service, object())
