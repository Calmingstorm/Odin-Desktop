"""Automatic recovery through the actual IPC/core/runner and durable delivery."""
import asyncio
import os

import pytest

from src.discord import turn_resume
from src.llm.errors import LLMCapacityError
from src.llm.recovery import RecoveryPolicy
from src.llm.types import LLMResponse
from src.turn_state.store import TurnKey, TurnStatus
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, configured, service, settled


async def wait_until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 5)


def recover_capacity(core):
    breaker = core.engine.deps.llm_gateway.capacity_breaker_for()
    breaker._opened_at = 0.0
    admission = breaker.acquire_attempt()
    if not isinstance(admission, float):
        breaker.attempt_succeeded(admission)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [
    "automatic", "newer_request", "queued_during_rebuild", "disabled"])
async def test_capacity_recovery_retains_checkpoint_generation_and_reply(
        tmp_path, monkeypatch, mode):
    monkeypatch.setattr(turn_resume, "_AUTO_POLL_SECONDS", 0.01)
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()
    core = service(paths, socket_path, token_file, provider)

    def config(paths):
        cfg = configured(paths)
        cfg.turn_state.auto_resume = mode != "disabled"
        cfg.turn_state.resume_ttl_hours = 72.0
        return cfg

    core.config_provider = config
    available = False
    prompts = []
    admitted = []

    async def respond(**kwargs):
        provider.calls += 1
        if not available:
            raise LLMCapacityError("Temporary test capacity", provider="compat", model="test")
        prompts.append(kwargs)
        # This is executed inside the real model invocation. A raw run_resumed
        # call from the manager cannot satisfy task-owned Desktop admission.
        row = core.store.connection.execute(
            "SELECT * FROM desktop_requests WHERE state='running'").fetchone()
        message = core.requests.fetch_request(row["conversation_id"], row["request_id"])
        core.requests.assert_delivery_context(message.request_context)
        return LLMResponse(text="Recovered the preserved request.")

    provider.chat_with_tools = respond
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        run_resumed = core.engine.runner.run_resumed

        async def retained_resume(st):
            core.requests.assert_request(st.message)
            admitted.append((st.message.request_id, st.message.generation))
            return await run_resumed(st)

        monkeypatch.setattr(core.engine.runner, "run_resumed", retained_resume)
        manager = core.resume_manager
        assert manager._auto_resume_enabled is (mode != "disabled")
        assert manager._resume_ttl_hours == 72.0
        assert core.engine.runner._on_turn_suspended == manager.on_turn_suspended
        core.engine.deps.llm_gateway._recovery_policy_source = lambda: RecoveryPolicy(
            deadline_seconds=0.05, backoff_base=0.001, backoff_cap=0.002,
            retry_after_cap=0.005)
        reader, writer, _ = await connect(socket_path)
        cid = (await request(reader, writer, "conversations.create", {}))[
            "result"]["conversation"]["id"]
        result = await request(reader, writer, "submission.send", {
            "client_submission_id": "capacity", "conversation_id": cid,
            "text": "Complete this original request"})
        rid = result["result"]["request_id"]
        await settled(core)
        row = core.requests.get_request(rid)
        assert row["state"] == "suspended" and row["generation"] == 1
        key = TurnKey("conversation", cid, rid)
        checkpoint = core.engine.deps.turn_store.load_resumable_sync(key)
        before_generation = checkpoint["generation"]
        if mode == "disabled":
            assert manager._waiters == {}
        else:
            assert key in manager._waiters

        if mode == "newer_request":
            # A newer real submission advances the session even with capacity
            # still absent. It is preserved too, never silently discarded.
            newer = await request(reader, writer, "submission.send", {
                "client_submission_id": "newer", "conversation_id": cid,
                "text": "A newer independent request"})
            await settled(core)
            newer_rid = newer["result"]["request_id"]
            assert core.requests.get_request(newer_rid)["state"] == "suspended"
            # Keep this independent waiter's work explicit for this assertion.
            waiter = manager._waiters.pop(TurnKey("conversation", cid, newer_rid))
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

        if mode == "queued_during_rebuild":
            rebuild = manager._validate_and_rebuild

            async def rebuild_with_new_input(key, row):
                restored = await rebuild(key, row)
                # Admission is independent of the channel lock. This input is
                # durable but cannot yet advance the in-memory session revision.
                newer = await request(reader, writer, "submission.send", {
                    "client_submission_id": "queued-newer", "conversation_id": cid,
                    "text": "A newer queued independent request"})
                assert core.requests.get_request(newer["result"]["request_id"])["state"] == "queued"
                return restored

            monkeypatch.setattr(manager, "_validate_and_rebuild", rebuild_with_new_input)

        calls_before = provider.calls
        available = True
        recover_capacity(core)
        if mode == "automatic":
            await wait_until(lambda: core.requests.get_request(rid)["state"] == "completed")
            await settled(core)
            row = core.requests.get_request(rid)
            assert row["generation"] == 2
            # The ledger preserves logical lineage with a fresh lease; the
            # Desktop execution/delivery generation is the one that advances.
            assert row["ledger_generation"] == before_generation
            assert core.engine.deps.turn_store.turn_status_sync(key) == (
                TurnStatus.TERMINAL_COMPLETED)
            assert admitted == [(rid, 2)]
            assert provider.calls == calls_before + 1
            # A reconstructed checkpoint keeps the original model transcript,
            # rather than seeding a fresh user prompt or adding a resume word.
            assert prompts[0]["messages"] == checkpoint["payload"]["fields"]["messages"]
        else:
            if mode in {"newer_request", "queued_during_rebuild"}:
                await wait_until(lambda: key not in manager._waiters)
            else:
                await asyncio.sleep(0.05)
            row = core.requests.get_request(rid)
            assert row["state"] == "suspended" and row["generation"] == 1
            if mode == "queued_during_rebuild":
                await settled(core)
                assert provider.calls == calls_before + 1  # only the newer work
                assert all(request_id != rid for request_id, _generation in admitted)
                monkeypatch.setattr(manager, "_validate_and_rebuild", rebuild)
            else:
                assert provider.calls == calls_before
            # Stand-down is not terminal rejection: owner control still works.
            resumed = await request(reader, writer, "control.resume", {
                "control_command_id": "explicit", "conversation_id": cid,
                "request_id": rid, "generation": 1})
            assert resumed["result"] == {"disposition": "admitted"}
            await settled(core)
            assert core.requests.get_request(rid)["state"] == "completed"
            assert admitted == [(rid, 2)]

        snapshot = await request(reader, writer, "conversation.snapshot", {"conversation_id": cid})
        messages = snapshot["result"]["messages"]["items"]
        assert messages[-1]["text"] == "Recovered the preserved request."
        assert len([item for item in messages if item["role"] == "user"]) == (
            2 if mode in {"newer_request", "queued_during_rebuild"} else 1)
        starts = [event["payload"]["generation"] for event in core.events.between(0)
                  if event["type"] == "request.started" and event["payload"]["request_id"] == rid]
        assert starts == [1, 2]
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        await core.close()
        assert not core.resume_manager._waiters
        os.close(read_fd)
        os.close(write_fd)
