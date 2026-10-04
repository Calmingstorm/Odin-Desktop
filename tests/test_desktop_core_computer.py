"""Pure policy and unavailable Phase 2 admission. No native lifecycle/input."""

from dataclasses import replace

import pytest

from src.computer.integration import ComputerIntegration
from src.computer.manager import ComputerLifecycle
from src.computer.models import ComputerError, RequestContext, SessionGrant
from src.computer.policy import foreground, owned


def context():
    return RequestContext("owner", "conversation", "turn", "localhost")


def test_foreground_is_desktop_only_and_not_background():
    foreground(context())
    for surface in ("discord", "webui", "", "untrusted"):
        with pytest.raises(ComputerError, match="foreground_only"):
            foreground(replace(context(), surface=surface))
    with pytest.raises(ComputerError, match="foreground_only"):
        foreground(replace(context(), origin="agent"))


@pytest.mark.parametrize("field", ["owner_id", "channel_id", "turn_id", "host_id"])
def test_desktop_context_still_requires_exact_owner_conversation_turn_host(field):
    grant = SessionGrant("session", "owner", "conversation", "turn", "localhost", 1,
                         "active", "drawing", 0, 100)
    owned(context(), grant)
    with pytest.raises(ComputerError, match="not_found"):
        owned(replace(context(), **{field: "foreign"}), grant)


def test_phase1_admission_never_infers_authority_from_bot_or_message():
    service = ComputerIntegration.__new__(ComputerIntegration)
    assert service._authorize(context()) is False
    assert ComputerLifecycle.authorize_context(object(), context()) is False
    with pytest.raises(PermissionError, match="unavailable until Phase 2"):
        service._context(object())
    with pytest.raises(PermissionError, match="unavailable until Phase 2"):
        service._operator_context("owner", "guessed-session", emergency=True)


@pytest.mark.asyncio
async def test_phase1_control_and_finalization_cannot_make_unadmitted_requests():
    service = ComputerIntegration.__new__(ComputerIntegration)
    with pytest.raises(PermissionError, match="unavailable until Phase 2"):
        await service.stop_channel("owner", "guessed-conversation")
    with pytest.raises(PermissionError, match="unavailable until Phase 2"):
        await service.finish_turn(object())
