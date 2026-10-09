"""Durable request controls exercise the unchanged channel mailbox primitives."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.desktop.commands import CommandJournal, JournalStore
from src.desktop.controls import ControlService
from src.desktop.events import EventJournal
from src.discord.channel_state import ChannelStateRegistry, ChatTurnInbox
from src.discord.steer_notifications import finish_steer_notifications, notify_steer

pytest_plugins = ["tests.test_desktop_engine_services"]


class RequestRows:
    def __init__(self, store):
        self.store = store
        self.resumed = []
        with store.transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS desktop_requests (
                request_id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,owner TEXT NOT NULL,generation INTEGER NOT NULL,
                state TEXT NOT NULL,text TEXT NOT NULL,attachments TEXT NOT NULL,
                created_at REAL NOT NULL,started_at REAL,ended_at REAL,
                unknown_effects TEXT NOT NULL,ledger_generation TEXT)""")

    def add(self, request_id="r", conversation_id="c", generation=1, state="running",
            ledger_generation=None, unknown_effects=None):
        with self.store.transaction() as connection:
            connection.execute("""INSERT INTO desktop_requests VALUES
                (?,?,?,'owner',?,?,?, '[]',1,NULL,NULL,?,?)""",
                               (request_id, conversation_id, "message-" + request_id,
                                generation, state, "original task",
                                json.dumps(unknown_effects or []), ledger_generation))

    def get_request(self, request_id):
        row = self.store.connection.execute("SELECT * FROM desktop_requests WHERE request_id=?",
                                            (request_id,)).fetchone()
        return dict(row) if row else None

    def binding(self, conversation_id, request_id, generation):
        row = self.get_request(request_id)
        if row and (row["conversation_id"], row["generation"]) == (conversation_id, generation):
            return row
        return None

    async def launch_resume(self, row, turn):
        self.resumed.append((row, turn))


class ControlHarness:
    def __init__(self, tmp_path):
        self.store = JournalStore(tmp_path / "journal" / "state.sqlite3", "profile")
        self.events = EventJournal(self.store)
        self.requests = RequestRows(self.store)
        self.channels = ChannelStateRegistry()
        self.authority = SimpleNamespace(owner_id="owner")
        self.authorized = True
        self.permissions = SimpleNamespace(
            is_owner=lambda owner: self.authorized and owner == "owner")
        self.controls = ControlService(self.store, self.events, self.requests, self.channels,
                                       authority=self.authority, permissions=self.permissions)

    def running(self, request_id="r", conversation_id="c", generation=1):
        self.requests.add(request_id, conversation_id, generation)
        event = self.channels.set_active_request(conversation_id, request_id)
        inbox = ChatTurnInbox(requester_id="owner")
        self.channels.bind_steer_inbox(conversation_id, request_id, inbox)
        return event, inbox

    def params(self, command_id="cmd", request_id="r", conversation_id="c", generation=1, **kw):
        return {"control_command_id": command_id, "request_id": request_id,
                "conversation_id": conversation_id, "generation": generation, **kw}

    def dispositions(self, command_id="cmd"):
        return [frame["payload"]["disposition"] for frame in self.events.between(0)
                if frame["type"] == "control.receipt"
                and frame["payload"]["control_command_id"] == command_id]


@pytest.fixture
def h(tmp_path):
    harness = ControlHarness(tmp_path)
    yield harness
    harness.store.close()


async def test_stop_receipt_deduplicates_control_under_new_envelopes(h):
    cancel, _ = h.running()
    params = h.params()
    answer = await h.controls.dispatch("control.stop", params)
    assert answer == {"ok": True, "result": {"disposition": "requested"}}
    assert cancel.is_set()
    journal = CommandJournal(h.store)
    first = journal.execute("envelope-1", "control.stop", params, lambda: answer)
    # A different envelope still hits the semantic control identity, rather
    # than delivering another stop to whatever happens to own this channel.
    h.store.connection.execute("UPDATE desktop_requests SET generation=2,state='running'")
    next_cancel = h.channels.set_active_request("c", "r")
    retry = await h.controls.dispatch("control.stop", params)
    second = journal.execute("envelope-2", "control.stop", params, lambda: retry)
    assert first == second == answer
    assert not next_cancel.is_set()
    assert h.dispositions() == ["requested"]


async def test_control_identity_conflict_does_not_deliver_to_successor(h):
    h.running()
    await h.controls.dispatch("control.stop", h.params())
    h.store.connection.execute("UPDATE desktop_requests SET generation=2,state='running'")
    cancel = h.channels.set_active_request("c", "r")
    answer = await h.controls.dispatch("control.stop", h.params(generation=2))
    assert answer["error"]["code"] == "id_conflict"
    assert not cancel.is_set()


