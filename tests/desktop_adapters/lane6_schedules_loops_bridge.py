"""Fixture-only compatibility names over the actual profile-local service graph.

No alternate loop, admission guard, permission tier, or publication algorithm.
Only provider/reflector external boundaries are scripted by the frozen cases.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path as Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from src.config.schema import Config
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.permissions.manager import PermissionManager
from tests.fakes import FakeLLM as ScriptedLLM

CURRENT = ContextVar("lane6_schedules_loops_fixture")


class FakeLLM(ScriptedLLM):
    async def drain_and_close(self):
        self.closed = True

    async def close(self):
        self.closed = True


class Graph:
    def __init__(self, root, *, config_overrides=None, fake_llm=None, reflector=None):
        self.paths = ProfilePaths.from_xdg("loops", home=root, environ={})
        self.authority = OwnerAuthority(self.paths)
        self.permissions = PermissionManager(self.authority)
        self.owner_context = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
        self.owner_token = self.permissions.set_request_owner(self.owner_context)
        self.store = JournalStore(self.paths.data_dir / "journal.sqlite3", "loops")
        self.events = PublicationEventJournal(self.store)
        self.conversations = ConversationStore(self.store, self.events)
        self.transcript = TranscriptStore(self.store, self.events, self.conversations)
        self.delivery = DurableDelivery(
            self.store, self.events, transcript_commit=self.transcript.commit
        )
        values = dict(config_overrides or {})
        values.setdefault("search", {"enabled": False})
        values.setdefault("browser", {"enabled": False})
        values.setdefault("openai_codex", {"enabled": False})
        values.setdefault("context", {"directory": str(self.paths.data_dir / "context")})
        self.config = Config(**values)
        self.engine = build_engine_services(self.config, self.paths, self.permissions,
            delivery=self.delivery, codex_client=fake_llm,
            runtime_context=SimpleNamespace(reflector=reflector))
        self.requests = RequestService(self.store, self.conversations, self.transcript,
            engine=self.engine, permissions=self.permissions, authority=self.authority,
            delivery=self.delivery)
        self.engine.bind_requests(self.requests)
        self.cid = self.conversations.create()["conversation"]["id"]
        self.tool_loop = RunnerView(self)
        for name, value in vars(self.engine.deps).items():
            if name != "get_config":
                setattr(self, name, value)
        self.cost_tracker = self.llm_gateway.cost_tracker
        self.trajectory_saver = self.turn_recorder._trajectory_saver
        self.agent_task_tools = self.native_owners["agents"]
        self.delivery.assert_context = self.requests.assert_delivery_context
        self.permissions.reset_request_owner(self.owner_token)

    def admit(self, text, kind="loop_iteration"):
        token = self.permissions.set_request_owner(self.owner_context)
        try:
            return self.requests._register_background(kind, uuid4().hex, text, self.cid,
                                                       self.authority.owner_id)
        finally:
            self.permissions.reset_request_owner(token)

    async def iteration(self, prompt, prev=None, cancel_event=None):
        message = self.admit(prompt)
        async with self.execution(message):
            return await self.engine.runner.run_autonomous(prompt, message, prev,
                message.owner_id, cancel_event=cancel_event)

    @asynccontextmanager
    async def execution(self, message, *, settle=True):
        token = self.permissions.set_request_owner(self.owner_context)
        try:
            async with self.requests.background_execution(message, settle=settle):
                yield message
        finally:
            self.permissions.reset_request_owner(token)

    async def close(self):
        await self.loop_manager.shutdown()
        await self.requests.close()
        await self.engine.close()
        self.store.close()
        self.authority.release_runtime()


def graph(**kwargs):
    state = CURRENT.get()
    built = Graph(state.root / str(len(state.graphs)), **kwargs)
    state.graphs.append(built)
    state.latest = built
    return built


def owner_id():
    return CURRENT.get().latest.authority.owner_id


def make_bot(*, config_overrides=None, fake_llm=None, reflector=None):
    return graph(config_overrides=config_overrides, fake_llm=fake_llm, reflector=reflector)


async def run_iteration(bot, prompt="do the loop work", prev=None, user_id="4242"):
    return await bot.iteration(prompt, prev)


class RunnerView:
    """Map historical caller setup to sealed admission, never bypass the guard."""
    def __init__(self, graph):
        self.graph = graph

    async def run_autonomous(self, prompt, channel, prev, user_id, *, cancel_event=None):
        return await self.graph.iteration(prompt, prev, cancel_event)

    async def dispatch_loop_tool(self, name, inp, proxy, user_id):
        graph = self.graph
        message = graph.admit("Dispatch the selected tool")
        async with graph.execution(message):
            return await graph.engine.runner.dispatch_loop_tool(name, inp, message,
                                                               message.owner_id)


class Channel:
    """Read-only legacy output view of committed local delivery, not a send sink."""
    def __init__(self, id=777):
        self.graph = CURRENT.get().latest
        self.id = self.graph.cid

    @property
    def sent(self):
        return self.graph.transcript.read_conversation(self.id)


def LoopManager():  # noqa: N802
    return graph().loop_manager


def start_loop(manager, goal, channel, requester_id, requester_name, callback, **kwargs):
    graph = channel.graph
    if graph.loop_manager is not manager:
        raise AssertionError("Loop manager differs from admitted graph")
    admitted = {}

    def before_start(info):
        admitted["message"] = graph.admit(goal, "loop")

    def execution(info):
        return graph.execution(admitted["message"], settle=False)

    async def publish(info, text):
        graph.requests.assert_bound_request(admitted["message"])
        await graph.delivery.send(admitted["message"].channel, text)

    def settled(info):
        token = graph.permissions.set_request_owner(graph.owner_context)
        try:
            graph.requests.settle_background(admitted["message"],
                "completed" if info.status == "completed" else
                "cancelled" if info.status == "stopped" else "failed")
        finally:
            graph.permissions.reset_request_owner(token)

    return manager.start_admitted_loop(goal, channel, graph.authority.owner_id,
        requester_name, callback, before_start=before_start, execution=execution,
        publish=publish, on_settled=settled, **kwargs)


def _bot(*, reflection_enabled=True, gate_verdict=(True, "test")):
    reflector = Mock()
    reflector.reflect_on_operation = AsyncMock()
    graph = make_bot(config_overrides={"learning": {
        "enabled": True, "loop_reflection_enabled": reflection_enabled}}, reflector=reflector)
    gate = Mock()
    gate.evaluate = Mock(return_value=gate_verdict)
    graph._loop_reflection_gate = gate
    graph.turn_recorder._loop_reflection_gate = gate
    return graph


def _recorder(bot):
    bot.turn_recorder._reflector = getattr(bot, "reflector", None)
    return bot.turn_recorder
