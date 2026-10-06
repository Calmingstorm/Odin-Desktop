"""Ingress proofs with temporary profiles and ephemeral loopback only."""
import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager

import aiohttp
import pytest
from pydantic import ValidationError

from src.config.apply_registry import REDACTED
from src.config.schema import WebhookConfig
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.schedules import ScheduleService
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.desktop.transcript import TranscriptStore
from src.desktop.webhooks import MAX_BODY, WebhookIngress, format_event
from src.scheduler.scheduler import Scheduler


class Keyring:
    def __init__(self):
        self.values = {}
    def get_password(self, namespace, name):
        return self.values.get((namespace, name))
    def set_password(self, namespace, name, value):
        self.values[namespace, name] = value
    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


@asynccontextmanager
async def graph(tmp_path, source='generic', trigger=None, enabled=True):
    paths = ProfilePaths.from_xdg('test', home=tmp_path, environ={})
    paths.create_private()
    authority = OwnerAuthority(paths)
    paths.config_file.write_text('# temporary profile\npersonality:\n  custom_name: Odin\n')
    owner = authority.authenticate_local(peer_uid=authority.owner_uid)
    store = JournalStore(paths.data_dir / 'journal.sqlite3', 'test')
    conversations = ConversationStore(store, EventJournal(store))
    transcript = TranscriptStore(store, conversations.events, conversations)
    cid = conversations.create()['conversation']['id']
    scheduler = Scheduler(str(paths.data_dir / 'schedules.json'), desktop_recovery=True)
    service = ScheduleService(scheduler, authority=authority, conversations=conversations)
    item = await service.invoke('schedules.save', {'description': 'Delivery',
        'channel_id': cid, 'action': 'reminder', 'message': 'Result',
        'trigger': trigger or {'source': source}}, owner=owner)
    settings = SettingsService(paths, ProfileSecretStore(paths, backend=Keyring()))
    changes = [{'path': 'webhook.bind_address', 'value': '127.0.0.1'},
               {'path': 'webhook.port', 'value': 0},
               {'path': 'webhook.enabled', 'value': enabled},
               {'path': f"webhook.triggers.{item['id']}.source", 'value': source}]
    await settings.handle('settings.set',
                          {'expected_revision': settings.revision, 'changes': changes})
    await settings.handle('secrets.set', {'path': f"webhook.triggers.{item['id']}.secret",
                                          'value': 'temporary-webhook-credential'})
    seen = []
    async def effect(schedule):
        seen.append(schedule)
        assert scheduler.assert_run_binding(schedule) == schedule['run_binding']
        assert store.connection.execute(
            "SELECT count(*) FROM desktop_webhook_receipts WHERE state='dispatching'").fetchone()[0]
    scheduler._callback = effect
    ingress = WebhookIngress(settings, scheduler, store, transcript, owner_id=owner.owner_id)
    service.ingress = settings.ingress = ingress
    await ingress.start()
    try:
        yield ingress, scheduler, settings, service, owner, item, cid, seen
    finally:
        await ingress.close()
        store.close()
        authority.release_runtime()


async def post(ingress, source='generic', data=None, body=None, headers=None):
    body = body if body is not None else json.dumps(
        data or {'title': 'Incoming', 'message': 'Notice'}).encode()
    headers = headers or ({'X-Webhook-Secret': 'temporary-webhook-credential'}
        if source == 'generic'
        else {('X-Hub-Signature-256' if source == 'github' else 'X-Gitea-Signature'):
            hmac.new(b'temporary-webhook-credential', body, hashlib.sha256).hexdigest()})
    async with aiohttp.ClientSession() as client:
        async with client.post(f'http://127.0.0.1:{ingress.address[1]}/webhook/{source}',
                               data=body, headers=headers) as response:
            return response.status, await response.text()


@pytest.mark.asyncio
async def test_identical_deliveries_have_unique_receipts_and_runs(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, _, _, _, _, cid, seen):
        results = [await post(ingress), await post(ingress)]
        assert all(result == (200, '{"status": "delivered"}') for result in results)
        assert len(seen) == 2
        receipts = ingress.store.connection.execute(
            'SELECT id,state,run_binding FROM desktop_webhook_receipts').fetchall()
        assert len(receipts) == 2 and receipts[0][0] != receipts[1][0]
        assert all(row[1] == 'delivered' and row[2] != 'null' for row in receipts)
        assert [row['text'] for row in ingress.transcript.all_messages(cid)] == (
            ['**Incoming**\nNotice'] * 2)
        assert len(await scheduler.history.query()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['generic', 'github', 'gitea'])