@pytest.mark.parametrize("method", ["control.stop", "control.steer"])
async def test_stale_generation_or_conversation_never_controls_current_owner(h, method):
    cancel, inbox = h.running(generation=2)
    answer = await h.controls.dispatch(method, h.params(text="change direction"))
    assert answer["result"] == {"disposition": "stale_binding"}
    assert not cancel.is_set() and inbox.inbox.empty()
    answer = await h.controls.dispatch(
        method, h.params("other", conversation_id="other", generation=2, text="change direction"))
    assert answer["result"] == {"disposition": "stale_binding"}
    assert not cancel.is_set() and inbox.inbox.empty()


async def test_stop_queued_withdraws_exact_request_without_stopping_running_owner(h):
    cancel, _ = h.running()
    h.requests.add("queued", state="queued")
    answer = await h.controls.dispatch("control.stop", h.params(request_id="queued"))
    assert answer["result"] == {"disposition": "requested"}
    assert h.requests.get_request("queued")["state"] == "cancelled"
    assert not cancel.is_set()
    assert h.dispositions() == ["confirmed"]
    assert [frame["type"] for frame in h.events.between(0)] == [
        "control.receipt", "request.cancelled"]


async def test_stop_only_confirms_actual_durable_owner_settlement(h):
    h.running()
    await h.controls.dispatch("control.stop", h.params())
    h.channels.finish_stop("c", "r", "Stopped.")
    import asyncio

    await asyncio.sleep(0)
    assert h.dispositions() == ["requested", "confirmed"]
    # New envelope gets original admission, not a different settlement result.
    answer = await h.controls.dispatch("control.stop", h.params())
    assert answer["result"] == {"disposition": "requested"}


async def test_unconfirmed_stop_cleanup_does_not_claim_confirmation(h):
    h.running()
    await h.controls.dispatch("control.stop", h.params())
    h.channels.clear_active_request("c", "r")
    import asyncio

    await asyncio.sleep(0)
    assert h.dispositions() == ["requested"]


async def test_steer_queued_then_consumed_is_not_model_compliance(h):
    _, inbox = h.running()
    answer = await h.controls.dispatch("control.steer", h.params(text="Use the quieter option."))
    assert answer["result"] == {"disposition": "queued", "sequence": 1}
    assert h.dispositions() == ["queued"]
    item = inbox.inbox.get_nowait()
    assert item["text"] == "Use the quieter option."
    notify_steer(item, "consumed")
    await finish_steer_notifications()
    assert h.dispositions() == ["queued", "consumed"]
    retry = await h.controls.dispatch("control.steer", h.params(text="Use the quieter option."))
    assert retry == answer
    assert inbox.inbox.empty()
    assert not h.controls.settle_steer("cmd", "r", 1, 1, "consumed")


async def test_closing_inbox_closes_unconsumed_controls_without_successor_leak(h):
    _, inbox = h.running()
    await h.controls.dispatch("control.steer", h.params(text="Adjust the plan."))
    h.channels.set_active_request("c", "successor")
    await finish_steer_notifications()
    assert inbox.inbox.empty()
    assert h.dispositions() == ["queued", "closed"]
    assert not h.controls.settle_steer("cmd", "successor", 2, 1, "consumed")


async def test_steer_refuses_stopping_owner_and_existing_mailbox_limit(h):
    _, inbox = h.running()
    inbox.inbox_sequence = 128
    answer = await h.controls.dispatch("control.steer", h.params(text="Adjust the plan."))
    assert answer["result"] == {"disposition": "closed"}
    assert inbox.inbox.empty()
    inbox.inbox_sequence = 0
    await h.controls.dispatch("control.stop", h.params("stop"))
    answer = await h.controls.dispatch("control.steer", h.params("after-stop", text="Adjust."))
    assert answer["result"] == {"disposition": "closed"}


@pytest.mark.parametrize("text", ["", "   ", None, 42])
async def test_steer_nonempty_text_validation(h, text):
    _, inbox = h.running()
    answer = await h.controls.dispatch("control.steer", h.params(text=text))
    assert answer["error"]["code"] == "bad_request"
    assert inbox.inbox.empty()


async def test_oversized_steer_matches_fixture_queued_outcome_and_4000_char_directive(h):
    _, inbox = h.running()
    text = "x" * 4000 + "different trailing content"
    answer = await h.controls.dispatch("control.steer", h.params(text=text))
    assert answer == {"ok": True, "result": {"disposition": "queued", "sequence": 1}}
    assert inbox.inbox.get_nowait()["text"] == "x" * 4000
    assert await h.controls.dispatch("control.steer", h.params(text=text)) == answer
    conflict = await h.controls.dispatch("control.steer", h.params(text="x" * 4001))
    assert conflict["error"]["code"] == "id_conflict"


