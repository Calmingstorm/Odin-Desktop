"""CLI replay plus real disposable socket/token, admission and guarded delivery."""
from __future__ import annotations

import ast
import asyncio
import io
import tempfile
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src import cli
from src.desktop.commands import CommandJournal, JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.ipc import IpcServer
from src.desktop.requests import RequestService
from src.desktop.transcript import TranscriptStore
from src.discord.channel_state import ChannelStateRegistry
from src.turn_state import TurnStateStore
from tests.desktop_adapters import step8_review_cli
from tests.desktop_adapters.process_cases import temporary_owner


class Engine:
    def __init__(self, ledger, delay, failed):
        self.deps = SimpleNamespace(turn_store=ledger, channel_state=ChannelStateRegistry())
        self.delay, self.failed = delay, failed
        self.calls = []

    async def run(self, message, **_kwargs):
        self.requests.assert_request(message)
        self.calls.append(message)
        if self.delay:
            await asyncio.sleep(self.delay)
        return ("test answer", False, self.failed, [], False)

    async def record_result(self, _message, _result):
        pass


@asynccontextmanager
async def graph(*, delay=0, failed=False):
    with tempfile.TemporaryDirectory(prefix="cli-") as temporary:
        root = Path(temporary)
        with temporary_owner(root / "owner") as state:
            token_file = root / "ipc.token"
            token_file.write_text("ab" * 32)
            token_file.chmod(0o600)
            store = JournalStore(state.paths.data_dir / "transport.sqlite3", "default")
            events = PublicationEventJournal(store)
            conversations = ConversationStore(store, events)
            transcript = TranscriptStore(store, events, conversations)
            ledger = TurnStateStore(state.paths.data_dir / "turns.sqlite3")
            engine = Engine(ledger, delay, failed)
            delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
            requests = RequestService(store, conversations, transcript, engine=engine,
                                      permissions=state.manager, authority=state.authority,
                                      delivery=delivery)
            engine.requests = requests
            delivery.assert_context = requests.assert_delivery_context
            journal = CommandJournal(store)
            calls = []

            async def dispatch(connection, request):
                assert state.authority.accepts(connection.owner_context)
                owner = state.manager.set_request_owner(connection.owner_context)
                try:
                    calls.append(request)
                    method, params = request["method"], request["params"]
                    if method == "submission.send":
                        answer = await journal.execute_async(
                            request["id"], method, params,
                            lambda: requests.handle_async(method, params, controls=None))
                        await requests.after_commit()
                    elif method == "conversations.create":
                        answer = journal.execute(request["id"], method, params,
                            lambda: {"ok": True, "result": conversations.handle(method, params)})
                    elif method == "conversation.snapshot":
                        answer = {"ok": True, "result": transcript.handle(method, params)}
                    elif method == "messages.list":
                        answer = {"ok": True, "result": transcript.handle(method, params)}
                    else:
                        answer = {"ok": True, "result": {"phase": "ready"}}
                    return {"t": "res", "id": request["id"], **answer}
                finally:
                    state.manager.reset_request_owner(owner)

            server = IpcServer(root / "runtime" / "core.sock", token_file, "default",
                state.authority, lambda: {"core": {"instance_id": state.authority.runtime_id,
                "version": "0"}, "capabilities": ["submission.send", "conversations.create",
                "conversation.snapshot", "status.get"], "features": [], "event_high": "0"},
                dispatch)
            try:
                await server.start()
                yield SimpleNamespace(server=server, token_file=token_file, engine=engine,
                    requests=requests, transcript=transcript, conversations=conversations,
                    delivery=delivery, authority=state.authority, calls=calls)
            finally:
                await server.shutdown()
                await requests.close()
                ledger.close()
                store.close()


def arguments(state, *extra):
    return ["--socket", str(state.server.socket_path), "--token-file", str(state.token_file),
            "--profile", "default", *extra]