async def test_auth_json_and_source_parity(tmp_path, source):
    async with graph(tmp_path, source) as (ingress, _, _, _, _, _, _, seen):
        assert (await post(ingress, source, headers={'X-Webhook-Secret': 'wrong'}))[0] == 403
        assert await post(ingress, source, body=b'{') == (400, '{"error": "invalid JSON"}')
        assert (await post(ingress, source, body=b'[]'))[0] == 400
        assert (await post(ingress, source))[0] == 200
        assert len(seen) == 1


@pytest.mark.asyncio
async def test_bound_secret_cannot_dispatch_other_matching_schedule(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, _, service, owner, _, cid, seen):
        await service.invoke('schedules.save', {'description': 'Other', 'action': 'reminder',
            'channel_id': cid, 'trigger': {'source': 'generic'}}, owner=owner)
        assert (await post(ingress))[0] == 200
        assert len(seen) == 1
        assert seen[0]['description'] == 'Delivery'


@pytest.mark.asyncio
async def test_and_matching_and_generic_has_no_repo(tmp_path):
    async with graph(tmp_path, trigger={'source': 'generic', 'repo': 'example'}) as values:
        ingress, _, _, _, _, _, cid, seen = values
        assert (await post(ingress, data={'repo': 'example'}))[0] == 200
        assert not seen
        assert len(ingress.transcript.all_messages(cid)) == 1


@pytest.mark.asyncio
async def test_disabled_no_schedule_and_revoked_listener(tmp_path):
    async with graph(tmp_path, enabled=False) as (ingress, _, settings, service, owner, item, _, _):
        assert ingress.address is None
        await settings.handle('settings.set', {'expected_revision': settings.revision,
            'changes': [{'path': 'webhook.enabled', 'value': True}]})
        assert ingress.address is not None
        await settings.handle('secrets.clear', {'path': f"webhook.triggers.{item['id']}.secret"})
        assert ingress.address is None
        await settings.handle('secrets.set', {'path': f"webhook.triggers.{item['id']}.secret",
                                              'value': 'temporary-webhook-credential'})
        assert ingress.address is not None
        await service.invoke('schedules.delete', {'id': item['id']}, owner=owner)
        assert ingress.address is None


@pytest.mark.asyncio
async def test_receipt_storage_failure_has_no_effect(tmp_path):
    async with graph(tmp_path) as (ingress, _, _, _, _, _, cid, seen):
        ingress.store.connection.execute(
            "CREATE TRIGGER deny_receipt BEFORE INSERT ON desktop_webhook_receipts "
            "BEGIN SELECT RAISE(ABORT,'temporary failure'); END")
        assert (await post(ingress))[0] == 503
        assert not seen and not ingress.transcript.all_messages(cid)


@pytest.mark.asyncio
async def test_unavailable_keyring_fences_hydrated_or_imported_credentials(tmp_path):
    async with graph(tmp_path) as (ingress, _, settings, _, _, _, _, seen):
        ingress._watcher.cancel()
        await asyncio.gather(ingress._watcher, return_exceptions=True)
        settings._keyring_error = 'Profile keyring is unavailable or locked'
        # A cached or imported secret must not become fallback authentication.
        assert not ingress._eligible(ingress.scheduler.list_all()[0])
        assert (await post(ingress))[0] == 403
        await ingress.sync()
        assert ingress.address is None
        assert not seen


@pytest.mark.asyncio
async def test_unknown_dispatch_fenced_and_not_redispatched_after_restart(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, _, _, _, item, _, seen):
        async def fail(*args, **kwargs):
            async with scheduler._lock:
                await kwargs['admission'](scheduler.list_all()[0])
            raise RuntimeError('temporary handoff failure')
        scheduler.fire_triggers = fail
        assert (await post(ingress))[0] == 200
        assert scheduler.list_all()[0]['paused']
        assert ingress.store.connection.execute(
            'SELECT state FROM desktop_webhook_receipts').fetchone()[0] == 'unknown'
        await ingress.close()
        restarted = WebhookIngress(ingress.settings, scheduler, ingress.store,
            ingress.transcript, owner_id=ingress.owner_id)
        await restarted.start()
        try:
            assert restarted.address is None
            assert not seen
        finally:
            await restarted.close()


