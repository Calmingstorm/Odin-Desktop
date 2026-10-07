"""Cancellation at lock handoff must not release another dispatch's envelope."""
import asyncio
import uuid
from types import SimpleNamespace

import pytest

from src.desktop import management, secrets
from tests.test_desktop_keyring_retry import collection, core  # noqa: F401


class HandoffLock(asyncio.Lock):
    """Real asyncio lock with deterministic observation/cancellation at handoff."""

    def __init__(self):
        super().__init__()
        self.dispatch = None
        self.owner = None
        self.acquiring = None
        self.reacquiring = asyncio.Event()
        self.releases = []
        self.cancel_on_handoff = False

    async def acquire(self):
        task = asyncio.current_task()
        if self.locked() and task is not self.dispatch:
            self.acquiring = task
            self.reacquiring.set()
        await super().acquire()
        self.owner = task
        if task is self.acquiring and self.cancel_on_handoff:
            # Cancel the real dispatch while its shield still awaits delivery.
            # Returning immediately makes this acquisition Task done before
            # dispatch handles cancellation, reproducing the handoff race.
            self.dispatch.cancel()
        return True

    def release(self):
        self.releases.append((asyncio.current_task(), self.owner))
        super().release()
        self.owner = None


@pytest.mark.asyncio
async def test_cancelled_unlock_reacquires_before_outer_envelope_release(
    core, collection, monkeypatch,  # noqa: F811 - imported pytest fixtures
):
    import threading

    monkeypatch.setattr(secrets, "UNLOCK_TIMEOUT", 100)
    service, *_ = core
    serial = HandoffLock()
    service._serial = serial
    collection.answer = threading.Event()
    collection.values["email.smtp.password"] = "fixture-never-adopted"
    settings = service.management.settings
    revision, event_high = settings.revision, service.events.high
    command_id = str(uuid.uuid4())
    request = {"id": command_id, "method": "secrets.unlock", "params": {}}
    shield_again = asyncio.Event()
    real_shield = asyncio.shield
    shield_calls = []

    def observe_shield(future):
        result = real_shield(future)
        if (asyncio.current_task() is serial.dispatch
                and isinstance(future, asyncio.Task)
                and future.get_coro().__name__ == "acquire"):
            shield_calls.append((future, result))
            if len(shield_calls) == 2:
                shield_again.set()
        return result

    monkeypatch.setattr(management.asyncio, "shield", observe_shield)
    connection = SimpleNamespace(owner_context=service.authority.authenticate_local(
        peer_uid=service.authority.owner_uid,
    ))
    dispatch = asyncio.create_task(service.dispatch(connection, request))
    serial.dispatch = dispatch
    contender = asyncio.current_task()
    try:
        assert await asyncio.to_thread(collection.started.wait, 2), (
            dispatch.result() if dispatch.done() else "unlock did not start"
        )
        row = service.store.connection.execute(
            "SELECT * FROM command_receipts WHERE command_id=?", (command_id,),
        ).fetchone()
        assert row["state"] == "pending" and row["response"] is None
        assert not service.store.connection.in_transaction
        # The prompt is genuinely outside serialization. A competing ordered
        # operation owns the real lock before cancellation starts reacquisition.
        await serial.acquire()
        assert serial.owner is contender
        dispatch.cancel()
        await asyncio.wait_for(serial.reacquiring.wait(), 2)
        assert serial.locked() and serial.owner is contender
        dispatch.cancel()
        await asyncio.wait_for(shield_again.wait(), 2)
        assert serial.locked() and serial.owner is contender
        assert not dispatch.done()
        assert not serial.acquiring.done() and not serial.acquiring.cancelled()
        assert shield_calls[0][1].cancelled()
        assert not shield_calls[1][1].done()
        assert shield_calls[0][0] is shield_calls[1][0] is serial.acquiring

        serial.cancel_on_handoff = True
        serial.release()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(dispatch, 2)
        assert dispatch.cancelled() and dispatch.cancelling() == 3
        assert serial.acquiring.done() and not serial.acquiring.cancelled()
        assert serial.acquiring.result() is True
        assert not serial.locked()
        assert serial.releases == [
            (dispatch, dispatch), (contender, contender),
            (dispatch, serial.acquiring),
        ]
        # Cancellation never finalizes success, adopts late native credentials,
        # emits a settings event, or readmits the same journal identity.
        row = service.store.connection.execute(
            "SELECT * FROM command_receipts WHERE command_id=?", (command_id,),
        ).fetchone()
        assert row["state"] == "pending" and row["response"] is None
        assert row["finished_at"] is None
        assert "fixture-never-adopted" not in row["binding"]
        assert not service.store.connection.in_transaction
        assert settings.revision == revision and service.events.high == event_high
        assert settings.config.email.smtp.password == ""
        assert settings._keyring_error and collection.unlock_calls == 1
        collection.answer.set()
        async with asyncio.timeout(2):
            while settings.secrets._unlock_pending:
                await asyncio.sleep(0)
        assert not collection.locked
        assert settings.config.email.smtp.password == ""
        assert settings.revision == revision and service.events.high == event_high
        replay = await service.dispatch(connection, request)
        assert not replay["ok"]
        assert replay["error"]["disposition"] == "outcome_unknown"
        assert collection.unlock_calls == 1
    finally:
        serial.cancel_on_handoff = False
        if serial.locked() and serial.owner is contender:
            serial.release()
        if not dispatch.done():
            dispatch.cancel()
        await asyncio.gather(dispatch, return_exceptions=True)
        collection.answer.set()