@pytest.mark.parametrize("piped", [True, False])
@pytest.mark.parametrize("json_mode", [True, False])
async def test_cli_actual_ipc_prompt_owner_and_guarded_reply(monkeypatch, capsys, piped, json_mode):
    import json

    async with graph(delay=0.05) as state:
        stdin = io.StringIO("  diagnose the test service\n" if piped else "ignored pipe")
        stdin.isatty = lambda: False
        monkeypatch.setattr(cli.sys, "stdin", stdin)
        args = arguments(state, "--timeout", "12")
        if not piped:
            args.append("diagnose the test service")
        if json_mode:
            args.append("--json")
        assert await asyncio.to_thread(cli.main, args) == 0
        output = capsys.readouterr()
        assert output.err == ""
        answer = json.loads(output.out) if json_mode else None
        if json_mode:
            assert answer["response"] == "test answer" and answer["is_error"] is False
            assert answer["outcome"] == "completed"
        else:
            assert output.out == "test answer\n"
        assert len(state.engine.calls) == 1
        message = state.engine.calls[0]
        assert message.content == "diagnose the test service"
        assert message.owner_id == state.authority.owner_id
        assert state.requests.get_request(message.id)["state"] == "completed"
        assert state.transcript.list(message.conversation_id)["items"][-1]["text"] == "test answer"
        assert [r["method"] for r in state.calls][:3] == [
            "conversations.create", "conversation.snapshot", "submission.send"]
        with pytest.raises(PermissionError):
            await state.delivery.send_reply(message.request_context, "untrusted preview")


@pytest.mark.parametrize("json_mode", [True, False])
async def test_cli_timeout_does_not_cancel_or_retry_work(capsys, json_mode):
    import json

    async with graph() as state:
        entered, release = asyncio.Event(), asyncio.Event()
        original = state.engine.run

        async def wait_at_admitted_execution(message, **kwargs):
            entered.set()
            await release.wait()
            return await original(message, **kwargs)

        state.engine.run = wait_at_admitted_execution
        args = arguments(state, "harmless prompt", "--timeout", "2")
        if json_mode:
            args.append("--json")
        pending = asyncio.create_task(asyncio.to_thread(cli.main, args))
        await asyncio.wait_for(entered.wait(), 5)
        assert await pending == 1
        output = capsys.readouterr()
        if json_mode:
            answer = json.loads(output.out)
            assert answer["is_error"] and answer["outcome"] == "timeout"
            assert state.requests.get_request(answer["request_id"])["state"] == "running"
        else:
            assert output.out == "" and "timed out" in output.err
        release.set()
        await asyncio.gather(*list(state.requests._tasks))
        assert len(state.engine.calls) == 1
        assert state.requests.get_request(state.engine.calls[0].id)["state"] == "completed"


@pytest.mark.parametrize("mode", ["wrong_token", "unsafe_token", "wrong_profile", "unsafe_socket"])
async def test_cli_auth_failure_no_submission_or_secret_output(capsys, mode):
    async with graph() as state:
        args = arguments(state, "harmless prompt", "--json")
        if mode == "wrong_token":
            state.token_file.write_text("cd" * 32)
        elif mode == "unsafe_token":
            state.token_file.chmod(0o644)
        elif mode == "unsafe_socket":
            state.server.socket_path.chmod(0o644)
        else:
            args[5] = "different"
        assert await asyncio.to_thread(cli.main, args) == 1
        output = capsys.readouterr()
        assert "connection failed" in output.out
        assert "ab" * 32 not in output.out + output.err
        assert "cd" * 32 not in output.out + output.err
        assert not state.calls and not state.engine.calls


async def test_cli_diagnostic_preserved_and_existing_conversation(capsys):
    async with graph() as state:
        assert await asyncio.to_thread(cli.main, arguments(state, "status.get")) == 0
        assert '"phase": "ready"' in capsys.readouterr().out
        assert not state.engine.calls
        cid = state.conversations.create()["conversation"]["id"]
        assert await asyncio.to_thread(cli.main,
            arguments(state, "--conversation", cid, "--prompt", "status.get")) == 0
        assert capsys.readouterr().out == "test answer\n"
        assert state.engine.calls[0].conversation_id == cid