@pytest.mark.asyncio
async def test_current_policy_checked_under_scheduler_lock(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, settings, _, _, item, _, seen):
        original = scheduler.fire_triggers
        async def revoke(*args, **kwargs):
            settings.config.webhook.triggers[item['id']].secret = ''
            return await original(*args, **kwargs)
        scheduler.fire_triggers = revoke
        assert (await post(ingress))[0] == 200
        assert not seen
        row = ingress.store.connection.execute(
            'SELECT state,run_binding FROM desktop_webhook_receipts').fetchone()
        assert tuple(row) == ('not_dispatched', 'null')


@pytest.mark.asyncio
async def test_size_and_delivery_only_routes(tmp_path):
    async with graph(tmp_path) as (ingress, _, _, _, _, _, _, seen):
        body = b'{"message":"' + b'x' * (MAX_BODY - 14) + b'"}'
        assert len(body) == MAX_BODY
        assert (await post(ingress, body=body))[0] == 200
        assert (await post(ingress, body=body + b' '))[0] == 413
        async with aiohttp.ClientSession() as client:
            for path in ['/health', '/api/chat', '/api/config', '/settings', '/status']:
                async with client.get(f'http://127.0.0.1:{ingress.address[1]}{path}') as response:
                    assert response.status == 404
        assert len(seen) == 1


@pytest.mark.parametrize('address', ['0.0.0.0', '::', 'localhost', '8.8.8.8'])
def test_nonexplicit_or_nonlocal_bind_rejected(address):
    with pytest.raises((ValidationError, ValueError)):
        WebhookConfig(bind_address=address)


@pytest.mark.parametrize('address', ['127.0.0.1', '::1', '192.168.1.2', '100.65.1.2',
                                     'fd7a:115c:a1e0::1', '169.254.1.1', 'fe80::1'])
def test_owner_selected_numeric_bind(address):
    assert WebhookConfig(bind_address=address).bind_address == address


@pytest.mark.asyncio
async def test_keyring_only_setting_and_schema(tmp_path):
    async with graph(tmp_path) as (ingress, _, settings, _, _, item, _, _):
        secret_path = f"webhook.triggers.{item['id']}.secret"
        assert 'temporary-webhook-credential' not in settings.paths.config_file.read_text()
        fields = settings.schema()['fields']
        secret = next(field for field in fields if field['path'] == secret_path)
        assert secret['desired'] == REDACTED
        await settings.reload()
        assert ingress.address is not None


@pytest.mark.asyncio
async def test_notice_follows_callback_and_uses_core_notice_outbox(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, _, _, _, _, cid, seen):
        original = scheduler._callback
        async def effect(schedule):
            assert not ingress.transcript.all_messages(cid)
            await original(schedule)
        scheduler._callback = effect
        assert (await post(ingress))[0] == 200
        message = ingress.transcript.all_messages(cid)[0]
        assert message['role'] == 'notice' and message['id'].startswith('m_wh_')
        assert 'request_id' not in message


@pytest.mark.asyncio
async def test_overlapping_deliveries_follow_retained_inflight_exclusion(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, _, _, _, _, cid, seen):
        entered, release = asyncio.Event(), asyncio.Event()
        original = scheduler._callback
        async def effect(schedule):
            entered.set()
            await release.wait()
            await original(schedule)
        scheduler._callback = effect
        first = asyncio.create_task(post(ingress))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert (await post(ingress))[0] == 200
            release.set()
            assert (await first)[0] == 200
            assert len(seen) == 1
            assert len(ingress.transcript.all_messages(cid)) == 2
            states = [row[0] for row in ingress.store.connection.execute(
                'SELECT state FROM desktop_webhook_receipts')]
            assert sorted(states) == ['delivered', 'not_dispatched']
        finally:
            release.set()
            await first


