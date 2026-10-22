"""Odin 4.22.0 (PR #729) in Desktop, on Desktop's own routes.

- #707: a running request keeps its Stop and Steer ownership through a session reset and
  a housekeeping pass (the real core's control service, not the registry alone).
- #716: read_conversation (Desktop's counterpart of Odin's read_channel) and the shared
  history search read a null, blank or whitespace limit as omitted and refuse a
  non-number clearly, on the real native route; read_conversation's 1..100 clamp and
  current-conversation authority are unchanged.
- #724: schedules.save refuses a cloud-metadata webhook and keeps private/homelab ones; a
  saved metadata schedule (from before the policy) is refused at run time, before any
  connection opens.
- #701: a PDF page selection of only image pages gets the no-text guidance.
- #710: knowledge.ingest stores a document that shares one chunk with a source that
  repeats it, and still reports a real near duplicate as a conflict.
- #723: through the real request service, a call whose ledger settlement fails waits for
  its held sibling: the request stays running and keeps its ownership until the sibling
  settles, then fails closed.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

import src.scheduler.scheduler as scheduler_module
from src.desktop.knowledge import KnowledgeService
from src.desktop.paths import ProfilePaths
from src.knowledge.store import CHUNK_SIZE, KnowledgeStore
from src.llm.types import LLMResponse, ToolCall
from tests.test_desktop_background_core import cleanup, session
from tests.test_desktop_core_lifecycle import connect, profile, request
from tests.test_desktop_request_core import Provider, service, settled
from tests.test_handlers_files_docs import _binary, _fake_fitz, _tools

pytest_plugins = ["tests.test_desktop_engine_services"]


def control(cid, rid, generation, name, **extra):
    return {"control_command_id": name, "conversation_id": cid, "request_id": rid,
            "generation": generation, **extra}


@pytest.mark.asyncio
async def test_stop_and_steer_reach_a_running_turn_after_its_session_reset(tmp_path):
    paths, socket_path, token_file = profile(tmp_path)
    provider = Provider(blocked=True)
    core = service(paths, socket_path, token_file, provider)
    read_fd, write_fd = os.pipe()
    writer = None
    try:
        await core.start(read_fd)
        reader, writer, _ = await connect(socket_path)
        cid = (await request(reader, writer, "conversations.create", {}))[
            "result"]["conversation"]["id"]
        sent = await request(reader, writer, "submission.send", {
            "client_submission_id": "running", "conversation_id": cid,
            "text": "Work on this until stopped"})
        rid = sent["result"]["request_id"]
        async with asyncio.timeout(5):
            await provider.entered.wait()
        deps = core.engine.deps
        generation = core.requests.get_request(rid)["generation"]
        deps.sessions.reset(cid)  # the turn keeps running without a session
        assert cid not in deps.sessions.ids()
        deps.channel_state.last_cleanup = 0
        deps.housekeeping.maybe_cleanup()  # the pass that used to drop its ownership
        assert deps.channel_state.active_requests.get(cid) == rid
        steered = await request(reader, writer, "control.steer", control(
            cid, rid, generation, "steer-after-reset", text="Change course, please"))
        assert steered.get("result", {}).get("disposition") == "queued", steered
        stopped = await request(reader, writer, "control.stop", control(
            cid, rid, generation, "stop-after-reset"))
        assert stopped.get("result") == {"disposition": "requested"}, stopped
        assert deps.channel_state.is_cancelled(cid)
        provider.release.set()
        await settled(core)
        assert core.requests.get_request(rid)["state"] in {"cancelled", "interrupted"}
    finally:
        provider.release.set()
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


def tool_results(provider):
    return [str(block["content"]) for message in provider.calls[-1]["messages"]
            if isinstance(message.get("content"), list)
            for block in message["content"] if block.get("type") == "tool_result"]


@pytest.mark.asyncio
async def test_optional_numbers_on_the_native_history_routes(graph):
    requests, _engine, provider, transcript, cid = graph
    for index in range(3):
        transcript.commit(cid, "assistant", f"heron note {index}")
    foreign = requests.conversations.create()["conversation"]["id"]
    transcript.commit(foreign, "assistant", "foreign heron note")
    calls = [
        ("omitted", "read_conversation", {}),
        ("null", "read_conversation", {"limit": None}),
        ("blank", "read_conversation", {"limit": ""}),
        ("spaces", "read_conversation", {"limit": "  "}),
        ("zero", "read_conversation", {"limit": 0}),
        ("negative", "read_conversation", {"limit": -5}),
        ("many", "read_conversation", {"limit": 500}),
        ("text", "read_conversation", {"limit": "many"}),
        ("selector", "read_conversation", {"limit": 5, "conversation_id": foreign}),
        ("history-blank", "search_history", {"query": "heron", "limit": ""}),
        ("history-text", "search_history", {"query": "heron", "limit": "many"}),
    ]
    provider.responses = [
        LLMResponse(tool_calls=[ToolCall(name, tool, args) for name, tool, args in calls]),
        LLMResponse(text="Numbers checked."),
    ]
    requests.submit({"client_submission_id": "numbers", "conversation_id": cid,
                     "text": "check the optional numbers"})
    await requests.after_commit()
    await asyncio.gather(*requests._tasks)
    results = dict(zip([name for name, _, _ in calls], tool_results(provider), strict=True))
    for name in ("omitted", "null", "blank", "spaces"):
        assert "heron note 2" in results[name] and "messages read" in results[name], name
        assert "foreign heron note" not in results[name]
    assert "1 messages read" in results["zero"]  # the clamp floor is unchanged
    assert "1 messages read" in results["negative"]
    assert "heron note 0" in results["many"]  # the cap (100) reads them all here
    assert "limit must be a whole number." in results["text"]
    assert "Only 'limit' is accepted" in results["selector"]
    assert "heron" in results["history-blank"] and "Found" in results["history-blank"]
    assert "limit must be a whole number." in results["history-text"]
    assert requests.snapshot(cid)["recent"][-1]["outcome"] == "completed"


METADATA = "http://169.254.169.254/latest/meta-data/"


@pytest.mark.asyncio
async def test_webhook_schedules_follow_the_destination_policy(tmp_path, monkeypatch):
    core, reader, writer, cid, rfd, wfd = await session(tmp_path, Provider())
    try:
        base = {"description": "Hook", "action": "webhook", "channel_id": cid,
                "cron": "0 9 * * *"}
        refused = await request(reader, writer, "schedules.save", {
            **base, "webhook_config": {"url": METADATA}})
        assert refused["ok"] is False and refused["error"]["code"] == "bad_request"
        assert refused["error"]["message"] == "Webhook URL targets a cloud-metadata address"
        kept = await request(reader, writer, "schedules.save", {
            **base, "webhook_config": {"url": "http://192.168.1.13:9/hook"}})
        assert kept["ok"], kept
        sid = kept["result"]["id"]
        scheduler = core.engine.deps.scheduler
        async with scheduler._lock:  # as saved by a version before the policy
            values = scheduler.list_all()
            for value in values:
                if value["id"] == sid:
                    value["webhook_config"]["url"] = METADATA
            await scheduler._publish(values)
        opened = []

        def no_connection():
            opened.append(True)
            raise AssertionError("a metadata webhook opened a connection")

        monkeypatch.setattr(scheduler_module, "_webhook_session", no_connection)
        ran = await request(reader, writer, "schedules.run", {"id": sid})
        assert ran["ok"] and ran["result"]["status"] == "failure", ran
        assert opened == []
    finally:
        await cleanup(core, writer, rfd, wfd)


@pytest.mark.asyncio
async def test_a_pdf_selection_of_only_image_pages_gets_the_no_text_guidance():
    with patch.dict(sys.modules, {"fitz": _fake_fitz(pages=["words", "", "  \n"])}), _binary():
        images = await _tools()._handle_analyze_pdf({"host": "s", "path": "/p", "pages": "2-3"})
        assert "no extractable text" in images and "## Page" not in images
        text = await _tools()._handle_analyze_pdf({"host": "s", "path": "/p", "pages": "1"})
        assert text.startswith("## Page 1\nwords")


@pytest.mark.asyncio
async def test_knowledge_ingest_reports_a_shared_repeated_chunk_as_stored(tmp_path):
    paths = ProfilePaths.from_xdg("knowledge", home=tmp_path, environ={})
    paths.data_dir.mkdir(parents=True)
    store = KnowledgeStore(str(paths.data_dir / "knowledge.db"))
    try:
        knowledge = KnowledgeService(paths, store=store)

        def para(text):
            return (text + " ") * ((CHUNK_SIZE - 50) // (len(text) + 1))

        repeated = "\n\n".join([para("boilerplate")] * 9 + [para("alpha")])
        assert (await knowledge.handle("knowledge.ingest", {
            "source": "a.md", "content": repeated}))["chunks"] > 0
        sharing = "\n\n".join([para("boilerplate")] + [para(f"bravo{i}") for i in range(9)])
        stored = await knowledge.handle("knowledge.ingest", {"source": "b.md", "content": sharing})
        assert stored == {"source": "b.md", "chunks": stored["chunks"]} and stored["chunks"] > 0
        near = "\n\n".join([para("bravo1"), para("bravo2"), para("bravo3"), para("bravo4"),
                             para("bravo5"), para("bravo6"), para("bravo7"), para("bravo8"),
                             para("bravo0"), para("charlie")])
        conflict = await knowledge.handle("knowledge.ingest", {"source": "c.md", "content": near})
        assert conflict["outcome"] == "conflict" and conflict["duplicate_of"] == "b.md"
    finally:
        store.close()


FAILURE = "FAILED tests/test_example.py::test_example - AssertionError\n1 failed"


def _git(*args, cwd):
    import subprocess

    subprocess.run(["git", "-c", "user.name=Odin Test", "-c", "user.email=test@example.invalid",
                    *args], cwd=cwd, check=True, capture_output=True)


def _stale_repository(root):
    """A clone whose branch tracks a remote named ``upstream``, two commits behind it."""
    root.mkdir(parents=True, exist_ok=True)
    remote, work, other = root / "upstream.git", root / "my work", root / "other"
    _git("init", "--bare", "-b", "main", str(remote), cwd=root)
    _git("clone", "--origin", "upstream", str(remote), str(work), cwd=root)
    _git("commit", "--allow-empty", "-m", "first", cwd=work)
    _git("push", "--set-upstream", "upstream", "main", cwd=work)
    _git("clone", str(remote), str(other), cwd=root)
    for message in ("second", "third"):
        _git("commit", "--allow-empty", "-m", message, cwd=other)
    _git("push", "origin", "main", cwd=other)
    return work


@pytest.mark.asyncio
async def test_a_failed_test_run_is_checked_in_the_repository_it_ran_in(tmp_path, monkeypatch):
    """#699 on this platform's real route (Windows and macOS: tests/windows, tests/macos)."""
    from src.config.schema import ToolsConfig
    from src.tools.executor import ToolExecutor

    work = _stale_repository(tmp_path / "test")
    # The engine runs from a stale checkout of its own: git must never ask there.
    monkeypatch.chdir(_stale_repository(tmp_path / "engine"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # A workspace of its own, apart from the engine's folder (as an installed profile's).
    route = ToolExecutor(config=ToolsConfig(local_working_dir=str(tmp_path / "workspace")))
    route._memory_path = str(tmp_path / "data" / "memory.json")  # apart from the workspace
    monkeypatch.setattr(route, "_resolve_host", lambda alias: ("127.0.0.1", "owner", None))
    annotated = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", f'cd "{work}" && python3 -m pytest -q')
    assert annotated.startswith(FAILURE)
    assert "[STALE BRANCH] main is 2 commit(s) behind upstream/main" in annotated
    missing = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", f'cd "{tmp_path / "missing"}" && python3 -m pytest')
    assert missing == FAILURE
    unchanged = await route._annotate_with_freshness(
        FAILURE, "localhost", "run_command", "python3 -m pytest -q")
    assert unchanged == FAILURE  # git asked in the workspace, never the engine's folder


@pytest.mark.asyncio
async def test_a_failing_settlement_waits_for_its_held_sibling(graph, monkeypatch):
    from src.turn_state.durability import TurnDurability

    requests, engine, provider, transcript, cid = graph
    transcript.commit(cid, "assistant", "a history marker")
    history = engine.deps.native_owners["transcript_history"]
    entered, release, failed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    search = history.search_history

    async def held_search(request, inp):
        entered.set()
        await release.wait()
        return await search(request, inp)

    monkeypatch.setattr(history, "search_history", held_search)
    settle = TurnDurability.after_tool

    async def settle_fails_for_one_call(self, block, **kwargs):
        if block.id == "fails":
            failed.set()
            raise RuntimeError("ledger settlement failed")
        return await settle(self, block, **kwargs)

    monkeypatch.setattr(TurnDurability, "after_tool", settle_fails_for_one_call)
    provider.responses = [
        LLMResponse(tool_calls=[
            ToolCall("held", "search_history", {"query": "history marker"}),
            ToolCall("fails", "read_conversation", {}),
        ]),
        LLMResponse(text="Not reached."),
    ]
    requests.submit({"client_submission_id": "batch", "conversation_id": cid,
                     "text": "run both"})
    await requests.after_commit()
    async with asyncio.timeout(5):
        await entered.wait()
        await failed.wait()
    await asyncio.sleep(0.2)  # time for a failure to end the turn, if it could
    rid = requests.store.connection.execute(
        "SELECT request_id FROM desktop_requests WHERE conversation_id=?", (cid,)).fetchone()[0]
    assert requests.get_request(rid)["state"] == "running"
    assert engine.deps.channel_state.active_requests.get(cid) == rid
    release.set()
    await asyncio.gather(*requests._tasks, return_exceptions=True)
    assert requests.get_request(rid)["state"] == "failed"
    assert len(provider.calls) == 1  # the failed batch was not retried
