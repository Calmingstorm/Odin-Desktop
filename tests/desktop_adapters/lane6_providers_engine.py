"""Legacy test spellings entering real durable single-owner Desktop requests."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.config.schema import Config
from src.desktop.attachments import AttachmentService
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.secrets import ProfileSecretStore
from src.desktop.services import build_engine_services
from src.desktop.settings import SettingsService
from src.desktop.transcript import TranscriptStore
from src.permissions.manager import PermissionManager
from tests.desktop_adapters.step5_llm_bridge import MemoryKeyring
from tests.fakes import FakeLLM

GRAPHS = []


class ScriptedProvider(FakeLLM):
    async def drain_and_close(self):
        return None


def make_bot(*, config_overrides=None, fake_llm=None):
    root = tempfile.TemporaryDirectory(prefix="lane6_providers_engine_")
    paths = ProfilePaths.from_xdg(home=Path(root.name), environ={})
    paths.create_private()
    cfg = Config(**(config_overrides or {}))
    cfg.context.directory = str(paths.data_dir / "context")
    cfg.learning.enabled = False
    cfg.browser.enabled = False
    cfg.search.enabled = False
    cfg.turn_state.enabled = False
    cfg.llm_provider.model = "codex:fake-model"
    settings = SettingsService(paths, ProfileSecretStore(paths, backend=MemoryKeyring()), config=cfg)
    key = cfg.openai_compatible.api_key
    if key:
        settings.secrets.set("openai_compatible.api_key", key)
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    store = JournalStore(paths.data_dir / "transport.sqlite3", paths.profile_id)
    events = PublicationEventJournal(store)
    conversations = ConversationStore(store, events)
    transcript = TranscriptStore(store, events, conversations)
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    attachments = AttachmentService(store, lambda _db, cid: conversations.get(cid))
    engine = build_engine_services(cfg, paths, permissions, delivery=delivery,
                                   codex_client=fake_llm, settings=settings)
    requests = RequestService(store, conversations, transcript, engine=engine,
        permissions=permissions, authority=authority, delivery=delivery, attachments=attachments)
    engine.bind_requests(requests)
    cid = conversations.create()["conversation"]["id"]
    bot = SimpleNamespace(**vars(engine.deps), tool_loop=engine.runner, config=cfg,
        engine=engine, requests=requests, store=store, transcript=transcript,
        authority=authority, cid=cid, _directory=root)
    GRAPHS.append(bot)
    return bot


def build(script, chat=None, **overrides):
    fake = ScriptedProvider(script, chat_responses=chat)
    return make_bot(config_overrides=overrides, fake_llm=fake), fake


async def _run(bot, content, *, autonomous=False):
    original = bot.engine.run
    if autonomous:
        async def execute(message, **kwargs):
            text = await bot.tool_loop.run_autonomous(content, message, None, message.owner_id)
            return text, False, False, [], False
        bot.engine.run = execute
    token = bot.permissions.set_request_owner(
        bot.authority.authenticate_local(peer_uid=bot.authority.owner_uid))
    try:
        row = bot.requests.submit({"client_submission_id": "lane6_providers_request",
            "conversation_id": bot.cid, "text": content})
        await bot.requests.after_commit()
        await asyncio.gather(*bot.requests._tasks)
        request = bot.requests.get_request(row["request_id"])
        text = bot.transcript.read_conversation(bot.cid)[-1]["text"]
        return text, False, request["state"] != "completed", [], False
    finally:
        bot.engine.run = original
        await bot.requests.close()
        await bot.engine.close()
        bot.store.close()
        bot.permissions.reset_request_owner(token)
        bot.authority.release_runtime()
        bot._directory.cleanup()
        GRAPHS.remove(bot)


async def run_loop(bot, msg, history=None):
    return await _run(bot, msg.content)


async def run_iteration(bot, prompt="do the loop work", prev=None, user_id=None):
    return (await _run(bot, prompt, autonomous=True))[0]
