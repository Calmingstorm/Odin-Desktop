"""Canonical batch lineage: real admission, native dispatch and retained manager.

Only the remote provider transport is deterministic. No replacement agent loop,
permission tier, chat transport, listener or synthetic manager is installed.
"""
import asyncio
import json

import pytest

from src.agents.manager import AgentManager
from src.config.schema import OpenAICompatibleModelProfile
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.core import profile_config
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.desktop.work import WorkService
from src.discord.native_tools.agents_tasks import AgentTaskTools
from src.llm.types import LLMResponse
from src.permissions.manager import PermissionManager


class Lane6AgentsProvider:
    model = "fixture"
    provider_name = "compat"

    def __init__(self):
        self.calls = []

    async def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(text="The harmless calculation is complete.")

    async def chat(self, **kwargs):
        return "COMPLETE"

    async def drain_and_close(self):
        pass


@pytest.mark.asyncio
async def test_lane6_agents_canonical_native_admission_result_and_owner(tmp_path):
    paths = ProfilePaths.from_xdg("lane6-agents", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    authority.acquire_runtime()
    permissions = PermissionManager(authority)
    owner = authority.authenticate_local(peer_uid=authority.owner_uid)
    owner_token = permissions.set_request_owner(owner)
    store = JournalStore(paths.data_dir / "journal.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    cfg = profile_config(paths)
    cfg.openai_codex.enabled = False
    cfg.openai_compatible.enabled = True
    cfg.openai_compatible.model_profiles["fixture"] = OpenAICompatibleModelProfile(
        total_window_tokens=131072, max_output_tokens=4096, supports_thinking_mode=True,
    )
    cfg.llm_provider.model = "compat:fixture"
    cfg.agents.model = "compat:fixture"
    cfg.learning.enabled = False
    cfg.browser.enabled = False
    provider = Lane6AgentsProvider()
    engine = build_engine_services(cfg, paths, permissions, delivery=delivery,
                                   compatible_client=provider)
    requests = RequestService(store, conversations, transcript, engine=engine,
                              permissions=permissions, authority=authority, delivery=delivery)
    engine.bind_requests(requests)
    work = WorkService(store, events, authority=authority, permissions=permissions,
                       requests=requests, conversations=conversations,
                       agents=engine.deps.agent_manager,
                       tasks=engine.deps.channel_state.background_tasks)
    native = engine.deps.native_owners["agents"]
    native._background_admission = requests
    native._work_service = work

    async def publish(message, text, kind=None):
        requests.assert_bound_request(message)
        return await delivery.send(message.channel, text)

    native._publish_background = publish
    engine.deps.background_work_ready = True
    engine.deps.tool_catalog.invalidate()
    try:
        assert isinstance(native, AgentTaskTools)
        assert isinstance(work.agents, AgentManager)
        assert native._agent_manager is work.agents is engine.deps.agent_manager
        assert native._tool_loop is engine.runner
        cid = conversations.create()["conversation"]["id"]
        root = requests._register_background("workflow", "fixture-root", "calculate", cid,
                                             authority.owner_id)
        async with requests.background_execution(root):
            result = await native._handle_spawn_agent(root, {
                "label": "fixture", "goal": "Complete a harmless calculation",
            })
            assert "spawned" in result, result
            agent = next(iter(work.agents._agents.values()))
            admitted = work.list()["items"][0]
            assert admitted["manager_id"] == agent.id
            assert admitted["owner_id"] == authority.owner_id
            assert admitted["conversation_id"] == cid
            assert admitted["manager_generation"] == str(agent.created_at)
            assert requests.get_request(admitted["request_id"])["state"] == "admitted"
            await asyncio.wait_for(agent._task, 10)
            await asyncio.sleep(0)
            assert agent.status == "completed", agent.error
            settled = work.list()["items"][0]
            assert settled["state"] == "completed"
            assert requests.get_request(admitted["request_id"])["state"] == "completed"
            page = json.loads(await native._handle_get_agent_results(
                {"agent_id": agent.id}, user_id=authority.owner_id, channel_id=cid))
            assert page["status"] == "completed"
            assert "harmless calculation" in page["preview"]
            refused = await native._handle_get_agent_results(
                {"agent_id": agent.id}, user_id="unissued-reader", channel_id=cid)
            assert "not found" in refused
        assert len(provider.calls) == 1
        assert provider.calls[0]["model"] == "fixture"
    finally:
        await requests.close()
        await engine.close()
        store.close()
        permissions.reset_request_owner(owner_token)
        authority.release_runtime()
