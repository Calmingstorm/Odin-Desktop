"""Bare resume through actual IPC/core, guarded manager and admitted execution."""
import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import pytest

from src.llm.errors import LLMCapacityError
from src.llm.recovery import RecoveryPolicy
from src.llm.types import LLMResponse
from src.tools.effect_classifier import ToolEffectClass
from src.turn_state.store import OpState, TurnKey, TurnStatus
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, service, settled


@asynccontextmanager
async def running(paths_and_socket):
    paths, socket_path, token_file = paths_and_socket
    provider = Provider()
    core = service(paths, socket_path, token_file, provider)
    rfd, wfd = os.pipe()
    writer = None
    try:
        await core.start(rfd)
        # Explicit intake tests must not race an automatic waiter.
        if core.resume_manager is not None:
            core.resume_manager._auto_resume_enabled = False
        reader, writer, _ = await connect(socket_path)
        yield core, provider, reader, writer
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(rfd)
        os.close(wfd)


async def suspend(core, provider, reader, writer):
    core.engine.deps.llm_gateway._recovery_policy_source = lambda: RecoveryPolicy(
        deadline_seconds=0.05, backoff_base=0.001, backoff_cap=0.002, retry_after_cap=0.005)

    async def unavailable(**_kwargs):
        provider.calls += 1
        raise LLMCapacityError("Temporary test capacity", provider="compat", model="test")

    provider.chat_with_tools = unavailable
    created = await request(reader, writer, "conversations.create", {})
    cid = created["result"]["conversation"]["id"]
    answer = await request(reader, writer, "submission.send", {
        "client_submission_id": "original", "conversation_id": cid, "text": "Say briefly"})
    rid = answer["result"]["request_id"]
    await settled(core)
    assert core.requests.get_request(rid)["state"] == "suspended"

    async def available(**_kwargs):
        provider.calls += 1
        return LLMResponse(text="Completed preserved work.")

    provider.chat_with_tools = available
    breaker = core.engine.deps.llm_gateway.capacity_breaker_for()
    breaker._opened_at = 0.0
    probe = breaker.acquire_attempt()
    if not isinstance(probe, float):
        breaker.attempt_succeeded(probe)
    return cid, rid


