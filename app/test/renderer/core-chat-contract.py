"""Emit contracts from real desktop storage/delivery services, not a fixture core.

No engine execution or process controls occur here. Provider-backed end-to-end
execution is covered separately by test:real-core and smoke:real-core.
"""
import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.desktop.artifacts import ArtifactStore
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal, RequestContext
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.search import TranscriptSearch
from src.desktop.tool_details import ToolDetailsStore
from src.desktop.transcript import TranscriptStore
from src.permissions.manager import PermissionManager
from src.tools.media_result import BinaryAttachment
from src.tools.output_retention import OutputStore


async def contracts(root):
    paths = ProfilePaths.from_xdg('renderer-contract', home=root, environ={})
    authority = OwnerAuthority(paths)
    owner = authority.authenticate_local(peer_uid=authority.owner_uid)
    permissions = PermissionManager(authority)
    token = permissions.set_request_owner(owner)
    journal = JournalStore(paths.data_dir / 'transport.sqlite3', 'renderer-contract')
    try:
        events = PublicationEventJournal(journal)
        conversations = ConversationStore(journal, events)
        transcript = TranscriptStore(journal, events, conversations)
        delivery = DurableDelivery(journal, events, transcript_commit=transcript.commit)
        requests = RequestService(journal, conversations, transcript,
            engine=SimpleNamespace(deps=SimpleNamespace()), permissions=permissions,
            authority=authority, delivery=delivery)
        cid = conversations.create('Real renderer contract')['conversation']['id']
        initial = transcript.snapshot(cid)
        admitted = requests.submit({'client_submission_id': 'renderer-send',
            'conversation_id': cid, 'text': 'contract needle'})
        context = RequestContext(cid, admitted['request_id'], 1, authority.owner_id,
                                 admitted['message_id'])
        delivery.tool_started(context, invocation_id='contract-call',
                              tool='run_command', summary='Harmless receipt')
        delivery.tool_settled(context, invocation_id='contract-call',
                              outcome='success', duration_ms=1)
        before_reply = events.between(initial['watermark'])
        await delivery.send_reply(context, 'Committed needle',
            guarded=delivery.guarded_reply(context, 'Committed needle'))
        reply_events = events.between(before_reply[-1]['cursor'])
        after_reply = transcript.snapshot(cid)
        search = TranscriptSearch(transcript, events)
        hits = search.query({'query': 'needle'})
        around = search.around({'conversation_id': cid,
            'message_id': admitted['message_id'], 'before': 0, 'after': 1})
        child = conversations.create('Child', cid, admitted['message_id'])
        child_snapshot = transcript.snapshot(child['conversation']['id'])
        before_reset = events.high
        reset = conversations.reset_context(cid, conversations.get(cid)['rev'])
        reset_events = events.between(before_reset)
        renamed = conversations.update(cid, reset['conversation']['rev'], title='Renamed')
        archived = conversations.update(cid, renamed['conversation']['rev'], archived=True)
        deleted_child = conversations.delete(child['conversation']['id'],
                                             child['conversation']['rev'])
        listed = conversations.list()

        evidence = OutputStore(root / 'evidence.sqlite3')
        authorize = lambda *_: True
        artifacts = ArtifactStore(journal, output_store=evidence, authorize=authorize)
        details = ToolDetailsStore(journal, output_store=evidence,
                                   artifacts=artifacts, authorize=authorize)
        text = evidence.retain('first page second page', owner=authority.owner_id,
            channel=cid, tool='run_command')
        binary = evidence.retain_binary_bundle([BinaryAttachment(data=b'bytes',
            media_type='application/octet-stream', kind='file', content_index=0)],
            owner=authority.owner_id, channel=cid, tool='run_command')
        details.record(request_id=admitted['request_id'], invocation_id='contract-call',
            owner=authority.owner_id, conversation_id=cid, tool='run_command',
            arguments={'command': 'pwd'}, delivered_output='Real preview',
            cursor=f'{text.result_id}:0', attachment_cursor=f'{binary.result_id}:0')
        detail = details.detail(admitted['request_id'], 'contract-call', owner=authority.owner_id)
        pages = []
        cursor = detail['output']['cursor']
        while cursor:
            page = details.output(cursor, 10, owner=authority.owner_id, conversation_id=cid)
            pages.append(page)
            cursor = page.get('next_cursor')
        return dict(initial=initial, admitted=admitted, before_reply=before_reply,
            reply_events=reply_events, after_reply=after_reply, search=hits, around=around,
            child=child, child_snapshot=child_snapshot, reset=reset,
            reset_events=reset_events, renamed=renamed, archived=archived,
            deleted_child=deleted_child, listed=listed, detail=detail, pages=pages)
    finally:
        journal.close()
        permissions.reset_request_owner(token)
        authority.release_runtime()


with tempfile.TemporaryDirectory(prefix='odin-renderer-contract-') as directory:
    print(json.dumps(asyncio.run(contracts(Path(directory)))))
