"""Authenticated temporary Desktop composition for frozen lineage fixtures."""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from types import SimpleNamespace

from src.config.schema import Config
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.desktop.work import WorkService

lane6_agents_lineage_current = ContextVar("lane6_agents_lineage_current", default=None)


def lane6_agents_lineage_graph(owner):
    paths = owner.paths
    store = JournalStore(paths.data_dir / "lineage.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    config = Config()
    config.openai_codex.enabled = False
    config.openai_compatible.enabled = False
    config.learning.enabled = False
    config.browser.enabled = False
    config.context.directory = str(paths.data_dir / "context")
    engine = build_engine_services(config, paths, owner.manager, delivery=delivery)
    requests = RequestService(store, conversations, transcript, engine=engine,
                              permissions=owner.manager, authority=owner.authority,
                              delivery=delivery)
    engine.bind_requests(requests)
    work = WorkService(store, events, authority=owner.authority,
        permissions=owner.manager, requests=requests, conversations=conversations,
        agents=engine.deps.agent_manager, tasks=engine.deps.channel_state.background_tasks,
        loops=engine.deps.loop_manager,
        processes=engine.deps.tool_executor._ensure_process_registry())
    agents = engine.deps.native_owners["agents"]
    agents._background_admission = requests
    agents._work_service = work
    engine.deps.background_work_ready = True
    cid = conversations.create()["conversation"]["id"]
    message = requests._register_background("agent", "lineage-fixture", "harmless", cid,
                                             owner.authority.owner_id)
    return SimpleNamespace(owner=owner, store=store, engine=engine, requests=requests,
                           work=work, message=message, config=config)


def lane6_agents_lineage_runner():
    graph = lane6_agents_lineage_current.get()
    if graph is None:
        raise RuntimeError("Lineage runner requires authenticated fixture")
    return graph.engine.runner


def lane6_agents_lineage_owner_id():
    return lane6_agents_lineage_current.get().owner.authority.owner_id


def lane6_agents_lineage_message():
    return lane6_agents_lineage_current.get().message


def lane6_agents_lineage_executor(setup):
    executor = lane6_agents_lineage_current.get().engine.deps.tool_executor
    for name, value in vars(setup).items():
        setattr(executor, name, value)
    return executor


def lane6_agents_lineage_lifecycle_runner():
    graph = lane6_agents_lineage_current.get()
    runner = graph.engine.runner
    readiness = runner._tool_executor._builtin_policy._get_readiness
    # Hermetic dispatch seams are actual injected fixture providers, not live
    # computer qualification. Preserve authorization through the real owner.
    runner._tool_executor._builtin_policy._get_readiness = lambda: (
        dict(readiness()) | {"computer_act": True, "mcp_test": True})
    dispatch = runner.dispatch_loop_tool

    async def lane6_agents_lineage_bound_dispatch(name, inp, msg, owner, **kwargs):
        message = graph.requests._register_background(
            "workflow", uuid.uuid4().hex, "lifecycle dispatch", graph.message.conversation_id,
            graph.owner.authority.owner_id)
        async with graph.requests.background_execution(message):
            return await dispatch(name, inp, message, graph.owner.authority.owner_id, **kwargs)

    runner.dispatch_loop_tool = lane6_agents_lineage_bound_dispatch
    return runner
