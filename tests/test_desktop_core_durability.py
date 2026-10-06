"""D17 startup legacy parity and runtime ledger failure through the real core."""

import os
from types import SimpleNamespace

import pytest

from src.desktop.core import CoreService, profile_config
from src.discord.tool_loop import ToolLoopRunner
from src.llm.types import LLMResponse, ToolCall
from src.turn_state.durability import TurnDurability
from src.turn_state.store import TurnStateStore
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import settled


class Provider:
    model = "test"
    provider_name = "codex"

    def __init__(self, *, use_tool=False):
        self.calls = 0
        self.use_tool = use_tool

    async def chat_with_tools(self, **_kwargs):
        self.calls += 1
        if self.use_tool and self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall("time", "parse_time", {
                "expression": "in 1 hour"})], stop_reason="tool_use")
        return LLMResponse(text="A legacy reply.")

    async def chat(self, **_kwargs):
        return "COMPLETE"

    async def drain_and_close(self):
        pass


@pytest.mark.asyncio
async def test_copied_admit_missing_store_is_legacy_but_unwired_store_refuses():
    handle = await TurnDurability.admit(
        None, message=object(), system_prompt="prompt", tools=[], session_snapshot=None
    )
    assert not handle.enabled
    assert handle.blocked is None
    handle = await TurnDurability.admit(
        object(), message=object(), system_prompt="prompt", tools=[], session_snapshot=None)
    assert handle.blocked == "admission_error"


def config(paths):
    cfg = profile_config(paths)
    cfg.llm_provider.model = "codex:test"
    cfg.browser.enabled = False
    cfg.learning.enabled = False
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,error_result,use_tool", [
    ("off", False, False), ("failed_open", False, False),
    ("compatible_missing_key", False, False), ("open_raises", False, False),
    ("off", True, False), ("failed_open", True, False),
    ("off", False, True), ("failed_open", False, True)])
async def test_core_starts_and_real_ipc_request_replies_in_legacy_and_provider_cases(
        tmp_path, monkeypatch, caplog, mode, error_result, use_tool):
    paths, socket_path, token_file = profile(tmp_path)
    cfg = config(paths)
    provider = Provider(use_tool=use_tool)
    if mode == "off":
        cfg.turn_state.enabled = False

        def forbidden_open(*_args, **_kwargs):
            pytest.fail("Disabled turn durability must not open a ledger")

        monkeypatch.setattr("src.turn_state.TurnStateStore", forbidden_open)
    elif mode == "failed_open":
        pass  # Create the failure only after the profile identity is bootstrapped.
    elif mode == "open_raises":
        def failed_open(*_args, **_kwargs):
            raise OSError("harmless injected open failure")

        monkeypatch.setattr("src.turn_state.TurnStateStore", failed_open)
    else:
        cfg.openai_compatible.enabled = True
        cfg.openai_compatible.api_key = ""

        def forbidden_client(*_args, **_kwargs):
            pytest.fail("Missing-key compatible client must be skipped")

        monkeypatch.setattr("src.llm.OpenAICompatibleClient", forbidden_client)
    def runtime(*_args):
        if mode == "failed_open":
            # Real failed-open SQLite store, not a fake available flag.
            ledger_dir = paths.data_dir / "turn_state"
            ledger_dir.mkdir(parents=True)
            (ledger_dir / "turns.db").mkdir()
        return SimpleNamespace(codex_client=provider)

    core = CoreService(paths, socket_path, token_file, config_provider=lambda _: cfg,
                       runtime_provider=runtime)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        assert core.phase == "ready"
        assert isinstance(core.engine.runner, ToolLoopRunner)
        if error_result:
            # Keep the actual runner/provider/reply, but cover the error-result
            # session-accounting branch where a missing ledger is optional too.
            run = core.engine.runner.run

            async def failed_result(*args, **kwargs):
                text, sent, _error, tools, handoff = await run(*args, **kwargs)
                return text, sent, True, tools, handoff

            monkeypatch.setattr(core.engine.runner, "run", failed_result)
        reader, writer, _ = await connect(socket_path)
        status = (await request(reader, writer, "status.get", {}))["result"]
        diagnostics = status["diagnostics"]
        if mode in {"off", "failed_open", "open_raises"}:
            assert core.engine.deps.turn_store is None
            assert diagnostics["turn_durability"]["state"] == "off"
            assert diagnostics["turn_durability"]["reason"] == (
                "disabled_by_config" if mode == "off" else "store_open_failed")
        else:
            assert diagnostics["compatible_provider"] == {
                "state": "skipped", "reason": "missing_api_key"}
            assert "compatible provider skipped" in caplog.text
            assert core.engine.deps.llm_gateway.active_client is provider
            assert core.engine.deps.llm_gateway.compatible_client is None
        cid = (await request(reader, writer, "conversations.create", {}))[
            "result"]["conversation"]["id"]
        accepted = (await request(reader, writer, "submission.send", {
            "conversation_id": cid, "client_submission_id": mode, "text": "Say something brief"}))[
                "result"]
        await settled(core)
        assert core.requests.get_request(accepted["request_id"])["state"] == (
            "failed" if error_result else "completed")
        assert core.transcript.read_conversation(cid)[-1]["text"] == "A legacy reply."
        assert core.engine.deps.sessions.get_history(cid)[-1]["role"] == "assistant"
        if error_result:
            assert core.engine.deps.sessions.get_history(cid)[-1]["content"] == (
                "[Previous request encountered an error before tool execution.]")
        assert provider.calls == (2 if use_tool else 1)
        if mode in {"failed_open", "open_raises"}:
            assert "turn durability off" in caplog.text
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.asyncio
async def test_opened_ledger_dies_at_runtime_still_refuses_real_request(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider()
    core = CoreService(paths, socket_path, token_file, config_provider=config,
                       runtime_provider=lambda *_: SimpleNamespace(codex_client=provider))
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        ledger = core.engine.deps.turn_store
        assert isinstance(ledger, TurnStateStore) and ledger.available
        assert core.status()["diagnostics"]["turn_durability"]["state"] == "on"
        ledger.close()
        assert core.engine.deps.turn_store is ledger
        assert core.status()["diagnostics"]["turn_durability"] == {
            "state": "unavailable", "reason": "runtime_store_failure",
            "message": "Turn ledger unavailable; fresh turn admission is refused."}
        reader, writer, _ = await connect(socket_path)
        cid = (await request(reader, writer, "conversations.create", {}))[
            "result"]["conversation"]["id"]
        accepted = (await request(reader, writer, "submission.send", {
            "conversation_id": cid, "client_submission_id": "dead",
            "text": "Say something brief"}))[
                "result"]
        await settled(core)
        assert core.requests.get_request(accepted["request_id"])["state"] == "completed"
        assert provider.calls == 0
        assert "Refusing to execute it blind" in core.transcript.read_conversation(cid)[-1]["text"]
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)
