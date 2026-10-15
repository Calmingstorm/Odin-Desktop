"""Knowledge reads never stall the core's event loop while a worker thread holds the store.

The knowledge store serializes its shared connection with a thread lock, which
a write holds through FTS replacement and verification. Every caller on the
event loop must therefore read through a worker thread. Each test holds the
lock from another thread for a second, as a long write would, and requires a
10 ms heartbeat on the event loop to keep running while the call waits.
Carried over from Odin v4.16.0 (tests/test_knowledge_event_loop_reads.py), with
Desktop's own entry points: management health and the knowledge service close.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from src.desktop.knowledge import KnowledgeService
from src.desktop.management import _KnowledgeHealth
from src.desktop.paths import ProfilePaths
from src.discord.background_task import _execute_tool_captured
from src.discord.native_tools.knowledge import KnowledgeTools
from src.health.checker import check_all_async
from src.knowledge.importer import BulkImporter
from src.knowledge.store import KnowledgeStore

HOLD_SECONDS = 1.0
MAX_LOOP_GAP_SECONDS = 0.3
DOCUMENT = "The release checklist names each step and who owns it."


@pytest.fixture
async def store(tmp_path):
    knowledge = KnowledgeStore(str(tmp_path / "knowledge.db"))
    assert knowledge.available
    assert await knowledge.ingest(DOCUMENT, "checklist.md", dedup=False) > 0
    yield knowledge
    knowledge.close()


async def _while_held(store, call):
    """Run *call* while another thread holds the store's lock; return (gap, result, waited).

    An independent clock ends the hold, never the event loop, so a call that
    blocks the loop shows up as one long heartbeat gap instead of a deadlock.
    """
    acquired = threading.Event()

    def hold():
        with store._conn_lock:
            acquired.set()
            time.sleep(HOLD_SECONDS)

    gaps, stop, beating = [], asyncio.Event(), asyncio.Event()

    async def heartbeat():
        last = time.monotonic()
        beating.set()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert acquired.wait(5)
    beat = asyncio.create_task(heartbeat())
    # Beat first: a call that blocks before its first await must still show up.
    await beating.wait()
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(call(), 10)
    finally:
        waited = time.monotonic() - started
        stop.set()
        await beat
        holder.join(5)
    return max(gaps), result, waited


def _assert_responsive(gap, waited):
    # The call really waited for the store, and the loop kept running meanwhile.
    assert waited >= HOLD_SECONDS * 0.8
    assert gap < MAX_LOOP_GAP_SECONDS


async def test_management_health_check(store):
    from types import SimpleNamespace

    observed = SimpleNamespace(knowledge=_KnowledgeHealth(store, None))
    gap, body, waited = await _while_held(store, lambda: check_all_async(observed))
    _assert_responsive(gap, waited)
    knowledge = next(c for c in body["components"] if c["name"] == "knowledge")
    assert knowledge["status"] == "ok" and knowledge["metadata"]["chunks"] == 1


async def test_list_knowledge_tool(store):
    tools = KnowledgeTools(sessions=None, get_knowledge_store=lambda: store, embedder=None,
                           audit=None)
    # The dispatcher's real registration routes list_knowledge to the off-loop wrapper.
    from src.discord.native_tools.registry import register_native_handlers

    registered = {}

    class Recorder:
        owners: dict = {}  # no computer owner: its late registration is a no-op
        _handlers: dict = {}

        def register(self, name, owner_key, handler_attr, shape):
            registered[name] = (owner_key, handler_attr, shape)

    register_native_handlers(Recorder())
    assert registered["list_knowledge"] == ("knowledge", "_handle_list_knowledge_off_loop", "none")
    gap, text, waited = await _while_held(store, tools._handle_list_knowledge_off_loop)
    _assert_responsive(gap, waited)
    assert "checklist.md" in text


async def test_background_task_list_knowledge(store):
    gap, text, waited = await _while_held(store, lambda: _execute_tool_captured(
        "list_knowledge", {}, None, None, store, None, "tester"))
    _assert_responsive(gap, waited)
    assert text == "- checklist.md (1 chunks)"


async def test_file_import_legacy_lookup(store, tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Deploys wait for an idle turn before restarting.\n")
    importer = BulkImporter(store, None, admitted_roots=[tmp_path])
    gap, result, waited = await _while_held(
        store, lambda: importer._import_resolved_file(path, "tester"))
    _assert_responsive(gap, waited)
    assert result.status == "ok"


async def test_pdf_import_legacy_lookup(store, tmp_path):
    assert await store.ingest("Extracted PDF text.", "a.pdf", dedup=False) > 0
    importer = BulkImporter(store, None, admitted_roots=[tmp_path])
    gap, result, waited = await _while_held(store, lambda: importer._existing_legacy_pdf(
        "https://example.com/a.pdf", "example.com/a.pdf", "Extracted PDF text."))
    _assert_responsive(gap, waited)
    assert result is not None and result.source == "a.pdf"


async def test_knowledge_service_closes_its_store_off_the_loop(tmp_path):
    paths = ProfilePaths.from_xdg("knowledge", home=tmp_path, environ={})
    owned = KnowledgeStore(str(tmp_path / "owned.db"))
    service = KnowledgeService(paths, store=owned)
    service._owns_store = True  # as when the service opened the store itself
    gap, _, waited = await _while_held(owned, service.close)
    _assert_responsive(gap, waited)
    assert not owned.available


async def test_engine_shutdown_closes_the_graph_store_off_the_loop(tmp_path, monkeypatch):
    """The composed core's own teardown, after a cancelled listing left its worker in the store.

    Odin's review reproduction (desktop-1.1.1, F1): cancelling a listing coroutine
    does not stop its worker thread, which still holds the connection lock while
    shutdown closes the engine's knowledge store.
    """
    from tests.test_desktop_knowledge import _composed_core

    core, _, cleanup = await _composed_core(tmp_path, monkeypatch)
    store = core.engine.deps.knowledge_store
    await store.ingest(DOCUMENT, "checklist.md", dedup=False)
    entered, release = threading.Event(), threading.Event()
    armed = True

    def progress():
        nonlocal armed
        if armed:
            armed = False
            entered.set()
            release.wait(5)
        return 0

    store._conn.set_progress_handler(progress, 1)
    tools = KnowledgeTools(sessions=None, get_knowledge_store=lambda: store, embedder=None,
                           audit=None)
    reader = asyncio.create_task(tools._handle_list_knowledge_off_loop())
    timer, beat, closed = None, None, False
    gaps, stop = [], asyncio.Event()

    async def heartbeat():
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    try:
        assert await asyncio.to_thread(entered.wait, 5)
        reader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader
        beat = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.02)
        timer = threading.Timer(HOLD_SECONDS, release.set)  # an independent clock ends the hold
        timer.start()
        started = time.monotonic()
        await cleanup()
        closed = True
        stop.set()
        await beat
        _assert_responsive(max(gaps), time.monotonic() - started)
        assert not store.available
    finally:
        release.set()
        stop.set()
        if timer is not None:
            timer.join(5)
        if beat is not None and not beat.done():
            await beat
        if not closed:
            await cleanup()