async def test_revoked_authority_cannot_control_even_with_cached_identity(h):
    cancel, inbox = h.running()
    h.authorized = False
    answer = await h.controls.dispatch("control.stop", h.params())
    assert answer["error"]["code"] == "unauthorized"
    assert not cancel.is_set() and inbox.inbox.empty()


async def test_pending_crash_receipt_is_unknown_and_never_replayed(h):
    cancel, _ = h.running()
    params = h.params()
    from src.desktop.commands import canonical_json

    assert h.controls._reserve("control.stop", params,
                               canonical_json(["profile", "control.stop", params])) is None
    replacement = ControlService(h.store, h.events, h.requests, h.channels,
                                 authority=h.authority, permissions=h.permissions)
    answer = await replacement.dispatch("control.stop", params)
    assert answer["error"]["disposition"] == "outcome_unknown"
    assert not cancel.is_set()


@pytest.mark.parametrize("method", ["control.stop", "control.steer"])
async def test_durable_receipt_and_event_precede_process_local_input(h, monkeypatch, method):
    h.running()
    name = "request_stop" if method == "control.stop" else "request_steer"
    primitive = getattr(h.channels, name)
    calls = []

    def checked(*args, **kwargs):
        assert not h.store.connection.in_transaction
        assert h.dispositions() == ["requested" if method == "control.stop" else "queued"]
        row = h.store.connection.execute(
            "SELECT response FROM desktop_controls WHERE control_command_id='cmd'").fetchone()
        assert row[0] is None  # reservation stays unknown until input settles
        calls.append(1)
        return primitive(*args, **kwargs)

    monkeypatch.setattr(h.channels, name, checked)
    answer = await h.controls.dispatch(method, h.params(text="Adjust."))
    assert answer["ok"] and calls == [1]


@pytest.mark.parametrize("method", ["control.stop", "control.steer"])
async def test_external_input_failure_never_becomes_cached_success(h, monkeypatch, method):
    cancel, inbox = h.running()
    name = "request_stop" if method == "control.stop" else "request_steer"
    calls = []

    def unavailable(*_args, **_kwargs):
        calls.append(1)
        raise RuntimeError("primitive unavailable")

    monkeypatch.setattr(h.channels, name, unavailable)
    params = h.params(text="Adjust.")
    first = await h.controls.dispatch(method, params)
    second = await h.controls.dispatch(method, params)
    assert first["error"]["disposition"] == second["error"]["disposition"] == "outcome_unknown"
    assert calls == [1] and not cancel.is_set() and inbox.inbox.empty()


async def test_closed_request_stop_and_steer_are_truthful(h):
    h.requests.add(state="completed")
    stop = await h.controls.dispatch("control.stop", h.params())
    steer = await h.controls.dispatch("control.steer", h.params("steer", text="Adjust."))
    assert stop["result"] == {"disposition": "not_running"}
    assert steer["result"] == {"disposition": "closed"}


async def test_restart_closes_lost_steering_without_replaying_input_or_confirming_stop(h):
    _, inbox = h.running()
    queued = await h.controls.dispatch("control.steer", h.params(text="Adjust."))
    await h.controls.dispatch("control.stop", h.params("stop"))
    new_channels = ChannelStateRegistry()
    restarted = ControlService(h.store, h.events, h.requests, new_channels,
                               authority=h.authority, permissions=h.permissions)
    assert restarted.recover_after_restart() == 1
    assert restarted.recover_after_restart() == 0
    assert h.dispositions() == ["queued", "closed"]
    assert h.dispositions("stop") == ["requested"]
    assert await restarted.dispatch("control.steer", h.params(text="Adjust.")) == queued
    assert not new_channels.active_requests
    assert inbox.inbox.qsize() == 1  # simulated dead predecessor only, never new mailbox



def resolved_events(h):
    return [frame["payload"] for frame in h.events.between(0)
            if frame["type"] == "effects.resolved"]


async def test_acknowledge_dismisses_settled_unknown_effects_once(h):
    h.requests.add(state="completed", unknown_effects=[{"tool_call_id": "call-1"}])
    first = await h.controls.dispatch("effects.acknowledge", h.params("ack-1"))
    assert first == {"ok": True, "result": {"disposition": "acknowledged", "remaining": 0}}
    assert resolved_events(h) == [{"conversation_id": "c", "request_id": "r", "generation": 1,
                                   "remaining": 0}]
    # The same command is answered from its receipt; another command finds it already done.
    assert await h.controls.dispatch("effects.acknowledge", h.params("ack-1")) == first
    again = await h.controls.dispatch("effects.acknowledge", h.params("ack-2"))
    assert again["result"]["disposition"] == "already_acknowledged"
    assert len(resolved_events(h)) == 1
    # Presentation only: the request keeps its unknown effects and its state.
    row = h.requests.get_request("r")
    assert row["state"] == "completed" and json.loads(row["unknown_effects"])


