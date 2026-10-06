"""Actual alternate attempt; explicit blocked probes are not restored executions."""
from __future__ import annotations

import ast
import asyncio
import json
import urllib.error

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from src import cli
from tests.desktop_adapters import step8_review_cli_exact as adapter
from tests.test_desktop_step8_review_cli import arguments, graph


@pytest.mark.parametrize("interactive", [True, False])
def test_retained_empty_original(monkeypatch, capsys, interactive):
    module, _, _ = adapter.load()
    module.test_empty_prompt_prints_help_without_transport(monkeypatch, capsys, interactive)


def test_retained_unreadable_original(monkeypatch):
    module, _, _ = adapter.load()
    module.test_unreadable_prompt_path_does_not_prevent_normal_prose(monkeypatch)


@pytest.mark.parametrize("legacy", [["operator.yaml"], ["--config=operator"], ["-coperator"]])
def test_retained_legacy_original(monkeypatch, capsys, legacy):
    module, _, _ = adapter.load()
    module.test_python_client_refuses_legacy_daemon_arguments_before_network(
        monkeypatch, capsys, legacy)


async def test_probe_piped_original_actual_frames_not_http_facade(monkeypatch, capsys):
    """Original outer success assertions replay; original helper cannot map."""
    async with graph() as state:
        frames, transports, timeouts = [], [], []
        encode = cli.local_client.encode_frame
        prompt = cli.local_client._run_prompt

        def observe_frame(frame, *args, **kwargs):
            frames.append(dict(frame))
            return encode(frame, *args, **kwargs)

        async def observe_timeout(args):
            timeouts.append(args.timeout)
            return await prompt(args)

        monkeypatch.setattr(cli.local_client, "encode_frame", observe_frame)
        monkeypatch.setattr(cli.local_client, "_run_prompt", observe_timeout)
        module, _, _ = adapter.load(ipc_arguments=arguments(state),
                                   retain_original_transport=transports.append)
        await asyncio.to_thread(
            module.test_piped_prompt_and_environment_build_real_authenticated_request,
            monkeypatch, capsys)
        hello = next(frame for frame in frames if frame["t"] == "hello")
        submission = next(frame for frame in frames if frame.get("method") == "submission.send")
        assert hello["profile_id"] == "default"
        assert hello["client"] == {"name": "odin-cli", "version": "0"}
        assert hello["protocol"] == {"major": 0, "minor": 2}
        assert hello["token"] == state.token_file.read_text()
        assert len(transports) == 1 and timeouts == [12.0]
        assert submission["t"] == "req"
        assert set(submission) == {"t", "id", "method", "params"}
        assert set(submission["params"]) == {
            "client_submission_id", "conversation_id", "text"}
        assert submission["params"]["text"] == "diagnose the test service"
        assert submission == next(r for r in state.calls if r["method"] == "submission.send")
        assert len(state.engine.calls) == 1
        message = state.engine.calls[0]
        assert message.owner_id == state.authority.owner_id
        assert state.requests.get_request(message.id)["state"] == "completed"
        assert state.transcript.list(message.conversation_id)["items"][-1]["text"] == "test answer"
        with pytest.raises(PermissionError):
            await state.delivery.send_reply(message.request_context, "untrusted preview")
        # Invoke the exact inherited helper on the actually observed envelope.
        # AttributeError is a recorded blocker, never an HTTP shape synthesized
        # to make the immutable URL/header/body assertions appear to pass.
        with pytest.raises(AttributeError, match="full_url") as blocked:
            transports[0](submission, timeouts[0])
        assert blocked.traceback[-1].lineno + 1 == 47
        assert not hasattr(submission, "full_url")
        assert not hasattr(submission, "get_header")
        assert not hasattr(submission, "data")


@pytest.mark.parametrize("mode", ["closed_socket", "wrong_token"])
async def test_probe_original_failure_stdout_blocker(monkeypatch, capsys, mode):
    """Unchanged original error params/assertions, actual IPC connection fault."""
    async with graph() as state:
        if mode == "closed_socket":
            error = urllib.error.URLError("connection refused")
            await state.server.shutdown()
        else:
            error = urllib.error.HTTPError("http://example.invalid", 403, "Forbidden", {}, None)
            state.token_file.write_text("cd" * 32)
        armed, captured = [], []
        readouterr = capsys.readouterr

        def capture():
            output = readouterr()
            captured.append(output)
            return output

        monkeypatch.setattr(capsys, "readouterr", capture)
        module, _, _ = adapter.load(ipc_arguments=arguments(state),
                                   arm_real_failure=armed.append)
        with pytest.raises(AssertionError) as blocked:
            await asyncio.to_thread(module.test_transport_failure_is_nonzero_even_in_json_mode,
                                    monkeypatch, capsys, error)
        assert blocked.traceback[-1].lineno + 1 == 34
        assert armed == [error]
        assert len(captured) == 1
        assert captured[0].out == json.dumps({"response": "Desktop core connection failed",
            "is_error": True, "outcome": "connection_error"}) + "\n"
        assert captured[0].err == ""
        assert not state.calls and not state.engine.calls
        assert "ab" * 32 not in captured[0].out
        assert "cd" * 32 not in captured[0].out


def test_exact_corpus_and_reverse_replay_no_retirement():
    source = frozen_source(adapter.SOURCE_PATH)
    original, tree = adapter.adapt(source)
    assert corpus(original) == corpus(tree)
    assert len(corpus(original)["cases"]) == 5
    assert len(corpus(original)["assertions"]) == 15
    assert adapter.CORPUS_EXCLUSIONS == {}
    assert [dump(n) for n in ast.walk(original) if isinstance(n, ast.Assert)] == [
        dump(n) for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    with pytest.raises(ValueError, match="bytes changed"):
        adapter.adapt(source + b"\n")
    with pytest.raises(ValueError, match="allowlist changed"):
        adapter.adapt(source, rules=[])