def messages(core, cid):
    return core.transcript.list(cid)["items"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text,state", [("continue", "suspended"), (" ReSuMe!!. ", "interrupted")])
async def test_trigger_resumes_same_request_and_deduplicates_after_restart(tmp_path, text, state):
    paths = profile(tmp_path)
    async with running(paths) as (core, provider, reader, writer):
        cid, rid = await suspend(core, provider, reader, writer)
        with core.store.transaction() as db:
            db.execute("UPDATE desktop_requests SET state=? WHERE request_id=?", (state, rid))
        before = provider.calls
        params = {"client_submission_id": "trigger", "conversation_id": cid, "text": text}
        envelope = str(uuid.uuid4())
        answer = await request(reader, writer, "submission.send", params, envelope)
        assert answer["result"]["disposition"] == "accepted"
        assert answer["result"]["request_id"] == rid
        await settled(core)
        assert core.requests.get_request(rid)["generation"] == 2
        assert core.requests.get_request(rid)["state"] == "completed"
        assert [m["text"] for m in messages(core, cid) if m["role"] == "user"] == ["Say briefly"]
        assert messages(core, cid)[-1]["text"] == "Completed preserved work."
        assert provider.calls == before + 1
        assert await request(reader, writer, "submission.send", params, envelope) == answer
        replay = await request(reader, writer, "submission.send", params)
        assert replay["result"] == answer["result"]
        assert provider.calls == before + 1
        conflict = await request(reader, writer, "submission.send", {**params, "text": "different"})
        assert conflict["error"]["code"] == "id_conflict"
    async with running(paths) as (core, provider, reader, writer):
        replay = await request(reader, writer, "submission.send", params)
        assert replay["result"] == answer["result"]
        assert await request(reader, writer, "submission.send", params, envelope) == answer
        await settled(core)
        assert provider.calls == 0
        assert len([m for m in messages(core, cid) if m["role"] == "user"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("op_state", [OpState.OUTCOME_UNKNOWN, OpState.PREPARED, OpState.RUNNING])
async def test_unresolved_trigger_delivers_odin_notice_and_runs_nothing(
        tmp_path, monkeypatch, op_state):
    async with running(profile(tmp_path)) as (core, provider, reader, writer):
        cid, rid = await suspend(core, provider, reader, writer)
        ledger = core.engine.deps.turn_store
        key = TurnKey("conversation", cid, rid)
        checkpoint = ledger.load_resumable_sync(key)
        lease = ledger.acquire_resume_lease_sync(key, checkpoint["generation"])
        seq = checkpoint["payload"]["generation_seq"]
        ledger.record_intents_sync(lease, seq, [{"tool_call_id": "uncertain",
            "tool_name": "test_effect", "tool_input": {},
            "effect_class": ToolEffectClass.EXTERNAL_EFFECT_CAPABLE}])
        if op_state != OpState.PREPARED:
            ledger.mark_running_sync(lease, seq, "uncertain")
        if op_state == OpState.OUTCOME_UNKNOWN:
            ledger.settle_op_sync(lease, seq, "uncertain", state=op_state, result_text="Unknown")
        ledger.release_acquired_sync(lease)
        calls = provider.calls

        def forbidden(*_args, **_kwargs):
            pytest.fail("Recognized refusal must precede history, rebuild, model and tool work")

        monkeypatch.setattr(core.transcript, "model_context", forbidden)
        monkeypatch.setattr(core.requests, "_seed_session_context", forbidden)
        monkeypatch.setattr(core.resume_manager, "_validate_and_rebuild", forbidden)
        monkeypatch.setattr(core.engine.runner, "run_resumed", forbidden)
        monkeypatch.setattr(core.engine.runner._tool_executor, "execute", forbidden)
        params = {"client_submission_id": "blocked", "conversation_id": cid, "text": "continue"}
        answer = await request(reader, writer, "submission.send", params)
        assert answer["result"]["disposition"] == "rejected"
        assert answer["result"]["reason"] == "unknown_effects"
        notice = messages(core, cid)[-1]
        assert notice["role"] == "notice"
        assert notice["request_id"] == rid
        assert notice["text"] == (
            "I can't safely continue that work: 1 interrupted operation(s) (test_effect) "
            "have UNKNOWN outcomes — they may or may not have applied, and I will not re-run "
            "them automatically. Verify their current state, then ask fresh for whatever "
            "is still needed.")
        assert provider.calls == calls
        assert core.requests.get_request(rid)["generation"] == 1
        assert ledger.turn_status_sync(key) == TurnStatus.TERMINAL_REJECTED
        expected_state = (OpState.MANUAL_RESOLUTION_REQUIRED
                          if op_state == OpState.OUTCOME_UNKNOWN else op_state)
        stored_op = ledger._conn.execute(
            "SELECT state FROM operations WHERE message_id=?", (rid,)).fetchone()
        assert stored_op[0] == expected_state
        count = len(messages(core, cid))
        replay = await request(reader, writer, "submission.send", params)
        assert replay["result"] == answer["result"]
        assert len(messages(core, cid)) == count
        assert provider.calls == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("text,preserved", [("please continue", True), ("resume @x", True),
                                           ("continue?", True), ("continue", False)])
async def test_nontrigger_and_no_preserved_work_are_ordinary(tmp_path, text, preserved):
    async with running(profile(tmp_path)) as (core, provider, reader, writer):
        if preserved:
            cid, rid = await suspend(core, provider, reader, writer)
        else:
            created = await request(reader, writer, "conversations.create", {})
            cid = created["result"]["conversation"]["id"]
        before = provider.calls
        answer = await request(reader, writer, "submission.send", {
            "client_submission_id": "ordinary", "conversation_id": cid, "text": text})
        assert answer["result"]["disposition"] == "accepted"
        await settled(core)
        assert messages(core, cid)[-2]["text"] == text
        assert messages(core, cid)[-2]["role"] == "user"
        assert provider.calls == before + 1
        if preserved:
            assert core.requests.get_request(rid)["generation"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "exception", "no_manager"])
async def test_recognized_failure_never_falls_through(tmp_path, monkeypatch, failure):
    async with running(profile(tmp_path)) as (core, provider, reader, writer):
        cid, rid = await suspend(core, provider, reader, writer)
        before = provider.calls
        if failure == "missing":
            monkeypatch.setattr(core.resume_manager._store, "load_resumable_sync",
                                lambda _key: None)
        elif failure == "exception":
            def broken(_key):
                raise OSError("Isolated read failure")
            monkeypatch.setattr(core.resume_manager._store, "load_resumable_sync", broken)
        else:
            core.controls.resume_manager = None
        params = {"client_submission_id": "refused", "conversation_id": cid, "text": "continue"}
        answer = await request(reader, writer, "submission.send", params)
        assert answer["result"]["disposition"] != "accepted"
        assert messages(core, cid)[-1]["role"] == "notice"
        if failure == "missing":
            assert messages(core, cid)[-1]["text"] == (
                "That preserved work is no longer resumable (it was just rejected as unreadable, "
                "claimed by another resume, or expired). Nothing was resumed — ask fresh "
                "for what you need.")
        elif failure == "exception":
            assert messages(core, cid)[-1]["text"] == (
                "I recognized the resume command, but resuming failed internally while safely "
                "checking the preserved work. Nothing was resumed or started fresh — "
                "try `resume` again later.")
        assert len([m for m in messages(core, cid) if m["role"] == "user"]) == 1
        assert provider.calls == before
        replay = await request(reader, writer, "submission.send", params)
        assert replay["result"] == answer["result"]
        assert core.requests.get_request(rid)["generation"] == 1


@pytest.mark.asyncio
async def test_lost_semantic_receipt_is_never_reexecuted_after_restart(tmp_path, monkeypatch):
    paths = profile(tmp_path)
    async with running(paths) as (core, provider, reader, writer):
        cid, rid = await suspend(core, provider, reader, writer)

        async def interrupted_dispatch(*_args, **_kwargs):
            raise asyncio.CancelledError

        monkeypatch.setattr(core.controls, "dispatch", interrupted_dispatch)
        params = {"client_submission_id": "lost", "conversation_id": cid, "text": "continue"}
        connection = type("Connection", (), {"owner_context": core.authority.authenticate_local(
            peer_uid=core.authority.owner_uid)})()
        envelope = {"id": str(uuid.uuid4()), "method": "submission.send", "params": params}
        with pytest.raises(asyncio.CancelledError):
            await core.dispatch(connection, envelope)
        assert core.store.connection.execute("SELECT response FROM desktop_submissions WHERE "
            "client_submission_id='lost'").fetchone() is not None
    async with running(paths) as (core, provider, reader, writer):
        result = await request(reader, writer, "submission.send", params)
        assert result["result"]["disposition"] == "outcome_unknown"
        old_envelope = await request(reader, writer, "submission.send", params, envelope["id"])
        assert old_envelope["error"]["disposition"] == "outcome_unknown"
        await settled(core)
        assert provider.calls == 0
        assert core.requests.get_request(rid)["generation"] == 1
        assert len([m for m in messages(core, cid) if m["role"] == "user"]) == 1


@pytest.mark.asyncio
async def test_trigger_never_adopts_new_attachments_into_preserved_request(tmp_path, monkeypatch):
    async with running(profile(tmp_path)) as (core, provider, reader, writer):
        cid, rid = await suspend(core, provider, reader, writer)
        original = core.requests.get_request(rid)["attachments"]

        def forbidden(*_args, **_kwargs):
            pytest.fail("Bare resume must not adopt or process new attachment content")

        monkeypatch.setattr(core.attachments, "adopt_for_submission", forbidden)
        answer = await request(reader, writer, "submission.send", {
            "client_submission_id": "with-attachment", "conversation_id": cid,
            "text": "continue", "attachments": [{"ref": "not-adopted"}]})
        assert answer["result"]["disposition"] == "admitted"
        await settled(core)
        assert core.requests.get_request(rid)["attachments"] == original
        assert core.requests.get_request(rid)["generation"] == 2
        assert len([m for m in messages(core, cid) if m["role"] == "user"]) == 1


@pytest.mark.asyncio
async def test_explicit_trigger_can_resume_after_newer_request(tmp_path):
    async with running(profile(tmp_path)) as (core, provider, reader, writer):
        cid, rid = await suspend(core, provider, reader, writer)
        newer = await request(reader, writer, "submission.send", {
            "client_submission_id": "newer", "conversation_id": cid, "text": "Another request"})
        await settled(core)
        answer = await request(reader, writer, "submission.send", {
            "client_submission_id": "after-newer", "conversation_id": cid, "text": "continue"})
        assert answer["result"]["request_id"] == rid
        assert answer["result"]["disposition"] == "admitted"
        await settled(core)
        assert core.requests.get_request(rid)["generation"] == 2
        assert core.requests.get_request(newer["result"]["request_id"])["generation"] == 1
        assert [m["text"] for m in messages(core, cid) if m["role"] == "user"] == [
            "Say briefly", "Another request"]
