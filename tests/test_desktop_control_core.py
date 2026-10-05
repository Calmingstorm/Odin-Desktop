"""Controls through actual IPC, core wiring, retained runner and durable profile."""
import asyncio
import os

import pytest

from src.llm.errors import LLMCapacityError
from src.llm.recovery import RecoveryPolicy
from src.llm.types import LLMResponse
from src.tools.effect_classifier import ToolEffectClass
from src.turn_state.store import OpState, TurnKey, TurnStatus
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, service, settled


@pytest.mark.asyncio
async def test_ipc_stop_steer_binding_duplicate_settlement_and_restart(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider(blocked=True)
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, welcome = await connect(socket_path)
        assert {"control.stop", "control.steer", "control.resume"} <= set(welcome["capabilities"])
        created = await request(reader, writer, "conversations.create", {})
        cid = created["result"]["conversation"]["id"]
        admitted = await request(reader, writer, "submission.send", {
            "client_submission_id": "ipc-controlled", "conversation_id": cid,
            "text": "Say briefly"})
        rid = admitted["result"]["request_id"]
        await asyncio.wait_for(provider.entered.wait(), 2)
        params = {"control_command_id": "ipc-steer", "conversation_id": cid,
                  "request_id": rid, "generation": 1, "text": "Use a revised direction."}
        steer = await request(reader, writer, "control.steer", params)
        assert steer["result"] == {"disposition": "queued", "sequence": 1}
        assert (await request(reader, writer, "control.steer", params))["result"] == steer["result"]
        stale = {"control_command_id": "ipc-stale", "conversation_id": cid,
                 "request_id": rid, "generation": 2}
        assert (await request(reader, writer, "control.stop", stale))["result"] == {
            "disposition": "stale_binding"}
        assert not core.engine.deps.channel_state.cancel_events[cid].is_set()
        stop_params = {**stale, "control_command_id": "ipc-stop", "generation": 1}
        stop = await request(reader, writer, "control.stop", stop_params)
        assert stop["result"] == {"disposition": "requested"}
        provider.release.set()
        await settled(core)
        await asyncio.sleep(0)
        assert core.requests.get_request(rid)["state"] == "cancelled"
        receipts = [event["payload"] for event in core.events.between(0)
                    if event["type"] == "control.receipt"]
        assert [item["disposition"] for item in receipts
                if item["control_command_id"] == "ipc-stop"] == ["requested", "confirmed"]
        assert [item["disposition"] for item in receipts
                if item["control_command_id"] == "ipc-steer"] == ["queued", "closed"]
        assert provider.calls == 1
    finally:
        provider.release.set()
        if writer:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
    next_provider = Provider()
    core = service(paths, socket_path, token_file, next_provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _welcome = await connect(socket_path)
        replay = await request(reader, writer, "control.stop", stop_params)
        assert replay["result"] == stop["result"]
        assert (await request(reader, writer, "control.steer", params))["result"] == steer["result"]
        assert next_provider.calls == 0
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_effect", [False, True])
async def test_ipc_resume_wired_manager_exact_checkpoint_and_new_generation(
        tmp_path, unknown_effect):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        assert core.resume_manager._auto_resume_enabled is False
        core.engine.deps.llm_gateway._recovery_policy_source = lambda: RecoveryPolicy(
            deadline_seconds=0.05, backoff_base=0.001, backoff_cap=0.002, retry_after_cap=0.005)

        async def unavailable(**_kwargs):
            provider.calls += 1
            raise LLMCapacityError("Temporary test capacity", provider="compat", model="test")

        provider.chat_with_tools = unavailable
        reader, writer, welcome = await connect(socket_path)
        assert "control.resume" in welcome["capabilities"]
        created = await request(reader, writer, "conversations.create", {})
        cid = created["result"]["conversation"]["id"]
        submitted = await request(reader, writer, "submission.send", {
            "client_submission_id": "ipc-resume", "conversation_id": cid, "text": "Say briefly"})
        rid = submitted["result"]["request_id"]
        await settled(core)
        assert core.requests.get_request(rid)["state"] == "suspended"
        calls_before = provider.calls

        async def available(**_kwargs):
            provider.calls += 1
            return LLMResponse(text="Completed the preserved IPC request.")

        provider.chat_with_tools = available
        breaker = core.engine.deps.llm_gateway.capacity_breaker_for()
        breaker._opened_at = 0.0
        probe = breaker.acquire_attempt()
        if not isinstance(probe, float):
            breaker.attempt_succeeded(probe)
        params = {"control_command_id": "ipc-resume-control", "conversation_id": cid,
                  "request_id": rid, "generation": 1}
        if unknown_effect:
            # Record an uncertain operation without executing any command.
            # The wired manager must refuse the actual ledger checkpoint.
            ledger = core.engine.deps.turn_store
            key = TurnKey("conversation", cid, rid)
            checkpoint = ledger.load_resumable_sync(key)
            lease = ledger.acquire_resume_lease_sync(key, checkpoint["generation"])
            seq = checkpoint["payload"]["generation_seq"]
            ledger.record_intents_sync(lease, seq, [{"tool_call_id": "uncertain-test",
                "tool_name": "test_effect", "tool_input": {},
                "effect_class": ToolEffectClass.EXTERNAL_EFFECT_CAPABLE}])
            ledger.mark_running_sync(lease, seq, "uncertain-test")
            ledger.settle_op_sync(lease, seq, "uncertain-test", state=OpState.OUTCOME_UNKNOWN,
                                  result_text="Unknown test outcome")
            ledger.release_acquired_sync(lease)
            denied = await request(reader, writer, "control.resume", params)
            assert denied["result"] == {"disposition": "rejected", "reason": "unknown_effects"}
            assert core.requests.get_request(rid)["generation"] == 1
            assert ledger.turn_status_sync(key) == TurnStatus.TERMINAL_REJECTED
            assert provider.calls == calls_before
            op = ledger._conn.execute("SELECT state FROM operations WHERE message_id=?",
                                      (rid,)).fetchone()
            assert op[0] == OpState.MANUAL_RESOLUTION_REQUIRED
            replay = await request(reader, writer, "control.resume", params)
            assert replay["result"] == denied["result"] and provider.calls == calls_before
            return
        answer = await request(reader, writer, "control.resume", params)
        assert answer["result"] == {"disposition": "admitted"}
        await settled(core)
        row = core.requests.get_request(rid)
        assert row["generation"] == 2 and row["state"] == "completed"
        assert core.engine.deps.turn_store.turn_status_sync(
            TurnKey("conversation", cid, rid)) == TurnStatus.TERMINAL_COMPLETED
        snapshot = await request(reader, writer, "conversation.snapshot", {"conversation_id": cid})
        messages = snapshot["result"]["messages"]["items"]
        assert len([item for item in messages if item["role"] == "user"]) == 1
        assert messages[-1]["text"] == "Completed the preserved IPC request."
        assert provider.calls == calls_before + 1
        replay = await request(reader, writer, "control.resume", params)
        assert replay["result"] == answer["result"]
        assert provider.calls == calls_before + 1
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_ipc_steer_consumed_replans_same_request_without_followup(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider(blocked=True)
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    captured = []

    async def respond(**kwargs):
        provider.calls += 1
        captured.append(kwargs)
        if provider.calls == 1:
            provider.entered.set()
            await provider.release.wait()
            return LLMResponse(text="Initial reply before steering.")
        return LLMResponse(text="Revised reply after steering.")

    provider.chat_with_tools = respond
    try:
        await core.start(read_fd)
        reader, writer, _welcome = await connect(socket_path)
        created = await request(reader, writer, "conversations.create", {})
        cid = created["result"]["conversation"]["id"]
        submitted = await request(reader, writer, "submission.send", {
            "client_submission_id": "ipc-consumed", "conversation_id": cid, "text": "Say briefly"})
        rid = submitted["result"]["request_id"]
        await asyncio.wait_for(provider.entered.wait(), 2)
        params = {"control_command_id": "ipc-consumed-control", "conversation_id": cid,
                  "request_id": rid, "generation": 1, "text": "Use the revised direction."}
        admitted = await request(reader, writer, "control.steer", params)
        assert admitted["result"] == {"disposition": "queued", "sequence": 1}
        provider.release.set()
        await settled(core)
        from src.discord.steer_notifications import finish_steer_notifications
        await finish_steer_notifications()
        assert core.requests.get_request(rid)["state"] == "completed"
        assert provider.calls == 2
        assert "Use the revised direction." in str(captured[-1]["messages"])
        receipts = [event["payload"]["disposition"] for event in core.events.between(0)
                    if event["type"] == "control.receipt"]
        assert receipts == ["queued", "consumed"]
        snapshot = await request(reader, writer, "conversation.snapshot", {"conversation_id": cid})
        messages = snapshot["result"]["messages"]["items"]
        assert len([item for item in messages if item["role"] == "user"]) == 1
        assert messages[-1]["text"] == "Revised reply after steering."
        replay = await request(reader, writer, "control.steer", params)
        assert replay["result"] == admitted["result"]
        assert provider.calls == 2
    finally:
        provider.release.set()
        if writer:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