@pytest.mark.asyncio
async def test_cancelled_handoff_fences_and_recovers_notice_only(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, settings, _, _, _, cid, seen):
        entered = asyncio.Event()
        async def effect(schedule):
            entered.set()
            await asyncio.Event().wait()
        scheduler._callback = effect
        first = asyncio.create_task(post(ingress))
        await asyncio.wait_for(entered.wait(), 2)
        await ingress.close()
        await asyncio.gather(first, return_exceptions=True)
        assert scheduler.list_all()[0]['paused']
        restarted = WebhookIngress(settings, scheduler, ingress.store,
            ingress.transcript, owner_id=ingress.owner_id)
        await restarted.start()
        try:
            assert restarted.address is None
            assert len(ingress.transcript.all_messages(cid)) == 1
            assert not seen
            assert ingress.store.connection.execute(
                'SELECT state,published FROM desktop_webhook_receipts').fetchone()[0] == 'unknown'
        finally:
            await restarted.close()


@pytest.mark.asyncio
async def test_final_settlement_storage_failure_immediately_fences(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, _, _, _, _, _, seen):
        ingress.store.connection.execute(
            "CREATE TRIGGER deny_settlement BEFORE UPDATE ON desktop_webhook_receipts "
            "WHEN NEW.state='delivered' BEGIN SELECT RAISE(ABORT,'temporary failure'); END")
        assert (await post(ingress))[0] == 503
        assert len(seen) == 1
        assert scheduler.list_all()[0]['paused']
        assert scheduler.list_all()[0]['settlement'] == 'unknown'


@pytest.mark.asyncio
async def test_known_pre_effect_scheduler_storage_failure_does_not_pause(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, _, _, _, _, _, seen):
        async def unavailable(_candidate):
            raise OSError('temporary write failure')
        scheduler._publish = unavailable
        assert (await post(ingress))[0] == 200
        assert not seen
        assert not scheduler.list_all()[0].get('paused')
        assert ingress.store.connection.execute(
            'SELECT state FROM desktop_webhook_receipts').fetchone()[0] == 'not_dispatched'


@pytest.mark.asyncio
async def test_reopen_actual_store_and_recover_without_effect(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, settings, _, _, item, cid, seen):
        with ingress.store.transaction() as db:
            db.execute('INSERT INTO desktop_webhook_receipts VALUES (?,?,?,?,?,?,NULL,?,0)',
                ('wh_lost', item['id'], cid, 'generic', ingress._fingerprint(item),
                 'accepted', '**Lost acknowledgement**'))
        await ingress.close()
        path = settings.paths.data_dir / 'journal.sqlite3'
        ingress.store.close()
        store = JournalStore(path, 'test')
        events = EventJournal(store)
        transcript = TranscriptStore(store, events, ConversationStore(store, events))
        restarted = WebhookIngress(settings, scheduler, store, transcript,
                                   owner_id=ingress.owner_id)
        await restarted.start()
        try:
            assert restarted.address is None
            assert not seen
            assert transcript.all_messages(cid)[0]['text'] == '**Lost acknowledgement**'
            await restarted.recover()
            assert len(transcript.all_messages(cid)) == 1
        finally:
            await restarted.close()
            store.close()


@pytest.mark.asyncio
async def test_notice_publication_failure_repairs_without_rerun_or_pause(tmp_path):
    async with graph(tmp_path) as (ingress, scheduler, settings, _, _, _, cid, seen):
        ingress.store.connection.execute(
            "CREATE TRIGGER deny_notice BEFORE INSERT ON desktop_messages "
            "BEGIN SELECT RAISE(ABORT,'temporary failure'); END")
        assert (await post(ingress))[0] == 500
        assert len(seen) == 1 and not scheduler.list_all()[0].get('paused')
        assert not ingress.transcript.all_messages(cid)
        row = ingress.store.connection.execute(
            'SELECT state,published FROM desktop_webhook_receipts').fetchone()
        assert tuple(row) == ('delivered', 0)
        ingress.store.connection.execute('DROP TRIGGER deny_notice')
        await ingress.close()
        restarted = WebhookIngress(settings, scheduler, ingress.store,
            ingress.transcript, owner_id=ingress.owner_id)
        await restarted.start()
        try:
            assert len(seen) == 1
            assert len(ingress.transcript.all_messages(cid)) == 1
            assert not scheduler.list_all()[0].get('paused')
        finally:
            await restarted.close()


