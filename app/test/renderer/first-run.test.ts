import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigField, CoreStatus, FirstRunStatus, NotificationSettings, Result } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const failure = (code = 'unavailable'): Result<never> => ({ ok: false, error: { code, message: 'Profile keyring is unavailable or locked' } })
const meta = () => ({ schema_version: 1, revision: 'r1', fields: [], status: { counts: {}, desired_revision: 'r1', effective_revision: 'r1', keyring_error: null } })
const core = (first_run?: FirstRunStatus): CoreStatus => ({ phase: 'ready', core_instance_id: 'test-core', version: 'test', capabilities: [], first_run })
const project = (state: FirstRunStatus['state'], reason: FirstRunStatus['reason'] = 'provider_not_configured', keyring_unavailable = false): FirstRunStatus => ({ state, reason, keyring_unavailable })
const mounts: Mounted[] = []
let bridge: Record<string, ReturnType<typeof vi.fn>>
let store: typeof import('../../src/renderer/src/store')
let statuses: typeof import('../../src/renderer/src/stores/status')
let settings: typeof import('../../src/renderer/src/stores/settings')

beforeEach(async () => {
  vi.resetModules()
  bridge = {
    status: vi.fn(async () => ok(core(project('fresh')))),
    usage: vi.fn(async () => failure()),
    settingsSchema: vi.fn(async () => ok(meta())),
    codexAccounts: vi.fn(async () => ok({ configured: false, accounts: [] })),
    secretsSet: vi.fn(async () => ok({ configured: true })),
    secretsClear: vi.fn(async () => ok({ configured: false })),
    settingsSet: vi.fn(async () => ok({ revision: 'r2', fields: [] })),
    setNotifications: vi.fn(), setAutostart: vi.fn()
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
  store = await import('../../src/renderer/src/store')
  statuses = await import('../../src/renderer/src/stores/status')
  settings = await import('../../src/renderer/src/stores/settings')
  store.state.app = { ...store.state.app, link: 'ready', coreInstanceId: 'test-core' }
  await statuses.refreshStatus()
})
afterEach(() => { for (const v of mounts.splice(0)) v.unmount() })

async function banner(dismissible = false): Promise<Mounted> {
  const v = mount((await import('../../src/renderer/src/components/FirstRunBanner.vue')).default, { dismissible })
  mounts.push(v)
  await flush()
  return v
}
const stateOf = (v: Mounted): unknown => v.root.find('section')!.props['data-state']

describe('P3.2 core-authoritative first run', () => {
  it.each(['fresh', 'incomplete', 'saved', 'effective-ready', 'degraded'] as const)('shows %s only when the current core reports it', async (state) => {
    bridge.status!.mockResolvedValue(ok(core(project(state, state === 'effective-ready' ? 'provider_effective' : 'provider_runtime_unavailable'))))
    await statuses.refreshStatus()
    expect(stateOf(await banner())).toBe(state)
  })

  it('does not infer readiness from phase, model, credentials, or settings; a second mount still reports fresh', async () => {
    bridge.status!.mockResolvedValue(ok({ ...core(project('fresh')), model: { main: 'model', effort: 'high', provider: 'provider' } }))
    await statuses.refreshStatus()
    settings.settings.meta = meta()
    const secret = { path: 'kimi.api_key', sensitivity: 'secret' } as unknown as ConfigField
    await settings.setSecret(secret, 'TEST-ONLY-SECRET')
    expect(stateOf(await banner())).toBe('fresh')
    expect(stateOf(await banner())).toBe('fresh')
    bridge.status!.mockResolvedValue(ok(core()))
    await statuses.refreshStatus()
    expect(stateOf(await banner())).toBe('unavailable')
  })

  it('a saved model remains saved-not-effective; revision and connection failures remain retryable without completing setup', async () => {
    const model = { path: 'llm_provider.model', sensitivity: 'public', apply_handler: 'settings.set' } as unknown as ConfigField
    settings.settings.meta = { ...meta(), fields: [model] }
    const v = await banner()
    bridge.status!.mockResolvedValue(ok(core(project('saved', 'provider_identity_not_adopted'))))
    expect(await settings.saveField(model, 'test-model')).toBe(true)
    await flush()
    expect(stateOf(v)).toBe('saved')
    bridge.settingsSet!.mockResolvedValue(failure('stale_binding'))
    expect(await settings.saveField(model, 'new-model')).toBe(false)
    expect(settings.settings.fields[model.path]?.status).toBe('error')
    expect(settings.settings.fields[model.path]?.message).toContain('Settings changed elsewhere')
    bridge.settingsSet!.mockResolvedValue(failure('unavailable'))
    expect(await settings.saveField(model, 'new-model')).toBe(false)
    expect(settings.settings.fields[model.path]?.status).toBe('error')
    await flush()
    expect(stateOf(v)).toBe('saved')
    expect(store.state.setupReminderHidden).toBe(false)
  })

  it('becomes unavailable on link loss and stays unavailable until a new recovery read, even if an old read arrives', async () => {
    bridge.status!.mockResolvedValue(ok(core(project('effective-ready', 'provider_effective'))))
    await statuses.refreshStatus()
    const v = await banner()
    expect(stateOf(v)).toBe('effective-ready')
    let resolve!: (value: Result<CoreStatus>) => void
    bridge.status!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const oldRead = statuses.refreshStatus()
    store.state.app.link = 'reconnecting'
    store.state.recoveryEpoch += 1
    store.state.app.link = 'ready'
    resolve(ok(core(project('effective-ready', 'provider_effective'))))
    await oldRead
    await flush()
    expect(stateOf(v)).toBe('unavailable')
    bridge.status!.mockResolvedValue(ok(core(project('saved', 'provider_identity_not_adopted'))))
    await statuses.refreshStatus()
    await flush()
    expect(stateOf(v)).toBe('saved')
  })

  it('shows unavailable for failed or rejected status reads without marking saved models ready', async () => {
    const v = await banner()
    bridge.status!.mockResolvedValue(failure())
    await statuses.refreshStatus()
    await flush()
    expect(stateOf(v)).toBe('unavailable')
    bridge.status!.mockRejectedValue(new Error('not displayed'))
    await statuses.refreshStatus()
    await flush()
    expect(stateOf(v)).toBe('unavailable')
    expect(v.root.textContent()).not.toContain('not displayed')
  })

  it('setup later leaves chat and settings navigable, without writing a completion flag or hiding Settings readiness', async () => {
    const v = await banner(true)
    v.root.button('Set up later').fire('click')
    await flush()
    expect(store.state.view).toBe('chat')
    expect(store.state.setupReminderHidden).toBe(true)
    v.root.button('Open Models and providers').fire('click')
    await flush()
    expect([store.state.view, store.state.settingsSection]).toEqual(['settings', 'models'])
    expect(stateOf(await banner())).toBe('fresh')
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })

  it('routes into the existing models form and retains its section on re-entry, never adding a second form', async () => {
    store.openSettings('models')
    const component = (await import('../../src/renderer/src/views/Settings.vue')).default
    const v = mount(component)
    mounts.push(v)
    await flush()
    expect(v.root.findAll((node) => node.props['aria-label'] === 'Codex accounts')).toHaveLength(1)
    v.root.button('← Back to chat').fire('click')
    v.unmount()
    store.openSettings()
    const reentry = mount(component)
    mounts.push(reentry)
    await flush()
    expect(store.state.settingsSection).toBe('models')
    expect(reentry.root.findAll((node) => node.props['aria-label'] === 'Codex accounts')).toHaveLength(1)
    store.openSettings('unrecognized')
    expect(store.state.settingsSection).toBe('models')
  })

  it.each(['keyring_unavailable', 'credential_state_unavailable'] as const)('Retry re-reads schema and accounts before status for %s, never replaying secret writes', async (reason) => {
    bridge.status!.mockResolvedValue(ok(core(project('degraded', reason, true))))
    await statuses.refreshStatus()
    const v = await banner()
    expect(v.root.textContent()).toContain('keyring')
    const calls: string[] = []
    bridge.settingsSchema!.mockImplementation(async () => { calls.push('schema'); return ok(meta()) })
    bridge.codexAccounts!.mockImplementation(async () => { calls.push('accounts'); return ok({ configured: false, accounts: [] }) })
    bridge.status!.mockImplementation(async () => { calls.push('status'); return ok(core(project('incomplete', 'provider_configuration_incomplete'))) })
    await v.root.button('Retry').fire('click')
    await flush()
    expect(calls).toEqual(['schema', 'accounts', 'status'])
    expect(stateOf(v)).toBe('incomplete')
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })

  it('clears transient credentials immediately on submission, including failed writes, and never adds them to a conversation draft', async () => {
    const { SecretDrafts } = await import('../../src/renderer/src/settings-form')
    let resolve!: (ok: boolean) => void
    const write = vi.fn(() => new Promise<boolean>((r) => { resolve = r }))
    const drafts = new SecretDrafts(write)
    drafts.values['kimi.api_key'] = 'ISOLATED-TEST-SECRET'
    const saving = drafts.save('kimi.api_key')
    expect(drafts.values['kimi.api_key']).toBeUndefined()
    expect(JSON.stringify(store.state)).not.toContain('ISOLATED-TEST-SECRET')
    drafts.values['kimi.api_key'] = 'NEWER-UNSAVED'
    resolve(false)
    await saving
    expect(drafts.values['kimi.api_key']).toBe('NEWER-UNSAVED')
    expect(write).toHaveBeenCalledTimes(1)
  })

  it('General exposes opt-in startup, previews, mute guidance and quiet hours immediately, then adopts persisted choices', async () => {
    const notifications: NotificationSettings = { enabled: true, previews: true, muted: [], quietHours: { enabled: false, start: '22:00', end: '08:00' } }
    store.state.notifications = notifications
    bridge.setNotifications!.mockImplementation(async (change) => ok({ notifications: { ...notifications, ...change } }))
    bridge.setAutostart!.mockImplementation(async (autostart) => ok({ autostart }))
    const v = mount((await import('../../src/renderer/src/views/settings/General.vue')).default)
    mounts.push(v)
    await flush()
    const startup = v.root.findAll((n) => n.props['data-testid'] === 'start-at-login')[0]!
    const previews = v.root.findAll((n) => n.props['data-testid'] === 'notification-previews')[0]!
    expect(startup.checked).toBe(false)
    expect(previews.checked).toBe(true)
    expect(v.root.textContent()).toContain('Exit stops Odin')
    expect(v.root.textContent()).toContain('mute a conversation')
    startup.checked = true
    await startup.fire('change')
    previews.checked = false
    await previews.fire('change')
    await flush()
    expect(store.state.autostart).toBe(true)
    expect(store.state.notifications?.previews).toBe(false)
    const reentry = mount((await import('../../src/renderer/src/views/settings/General.vue')).default)
    mounts.push(reentry)
    expect(reentry.root.findAll((n) => n.props['data-testid'] === 'start-at-login')[0]!.checked).toBe(true)
    expect(reentry.root.findAll((n) => n.props['data-testid'] === 'notification-previews')[0]!.checked).toBe(false)
  })
})
