"""Fixture-only transport projection onto real desktop ingress and stores.

The legacy capture callback observes a durable transcript readback; it never
implements delivery. No legacy health/config management surface is emulated.
"""
from __future__ import annotations

from contextvars import ContextVar

from aiohttp import web

from src.config.schema import Config
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.settings import SettingsService
from src.desktop.transcript import TranscriptStore
from src.scheduler.scheduler import Scheduler

_fixtures = ContextVar("inherited_webhook_fixture")


class InheritedIngress:
    def __init__(self, *, secret, channel_id, github_channel_id=""):
        from src.desktop.webhooks import WebhookIngress

        fixtures = _fixtures.get()
        paths = ProfilePaths.from_xdg(f"inherited-{len(fixtures['servers'])}",
                                     home=fixtures["root"], environ={})
        self.authority = OwnerAuthority(paths)
        self.store = JournalStore(paths.data_dir / "journal.sqlite3", paths.profile_id)
        events = EventJournal(self.store)
        self.conversations = ConversationStore(self.store, events)
        self.cid = self.conversations.create()["conversation"]["id"]
        self.transcript = TranscriptStore(self.store, events, self.conversations)
        self.scheduler = Scheduler(str(paths.data_dir / "schedules.json"), desktop_recovery=True)
        self.settings = SettingsService(paths, None, config=Config())
        self.ingress = WebhookIngress(self.settings, self.scheduler, self.store,
                                      self.transcript, owner_id=self.authority.owner_id)
        self._app = self.ingress.app
        self.observer = None
        self.channel = github_channel_id or channel_id
        self.observed = set()
        self.executions = []

        async def execute(schedule):
            # Real scheduler admission and durable desktop binding precede this
            # inert external-effect boundary. Event notices belong to ingress.
            self.scheduler.assert_run_binding(schedule)
            self.executions.append(schedule["id"])

        self.scheduler._callback = execute

        async def provision(_app):
            schedule = await self.scheduler.add(
                "Inherited GitHub delivery", "reminder", self.cid,
                requester_id=self.authority.owner_id, trigger={"source": "github"})
            self.settings.config.webhook = Config.model_validate({"webhook": {
                "enabled": True, "bind_address": "127.0.0.1", "port": 0,
                "triggers": {schedule["id"]: {"source": "github", "secret": secret}},
            }}).webhook

        @web.middleware
        async def observe_committed_delivery(request, handler):
            response = await handler(request)
            if response.status == 200:
                messages = self.transcript.list(self.cid)["items"]
                for message in messages:
                    if message["id"] not in self.observed:
                        self.observed.add(message["id"])
                        # No fabricated event text or destination. The legacy
                        # numeric channel is an alias for this real conversation.
                        if self.observer is not None:
                            await self.observer(self.channel, message["text"])
            return response

        self._app.on_startup.append(provision)
        self._app.middlewares.append(observe_committed_delivery)
        fixtures["servers"].append(self)

    def set_send_message(self, observer):
        self.observer = observer

    async def close(self):
        await self.ingress.close()
        await self.scheduler.stop()
        self.store.close()
        self.authority.release_runtime()


def make_server(*, secret, channel_id, github_channel_id=""):
    return InheritedIngress(secret=secret, channel_id=channel_id,
                            github_channel_id=github_channel_id)
