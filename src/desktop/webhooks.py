"""D10 delivery-only HTTP ingress; every delivery has its own durable identity.

The transport never authenticates an owner. A per-trigger key binds a delivery
to one current schedule. Accepted receipts are never replayed, including after
uncertain scheduler handoff. Native event text/headers follow frozen Odin.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
from uuid import uuid4

from aiohttp import web

from .commands import canonical_json

MAX_BODY = 10 * 1024 * 1024
SOURCES = ("generic", "github", "gitea")


def bounded_json(body):
    """Bound structural parsing without shrinking native message/string limits."""
    depth = nodes = 0
    quoted = escaped = False
    for byte in body:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
            continue
        if byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 64:
                raise ValueError('JSON nesting limit')
        elif byte in (93, 125):
            depth -= 1
        if byte in (34, 44, 91, 123):
            nodes += 1
            if nodes > 100000:
                raise ValueError('JSON node limit')
    def invalid_constant(_value):
        raise ValueError('nonfinite JSON')
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite JSON')
        return result
    return json.loads(body, parse_constant=invalid_constant, parse_float=finite_float)


def format_event(source, data, headers):
    """Native health/server.py formatting and trigger data (generic has no repo)."""
    if source == "generic":
        title, message = data.get("title", "Webhook"), data.get("message", "")
        return {"event": data.get("event", "generic"), "title": title}, (
            f"**{title}**\n{message}" if message else f"**{title}**")
    label = "GitHub" if source == "github" else "Gitea"
    event = headers.get("X-GitHub-Event" if source == "github" else "X-Gitea-Event", "unknown")
    repo = data.get("repository", {}).get("full_name", "unknown")
    if event == "push":
        pusher = data.get("pusher", {}).get("name" if source == "github" else "login", "unknown")
        commits = data.get("commits", [])
        ref = data.get("ref", "").replace("refs/heads/", "")
        lines = []
        for commit in commits[:5]:
            message = commit.get("message", "").split("\n")[0][:80]
            lines.append(f"  \u2022 `{commit.get('id', '')[:7]}` {message}")
        text = (f"**{label} Push** \u2014 `{repo}` (`{ref}`)\nBy: {pusher} | "
                f"{len(commits)} commit(s)\n" + "\n".join(lines))
    elif event == "pull_request" or (source == "gitea" and event in
            ("pull_request_approved", "pull_request_rejected")):
        pr = data.get("pull_request", {})
        number = f" #{pr.get('number', '')}" if source == "github" else ""
        text = (f"**{label} PR{number}** \u2014 `{repo}`\n{data.get('action', '')}: "
                f"**{pr.get('title', '')}** by {pr.get('user', {}).get('login', 'unknown')}")
    elif event == "issues":
        issue = data.get("issue", {})
        number = f" #{issue.get('number', '')}" if source == "github" else ""
        text = (f"**{label} Issue{number}** \u2014 `{repo}`\n{data.get('action', '')}: "
                f"**{issue.get('title', '')}** by {data.get('sender', {}).get('login', 'unknown')}")
    elif source == "github" and event == "release":
        release = data.get("release", {})
        text = (f"**GitHub Release** \u2014 `{repo}`\n{data.get('action', '')}: "
                f"**{release.get('tag_name', '')}** by "
                f"{release.get('author', {}).get('login', 'unknown')}")
    elif source == "github" and event == "workflow_run":
        workflow = data.get("workflow_run", {})
        conclusion = workflow.get("conclusion", "")
        status = f" ({conclusion})" if conclusion else ""
        text = (f"**GitHub Workflow** \u2014 `{repo}`\n{data.get('action', '')}: "
                f"**{workflow.get('name', '')}**{status} on `{workflow.get('head_branch', '')}`")
    else:
        text = f"**{label}** \u2014 `{repo}` \u2014 event: `{event}`"
    return {"event": event, "repo": repo}, text


class WebhookIngress:
    def __init__(self, settings, scheduler, store, transcript, *, owner_id,
                 admitting=lambda: True, permissions=None):
        self.settings, self.scheduler, self.store = settings, scheduler, store
        self.transcript, self.owner_id = transcript, owner_id
        self.admitting, self.permissions = admitting, permissions
        self.app = web.Application(client_max_size=MAX_BODY + 1)
        for source in SOURCES:
            self.app.router.add_post('/webhook/' + source, self._handle)
            self.app.router.add_post('/webhook/' + source + '/{schedule_id}', self._handle)
        self.runner = self.site = None
        self.address = None
        self._binding = None
        self._closed = False
        self._watcher = None
        self._sync_lock = asyncio.Lock()
        self._dirty = asyncio.Event()
        self._loop = None
        self._unsubscribe = []
        self._poll_schedules = False
        self._retry_sync = False
        self._next_bind_attempt = 0.0
        self._deliveries = set()
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS desktop_webhook_receipts (
                id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, destination TEXT NOT NULL,
                source TEXT NOT NULL, schedule_binding TEXT NOT NULL,
                state TEXT NOT NULL, run_binding TEXT, text TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0)''')
            # A restart cannot distinguish a handoff from a lost acknowledgement.
            db.execute("UPDATE desktop_webhook_receipts SET state='unknown' "
                       "WHERE state IN ('accepted','dispatching')")

    def _eligible(self, schedule, source=None):
        config = self.settings.config.webhook
        row = config.triggers.get(schedule.get('id'))
        if (self._closed or not self.admitting() or not config.enabled or
                not config.bind_address or getattr(self.settings, '_transaction_active', False) or
                getattr(self.settings, '_keyring_error', None) or
                not row or not row.secret or schedule.get('requester_id') != self.owner_id or
                schedule.get('paused') or schedule.get('inert_reason') or
                not schedule.get('trigger') or (source and row.source != source)):
            return False
        if sum(other.secret == row.secret for other in config.triggers.values()) != 1:
            return False
        try:
            self.scheduler._validate_trigger(schedule['trigger'])
            self.transcript.conversations.get(schedule['channel_id'])
        except Exception:
            return False
        return not schedule['trigger'].get('source') or schedule['trigger']['source'] == row.source

    def _fingerprint(self, schedule):
        return canonical_json({key: schedule.get(key) for key in
            ('id', '_generation', '_revision', 'created_at',
             'requester_id', 'channel_id', 'trigger')})

    async def start(self):
        if self._closed or self._watcher is not None:
            return
        self._loop = asyncio.get_running_loop()
        for owner in (self.settings, self.scheduler):
            subscribe = getattr(owner, 'subscribe_changes', None)
            if subscribe is not None:
                self._unsubscribe.append(subscribe(self.notify_change))
            else:
                self._poll_schedules = True
        await self.recover()
        try:
            await self.sync()
        except Exception:
            self._retry_sync = True
            await self._stop_listener()
        if not self._closed:
            self._watcher = asyncio.create_task(self._watch())

    def notify_change(self):
        """Hydration can publish from a worker; never synchronize inside its lock."""
        if not self._closed and self._loop is not None:
            self._loop.call_soon_threadsafe(self._mark_dirty)

    def _mark_dirty(self):
        if not self._closed:
            self._dirty.set()

    def _state_token(self):
        # No file reads, keyring I/O, secret hashes or schedule copies. The
        # native keyring has no persistent availability subscription; this also
        # catches cached availability/admission changes from legacy owners.
        return (getattr(self.settings, '_generation', None),
                getattr(self.settings, '_keyring_error', None),
                getattr(self.settings, '_transaction_active', False), self.admitting())

    async def recover(self):
        for row in self.store.connection.execute(
                "SELECT id FROM desktop_webhook_receipts WHERE published=0").fetchall():
            self._publish_notice(row[0])

    async def _watch(self):
        previous = self._state_token()
        while not self._closed:
            if self._retry_sync:
                # Mutations cannot accelerate retries on an occupied address.
                await asyncio.sleep(1.0)
            else:
                try:
                    await asyncio.wait_for(self._dirty.wait(), 1.0)
                except TimeoutError:
                    if not self._poll_schedules and self._state_token() == previous:
                        continue
            self._dirty.clear()
            previous = self._state_token()
            try:
                await self.sync()
            except Exception:
                # Bind/storage errors never turn into accepting a fallback address.
                self._retry_sync = True
                await self._stop_listener()

    async def sync(self):
        async with self._sync_lock:
            if self._closed:
                return
            config = self.settings.config.webhook
            eligible = False
            if config.enabled and config.bind_address:
                async with self.scheduler._lock:
                    eligible = any(self._eligible(row) for row in self.scheduler.list_all())
            binding = (config.bind_address, config.port) if eligible else None
            if binding == self._binding:
                if binding is not None or not eligible:
                    self._retry_sync = False
                return
            await self._stop_listener()
            if binding is not None and not self._closed:
                loop = asyncio.get_running_loop()
                if loop.time() < self._next_bind_attempt:
                    self._retry_sync = True
                    return
                runner = web.AppRunner(self.app, access_log=None,
                                       max_line_size=8190, max_field_size=8190)
                try:
                    await runner.setup()
                    site = web.TCPSite(runner, *binding)
                    await site.start()
                except BaseException as exc:
                    self._next_bind_attempt = loop.time() + 1.0
                    self._retry_sync = True
                    await runner.cleanup()
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    return
                self.runner, self.site, self._binding = runner, site, binding
                self.address = site._server.sockets[0].getsockname()
                self._retry_sync = False
            else:
                self._retry_sync = False

    async def _stop_listener(self):
        runner = self.runner
        self.runner = self.site = self.address = self._binding = None
        if runner is not None:
            cleanup = asyncio.create_task(runner.cleanup())
            cancelled = False
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
            cleanup.result()
            if cancelled:
                raise asyncio.CancelledError

    def intake_state(self):
        """Whether a trigger schedule can fire now: status() without counting schedules."""
        config = self.settings.config.webhook
        return ('closed' if self._closed else 'disabled' if not config.enabled else
                'unconfigured_bind' if not config.bind_address else
                'accepting' if self.address else 'not_bound')

    def status(self):
        config = self.settings.config.webhook
        eligible = sum(self._eligible(row) for row in self.scheduler.list_all())
        reason = ('closed' if self._closed else 'disabled' if not config.enabled else
                  'unconfigured_bind' if not config.bind_address else
                  'no_eligible_schedule' if not eligible else
                  'accepting' if self.address else 'not_bound')
        unknown = self.store.connection.execute(
            "SELECT count(*) FROM desktop_webhook_receipts WHERE state='unknown'").fetchone()[0]
        return {'reason': reason, 'address': self.address, 'eligible_schedules': eligible,
                'unknown_deliveries': unknown}

    async def close(self):
        self._closed = True
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        if self._watcher is not None:
            self._watcher.cancel()
            await asyncio.gather(self._watcher, return_exceptions=True)
        for task in tuple(self._deliveries):
            if task is not asyncio.current_task():
                task.cancel()
        await asyncio.gather(*(task for task in self._deliveries
                               if task is not asyncio.current_task()), return_exceptions=True)
        async with self._sync_lock:
            await self._stop_listener()

    @staticmethod
    def _authenticated(source, body, headers, secret):
        if not secret:
            return False
        if source == 'generic':
            return hmac.compare_digest(
                headers.get('X-Webhook-Secret', '').encode(), secret.encode())
        header = 'X-Hub-Signature-256' if source == 'github' else 'X-Gitea-Signature'
        signature = headers.get(header, '')
        if source == 'github' and signature.startswith('sha256='):
            signature = signature[7:]
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.encode(), expected.encode())

    async def _handle(self, request):
        task = asyncio.current_task()
        self._deliveries.add(task)
        try:
            return await self._deliver(request)
        finally:
            self._deliveries.discard(task)

    async def _deliver(self, request):
        source = request.path.split('/')[2]
        body = await request.read()
        if len(body) > MAX_BODY:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=len(body))
        if sum(len(k) + len(v) for k, v in request.raw_headers) > 65536:
            raise web.HTTPRequestHeaderFieldsTooLarge()
        relevant = ('X-Webhook-Secret', 'X-Hub-Signature-256', 'X-Gitea-Signature',
                    'X-GitHub-Event', 'X-Gitea-Event')
        if any(len(request.headers.getall(header, [])) > 1 for header in relevant):
            return web.json_response({'error': 'ambiguous headers'}, status=400)
        async with self.scheduler._lock:
            matches = []
            for schedule in self.scheduler.list_all():
                if request.match_info.get('schedule_id', schedule['id']) != schedule['id']:
                    continue
                if self._eligible(schedule, source):
                    row = self.settings.config.webhook.triggers[schedule['id']]
                    if self._authenticated(source, body, request.headers, row.secret):
                        matches.append((schedule, row.secret))
            if len(matches) != 1:
                error = 'invalid secret' if source == 'generic' else 'invalid signature'
                return web.json_response({'error': error}, status=403)
            schedule, secret = matches[0]
            fingerprint = self._fingerprint(schedule)
            try:
                data = bounded_json(body)
                if not isinstance(data, dict):
                    raise ValueError
                event_data, text = format_event(source, data, request.headers)
            except (ValueError, TypeError, AttributeError, RecursionError, UnicodeError):
                return web.json_response({'error': 'invalid JSON'}, status=400)
            receipt = 'wh_' + uuid4().hex
            # Body data is untrusted event text, not a credential readback route.
            for row in self.settings.config.webhook.triggers.values():
                if row.secret:
                    text = text.replace(row.secret, '[REDACTED]')
            try:
                with self.store.transaction() as db:
                    db.execute('INSERT INTO desktop_webhook_receipts VALUES (?,?,?,?,?,?,NULL,?,0)',
                               (receipt, schedule['id'], schedule['channel_id'], source,
                                fingerprint, 'accepted', text))
            except Exception:
                return web.json_response({'error': 'could not save webhook delivery'}, status=503)

        dispatched = False
        run_binding = None
        settled = False
        async def started(current):
            nonlocal run_binding
            run_binding = current.get('run_binding')
            with self.store.transaction() as db:
                db.execute('UPDATE desktop_webhook_receipts SET run_binding=? WHERE id=?',
                           (canonical_json(run_binding), receipt))
        async def admit(current):
            nonlocal dispatched
            # Scheduler owns this lock immediately before run_started publication.
            row = self.settings.config.webhook.triggers.get(current['id'])
            if (not self._eligible(current, source) or not row or row.secret != secret or
                    self._fingerprint(current) != fingerprint):
                return False
            with self.store.transaction() as db:
                changed = db.execute("UPDATE desktop_webhook_receipts SET state='dispatching' "
                                     "WHERE id=? AND state='accepted'",
                                     (receipt,)).rowcount
            dispatched = changed == 1
            return changed == 1

        token = None
        if self.permissions is not None:
            owner = self.permissions.authority.authenticate_local(
                peer_uid=self.permissions.authority.owner_uid)
            token = self.permissions.set_request_owner(owner)
        try:
            try:
                await self.scheduler.fire_triggers(source, event_data,
                    schedule_id=schedule['id'], admission=admit, run_started=started)
            except Exception:
                # Native _notify_triggers swallows dispatch errors, then _send
                # still delivers. Fence this receipt, not future deliveries.
                with self.store.transaction() as db:
                    db.execute("UPDATE desktop_webhook_receipts SET state=? WHERE id=?",
                               ('unknown' if dispatched else 'not_dispatched', receipt))
                settled = True
                self._publish_notice(receipt)
                return web.json_response({'status': 'delivered'})
            with self.store.transaction() as db:
                db.execute("UPDATE desktop_webhook_receipts SET state=?, run_binding=? WHERE id=?",
                           ('delivered' if dispatched else 'not_dispatched',
                            canonical_json(run_binding), receipt))
            settled = True
            self._publish_notice(receipt)
            return web.json_response({'status': 'delivered'})
        except asyncio.CancelledError:
            try:
                if not settled:
                    with self.store.transaction() as db:
                        db.execute("UPDATE desktop_webhook_receipts SET state=? WHERE id=?",
                                   ('unknown' if dispatched else 'not_dispatched', receipt))
            finally:
                if dispatched and not settled:
                    self._fence_unknown(receipt)
            raise
        except Exception:
            # Try to mark this handoff unknown now. If storage stays unavailable,
            # its persisted dispatching marker becomes unknown at next open.
            # Neither case admits receipt replay or pauses the valid definition.
            if dispatched and not settled:
                self._fence_unknown(receipt)
            return web.json_response({'error': ('could not publish webhook delivery' if settled
                                               else 'could not settle webhook delivery')},
                                     status=500 if settled else 503)
        finally:
            if token is not None:
                self.permissions.reset_request_owner(token)

    def _fence_unknown(self, receipt):
        try:
            with self.store.transaction() as db:
                db.execute("UPDATE desktop_webhook_receipts SET state='unknown' "
                           "WHERE id=? AND state IN ('accepted','dispatching')", (receipt,))
        except Exception:
            # The durable pre-effect marker already prevents internal replay.
            pass

    def _publish_notice(self, receipt):
        with self.store.transaction() as db:
            row = db.execute('SELECT destination,text,published FROM desktop_webhook_receipts '
                             'WHERE id=?',
                             (receipt,)).fetchone()
            if row is not None and not row['published']:
                self.transcript.commit(row['destination'], 'notice', row['text'], id='m_' + receipt)
                db.execute('UPDATE desktop_webhook_receipts SET published=1 WHERE id=?', (receipt,))
