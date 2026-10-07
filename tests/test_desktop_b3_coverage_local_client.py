"""Client reply and CLI contracts using inert IPC boundaries, never a live core."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.desktop import local_client as module
from src.desktop.protocol import ProtocolError


def args(**changes):
    values = dict(socket="fixture.sock", token_file="fixture.token", profile="default",
                  conversation="conversation", prompt="fixture prompt", timeout=1, json=True)
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("message,reason", [
    ({"t": "bye"}, "core closed"),
    ({"t": "res", "id": "identity", "ok": False}, "core refused"),
    ({"t": "res", "id": "identity", "ok": True, "result": []}, "invalid core response"),
])
async def test_rpc_rejects_closed_refused_and_nonobject_response(message, reason):
    client = SimpleNamespace(request=AsyncMock(return_value="identity"),
                             read=AsyncMock(side_effect=[{"t": "event"}, message]))
    with pytest.raises(ProtocolError, match=reason):
        await module._call(client, "fixture.method", {"fixture": True})
    client.request.assert_awaited_once_with("fixture.method", {"fixture": True})
    assert client.read.await_count == 2


def mock_connection(monkeypatch):
    client = SimpleNamespace(close=AsyncMock())
    connect = AsyncMock(return_value=client)
    monkeypatch.setattr(module.LocalClient, "connect", connect)
    return client, connect


def page(items, has_more=False):
    return {"items": items, "has_more": has_more}


@pytest.mark.asyncio
async def test_prompt_pages_prior_ids_and_finds_only_new_guarded_reply(monkeypatch):
    client, connect = mock_connection(monkeypatch)
    snapshots = [
        {"messages": page([{"id": "old"}], True)},
        page([{"id": "older"}]),
        {"request_id": "request", "generation": 2, "disposition": "accepted"},
        {"recent": [{"request_id": "request", "generation": 1, "outcome": "completed"},
                    {"request_id": "request", "generation": 2, "outcome": "completed"}],
         "messages": page([{"id": "old", "request_id": "request", "role": "assistant",
                            "text": "stale reply"}], True)},
        page([{"id": "new", "request_id": "request", "role": "assistant", "text": "guarded"},
              {"id": "user", "request_id": "request", "role": "user", "text": "ignored"},
              {"id": "foreign", "request_id": "foreign", "role": "assistant", "text": "ignored"}]),
    ]
    call = AsyncMock(side_effect=snapshots)
    monkeypatch.setattr(module, "_call", call)
    result = {}
    await module._prompt(args(), result)
    assert result == {"conversation_id": "conversation", "request_id": "request",
                      "generation": 2, "response": "guarded", "outcome": "completed",
                      "is_error": False}
    assert call.await_args_list[1].args == (client, "messages.list", {
        "conversation_id": "conversation", "limit": 100, "before": "old"})
    assert call.await_args_list[4].args[-1]["before"] == "old"
    connect.assert_awaited_once_with("fixture.sock", "fixture.token", "default")
    client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["refused", "suspended"])
async def test_prompt_refused_admission_is_not_retried(monkeypatch, disposition):
    client, _ = mock_connection(monkeypatch)
    call = AsyncMock(side_effect=[{"conversation": {"id": "created"}},
        {"messages": page([])}, {"request_id": "request", "disposition": disposition}])
    monkeypatch.setattr(module, "_call", call)
    result = {}
    await module._prompt(args(conversation=None), result)
    assert result["conversation_id"] == "created"
    assert result["is_error"] is True and result["outcome"] == disposition
    assert call.await_count == 3
    client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("generation", [0, False, "1"])
async def test_prompt_rejects_invalid_generation_and_closes_client(monkeypatch, generation):
    client, _ = mock_connection(monkeypatch)
    monkeypatch.setattr(module, "_call", AsyncMock(side_effect=[
        {"messages": page([])}, {"request_id": "r", "generation": generation,
                                "disposition": "accepted"}]))
    with pytest.raises(ProtocolError, match="invalid admitted generation"):
        await module._prompt(args(), {})
    client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["prior", "terminal"])
async def test_prompt_rejects_empty_page_claiming_more_history(monkeypatch, where):
    client, _ = mock_connection(monkeypatch)
    responses = [{"messages": page([], True)}] if where == "prior" else [
        {"messages": page([])}, {"request_id": "r", "disposition": "accepted"},
        {"recent": [{"request_id": "r", "generation": 1, "outcome": "completed"}],
         "messages": page([], True)}]
    monkeypatch.setattr(module, "_call", AsyncMock(side_effect=responses))
    with pytest.raises(ProtocolError, match="invalid transcript pagination"):
        await module._prompt(args(), {})
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminal_failed_request_without_reply_reports_error(monkeypatch):
    client, _ = mock_connection(monkeypatch)
    monkeypatch.setattr(module, "_call", AsyncMock(side_effect=[
        {"messages": page([])}, {"request_id": "r", "disposition": "accepted"},
        {"recent": [{"request_id": "r", "generation": 1, "outcome": "failed"}],
         "messages": page([])}]))
    result = {}
    await module._prompt(args(), result)
    assert result["is_error"] and result["outcome"] == "failed"
    assert "without a guarded reply" in result["response"]
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_completed_effect_waits_for_committed_reply(monkeypatch):
    client, _ = mock_connection(monkeypatch)
    recent = [{"request_id": "r", "generation": 1, "outcome": "completed"}]
    monkeypatch.setattr(module, "_call", AsyncMock(side_effect=[
        {"messages": page([])}, {"request_id": "r", "disposition": "accepted"},
        {"recent": recent, "messages": page([])},
        {"recent": recent, "messages": page([{"id": "published", "request_id": "r",
                                             "role": "assistant", "text": "reply"}])}]))
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    result = {}
    await module._prompt(args(), result)
    sleep.assert_awaited_once_with(0.05)
    assert result["response"] == "reply" and result["is_error"] is False
    client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error,outcome", [(TimeoutError(), "timeout"),
                                         (OSError(), "connection_error")])
async def test_prompt_wrapper_returns_scrubbed_json_failure(monkeypatch, capsys, error, outcome):
    monkeypatch.setattr(module, "_prompt", AsyncMock(side_effect=error))
    assert await module._run_prompt(args()) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["outcome"] == outcome and result["is_error"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_plain_prompt_output_uses_correct_stream(monkeypatch, capsys, failed):
    async def prompt(_args, result):
        result.update(response="bounded reply", is_error=failed)
    monkeypatch.setattr(module, "_prompt", prompt)
    assert await module._run_prompt(args(json=False)) == int(failed)
    output = capsys.readouterr()
    assert (output.err if failed else output.out) == "bounded reply\n"
    assert (output.out if failed else output.err) == ""


BASE = ["--socket", "fixture.sock", "--token-file", "fixture.token", "--profile", "default"]


@pytest.mark.parametrize("extra", [
    ["--timeout", "nan"], ["--timeout", "0"], ["--timeout", "inf"],
    ["positional", "--prompt", "explicit"], ["--method", "status.get", "prompt"],
    ["--method", "status.get", "--prompt", "explicit"],
])
def test_cli_refuses_conflicting_or_unbounded_requests(extra):
    with pytest.raises(SystemExit) as failure:
        module.main(BASE + extra)
    assert failure.value.code == 2


@pytest.mark.parametrize("input_kind", ["tty", "pipe", "broken", "empty"])
def test_cli_handles_implicit_diagnostic_and_stdin_prompts(monkeypatch, input_kind):
    stdin = Mock()
    stdin.isatty.return_value = input_kind == "tty"
    stdin.read.side_effect = OSError() if input_kind == "broken" else None
    stdin.read.return_value = "  " if input_kind == "empty" else "  prompt from pipe  "
    monkeypatch.setattr(module.sys, "stdin", stdin)
    diagnostic, prompt = AsyncMock(return_value=7), AsyncMock(return_value=9)
    monkeypatch.setattr(module, "_run", diagnostic)
    monkeypatch.setattr(module, "_run_prompt", prompt)
    result = module.main(BASE)
    if input_kind in ("tty", "broken"):
        assert result == 7
        assert diagnostic.call_args.args[0].method == "status.get"
        prompt.assert_not_called()
    elif input_kind == "pipe":
        assert result == 9
        assert prompt.call_args.args[0].prompt == "prompt from pipe"
        diagnostic.assert_not_called()
    else:
        assert result == 1
        diagnostic.assert_not_called()
        prompt.assert_not_called()


def test_cli_connection_failure_is_scrubbed(monkeypatch, capsys):
    monkeypatch.setattr(module, "_run", AsyncMock(side_effect=OSError("sensitive fixture")))
    assert module.main(BASE + ["--method", "status.get"]) == 1
    assert capsys.readouterr().err == "Desktop core connection failed\n"
