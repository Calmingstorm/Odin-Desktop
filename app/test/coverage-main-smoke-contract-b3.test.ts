import { afterEach, describe, expect, it, vi } from 'vitest'
import { assertFreshManagementStatus, configureCannedProvider, realCoreCapabilities, realCoreSmoke } from '../src/main/real-core-smoke'

vi.mock('electron', () => ({ dialog: {} }))
afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks() })
describe('real-core smoke safety and provider configuration contracts', () => {
  it('requires exact fresh-profile capabilities, readiness, limits and opt-in ingress', () => {
    const status: any = { phase: 'ready', capabilities: [...realCoreCapabilities], model: { main: 'gpt-6.1-sol', effort: null, provider: 'codex' },
      providers: [{ name: 'codex', health: 'unavailable' }, { name: 'ollama', health: 'disabled' }, { name: 'compat', health: 'disabled' }],
      limits: { chunk_bytes: 512 * 1024, attachment_bytes: 50 * 1024 * 1024, attachments_per_turn: 10 }, summary: 'Codex: unavailable',
      first_run: { state: 'degraded', reason: 'keyring_unavailable', keyring_unavailable: true },
      webhook_ingress: { reason: 'disabled', address: null, eligible_schedules: 0, unknown_deliveries: 0 } };
    expect(() => assertFreshManagementStatus(status)).not.toThrow();
    expect(() => assertFreshManagementStatus({ ...status, first_run: { state: 'fresh', reason: 'provider_not_configured', keyring_unavailable: false } }, true)).not.toThrow();
    expect(() => assertFreshManagementStatus({ ...status, capabilities: ['status.get'] })).toThrow();
    expect(() => assertFreshManagementStatus({ ...status, webhook_ingress: { ...status.webhook_ingress, reason: 'accepting', address: ['127.0.0.1', 9999] } })).toThrow();
    expect(() => assertFreshManagementStatus({ ...status, first_run: { state: 'effective-ready', reason: 'provider_effective', keyring_unavailable: false } })).toThrow();
  })
  it('configures only a loopback canned peer with fresh settings revisions, secret isolation and verified serving identity', async () => {
    let revision = 0;
    const broker: any = { request: vi.fn(async (method: string) => {
      if (method === 'settings.schema') return { ok: true, result: { revision: `rev${++revision}` } };
      if (method === 'status.get') return { ok: true, result: { model: { main: 'canned-contract', effort: null, provider: 'compat' } } };
      return { ok: true, result: {} };
    }) };
    await configureCannedProvider(broker, 'http://127.0.0.1:41234');
    const calls = broker.request.mock.calls;
    expect(calls.filter(([method]: string[]) => method === 'settings.schema')).toHaveLength(6);
    expect(calls).toEqual([
      ['settings.schema', undefined], ['providers.compat.set', { expected_revision: 'rev1', changes: [{ path: 'openai_compatible.enabled', value: false }] }],
      ['settings.schema', undefined], ['providers.codex.set', { expected_revision: 'rev2', changes: [{ path: 'openai_codex.enabled', value: false }] }],
      ['settings.schema', undefined], ['providers.auxiliary.set', { expected_revision: 'rev3', changes: [{ path: 'openai_codex.auxiliary.enabled', value: false }] }],
      ['settings.schema', undefined], ['providers.compat.set', { expected_revision: 'rev4', changes: [
        { path: 'openai_compatible.base_url', value: 'http://127.0.0.1:41234' }, { path: 'openai_compatible.model', value: 'canned-contract' },
        { path: 'openai_compatible.preset', value: 'custom' }, { path: 'openai_compatible.reasoning_dialect', value: 'none' },
        { path: 'openai_compatible.reasoning_effort', value: 'none' }, { path: 'openai_compatible.max_tokens', value: 4096 }
      ] }], ['secrets.set', { path: 'openai_compatible.api_key', value: 'canned-local-test-only' }],
      ['settings.schema', undefined], ['providers.compat.set', { expected_revision: 'rev5', changes: [{ path: 'openai_compatible.enabled', value: true }] }],
      ['settings.schema', undefined], ['models.main.set', { model: 'compat:canned-contract', expected_revision: 'rev6' }], ['status.get', undefined]
    ]);
    for (const invalid of ['https://127.0.0.1:41234', 'http://example.test:41234', 'http://127.0.0.1', 'http://user:pass@127.0.0.1:41234']) {
      broker.request.mockClear(); await expect(configureCannedProvider(broker, invalid)).rejects.toThrow(); expect(broker.request).not.toHaveBeenCalled();
    }
    broker.request.mockResolvedValueOnce({ ok: false, error: { code: 'fixture_failure' } });
    await expect(configureCannedProvider(broker, 'http://127.0.0.1:41234')).rejects.toThrow('settings.schema failed');
  })
  it('refuses real-core smoke outside disposable ownership before any renderer/core request', async () => {
    const win: any = { webContents: { executeJavaScript: vi.fn() } }; const broker: any = { request: vi.fn() };
    vi.stubEnv('ODIN_REAL_CORE_ROOT', '/not/disposable'); vi.stubEnv('HOME', '/not/disposable');
    await expect(realCoreSmoke(win, broker, '/mock/out.png')).rejects.toThrow('smoke requires disposable HOME');
    vi.stubEnv('ODIN_REAL_CORE_ROOT', '/tmp/odrc-mock'); vi.stubEnv('HOME', '/tmp/odrc-mock');
    vi.spyOn(process, 'getuid').mockReturnValue(0);
    await expect(realCoreSmoke(win, broker, '/mock/out.png')).rejects.toThrow('smoke must not run as root');
    vi.spyOn(process, 'getuid').mockReturnValue(1001); vi.stubEnv('ODIN_REAL_CORE_OUTER_PID_NS', '');
    await expect(realCoreSmoke(win, broker, '/mock/out.png')).rejects.toThrow('smoke requires the isolated PID namespace runner');
    expect(win.webContents.executeJavaScript).not.toHaveBeenCalled(); expect(broker.request).not.toHaveBeenCalled();
  })
})