@pytest.mark.asyncio
async def test_notice_cannot_echo_any_trigger_secret(tmp_path):
    async with graph(tmp_path) as (ingress, _, _, _, _, _, cid, _):
        assert (await post(ingress, data={'message': 'temporary-webhook-credential'}))[0] == 200
        assert 'temporary-webhook-credential' not in str(ingress.transcript.all_messages(cid))
        assert '[REDACTED]' in ingress.transcript.all_messages(cid)[0]['text']


def test_frozen_gitea_push_text():
    data = {'repository': {'full_name': 'owner/repo'}, 'pusher': {'login': 'author'},
            'ref': 'refs/heads/main',
            'commits': [{'id': 'abcdef01234', 'message': 'summary\nbody'}]}
    event, text = format_event('gitea', data, {'X-Gitea-Event': 'push'})
    assert event == {'event': 'push', 'repo': 'owner/repo'}
    assert text == ('**Gitea Push** \u2014 `owner/repo` (`main`)\n'
                    'By: author | 1 commit(s)\n  \u2022 `abcdef0` summary')


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [b'{"title":NaN}', b'{"title":1e400}',
    b'{"nested":' + b'[' * 65 + b'0' + b']' * 65 + b'}',
    b'{"nested":[' + b'0,' * 100001 + b'0]}'])
async def test_bounded_structure(tmp_path, body):
    async with graph(tmp_path) as (ingress, _, _, _, _, _, _, seen):
        assert (await post(ingress, body=body))[0] == 400
        assert not seen


@pytest.mark.asyncio
async def test_duplicate_auth_headers_rejected(tmp_path):
    async with graph(tmp_path) as (ingress, _, _, _, _, _, _, seen):
        headers = [('X-Webhook-Secret', 'temporary-webhook-credential'),
                   ('X-Webhook-Secret', 'temporary-webhook-credential')]
        assert (await post(ingress, headers=headers))[0] == 400
        assert not seen


@pytest.mark.asyncio
async def test_parent_loss_closes_real_core_listener(tmp_path):
    import os

    from src.desktop.core import CoreService
    paths = ProfilePaths.from_xdg('test', home=tmp_path, environ={})
    paths.create_private()
    token = paths.config_dir / 'ipc.token'
    token.write_text('ab' * 32)
    token.chmod(0o600)
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, tmp_path / 'core.sock', token, secret_backend=Keyring())
    running = asyncio.create_task(core.run(read_fd))
    writer = None
    try:
        for _ in range(200):
            if core.phase == 'ready' and core.webhooks is not None and core.socket_path.exists():
                break
            await asyncio.sleep(0.01)
        from tests.test_desktop_core_lifecycle import connect
        _, writer, welcome = await connect(core.socket_path)
        assert welcome['t'] == 'welcome'
        owner = core.authority.authenticate_local(peer_uid=core.authority.owner_uid)
        cid = core.conversations.create()['conversation']['id']
        permission_token = core.permissions.set_request_owner(owner)
        try:
            item = await core.schedules.invoke('schedules.save', {'description': 'Core hook',
                'channel_id': cid, 'action': 'reminder', 'message': 'Reminder',
                'trigger': {'source': 'generic'}}, owner=owner)
        finally:
            core.permissions.reset_request_owner(permission_token)
        await core.settings.handle('settings.set', {'expected_revision': core.settings.revision,
            'changes': [{'path': 'webhook.enabled', 'value': True},
                {'path': 'webhook.bind_address', 'value': '127.0.0.1'},
                {'path': 'webhook.port', 'value': 0},
                {'path': f"webhook.triggers.{item['id']}.source", 'value': 'generic'}]})
        await core.settings.handle('secrets.set', {'path': f"webhook.triggers.{item['id']}.secret",
                                                  'value': 'temporary-webhook-credential'})
        port = core.webhooks.address[1]
        assert 'Webhook ingress: accepting' in str(core.management.runtime.status()['summary'])
        assert (await post(core.webhooks))[0] == 200
        assert core.store.connection.execute(
            'SELECT count(*) FROM desktop_delivery_outbox').fetchone()[0] > 0
        os.close(write_fd)
        write_fd = None
        assert await asyncio.wait_for(running, 10) == 0
        assert core.webhooks.address is None
        with pytest.raises(OSError):
            await asyncio.open_connection('127.0.0.1', port)
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        if write_fd is not None:
            os.close(write_fd)
        os.close(read_fd)
        if not running.done():
            core.lifetime.request_stop('test_cleanup')
            await running
