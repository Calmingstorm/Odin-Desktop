import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigMeta, OutboundWebhookStatus, OutboundWebhookTarget, Result } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'
const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const fail = (code: string, extra = {}): Result<never> => ({ ok: false, error: { code, message: 'Not confirmed.', ...extra } })
const target = (): OutboundWebhookTarget => ({ id: 'target1', name: 'Operations', url: 'https://user:[REDACTED]@example.com/events', has_secret: true, events: ['health'], enabled: true, scrub_secrets: true, verify_ssl: true, created_at: '' })
const status = (): OutboundWebhookStatus => ({ webhook_count: 1, enabled_count: 1, scrub_secrets: true, rate_limit_seconds: 2, webhooks: [target()], stats: {} })
let view: Mounted | undefined
type TestDraft = { url: string; secret: string; name: string; secretIntent: string; urlIntent: string; enabled: boolean; events: string[]; tls: boolean; scrub: boolean }
type OutboundMounted = Omit<Mounted, 'setup'> & { setup: Record<string, unknown> & { draft: TestDraft } }
let bridge: Record<'settingsSchema' | 'outboundWebhooksList' | 'outboundWebhooksSave' | 'outboundWebhooksDelete' | 'outboundWebhooksTest', ReturnType<typeof vi.fn>>
beforeEach(() => {
  vi.resetModules()
  bridge = {
    settingsSchema: vi.fn(async () => ok({ revision: 'rev1', fields: [] } as unknown as ConfigMeta)),
    outboundWebhooksList: vi.fn(async () => ok(status())), outboundWebhooksSave: vi.fn(async () => ok(target())),
    outboundWebhooksDelete: vi.fn(async () => ok({ status: 'deleted', webhook_id: 'target1' })),
    outboundWebhooksTest: vi.fn(async () => ok({ webhook_id: 'target1', webhook_name: 'Operations', event_type: 'custom', status_code: 204, success: true, attempt: 1, latency_ms: 12, timestamp: '' }))
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
})
afterEach(() => { view?.unmount(); view = undefined })
async function open(): Promise<OutboundMounted> { view = mount((await import('../../src/renderer/src/components/OutboundWebhooks.vue')).default); await flush(); return view as OutboundMounted }
async function invoke(v: Mounted, name: string, ...args: unknown[]): Promise<void> { await (v.setup[name] as (...args: unknown[]) => Promise<void>)(...args); await flush() }
async function answer(yes = true): Promise<void> { const { dialog } = await import('../../src/renderer/src/dialog'); expect(dialog.current).not.toBeNull(); dialog.current!.resolve(yes ? true : null); await flush() }
describe('outbound webhook owner workflow', () => {
  it('masks userinfo, query and fragment; keep never submits a display-redacted URL', async () => {
    const row = { ...target(), url: 'https://user:[REDACTED]@example.com/events?token=synthetic-query#synthetic-fragment' }
    bridge.outboundWebhooksList.mockResolvedValue(ok({ ...status(), webhooks: [row] }))
    const v = await open()
    expect(v.root.textContent()).toContain('https://example.com/events')
    expect(v.root.textContent()).toContain('Private endpoint configured (write-only)')
    expect(v.root.textContent()).not.toContain('synthetic-query')
    expect(v.root.textContent()).not.toContain('synthetic-fragment')
    await invoke(v, 'edit', row); await invoke(v, 'save')
    expect(bridge.outboundWebhooksSave.mock.calls[0]![0]).not.toHaveProperty('url')
  })
  it('query-only endpoints are private and explicit removal strips all private URL parts', async () => {
    const row = { ...target(), url: 'https://example.com/events?token=synthetic-query#synthetic-fragment' }
    bridge.outboundWebhooksList.mockResolvedValue(ok({ ...status(), webhooks: [row] }))
    const v = await open(); expect(v.root.textContent()).toContain('Private endpoint configured (write-only)')
    await invoke(v, 'edit', row); v.setup.draft.urlIntent = 'remove'; await flush()
    const pending = invoke(v, 'save'); await flush(); await answer(); await pending
    expect(bridge.outboundWebhooksSave).toHaveBeenCalledWith(expect.objectContaining({ url: 'https://example.com/events' }))
  })
  it('uses native Add/Edit dialog and row/switch semantics', async () => {
    const v = await open(); await invoke(v, 'edit')
    expect(v.root.findAll(n => n.tag === 'dialog' && n.props['aria-label'] === 'Add outbound target')).toHaveLength(1)
    await invoke(v, 'cancel'); await invoke(v, 'edit', target())
    expect(v.root.findAll(n => n.tag === 'dialog' && n.props['aria-label'] === 'Edit outbound target')).toHaveLength(1)
    expect(v.root.findAll(n => n.props.role === 'switch')).toHaveLength(3)
  })
  it('locks all actions during confirmation, preserves cancelled drafts and rejects programmatic mutation', async () => {
    const v = await open(); await invoke(v, 'edit', target()); v.setup.draft.tls = false; v.setup.draft.urlIntent = 'replace'; await flush()
    v.setup.draft.url = 'https://example.com/private?token=unsent'
    let pending = invoke(v, 'save'); await flush()
    expect(v.setup.locked).toBe(true)
    expect(v.root.findAll(n => n.tag === 'fieldset' && n.props.disabled === true).length).toBeGreaterThan(0)
    const originalDraft = v.setup.draft
    await invoke(v, 'cancel'); await invoke(v, 'edit'); await invoke(v, 'refresh'); await invoke(v, 'save')
    expect(v.setup.draft).toBe(originalDraft); expect(v.setup.draft.url).toContain('unsent')
    await answer(false); await pending; expect(v.setup.draft.url).toContain('unsent')
    pending = invoke(v, 'save'); await flush(); v.setup.draft.url = 'https://example.com/newer?token=not-submitted'
    await answer(); await pending
    expect(bridge.outboundWebhooksSave).not.toHaveBeenCalled()
    expect(v.setup.draft.url).toContain('not-submitted')
    expect(v.root.textContent()).toContain('Draft changed during confirmation')
  })
  it('refuses external test when local or fresh owner metadata revision changes', async () => {
    const v = await open(); const { settings } = await import('../../src/renderer/src/stores/settings')
    let pending = invoke(v, 'test', target()); await flush(); settings.meta!.revision = 'newer'; await answer(); await pending
    expect(bridge.outboundWebhooksTest).not.toHaveBeenCalled()
    await invoke(v, 'refresh')
    pending = invoke(v, 'test', target()); await flush(); bridge.settingsSchema.mockResolvedValue(ok({ revision: 'external-newer', fields: [] })); await answer(); await pending
    expect(bridge.outboundWebhooksTest).not.toHaveBeenCalled()
  })
  it('external test binds expected revision and unknown receipt never replays', async () => {
    const v = await open(); bridge.outboundWebhooksTest.mockResolvedValue(fail('no_receipt', { command_id: 'unknown-test' }))
    const pending = invoke(v, 'test', target()); await flush(); await answer(); await pending
    expect(bridge.outboundWebhooksTest).toHaveBeenCalledWith({ id: 'target1', expected_revision: 'rev1' })
    await invoke(v, 'test', target()); await invoke(v, 'refresh')
    expect(bridge.outboundWebhooksTest).toHaveBeenCalledTimes(1)
  })
  it('shows target facts without credential readback or unsupported global controls', async () => {
    const v = await open(); expect(v.root.textContent()).toContain('Private endpoint configured (write-only)')
    expect(v.root.textContent()).toContain('https://example.com/events'); expect(v.root.textContent()).not.toContain('[REDACTED]'); expect(v.root.textContent()).not.toContain('user:')
    expect(v.root.textContent()).not.toContain('Rate limit:')
    await invoke(v, 'edit', target()); expect(v.setup.draft.url).toBe(''); expect(v.setup.draft.secret).toBe('')
    expect(v.root.findAll(n => n.props['data-testid'] === 'outbound-url')).toHaveLength(0)
  })
  it('Cancel writes nothing and credential-intent changes erase drafts', async () => {
    const v = await open(); await invoke(v, 'edit', target()); v.setup.draft.secretIntent = 'replace'; v.setup.draft.urlIntent = 'replace'; await flush()
    v.setup.draft.secret = 'local-signing-key'; v.setup.draft.url = 'https://other:private@example.com'
    v.setup.draft.secretIntent = 'keep'; v.setup.draft.urlIntent = 'keep'; await flush()
    expect(v.setup.draft.secret).toBe(''); expect(v.setup.draft.url).toBe(''); await invoke(v, 'cancel')
    expect(v.setup.draft).toBeNull(); expect(bridge.outboundWebhooksSave).not.toHaveBeenCalled()
  })
  it('keep sends no credential values, with explicit per-target enablement and filters', async () => {
    const v = await open(); await invoke(v, 'edit', target()); v.setup.draft.enabled = false; v.setup.draft.events = ['alert', 'schedule']; await invoke(v, 'save')
    expect(bridge.outboundWebhooksSave).toHaveBeenCalledWith({ id: 'target1', expected_revision: 'rev1', name: 'Operations', events: ['alert', 'schedule'], enabled: false, scrub_secrets: true, verify_ssl: true }); expect(v.setup.draft).toBeNull()
  })
  it('new target uses owner credential transaction, clearing submitted values and preventing duplicate save', async () => {
    const v = await open(); await invoke(v, 'edit'); v.setup.draft.url = 'https://u:p@example.com/new'; v.setup.draft.name = 'New'; v.setup.draft.secretIntent = 'replace'; await flush(); v.setup.draft.secret = 'new-signing-key'
    let land!: (result: unknown) => void; bridge.outboundWebhooksSave.mockImplementation(() => new Promise(resolve => { land = resolve }))
    const pending = invoke(v, 'save'); await flush(); expect(v.setup.draft.secret).toBe(''); expect(v.setup.draft.url).toBe('')
    expect(bridge.outboundWebhooksSave).toHaveBeenCalledWith(expect.objectContaining({ url: 'https://u:p@example.com/new', secret: 'new-signing-key', expected_revision: 'rev1' }))
    await invoke(v, 'save'); expect(bridge.outboundWebhooksSave).toHaveBeenCalledTimes(1); land(ok(target())); await pending
  })
  it('remove private credentials sends public URL and remove key sends explicit empty string', async () => {
    const v = await open(); await invoke(v, 'edit', target()); v.setup.draft.urlIntent = 'remove'; v.setup.draft.secretIntent = 'remove'; await flush()
    let pending = invoke(v, 'save'); await flush(); await answer(false); await pending; expect(bridge.outboundWebhooksSave).not.toHaveBeenCalled()
    pending = invoke(v, 'save'); await flush(); await answer(); await pending
    expect(bridge.outboundWebhooksSave).toHaveBeenCalledWith(expect.objectContaining({ url: 'https://example.com/events', secret: '' }))
  })
  it('masked URL is never used as replacement and absent URL fails validation', async () => {
    const v = await open(); await invoke(v, 'edit'); await invoke(v, 'save'); expect(bridge.outboundWebhooksSave).not.toHaveBeenCalled()
    v.setup.draft.url = target().url; await invoke(v, 'save'); expect(bridge.outboundWebhooksSave).not.toHaveBeenCalled(); expect(v.root.textContent()).toContain('Masked URLs cannot be saved')
  })
  it('TLS and scrubbing weakening need separate confirmation and cancellation writes nothing', async () => {
    const v = await open(); await invoke(v, 'edit', target()); v.setup.draft.tls = false
    let pending = invoke(v, 'save'); await flush(); await answer(false); await pending; expect(bridge.outboundWebhooksSave).not.toHaveBeenCalled()
    v.setup.draft.scrub = false; pending = invoke(v, 'save'); await flush(); await answer(); await answer(); await pending
    expect(bridge.outboundWebhooksSave).toHaveBeenCalledWith(expect.objectContaining({ verify_ssl: false, scrub_secrets: false }))
  })
  it('local revision conflict and owner stale refusal never rebase or replay', async () => {
    const v = await open(); await invoke(v, 'edit', target()); const { settings } = await import('../../src/renderer/src/stores/settings'); settings.meta!.revision = 'newer'
    await invoke(v, 'save'); expect(bridge.outboundWebhooksSave).not.toHaveBeenCalled(); expect(v.root.textContent()).toContain('Save not confirmed')
    await invoke(v, 'refresh'); await invoke(v, 'edit', target()); bridge.outboundWebhooksSave.mockResolvedValue(fail('stale_binding')); await invoke(v, 'save'); await invoke(v, 'save'); expect(bridge.outboundWebhooksSave).toHaveBeenCalledTimes(1)
  })
  it('unknown outcome fences all targets through shared act and settings queue', async () => {
    const v = await open(); await invoke(v, 'edit', target()); bridge.outboundWebhooksSave.mockResolvedValue(fail('no_receipt', { command_id: 'pending-command' }))
    await invoke(v, 'save'); await invoke(v, 'save'); await invoke(v, 'remove', target()); await invoke(v, 'refresh')
    expect(bridge.outboundWebhooksSave).toHaveBeenCalledTimes(1); expect(bridge.outboundWebhooksDelete).not.toHaveBeenCalled()
    const { management } = await import('../../src/renderer/src/stores/management'); expect(management.busy['outbound-webhooks']).toBe(true); expect(v.root.textContent()).toContain("It's never sent twice")
  })
  it('delete and external test are confirmed commands; test reports measured delivery', async () => {
    const v = await open(); let pending = invoke(v, 'remove', target()); await flush(); await answer(false); await pending; expect(bridge.outboundWebhooksDelete).not.toHaveBeenCalled()
    pending = invoke(v, 'test', target()); await flush(); expect(bridge.outboundWebhooksTest).not.toHaveBeenCalled(); await answer(); await pending; expect(v.root.textContent()).toContain('Test delivered: HTTP 204, 12 ms, attempt 1')
    pending = invoke(v, 'remove', target()); await flush(); await answer(); await pending; expect(bridge.outboundWebhooksDelete).toHaveBeenCalledWith({ id: 'target1', expected_revision: 'rev1' })
  })
  it('late save receipt reloads targets without replay or implicit unknown-settings reset', async () => {
    const v = await open(); await invoke(v, 'edit', target()); bridge.outboundWebhooksSave.mockResolvedValue(fail('no_receipt', { command_id: 'late-save' }))
    await invoke(v, 'save'); const reads = bridge.outboundWebhooksList.mock.calls.length
    const { applyReceipt } = await import('../../src/renderer/src/store'); applyReceipt({ id: 'late-save', settled: ok(target()) }); await flush()
    expect(bridge.outboundWebhooksList.mock.calls.length).toBeGreaterThan(reads)
    expect(v.setup.draft).toBeNull(); expect(bridge.outboundWebhooksSave).toHaveBeenCalledTimes(1)
    const { settings } = await import('../../src/renderer/src/stores/settings'); expect(settings.unknownSave).toBe(true)
    await invoke(v, 'refresh'); expect(settings.unknownSave).toBe(false)
  })
  it('null delivery receipt is not reported as successful delivery', async () => {
    const v = await open(); bridge.outboundWebhooksTest.mockResolvedValue(ok(null))
    const pending = invoke(v, 'test', target()); await flush(); await answer(); await pending
    expect(v.root.textContent()).toContain('did not report a measured delivery'); expect(v.root.textContent()).not.toContain('Test delivered:')
  })
  it('read refusal removes stale targets, locks actions, and explicit refresh recovers', async () => {
    const v = await open(); bridge.outboundWebhooksList.mockResolvedValue(fail('unavailable')); await invoke(v, 'refresh')
    expect(v.setup.snapshot).toBeNull(); expect(v.root.textContent()).not.toContain('Operations'); await invoke(v, 'edit'); expect(v.setup.draft).toBeNull()
    bridge.outboundWebhooksList.mockResolvedValue(ok(status())); await invoke(v, 'refresh'); await invoke(v, 'edit'); expect(v.setup.draft).not.toBeNull()
  })
  it('core replacement invalidates observations before late save can report success', async () => {
    const v = await open(); await invoke(v, 'edit', target()); let land!: (result: unknown) => void; bridge.outboundWebhooksSave.mockImplementation(() => new Promise(resolve => { land = resolve }))
    const pending = invoke(v, 'save'); await flush(); const { state } = await import('../../src/renderer/src/store'); state.recoveryEpoch += 1; await flush(); land(ok(target())); await pending
    expect(v.setup.snapshot).toBeNull(); expect(v.setup.stale).toBe(true); expect(v.setup.draft).not.toBeNull(); expect(v.root.textContent()).not.toContain('Target saved.')
  })
})