async def test_cli_failed_guarded_reply_is_nonzero(capsys):
    async with graph(failed=True) as state:
        assert await asyncio.to_thread(cli.main, arguments(state, "prompt", "--json")) == 1
        import json
        answer = json.loads(capsys.readouterr().out)
        assert answer["is_error"] is True and answer["outcome"] == "failed"
        assert answer["response"] == "test answer"


@pytest.mark.parametrize("json_mode", [True, False])
async def test_cli_connection_failure_nonzero_and_output(capsys, json_mode):
    import json

    async with graph() as state:
        await state.server.shutdown()
        args = arguments(state, "harmless prompt")
        if json_mode:
            args.append("--json")
        assert await asyncio.to_thread(cli.main, args) == 1
        output = capsys.readouterr()
        if json_mode:
            answer = json.loads(output.out)
            assert answer["is_error"] is True and answer["outcome"] == "connection_error"
            assert answer["response"] == "Desktop core connection failed"
            assert output.err == ""
        else:
            assert output.out == ""
            assert output.err == "Desktop core connection failed\n"
        assert not state.calls and not state.engine.calls


async def test_cli_finds_exact_guarded_reply_beyond_first_transcript_page(capsys):
    async with graph() as state:
        original = state.engine.record_result
        async def noisy(message, result):
            await original(message, result)
            for index in range(110):
                state.transcript.commit(message.conversation_id, "notice", f"progress {index}")
        state.engine.record_result = noisy
        assert await asyncio.to_thread(cli.main, arguments(state, "harmless prompt")) == 0
        assert capsys.readouterr().out == "test answer\n"
        assert any(item["method"] == "messages.list" for item in state.calls)


async def test_cli_completed_without_committed_guarded_reply_is_bounded(capsys):
    import json

    async with graph() as state:
        original = state.delivery.transcript_commit
        def fail_assistant(*args, **kwargs):
            if kwargs.get("role") == "assistant":
                raise OSError("disposable publication fault")
            return original(*args, **kwargs)
        state.delivery.transcript_commit = fail_assistant
        assert await asyncio.to_thread(cli.main,
            arguments(state, "harmless prompt", "--timeout", "0.2", "--json")) == 1
        answer = json.loads(capsys.readouterr().out)
        assert answer["is_error"] and answer["outcome"] == "timeout"
        assert len(state.engine.calls) == 1
        assert state.requests.get_request(state.engine.calls[0].id)["state"] == "completed"


async def test_cli_refused_resume_never_returns_prior_guarded_reply(capsys):
    import json

    async with graph() as state:
        cid = state.conversations.create()["conversation"]["id"]
        assert await asyncio.to_thread(cli.main,
            arguments(state, "--conversation", cid, "harmless prompt")) == 0
        capsys.readouterr()
        rid = state.engine.calls[0].id
        with state.requests.store.transaction() as db:
            db.execute("UPDATE desktop_requests SET state='suspended' WHERE request_id=?", (rid,))
        assert await asyncio.to_thread(cli.main,
            arguments(state, "--conversation", cid, "--prompt", "resume", "--json")) == 1
        answer = json.loads(capsys.readouterr().out)
        assert answer["request_id"] == rid and answer["is_error"] is True
        assert answer["outcome"] == "outcome_unknown"
        assert answer["response"] != "test answer"
        assert len(state.engine.calls) == 1


