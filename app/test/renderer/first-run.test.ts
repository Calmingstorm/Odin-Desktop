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
    secretsUnlock: vi.fn(async () => ok({ unlocked: true })),
    settingsSet: vi.fn(async () => ok({ revision: 'r2', fields: [] })),
    getSetupReminderHidden: vi.fn(async () => ok({ hidden: false })),
    setSetupReminderHidden: vi.fn(async (hidden) => ok({ hidden })),
    setNotifications: vi.fn(), setAutostart: vi.fn()
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
  store = await import('../../src/renderer/src/store')
  statuses = await import('../../src/renderer/src/stores/status')
  settings = await import('../../src/renderer/src/stores/settings')
  store.state.app = { ...store.state.app, link: 'ready', coreInstanceId: 'test-core' }
  await store.loadSetupReminder()
  await statuses.refreshStatus()
})
afterEach(() => { for (const v of mounts.splice(0)) v.unmount() })

async function banner(dismissible = false): Promise<Mounted> {
  const v = mount((await import('../../src/renderer/src/components/FirstRunBanner.vue')).default, { dismissible })
  mounts.push(v)
  await flush()
  return v
}
const stateOf = (v: Mounted): unknown => v.root.find('section')?.props['data-state'] ?? 'absent'

describe('P3.2 core-authoritative first run', () => {
  it('keeps dismissed invitations hidden on later incompleteness, but never hides operational notices', async () => {
    bridge.getSetupReminderHidden!.mockResolvedValue(ok({ hidden: true }))
    await store.loadSetupReminder()
    const v = await banner(true)
    expect(stateOf(v)).toBe('absent')
    for (const [state, reason] of [['incomplete', 'provider_configuration_incomplete'], ['saved', 'provider_identity_not_adopted'],
      ['degraded', 'credential_state_unavailable'], ['degraded', 'keyring_unavailable']] as const) {
      bridge.status!.mockResolvedValue(ok(core(project(state, reason, reason === 'keyring_unavailable'))))
      await statuses.refreshStatus()
      await flush()
      expect(stateOf(v)).toBe(state === 'incomplete' ? 'absent' : state)
      if (state !== 'incomplete') expect(v.root.findAll((node) => node.props['data-testid'] === 'first-run-later')).toHaveLength(0)
    }
    expect(bridge.secretsUnlock).not.toHaveBeenCalled()
  })

  it('shows invitations and operational notices only in chat', async () => {
    const v = await banner(true)
    v.root.button('Open Models and providers').fire('click')
    await flush()
    expect(stateOf(v)).toBe('absent')
    bridge.status!.mockResolvedValue(ok(core(project('degraded', 'credential_state_unavailable'))))
    await statuses.refreshStatus()
    await flush()
    expect(stateOf(v)).toBe('absent')
    store.state.view = 'chat'
    await flush()
    expect(stateOf(v)).toBe('degraded')
  })

  it('failed dismissal stays visible, scrubs errors, and permits explicit retry without core writes', async () => {
    const v = await banner(true)
    bridge.setSetupReminderHidden!.mockRejectedValueOnce(new Error('PRIVATE-PATH'))
    await v.root.button('Set up later').fire('click')
    await flush()
    expect(store.state.setupReminderHidden).toBe(false)
    expect(v.root.textContent()).toContain('Could not save this preference')
    expect(v.root.textContent()).not.toContain('PRIVATE-PATH')
    await v.root.button('Set up later').fire('click')
    await flush()
    expect(stateOf(v)).toBe('absent')
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })

  it.each([true, false])('late bootstrap cannot undo owner dismissal; failed save still settles bootstrap (success=%s)', async (success) => {
    store.state.setupReminderLoaded = false
    let resolve!: (value: Result<{ hidden: boolean }>) => void
    bridge.getSetupReminderHidden!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    bridge.setSetupReminderHidden!.mockResolvedValueOnce(success ? ok({ hidden: true }) : failure())
    const read = store.loadSetupReminder()
    expect(await store.dismissSetupReminder()).toBe(success)
    resolve(ok({ hidden: false }))
    await read
    expect(store.state.setupReminderHidden).toBe(success)
    expect(store.state.setupReminderLoaded).toBe(true)
  })

  it('failed bootstrap is best effort and does not fabricate readiness or successful saving', async () => {
    bridge.getSetupReminderHidden!.mockRejectedValueOnce(new Error('private'))
    await store.loadSetupReminder()
    expect(store.state.setupReminderLoaded).toBe(true)
    bridge.setSetupReminderHidden!.mockResolvedValueOnce(failure())
    expect(await store.dismissSetupReminder()).toBe(false)
    expect(store.state.setupReminderHidden).toBe(false)
  })

  it('an overlapping read cannot consume an in-flight dismissal receipt, and owner writes do not replay', async () => {
    let resolve!: (value: Result<{ hidden: boolean }>) => void
    bridge.setSetupReminderHidden!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const dismissal = store.dismissSetupReminder()
    expect(await store.dismissSetupReminder()).toBe(false)
    await store.loadSetupReminder()
    resolve(ok({ hidden: true }))
    expect(await dismissal).toBe(true)
    expect(store.state.setupReminderHidden).toBe(true)
    expect(bridge.setSetupReminderHidden).toHaveBeenCalledTimes(1)
  })

  it('does not read replacement-core status after settings rehydration crosses epochs', async () => {
    bridge.status!.mockResolvedValue(ok(core(project('degraded', 'credential_state_unavailable'))))
    await statuses.refreshStatus()
    const v = await banner()
    let resolve!: (value: Result<ReturnType<typeof meta>>) => void
    bridge.settingsSchema!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const reads = bridge.status!.mock.calls.length
    const retry = v.root.button('Retry').fire('click')
    await flush()
    store.state.recoveryEpoch += 1
    resolve(ok(meta()))
    await retry
    expect(bridge.status).toHaveBeenCalledTimes(reads)
  })

  it('does not adopt old-core accounts returned during explicit Retry after recovery', async () => {
    bridge.status!.mockResolvedValue(ok(core(project('degraded', 'credential_state_unavailable'))))
    await statuses.refreshStatus()
    const v = await banner()
    let resolve!: (value: Result<{ configured: boolean; accounts: unknown[] }>) => void
    settings.settings.codex.stale = true
    bridge.codexAccounts!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const retry = v.root.button('Retry').fire('click')
    await flush()
    store.state.recoveryEpoch += 1
    store.state.app.coreInstanceId = 'replacement-core'
    resolve(ok({ configured: true, accounts: [{ email: 'old-core@example.test' }] }))
    await retry
    expect(settings.settings.codex.status).toBeNull()
    expect(settings.settings.codex.stale).toBe(true)
  })

  it('qualifies independent keyring metadata by epoch and instance without first_run', async () => {
    store.state.setupReminderHidden = true
    bridge.status!.mockResolvedValue(ok(core()))
    await statuses.refreshStatus()
    bridge.settingsSchema!.mockResolvedValue(ok({ ...meta(), status: { ...meta().status, keyring_error: 'keyring_unavailable' } }))
    await settings.loadSettings()
    const v = await banner(true)
    expect(stateOf(v)).toBe('keyring-attention')
    expect(v.root.textContent()).toContain('Keyring needs attention')
    expect(v.root.findAll((node) => node.props['data-testid'] === 'first-run-later')).toHaveLength(0)
    expect(bridge.secretsUnlock).not.toHaveBeenCalled()
    store.state.recoveryEpoch += 1
    await flush()
    expect(stateOf(v)).toBe('absent')
  })

  it('effective ready plus a current keyring error has an action warning without empty paragraphs or success sentence', async () => {
    bridge.status!.mockResolvedValue(ok(core(project('effective-ready', 'provider_effective'))))
    await statuses.refreshStatus()
    bridge.settingsSchema!.mockResolvedValue(ok({ ...meta(), status: { ...meta().status, keyring_error: 'locked' } }))
    await settings.loadSettings()
    const v = await banner(true)
    expect(v.root.textContent()).toContain('Keyring needs attention')
    expect(v.root.textContent()).not.toContain('generation or connection test')
    expect(v.root.findAll((node) => node.tag === 'p').every((node) => node.textContent().trim())).toBe(true)
  })

  it.each(['fresh', 'incomplete', 'saved', 'effective-ready', 'degraded'] as const)('projects %s only when the current core reports it, without a ready banner', async (state) => {
    bridge.status!.mockResolvedValue(ok(core(project(state, state === 'effective-ready' ? 'provider_effective' : 'provider_runtime_unavailable'))))
    await statuses.refreshStatus()
    expect(stateOf(await banner())).toBe(state === 'effective-ready' ? 'absent' : state)
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
    expect(stateOf(await banner())).toBe('absent')
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
    expect(stateOf(v)).toBe('absent')
    let resolve!: (value: Result<CoreStatus>) => void
    bridge.status!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const oldRead = statuses.refreshStatus()
    store.state.app.link = 'reconnecting'
    store.state.recoveryEpoch += 1
    store.state.app.link = 'ready'
    resolve(ok(core(project('effective-ready', 'provider_effective'))))
    await oldRead
    await flush()
    expect(stateOf(v)).toBe('absent')
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
    expect(stateOf(v)).toBe('absent')
    bridge.status!.mockRejectedValue(new Error('not displayed'))
    await statuses.refreshStatus()
    await flush()
    expect(stateOf(v)).toBe('absent')
    expect(v.root.textContent()).not.toContain('not displayed')
  })

  it('setup later persists only the invitation preference, keeps navigation, and never completes setup', async () => {
    const v = await banner(true)
    await v.root.button('Set up later').fire('click')
    await flush()
    expect(store.state.view).toBe('chat')
    expect(store.state.setupReminderHidden).toBe(true)
    expect(bridge.setSetupReminderHidden).toHaveBeenCalledExactlyOnceWith(true)
    expect(stateOf(v)).toBe('absent')
    store.openSettings('models')
    await flush()
    expect([store.state.view, store.state.settingsSection]).toEqual(['settings', 'models'])
    expect(stateOf(await banner())).toBe('absent')
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

  it.each(['keyring_unavailable', 'credential_state_unavailable'] as const)('Retry unlocks only for a keyring failure, then re-reads schema/accounts/status for %s', async (reason) => {
    bridge.status!.mockResolvedValue(ok(core(project('degraded', reason, reason === 'keyring_unavailable'))))
    await statuses.refreshStatus()
    const v = await banner()
    const calls: string[] = []
    bridge.secretsUnlock!.mockImplementation(async () => { calls.push('unlock'); return ok({ unlocked: true }) })
    bridge.settingsSchema!.mockImplementation(async () => { calls.push('schema'); return ok(meta()) })
    bridge.codexAccounts!.mockImplementation(async () => { calls.push('accounts'); return ok({ configured: false, accounts: [] }) })
    bridge.status!.mockImplementation(async () => { calls.push('status'); return ok(core(project('incomplete', 'provider_configuration_incomplete'))) })
    await v.root.button('Retry').fire('click')
    await flush()
    expect(calls).toEqual(reason === 'keyring_unavailable' ? ['unlock', 'schema', 'accounts', 'status'] : ['schema', 'accounts', 'status'])
    expect(stateOf(v)).toBe('incomplete')
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })

  it('mounting and background reads never unlock; a held Retry unlocks once and rehydrates only after success', async () => {
    bridge.status!.mockResolvedValue(ok(core(project('degraded', 'keyring_unavailable', true))))
    await statuses.refreshStatus()
    const v = await banner()
    await Promise.all([settings.loadSettings(), settings.loadCodex(), statuses.refreshStatus()])
    expect(bridge.secretsUnlock).not.toHaveBeenCalled()
    let resolve!: (value: Result<{ unlocked: true }>) => void
    bridge.secretsUnlock!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const reads = bridge.settingsSchema!.mock.calls.length
    const retry = v.root.button('Retry').fire('click')
    await flush()
    await v.root.button('Retrying…').fire('click')
    expect(bridge.secretsUnlock).toHaveBeenCalledTimes(1)
    expect(bridge.settingsSchema).toHaveBeenCalledTimes(reads)
    resolve(ok({ unlocked: true }))
    await retry
    await flush()
    expect(bridge.settingsSchema).toHaveBeenCalledTimes(reads + 1)
  })

  it('failed unlock stays degraded without rehydrating or exposing exception details, and remains retryable', async () => {
    bridge.status!.mockResolvedValue(ok(core(project('degraded', 'keyring_unavailable', true))))
    await statuses.refreshStatus()
    const v = await banner()
    bridge.secretsUnlock!.mockResolvedValueOnce({ ok: false, error: { code: 'keyring_unavailable', message: 'not displayed' } })
    await v.root.button('Retry').fire('click')
    await flush()
    expect(stateOf(v)).toBe('degraded')
    expect(v.root.textContent()).toContain('could not be unlocked')
    expect(v.root.textContent()).not.toContain('not displayed')
    expect(bridge.settingsSchema).not.toHaveBeenCalled()
    await v.root.button('Retry').fire('click')
    await flush()
    expect(bridge.secretsUnlock).toHaveBeenCalledTimes(2)
    expect(bridge.settingsSchema).toHaveBeenCalledTimes(1)
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })

  it('does not rehydrate a replacement core after a late unlock answer from the old one', async () => {
    bridge.status!.mockResolvedValue(ok(core(project('degraded', 'keyring_unavailable', true))))
    await statuses.refreshStatus()
    const v = await banner()
    let resolve!: (value: Result<{ unlocked: true }>) => void
    bridge.secretsUnlock!.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const retry = v.root.button('Retry').fire('click')
    store.state.recoveryEpoch += 1
    store.state.app.coreInstanceId = 'replacement-core'
    resolve(ok({ unlocked: true }))
    await retry
    await flush()
    expect(bridge.settingsSchema).not.toHaveBeenCalled()
    expect(bridge.codexAccounts).not.toHaveBeenCalled()
    expect(stateOf(v)).toBe('absent')
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

  it('General disables start at login where it isn\'t offered, and says why', async () => {
    store.state.notifications = { enabled: true, previews: true, muted: [], quietHours: { enabled: false, start: '22:00', end: '08:00' } }
    store.state.autostartUnavailable = 'Start at login comes with the installed Windows app.'
    const v = mount((await import('../../src/renderer/src/views/settings/General.vue')).default)
    mounts.push(v)
    await flush()
    const startup = v.root.findAll((n) => n.props['data-testid'] === 'start-at-login')[0]!
    expect(startup.props.disabled).toBe(true)
    const note = v.root.findAll((n) => n.props['data-testid'] === 'start-at-login-unavailable')[0]!
    expect(note.textContent()).toBe('Start at login comes with the installed Windows app.')
    store.state.autostartUnavailable = ''
    await flush()
    expect(v.root.findAll((n) => n.props['data-testid'] === 'start-at-login')[0]!.props.disabled).toBe(false)
    expect(v.root.findAll((n) => n.props['data-testid'] === 'start-at-login-unavailable')).toEqual([])
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
    expect(v.root.textContent()).toContain('Closing the window keeps Odin running in the tray. Exit stops it.')
    expect(v.root.textContent()).toContain('Mute or unmute one from its')
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
