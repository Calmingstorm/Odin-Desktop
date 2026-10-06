// Compiled Vue object bindings. Native focus/keyboard/axe are a separate Electron gate.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigMeta, CoreStatus, Result, ScheduleRow } from '../../src/shared/api'
import { flush, mount, type Host, type Mounted } from './component-host'
const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const fail = (code = 'unavailable'): Result<never> => ({ ok: false, error: { code, message: 'Read or write not confirmed.' } })
const triggerRow = (source?: 'generic' | 'github' | 'gitea' | 'gitlab'): ScheduleRow => ({ id: 's1', description: 'Delivery', action: 'reminder', channel_id: 'c1', paused: false, created_at: '', trigger: { ...(source ? { source } : {}), event: 'deploy' } })
function metadata(enabled = false): ConfigMeta {
  return { revision: 'rev1', fields: [
    { path: 'webhook.enabled', desired: enabled }, { path: 'webhook.bind_address', desired: '127.0.0.1' },
    { path: 'webhook.port', desired: 0 }, { path: 'webhook.triggers.s1.source', desired: 'generic' },
    { path: 'webhook.triggers.s1.secret', configured: true, desired: 'never-fill-this', effective: 'never-fill-this' }
  ] } as ConfigMeta
}
function core(reason = 'no_eligible_schedule'): CoreStatus {
  return { webhook_ingress: { reason, address: reason === 'accepting' ? ['127.0.0.1', 45678] : null, eligible_schedules: reason === 'accepting' ? 1 : 0, unknown_deliveries: 2 } } as CoreStatus
}
let view: Mounted | undefined
let bridge: Record<'settingsSchema' | 'status' | 'settingsSet' | 'secretsSet' | 'secretsClear', ReturnType<typeof vi.fn>>
beforeEach(() => {
  vi.resetModules()
  bridge = {
    settingsSchema: vi.fn(async () => ok(metadata())), status: vi.fn(async () => ok(core())),
    settingsSet: vi.fn(async () => ok({ revision: 'rev2', fields: [] })),
    secretsSet: vi.fn(async () => ok({ set: true })), secretsClear: vi.fn(async () => ok({ set: false }))
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
})
afterEach(() => { view?.unmount(); view = undefined })
async function open(row = triggerRow()): Promise<Mounted> {
  const { schedules } = await import('../../src/renderer/src/stores/schedules')
  schedules.list = [row]
  const component = (await import('../../src/renderer/src/components/WebhookIngress.vue')).default
  view = mount(component); await flush()
  view.setup.selected = row.id; await flush()
  return view
}
const control = (v: Mounted, id: string): Host => {
  const matches = v.root.findAll((node) => node.props['data-testid'] === id)
  expect(matches).toHaveLength(1)
  return matches[0]!
}
const call = (v: Mounted, name: string): Promise<void> => (v.setup[name] as () => Promise<void>)()

describe('inbound listener observed state and write-only setup', () => {
  it('enabled is not accepting; displays measurements, never a secret readback or fake endpoint', async () => {
    bridge.settingsSchema.mockResolvedValue(ok(metadata(true)))
    const v = await open()
    expect(v.root.textContent()).toContain('Off: no eligible schedule')
    expect(v.root.textContent()).toContain('Unknown deliveries: 2')
    expect(v.root.textContent()).not.toContain('Delivery URL:')
    expect(control(v, 'webhook-ingress-enabled').checked).toBe(true)
    expect(control(v, 'webhook-ingress-secret').value).toBe('')
    expect(v.root.textContent()).not.toContain('never-fill-this')
  })
  it('shows the measured accepting address and schedule-scoped IPv6 route', async () => {
    bridge.status.mockResolvedValue(ok({ ...core('accepting'), webhook_ingress: { ...core('accepting').webhook_ingress!, address: ['fd00::1', 4242, 0, 0] } } as CoreStatus))
    const v = await open()
    expect(control(v, 'webhook-ingress-status').textContent()).toContain('Accepting deliveries')
    expect(control(v, 'webhook-ingress-endpoint').textContent()).toContain('http://[fd00::1]:4242/webhook/generic/s1')
  })
  it('shows absent status and unreachable settings honestly', async () => {
    bridge.status.mockResolvedValue(ok({} as CoreStatus))
    const v = await open()
    expect(v.root.textContent()).toContain('Webhook ingress status unavailable')
    bridge.settingsSchema.mockResolvedValue(fail())
    await call(v, 'refresh'); await flush()
    expect(v.root.textContent()).toContain('Webhook settings unavailable')
    expect(v.root.findAll((n) => n.tag === 'input')).toHaveLength(0)
  })
  it.each(['paused', 'inert', 'mismatched'] as const)('listener accepting is not selected %s schedule eligibility', async (condition) => {
    bridge.status.mockResolvedValue(ok(core('accepting')))
    const item = triggerRow(condition === 'mismatched' ? 'github' : undefined)
    if (condition === 'paused') item.paused = true
    if (condition === 'inert') item.inert_reason = 'Elapsed'
    const v = await open(item)
    expect(control(v, 'webhook-ingress-selected-status').textContent()).toContain('cannot receive deliveries')
    expect(control(v, 'webhook-ingress-endpoint').textContent()).toContain('not selected-schedule eligibility proof')
  })
  it.each([
    ['generic', 'X-Webhook-Secret'], ['github', 'X-Hub-Signature-256'], ['gitea', 'X-Gitea-Signature']
  ])('shows actual %s authentication without echoing a secret', async (source, header) => {
    const data = metadata()
    data.fields.find((f) => f.path === 'webhook.triggers.s1.source')!.desired = source
    bridge.settingsSchema.mockResolvedValue(ok(data))
    const v = await open()
    expect(v.root.textContent()).toContain(header)
    if (source !== 'generic') expect(v.root.textContent()).toContain('HMAC SHA256 hex digest of the raw request body')
    expect(v.root.textContent()).not.toContain('never-fill-this')
  })
  it('explicit refresh warns before resetting unsaved listener/source/secret drafts', async () => {
    const v = await open()
    v.setup.enabled = true; v.setup.bind = '192.168.1.2'; v.setup.port = '8082'; v.setup.source = 'github'; v.setup.secret = 'draft'
    expect(v.root.textContent()).toContain('Refresh replaces unsaved listener and source drafts')
    await call(v, 'refresh'); await flush()
    expect(v.setup.enabled).toBe(false); expect(v.setup.bind).toBe('127.0.0.1'); expect(v.setup.port).toBe('0')
    expect(v.setup.source).toBe('generic'); expect(v.setup.secret).toBe('')
    expect(v.root.textContent()).toContain('Refreshing replaces unsaved listener and source drafts')
    expect(bridge.settingsSet).not.toHaveBeenCalled()
  })
  it('reports real keyring-unavailable metadata as unknown secret presence', async () => {
    const data = metadata()
    data.status = { counts: {}, desired_revision: 'rev1', effective_revision: null, keyring_error: 'keyring_unavailable' }
    data.fields.find((f) => f.path === 'webhook.triggers.s1.secret')!.configured = null
    bridge.settingsSchema.mockResolvedValue(ok(data))
    const v = await open()
    expect(v.root.textContent()).toContain('Keyring error: keyring_unavailable')
    expect(v.root.textContent()).toContain('Secret: Not reported')
  })
  it.each(['127.0.0.1', '169.254.2.3', '192.168.1.3', '100.70.1.2', 'fe80::1', 'fd00::1'])('leaves address validation to core for %s', async (address) => {
    const v = await open()
    v.setup.bind = address; v.setup.port = '0'; v.setup.enabled = true
    await call(v, 'saveListener')
    expect(bridge.settingsSet).toHaveBeenCalledWith({ expected_revision: 'rev1', changes: [
      { path: 'webhook.enabled', value: true }, { path: 'webhook.bind_address', value: address }, { path: 'webhook.port', value: 0 }
    ] })
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })
  it('saves source first then exact secret path, clears pending draft and prevents duplicates', async () => {
    let land!: (result: unknown) => void
    bridge.settingsSet.mockImplementation(() => new Promise((resolve) => { land = resolve }))
    const v = await open()
    control(v, 'webhook-ingress-secret').type('new-secret'); v.setup.source = 'github'
    const pending = call(v, 'saveTrigger'); await flush()
    expect(control(v, 'webhook-ingress-secret').value).toBe('')
    expect(bridge.settingsSet).toHaveBeenCalledWith({ expected_revision: 'rev1', changes: [{ path: 'webhook.triggers.s1.source', value: 'github' }] })
    expect(bridge.secretsSet).not.toHaveBeenCalled()
    await call(v, 'saveTrigger')
    expect(bridge.settingsSet).toHaveBeenCalledTimes(1)
    expect(v.root.button('Save trigger source and secret').props.disabled).toBe(true)
    land(ok({ revision: 'rev2', fields: [] })); await pending; await flush()
    expect(bridge.secretsSet).toHaveBeenCalledWith({ path: 'webhook.triggers.s1.secret', value: 'new-secret' })
    expect(v.setup.secret).toBe('')
    expect(v.root.textContent()).toContain('Source and secret saved')
  })
  it('source stale refusal discards draft and never sends a secret or auto-retries', async () => {
    bridge.settingsSet.mockResolvedValue(fail('stale_binding'))
    const v = await open(); v.setup.secret = 'new-secret'
    await call(v, 'saveTrigger'); await flush()
    expect(bridge.secretsSet).not.toHaveBeenCalled()
    expect(v.setup.secret).toBe('')
    expect(v.root.textContent()).toContain('Settings changed elsewhere')
    await call(v, 'saveTrigger'); expect(bridge.settingsSet).toHaveBeenCalledTimes(1)
    await call(v, 'refresh'); expect(v.setup.stale).toBe(false)
  })
  it('reports partial setup and previous secret uncertainty without leaking failure detail', async () => {
    bridge.secretsSet.mockRejectedValue(new Error('new-secret'))
    const v = await open(); v.setup.secret = 'new-secret'
    await call(v, 'saveTrigger'); await flush()
    expect(v.root.textContent()).toContain('Partial setup: source saved')
    expect(v.root.textContent()).toContain('previous secret')
    expect(v.root.textContent()).not.toContain('new-secret')
    expect(v.setup.secret).toBe('')
  })
  it('clears only selected secret with no settings rewrite or confirmation', async () => {
    const v = await open(); v.setup.secret = 'discard-draft'
    await call(v, 'clearTriggerSecret'); await flush()
    expect(bridge.secretsClear).toHaveBeenCalledWith({ path: 'webhook.triggers.s1.secret' })
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    expect(v.setup.secret).toBe('')
    expect(v.root.textContent()).toContain('Per-trigger secret cleared')
  })
  it('does not claim clearing succeeded after unavailable result', async () => {
    bridge.secretsClear.mockResolvedValue(fail())
    const v = await open(); await call(v, 'clearTriggerSecret'); await flush()
    expect(v.root.textContent()).toContain('Secret clearing was not confirmed')
  })
  it('clears drafts on selection/unmount and stops second stage after unmount', async () => {
    let land!: (result: unknown) => void
    bridge.settingsSet.mockImplementation(() => new Promise((resolve) => { land = resolve }))
    const v = await open(); v.setup.secret = 'draft'
    v.setup.selected = ''; expect(v.setup.secret).toBe('')
    v.setup.selected = 's1'; v.setup.secret = 'submitted'
    const pending = call(v, 'saveTrigger')
    v.unmount(); expect(v.setup.secret).toBe('')
    land(ok({ revision: 'rev2', fields: [] })); await pending
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })
  it('rejects older refresh and invalidates acceptance/drafts on core identity change', async () => {
    const v = await open()
    let land!: (result: unknown) => void
    bridge.status.mockImplementationOnce(() => new Promise((resolve) => { land = resolve }))
    const old = call(v, 'refresh')
    bridge.status.mockResolvedValue(ok(core('disabled'))); await call(v, 'refresh')
    land(ok(core('accepting'))); await old; await flush()
    expect(v.root.textContent()).toContain('Disabled')
    expect(v.root.textContent()).not.toContain('Accepting deliveries')
    v.setup.secret = 'draft'
    const { state } = await import('../../src/renderer/src/store')
    state.recoveryEpoch += 1; await flush()
    expect(v.setup.secret).toBe(''); expect(v.setup.stale).toBe(true)
    expect(v.root.textContent()).toContain('Webhook ingress status unavailable')
  })
  it('labels GitLab ingress unavailable without rejecting scheduler matching', async () => {
    const v = await open(triggerRow('gitlab'))
    expect(v.root.textContent()).toContain('GitLab scheduler matching is supported')
    expect(v.root.findAll((n) => n.props['data-testid'] === 'webhook-ingress-secret')).toHaveLength(0)
    v.setup.secret = 'draft'; await call(v, 'saveTrigger')
    expect(bridge.settingsSet).not.toHaveBeenCalled()
  })
  it('exposes wrapping labels, write-only hint, status, fieldset and busy bindings', async () => {
    const v = await open()
    for (const node of v.root.findAll((n) => ['input', 'select'].includes(n.tag))) {
      let label = node.parent
      while (label && label.tag !== 'label') label = label.parent
      expect(label?.textContent().trim()).toBeTruthy()
    }
    const password = control(v, 'webhook-ingress-secret')
    expect(password.props.type).toBe('password'); expect(password.props.autocomplete).toBe('new-password')
    expect(v.root.findAll((n) => n.props.id === password.props['aria-describedby'])).toHaveLength(1)
    expect(control(v, 'webhook-ingress-status').props.role).toBe('status')
    expect(v.root.findAll((n) => n.tag === 'legend').map((n) => n.textContent())).toEqual(['Inbound listener setup', 'Per-trigger delivery setup'])
    v.setup.busy = true; await flush()
    expect(control(v, 'webhook-ingress').props['aria-busy']).toBe(true)
    expect(v.root.findAll((n) => n.tag === 'fieldset').every((n) => n.props.disabled)).toBe(true)
  })
})