async def test_cli_resume_generation_from_receipt_outside_recent20(tmp_path, capsys):
    import json

    from src.llm.errors import LLMCapacityError
    from tests.desktop_adapters import step8_review_resume
    from tests.fakes import FakeMessage, text_response, tool_call_response

    async with aclosing(step8_review_resume.owner_fixture(tmp_path)) as owners:
        owner = await anext(owners)
        harness = step8_review_resume.Harness(
            [tool_call_response(("parse_time", {"expression": "tomorrow"}))], tmp_path)
        def capacity():
            harness.fake.responses.append(capacity)
            raise LLMCapacityError("fixture capacity", provider="codex", model="fake-model")
        harness.fake.responses.append(capacity)
        await harness.run(FakeMessage("harmless preserved work"))
        for task in list(harness.manager._waiters.values()):
            task.cancel()
        await asyncio.sleep(0)
        suspended = harness.requests.snapshot(harness.cid)["recent"][-1]
        rid = suspended["request_id"]
        harness.fake.responses.clear()
        harness.fake.responses.extend(text_response(f"later {i}") for i in range(25))
        breaker = harness.engine.deps.llm_gateway.capacity_breaker_for()
        breaker._opened_at = 0
        probe = breaker.acquire_attempt()
        if not isinstance(probe, float):
            breaker.attempt_succeeded(probe)
        for index in range(25):
            await harness.run(FakeMessage(f"later request {index}"))
        assert rid not in {item["request_id"] for item in
                           harness.requests.snapshot(harness.cid)["recent"]}
        harness.fake.responses.clear()
        harness.fake.responses.append(text_response("resumed guarded answer"))
        with tempfile.TemporaryDirectory(prefix="cli-resume-") as root:
            token_file = Path(root) / "ipc.token"
            token_file.write_text("ab" * 32)
            token_file.chmod(0o600)
            admissions = []
            async def dispatch(connection, request):
                token = owner.manager.set_request_owner(connection.owner_context)
                try:
                    if request["method"] == "submission.send":
                        result = await harness.requests.handle_async(
                            request["method"], request["params"], controls=harness.controls)
                        admissions.append(result)
                        await harness.requests.after_commit()
                    else:
                        result = {"ok": True, "result": harness.transcript.handle(
                            request["method"], request["params"])}
                    return {"t": "res", "id": request["id"], **result}
                finally:
                    owner.manager.reset_request_owner(token)
            server = IpcServer(Path(root) / "runtime" / "core.sock", token_file,
                "default", owner.authority, lambda: {"core": {
                    "instance_id": owner.authority.runtime_id, "version": "0"},
                    "capabilities": [], "features": [], "event_high": "0"}, dispatch)
            await server.start()
            try:
                state = SimpleNamespace(server=server, token_file=token_file)
                assert await asyncio.to_thread(cli.main, arguments(state,
                    "--conversation", harness.cid, "--prompt", "resume", "--json",
                    "--timeout", "20")) == 0
                answer = json.loads(capsys.readouterr().out)
                assert answer["request_id"] == rid and answer["generation"] == 2
                assert admissions[0]["result"]["generation"] == 2
                assert answer["response"] == "resumed guarded answer"
                assert answer["is_error"] is False
            finally:
                await server.shutdown()


def test_cli_loader_complete_corpus_and_retirement_pins():
    original, adapted = step8_review_cli.adapt(frozen_source(step8_review_cli.SOURCE_PATH))
    assert corpus(original) == corpus(adapted)
    assert len(corpus(original)["cases"]) == 5
    assert len(corpus(original)["assertions"]) == 15
    assert step8_review_cli.CORPUS_SELECTIONS == {"test_campaign_cli_coverage": None}
    assert len(step8_review_cli.CORPUS_EXCLUSIONS["test_campaign_cli_coverage"]) == 2


def test_cli_loader_refuses_bytes_hunks_and_collateral(monkeypatch):
    source = frozen_source(step8_review_cli.SOURCE_PATH)
    with pytest.raises(ValueError, match="bytes changed"):
        step8_review_cli.adapt(source + b"\n")
    with pytest.raises(ValueError, match="duplicate"):
        step8_review_cli.adapt(source, hunks=step8_review_cli.SETUP_HUNKS * 2)
    with pytest.raises(ValueError, match="exact admitted"):
        step8_review_cli.adapt(source, hunks=[])
    put = step8_review_cli._put
    def corrupt(tree, path, node):
        put(tree, path, node)
        tree.body.append(ast.parse("unadmitted = 1").body[0])
    monkeypatch.setattr(step8_review_cli, "_put", corrupt)
    with pytest.raises(ValueError, match="complete AST reverse replay"):
        step8_review_cli.adapt(source)
