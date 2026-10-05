"""D17 failure explanations are durable core notices, never model replies."""
from __future__ import annotations

import json
import os

import pytest

from src.desktop.core import CoreService, profile_config
from src.error_presentation import format_user_facing_error
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, service, settled


def without_provider(paths):
    cfg = profile_config(paths)
    cfg.openai_codex.enabled = False
    cfg.openai_compatible.enabled = False
    cfg.browser.enabled = False
    cfg.learning.enabled = False
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["no_provider", "runner", "long_reason", "timeout"])
async def test_pre_reply_failure_commits_bounded_notice_and_survives_reconnect(
        tmp_path, monkeypatch, failure):
    paths, socket_path, token_file = profile(tmp_path)
    if failure == "no_provider":
        core = CoreService(paths, socket_path, token_file, config_provider=without_provider)
        expected = "No LLM provider available. Please try again later."
    else:
        core = service(paths, socket_path, token_file, Provider())
        reason = ("Connector refused api_key=fictional-private-key-12345\nprivate second line"
                  if failure == "runner" else "connector refused " + "x" * 5000)
        error = TimeoutError(reason) if failure == "timeout" else RuntimeError(reason)
        prefix = "Tool execution timed out" if failure == "timeout" else "Tool execution failed"
        expected = f"{prefix}: {format_user_facing_error(error)}"

        async def fail(*_args, **_kwargs):
            raise error

    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        assert core.status()["phase"] == "ready"
        if failure != "no_provider":
            monkeypatch.setattr(core.engine.runner, "run", fail)
        reader, writer, _ = await connect(socket_path)
        created = await request(reader, writer, "conversations.create")
        cid = created["result"]["conversation"]["id"]
        params = {"client_submission_id": "failure", "conversation_id": cid,
                  "text": "Give a brief reply"}
        admitted = await request(reader, writer, "submission.send", params)
        rid = admitted["result"]["request_id"]
        await settled(core)
        snapshot = await request(reader, writer, "conversation.snapshot", {
            "conversation_id": cid})
        messages = snapshot["result"]["messages"]["items"]
        assert [item["role"] for item in messages] == ["user", "notice"]
        notice = messages[-1]
        assert notice["text"] == expected
        assert notice["request_id"] == rid
        assert len(notice["text"]) <= len("Tool execution timed out: ") + 200
        assert "fictional-private-key-12345" not in json.dumps(snapshot)
        assert "private second line" not in json.dumps(snapshot)
        if failure == "runner":
            assert notice["text"].startswith(
                "Tool execution failed: RuntimeError: Connector refused")
        assert core.requests.get_request(rid)["state"] == "failed"
        assert snapshot["result"]["recent"][-1]["outcome"] == "failed"
        assert [item["role"] for item in core.transcript.model_context(cid)] == ["user"]
        publications = [json.loads(row[0]) for row in core.store.connection.execute(
            "SELECT payload FROM desktop_delivery_outbox "
            "WHERE request_id=? AND kind='message.committed'", (rid,))]
        assert any(frame["payload"]["message"] == notice for frame in publications)
        # Submission retries and delivery recovery publish existing evidence;
        # neither reruns failed work nor manufactures a second failure notice.
        assert (await request(reader, writer, "submission.send", params))["result"] == (
            admitted["result"])
        await settled(core)
        await core.delivery.recover()
        writer.close()
        await writer.wait_closed()
        writer = None
        reader, writer, _ = await connect(socket_path)
        reloaded = await request(reader, writer, "messages.list", {
            "conversation_id": cid, "limit": 100})
        assert reloaded["result"]["items"] == messages
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_post_reply_accounting_failure_does_not_invent_execution_notice(
        tmp_path, monkeypatch):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None

    async def fail_accounting(*_args, **_kwargs):
        raise RuntimeError("Accounting unavailable")

    try:
        await core.start(read_fd)
        monkeypatch.setattr(core.engine, "record_result", fail_accounting)
        reader, writer, _ = await connect(socket_path)
        created = await request(reader, writer, "conversations.create")
        cid = created["result"]["conversation"]["id"]
        result = await request(reader, writer, "submission.send", {
            "client_submission_id": "accounting", "conversation_id": cid, "text": "Reply"})
        await settled(core)
        messages = core.transcript.list(cid)["items"]
        assert [item["role"] for item in messages] == ["user", "assistant"]
        assert messages[-1]["text"] == "Guarded answer 1."
        assert core.requests.get_request(result["result"]["request_id"])["state"] == "completed"
        assert provider.calls == 1
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