@pytest.mark.parametrize(("state", "effects", "target"), [
    ("running", [{"tool_call_id": "call-1"}], {}),
    ("completed", [], {}),
    ("completed", [{"tool_call_id": "call-1"}], {"generation": 2}),
    ("completed", [{"tool_call_id": "call-1"}], {"conversation_id": "other"}),
    ("completed", [{"tool_call_id": "call-1"}], {"request_id": "missing"}),
])
async def test_acknowledge_only_matches_ended_requests_with_unknown_effects(h, state, effects,
                                                                         target):
    h.requests.add(state=state, unknown_effects=effects)
    answer = await h.controls.dispatch("effects.acknowledge", h.params("ack", **target))
    assert answer == {"ok": True, "result": {"disposition": "not_found", "remaining": 0}}
    assert resolved_events(h) == []


async def test_acknowledge_requires_the_current_owner(h):
    h.requests.add(state="completed", unknown_effects=[{"tool_call_id": "call-1"}])
    h.authorized = False
    answer = await h.controls.dispatch("effects.acknowledge", h.params("ack"))
    assert answer["error"]["code"] == "unauthorized"
    assert resolved_events(h) == []


@pytest.fixture
def integrated_graph(request):
    """Use the actual stacked engine fixture when running composed gates.

    The plugin above supplies the actual request/runner graph. Absence fails
    the test rather than skipping an unproven gate.
    """
    return request.getfixturevalue("graph")


async def test_integrated_stop_uses_real_runner_ledger_and_committed_cancel(integrated_graph):
    import asyncio

    requests, engine, provider, _transcript, cid = integrated_graph
    entered = asyncio.Event()
    release = asyncio.Event()
    original_call = provider.chat_with_tools

    async def blocked(**kwargs):
        entered.set()
        await release.wait()
        return await original_call(**kwargs)

    provider.chat_with_tools = blocked
    admitted = requests.submit({"client_submission_id": "actual-stop", "conversation_id": cid,
                                "text": "Say something brief"})
    await requests.after_commit()
    await entered.wait()
    controls = ControlService(requests.store, requests.events, requests,
                              engine.deps.channel_state, authority=requests.authority,
                              permissions=requests.permissions)
    params = {"control_command_id": "actual-stop-control", "conversation_id": cid,
              "request_id": admitted["request_id"], "generation": 1}
    answer = await controls.dispatch("control.stop", params)
    assert answer["result"] == {"disposition": "requested"}
    release.set()
    await asyncio.gather(*requests._tasks)
    await asyncio.sleep(0)
    row = requests.get_request(admitted["request_id"])
    assert row["state"] == "cancelled"
    from src.turn_state.store import TurnKey, TurnStatus

    assert engine.deps.turn_store.turn_status_sync(
        TurnKey("conversation", cid, row["request_id"])) == TurnStatus.TERMINAL_CANCELLED
    events = requests.events.between(0)
    receipts = [event["payload"]["disposition"] for event in events
                if event["type"] == "control.receipt"]
    assert receipts == ["requested", "confirmed"]


async def test_integrated_steer_consumes_real_mailbox_and_no_followup_turn(integrated_graph):
    import asyncio

    from src.llm.types import LLMResponse

    requests, engine, provider, transcript, cid = integrated_graph
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def blocked(**kwargs):
        nonlocal calls
        calls += 1
        provider.calls.append(kwargs)
        if calls == 1:
            entered.set()
            await release.wait()
            return LLMResponse(text="Initial answer before direction change.")
        return LLMResponse(text="Revised answer using the requested direction.")

    provider.chat_with_tools = blocked
    admitted = requests.submit({"client_submission_id": "actual-steer", "conversation_id": cid,
                                "text": "Say something brief"})
    await requests.after_commit()
    await entered.wait()
    controls = ControlService(requests.store, requests.events, requests,
                              engine.deps.channel_state, authority=requests.authority,
                              permissions=requests.permissions)
    params = {"control_command_id": "actual-steer-control", "conversation_id": cid,
              "request_id": admitted["request_id"], "generation": 1,
              "text": "Use the revised direction instead."}
    assert (await controls.dispatch("control.steer", params))["result"] == {
        "disposition": "queued", "sequence": 1}
    release.set()
    await asyncio.gather(*requests._tasks)
    await finish_steer_notifications()
    assert requests.get_request(admitted["request_id"])["state"] == "completed"
    assert len(provider.calls) >= 2
    messages = provider.calls[-1]["messages"]
    assert "Use the revised direction instead." in json.dumps(messages)
    rows = transcript.read_conversation(cid)
    assert len([row for row in rows if row["role"] == "user"]) == 1
    assert rows[-1]["text"] == "Revised answer using the requested direction."
    receipts = [event["payload"]["disposition"] for event in requests.events.between(0)
                if event["type"] == "control.receipt"]
    assert receipts == ["queued", "consumed"]
