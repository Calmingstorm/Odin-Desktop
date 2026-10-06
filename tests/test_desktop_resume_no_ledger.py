"""Optional turn durability must not strand controls in outcome_unknown."""

import asyncio
import os
from types import SimpleNamespace

import pytest

from src.desktop.core import CoreService
from src.llm.errors import LLMCapacityError
from src.llm.recovery import RecoveryPolicy
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, configured, settled


def config(paths):
    cfg = configured(paths)
    cfg.turn_state.auto_resume = False
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "failed_open"])
async def test_no_ledger_rejects_preserved_resume_but_stop_and_steer_work(
        tmp_path, monkeypatch, mode):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()

    async def unavailable(**_kwargs):
        provider.calls += 1
        raise LLMCapacityError("Harmless test capacity outage", provider="compat", model="test")

    provider.chat_with_tools = unavailable
    core = CoreService(
        paths, socket_path, token_file, config_provider=config,
        runtime_provider=lambda *_: SimpleNamespace(compatible_client=provider))
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        core.engine.deps.llm_gateway._recovery_policy_source = lambda: RecoveryPolicy(
            deadline_seconds=0.05, backoff_base=0.001, backoff_cap=0.002,
            retry_after_cap=0.005)
        reader, writer, _ = await connect(socket_path)
        cid = (await request(reader, writer, "conversations.create", {}))[
            "result"]["conversation"]["id"]
        rid = (await request(reader, writer, "submission.send", {
            "client_submission_id": "preserved", "conversation_id": cid,
            # Initial submission builds the real executor/tool catalog. Shared
            # self-hosted CI can exceed the generic 3s IPC fixture wait here.
            # Keep a finite bound and every admission/durability assertion.
            "text": "Keep this original request."}, timeout=15))["result"]["request_id"]
        await settled(core)
        assert core.requests.get_request(rid)["state"] == "suspended"
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)

    cfg = config(paths)
    if mode == "disabled":
        cfg.turn_state.enabled = False

        def forbidden_open(*_args, **_kwargs):
            pytest.fail("Disabled turn durability must not open a ledger")

        monkeypatch.setattr("src.turn_state.TurnStateStore", forbidden_open)
    else:
        def failed_open(*_args, **_kwargs):
            raise OSError("Harmless injected ledger-open failure")

        monkeypatch.setattr("src.turn_state.TurnStateStore", failed_open)

    provider = Provider(blocked=True)
    core = CoreService(
        paths, socket_path, token_file, config_provider=lambda _: cfg,
        runtime_provider=lambda *_: SimpleNamespace(compatible_client=provider))
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        assert core.engine.deps.turn_store is None
        assert core.resume_manager is None
        assert core.engine.runner._on_turn_suspended is None
        reader, writer, _ = await connect(socket_path)
        params = {"control_command_id": "missing-ledger", "conversation_id": cid,
                  "request_id": rid, "generation": 1}
        refused = await request(reader, writer, "control.resume", params)
        assert refused["result"] == {
            "disposition": "rejected", "reason": "resume_unavailable"}
        assert (await request(reader, writer, "control.resume", params))["result"] == (
            refused["result"])
        assert core.requests.get_request(rid)["generation"] == 1
        assert provider.calls == 0
        assert core.store.connection.execute(
            "SELECT disposition FROM desktop_controls WHERE control_command_id=?",
            (params["control_command_id"],)).fetchone()[0] == "rejected"

        live_rid = (await request(reader, writer, "submission.send", {
            "client_submission_id": "legacy-active", "conversation_id": cid,
            "text": "A controllable legacy request."}, timeout=15))["result"]["request_id"]
        await asyncio.wait_for(provider.entered.wait(), 2)
        binding = {"conversation_id": cid, "request_id": live_rid, "generation": 1}
        steer = await request(reader, writer, "control.steer", {
            **binding, "control_command_id": "legacy-steer", "text": "Use a short reply."})
        assert steer["result"] == {"disposition": "queued", "sequence": 1}
        stop = await request(reader, writer, "control.stop", {
            **binding, "control_command_id": "legacy-stop"})
        assert stop["result"] == {"disposition": "requested"}
        provider.release.set()
        await settled(core)
        receipts = [event["payload"] for event in core.events.between(0)
                    if event["type"] == "control.receipt"]
        assert [item["disposition"] for item in receipts
                if item["control_command_id"] == "legacy-stop"] == ["requested", "confirmed"]
        assert [item["disposition"] for item in receipts
                if item["control_command_id"] == "legacy-steer"] == ["queued", "closed"]
        assert provider.calls == 1
    finally:
        provider.release.set()
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
