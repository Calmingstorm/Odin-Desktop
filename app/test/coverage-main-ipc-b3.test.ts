import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IPC, SETTINGS_SHAPED } from '../src/shared/api'
import { DeviceLoginBoundary, CODEX_VERIFICATION_URL } from '../src/main/device-login'
import { registerIpc, type IpcDeps } from '../src/main/ipc'

const handlers = vi.hoisted(() => new Map<string, (event: any, value?: any) => any>())
vi.mock('electron', () => ({ ipcMain: { handle: (channel: string, handler: any) => handlers.set(channel, handler) } }))
const id = 'b3b3b3b3-1234-4123-8123-123456789abc'
const frame = { url: 'app://odin/index.html', processId: 2, routingId: 3 }
const event = { sender: { id: 7 }, senderFrame: frame }
let deps: any
const ok = (result: any) => ({ ok: true, result })
const failed = { ok: false, error: { code: 'unavailable', message: 'fixture failure' } }
async function call(channel: string, value?: any) { return handlers.get(channel)!(event, value) }
beforeEach(() => {
  handlers.clear();
  deps = {
    broker: { coreInstanceId: 'core1', request: vi.fn(async () => ok({ marker: 'core result' })) },
    deviceLogin: new DeviceLoginBoundary(), windowId: () => 7, mainFrame: () => frame,
    releases: { check: vi.fn(async () => ({ state: 'equal' })), open: vi.fn(async () => ok({ opened: true })) },
    drafts: { get: vi.fn(() => 'saved draft'), set: vi.fn() },
    attachments: { stagePath: vi.fn(async (path: string) => path.endsWith('bad') ? failed : ok({ id, path })),
      stageBytes: vi.fn(async () => ok({ id })), upload: vi.fn(async () => ok({ ref: 'uploaded' })), cancel: vi.fn() },
    artifacts: { fetchBytes: vi.fn(async () => ok(Buffer.from('abc'))), check: vi.fn(() => ok({ available: true })),
      open: vi.fn(() => ok({ opened: true })), saveAs: vi.fn(() => ok({ saved: true })), reveal: vi.fn(() => ok({ revealed: true })) },
    pickFiles: vi.fn(async () => ['/mock/good', '/mock/bad']), chooseSavePath: vi.fn(async () => '/mock/saved'),
    copyText: vi.fn(), openVerification: vi.fn(async () => undefined),
    getSettings: vi.fn(() => ({ appearance: 'dark' })), setAutostart: vi.fn(enabled => ({ autostart: enabled })),
    setNotifications: vi.fn(value => ({ notifications: value })), setAppearance: vi.fn(appearance => ({ appearance })),
    setConversationMuted: vi.fn((conversation, muted) => ({ conversation, muted })),
    appState: vi.fn(() => ({ link: 'ready', cleanupWarning: { id: 'notice1' } })),
    acknowledgeCleanup: vi.fn(() => ({ cleanupWarning: null }))
  };
  registerIpc(deps as IpcDeps);
})
describe('named IPC behavior through the real validation boundary', () => {
  it('maps conversation/control/read methods with stable command IDs and bounded default limits', async () => {
    for (const [channel, method, payload, params, command] of [
      [IPC.createConversation, 'conversations.create', { command_id: id, title: 'Title' }, { title: 'Title' }, id],
      [IPC.updateConversation, 'conversations.update', { command_id: id, id: 'c1', expected_rev: 0, title: 'Renamed' }, { id: 'c1', expected_rev: 0, title: 'Renamed' }, id],
      [IPC.deleteConversation, 'conversations.delete', { command_id: id, id: 'c1', expected_rev: 0 }, { id: 'c1', expected_rev: 0 }, id],
      [IPC.resetContext, 'conversations.reset_context', { command_id: id, id: 'c1', expected_rev: 0 }, { id: 'c1', expected_rev: 0 }, id],
      [IPC.markRead, 'conversations.mark_read', { id: 'c1', through_message_id: 'm1' }],
      [IPC.search, 'search.query', { query: ' query ' }, { query: 'query' }],
      [IPC.messagesAround, 'messages.around', { conversation_id: 'c1', message_id: 'm1' }],
      [IPC.listMessages, 'messages.list', { conversation_id: 'c1' }, { conversation_id: 'c1', limit: 100 }],
      [IPC.snapshotConversation, 'conversation.snapshot', { conversation_id: 'c1', limit: 20 }, { conversation_id: 'c1', limit: 20 }],
      [IPC.submit, 'submission.send', { client_submission_id: id, conversation_id: 'c1', text: 'hello' }, undefined, id],
      [IPC.stop, 'control.stop', { control_command_id: id, conversation_id: 'c1', request_id: 'r1', generation: 1 }, undefined, id],
      [IPC.steer, 'control.steer', { control_command_id: id, conversation_id: 'c1', request_id: 'r1', generation: 1, text: 'focus' }, undefined, id],
      [IPC.resumeRequest, 'control.resume', { control_command_id: id, conversation_id: 'c1', request_id: 'r1', generation: 1 }, undefined, id],
      [IPC.workList, 'work.list', {}],
      [IPC.workControl, 'work.control', { control_command_id: id, kind: 'process', id: 'p1', action: 'stop' }, undefined, id],
      [IPC.toolDetail, 'tool.detail', { request_id: 'r1', invocation_id: 'i1' }],
      [IPC.toolOutput, 'tool.output', { cursor: 'cursor', limit: 100 }],
      [IPC.reportPage, 'reports.page', { report_id: 'report', page: 1 }],
      [IPC.usage, 'usage.get', { period: '24h' }], [IPC.reload, 'runtime.reload', { scope: 'skills' }]
    ] as any[]) {
      deps.broker.request.mockClear();
      expect(await call(channel, payload)).toEqual(ok({ marker: 'core result' }));
      if (command) expect(deps.broker.request).toHaveBeenCalledExactlyOnceWith(method, params ?? payload, command);
      else expect(deps.broker.request).toHaveBeenCalledExactlyOnceWith(method, params ?? payload);
    }
    deps.broker.request.mockResolvedValueOnce(failed); expect(await call(IPC.listConversations)).toEqual(failed);
  })
  it('aggregates staging failures and preserves bytes and artifact outcomes', async () => {
    expect(await call(IPC.pickFiles)).toEqual(ok({ staged: [{ id, path: '/mock/good' }], errors: ['fixture failure'] }));
    expect(await call(IPC.attachPaths, { paths: ['/mock/second'] })).toEqual(ok({ staged: [{ id, path: '/mock/second' }], errors: [] }));
    expect(await call(IPC.attachBytes, { name: 'a.txt', mime: 'text/plain', data: new Uint8Array([65]) })).toEqual(ok({ id }));
    expect(deps.attachments.stageBytes).toHaveBeenCalledWith('a.txt', 'text/plain', Buffer.from('A'));
    expect(await call(IPC.uploadAttachment, { id, conversation_id: 'c1' })).toEqual(ok({ ref: 'uploaded' }));
    expect(deps.attachments.upload).toHaveBeenCalledWith(id, 'c1');
    expect(await call(IPC.cancelAttachment, { id })).toEqual(ok({ cancelled: true })); expect(deps.attachments.cancel).toHaveBeenCalledWith(id);
    expect(await call(IPC.fetchArtifact, { ref: 'ref1' })).toEqual(ok({ data: new Uint8Array(Buffer.from('abc')) }));
    deps.artifacts.fetchBytes.mockResolvedValueOnce(failed); expect(await call(IPC.fetchArtifact, { ref: 'ref1' })).toEqual(failed);
    expect(await call(IPC.checkArtifact, { ref: 'ref1' })).toEqual(ok({ available: true })); expect(deps.artifacts.check).toHaveBeenCalledWith('ref1');
    for (const [channel, method, result] of [[IPC.openArtifact, 'open', { opened: true }], [IPC.revealArtifact, 'reveal', { revealed: true }]] as const) {
      expect(await call(channel, { ref: 'ref1', name: 'a.txt' })).toEqual(ok(result)); expect(deps.artifacts[method]).toHaveBeenCalledWith('ref1', 'a.txt');
    }
    expect(await call(IPC.saveArtifact, { ref: 'ref1', name: 'a.txt' })).toEqual(ok({ saved: true }));
    expect(deps.chooseSavePath).toHaveBeenCalledWith('a.txt'); expect(deps.artifacts.saveAs).toHaveBeenCalledWith('ref1', '/mock/saved');
    deps.chooseSavePath.mockResolvedValueOnce(null); await call(IPC.saveArtifact, { ref: 'ref1', name: 'a.txt' });
    expect(deps.artifacts.saveAs).toHaveBeenLastCalledWith('ref1', null);
  })
  it('applies local settings/drafts/clipboard without core calls and converts thrown local errors', async () => {
    expect(await call(IPC.getDraft, { conversation_id: 'c1' })).toEqual(ok({ text: 'saved draft' }));
    expect(deps.drafts.get).toHaveBeenCalledWith('c1');
    expect(await call(IPC.setDraft, { conversation_id: 'c1', text: 'new draft' })).toEqual(ok({ saved: true })); expect(deps.drafts.set).toHaveBeenCalledWith('c1', 'new draft');
    expect(await call(IPC.copyText, { text: 'copied' })).toEqual(ok({ copied: true })); expect(deps.copyText).toHaveBeenCalledWith('copied');
    expect(await call(IPC.getSettings)).toEqual(ok({ appearance: 'dark' }));
    expect(await call(IPC.setAutostart, { enabled: true })).toEqual(ok({ autostart: true }));
    expect(await call(IPC.setNotifications, { previews: false })).toEqual(ok({ notifications: { previews: false } }));
    expect(await call(IPC.setAppearance, { appearance: 'light' })).toEqual(ok({ appearance: 'light' }));
    expect(await call(IPC.setConversationMuted, { conversation_id: 'c1', muted: true })).toEqual(ok({ conversation: 'c1', muted: true }));
    expect(deps.broker.request).not.toHaveBeenCalled();
    deps.copyText.mockImplementationOnce(() => { throw new Error('native refusal') });
    expect(await call(IPC.copyText, { text: 'copied' })).toEqual({ ok: false, error: { code: 'internal', message: 'Internal app error.' } });
    expect(await call(IPC.getAppState)).toEqual(deps.appState());
    expect(await handlers.get(IPC.getAppState)!({ ...event, sender: { id: 999 } })).toBeNull();
  })
  it('mints exactly one command ID for settings, secret and account commands, reaching only the named method', async () => {
    const change = { expected_revision: 'rev', changes: [{ path: 'models.main', value: 'fixture' }] };
    const entries = [[IPC.settingsSet, 'settings.set', change],
      ...Object.entries(SETTINGS_SHAPED).map(([method, { channel }]) => [channel, method, change]),
      [IPC.imageModelIntent, 'models.image.intent', { expected_revision: 'rev', operations: { image_model: 'follow' } }],
      [IPC.secretsSet, 'secrets.set', { path: 'fixture.key', value: 'synthetic-test-value' }],
      [IPC.secretsClear, 'secrets.clear', { path: 'fixture.key' }], [IPC.secretsUnlock, 'secrets.unlock', {}],
      [IPC.editLeaf, 'models.main.set', { method: 'models.main.set', params: { expected_revision: 'rev', model: 'fixture' } }],
      [IPC.codexActivate, 'codex.accounts.activate', { index: 1 }], [IPC.codexLabel, 'codex.accounts.label', { index: 1, label: 'Fixture' }],
      [IPC.codexRemove, 'codex.accounts.remove', { index: 1 }]] as any[];
    for (const [channel, method, payload] of entries) {
      deps.broker.request.mockClear(); expect(await call(channel, payload)).toEqual(ok({ marker: 'core result' }));
      expect(deps.broker.request).toHaveBeenCalledExactlyOnceWith(method, channel === IPC.editLeaf ? payload.params : payload, expect.stringMatching(/^[a-f0-9-]{36}$/));
    }
    await call(IPC.settingsSchema); expect(deps.broker.request).toHaveBeenLastCalledWith('settings.schema');
    await call(IPC.codexAccounts); expect(deps.broker.request).toHaveBeenLastCalledWith('codex.accounts.list');
  })
  it('holds device authorization in main while opening only its recognized verification URL', async () => {
    expect(await call(IPC.codexOpenVerification)).toMatchObject({ ok: false }); expect(deps.openVerification).not.toHaveBeenCalled();
    deps.broker.request.mockResolvedValueOnce(ok({ device_auth_id: 'synthetic-private-device', user_code: 'TEST-CODE', interval: 1, expires_in: 60, verify_url: CODEX_VERIFICATION_URL }));
    const begun = await call(IPC.codexLoginBegin); expect(begun).toMatchObject({ ok: true, result: { user_code: 'TEST-CODE' } });
    expect(JSON.stringify(begun)).not.toContain('synthetic-private-device');
    expect(await call(IPC.codexOpenVerification)).toEqual(ok({ opened: true })); expect(deps.openVerification).toHaveBeenCalledWith(CODEX_VERIFICATION_URL);
    deps.broker.request.mockResolvedValueOnce(ok({ status: 'pending', private: 'not exposed' }));
    expect(await call(IPC.codexLoginPoll, { login_id: begun.result.login_id })).toEqual(ok({ status: 'pending' }));
    expect(deps.broker.request).toHaveBeenLastCalledWith('codex.login.poll', { device_auth_id: 'synthetic-private-device', user_code: 'TEST-CODE' }, expect.any(String));
    deps.broker.request.mockResolvedValueOnce(failed); expect(await call(IPC.codexLoginPoll, { login_id: begun.result.login_id })).toEqual(failed);
    expect(await call(IPC.codexLoginPoll, { login_id: id })).toMatchObject({ ok: false });
    deps.broker.request.mockResolvedValueOnce(failed); expect(await call(IPC.codexLoginBegin)).toEqual(failed);
  })
  it('projects status readiness without extra private fields and rejects malformed projections', async () => {
    const first_run = { state: 'fresh', reason: 'provider_not_configured', keyring_unavailable: false };
    const webhook_ingress = { reason: 'closed', address: null, eligible_schedules: 0, unknown_deliveries: 0 };
    deps.broker.request.mockResolvedValueOnce(ok({ first_run: { ...first_run, secret: 'private' }, webhook_ingress: { ...webhook_ingress, secret: 'private' }, version: 'fixture' }));
    expect(await call(IPC.status)).toEqual(ok({ first_run, webhook_ingress, version: 'fixture' }));
    for (const result of [null, 'bad', { first_run: { state: 'impossible' } }, { webhook_ingress: { reason: 'impossible' } }]) {
      deps.broker.request.mockResolvedValueOnce(ok(result)); expect(await call(IPC.status)).toMatchObject({ ok: false, error: { code: 'internal' } });
    }
    deps.broker.request.mockResolvedValueOnce(failed); expect(await call(IPC.status)).toEqual(failed);
  })
})
