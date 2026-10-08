import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { flush, mount, type Mounted } from './component-host'
let mounted: Mounted | undefined
let odin: Record<string, any>
const ok = (result: unknown) => ({ ok: true, result })
const unavailable = { ok: false, error: { code: 'capability_unavailable', message: 'Unavailable' } }
beforeEach(() => {
  vi.resetModules()
  odin = { getDesktopInfo: vi.fn(async () => ok({ appVersion: '1.0.0', electronVersion: '44', chromiumVersion: '145', nodeVersion: '22', platform: 'linux', architecture: 'x64', license: 'MIT', packaged: false })), copyText: vi.fn(async () => ok({ copied: true })), openSettingsFolder: vi.fn(async () => ok({ opened: true })), settingsSchema: vi.fn(async () => unavailable), setNotifications: vi.fn(async () => unavailable), setAutostart: vi.fn(async (enabled) => ok({ autostart: enabled })), setAppearance: vi.fn(async (appearance) => ok({ appearance })) }
  ;(globalThis as any).window = { odin }
  ;(globalThis as any).document = { activeElement: null, getElementById: vi.fn(() => null) }
})
afterEach(() => { mounted?.unmount(); mounted = undefined })
async function general() {
  const { state } = await import('../../src/renderer/src/store')
  state.notifications = { enabled: true, previews: true, muted: [], quietHours: { enabled: true, start: '22:00', end: '08:00' } }
  mounted = mount((await import('../../src/renderer/src/views/settings/General.vue')).default)
  await flush()
  return { root: mounted.root, state }
}
describe('UI v1 General and explicit Advanced presentation', () => {
  it('reports a thrown preference transport as unconfirmed and blocks queued intent without claiming Saved', async () => {
    odin.setAppearance = vi.fn(async () => { throw new Error('private transport detail') })
    odin.setNotifications = vi.fn(async () => ok({ notifications: { enabled: true, previews: true, muted: [], quietHours: { enabled: false, start: '22:00', end: '08:00' } } }))
    const { root, state } = await general()
    const previous = state.appearance
    root.findAll((node) => node.props.name === 'appearance' && node.props.value === 'light')[0]!.fire('change')
    root.findAll((node) => node.props.id === 'start-at-login')[0]!.fire('change', { target: { checked: true } })
    await flush()
    expect(state.appearance).toBe(previous)
    expect(root.textContent()).toContain('The save outcome could not be confirmed.')
    expect(root.textContent()).toContain('An earlier save did not complete.')
    expect(root.textContent()).not.toContain('Saved.')
    expect(root.textContent()).not.toContain('private transport detail')
    expect(odin.setAutostart).not.toHaveBeenCalled()
    root.findAll((node) => node.props.id === 'quiet-hours-enabled')[0]!.fire('change', { target: { checked: false } })
    await flush()
    expect(odin.setNotifications).toHaveBeenCalledExactlyOnceWith({ quietHours: { enabled: false } })
    expect(state.notifications!.quietHours.enabled).toBe(false)
    expect(root.textContent()).toContain('Saved.')
  })
  it('does not call failed persistence Saved or adopt the rejected preference', async () => {
    const failure = { ok: false, error: { code: 'operation_failed', message: 'Preferences could not be persisted.' } }
    odin.setAppearance = vi.fn(async () => failure)
    odin.setNotifications = vi.fn(async () => failure)
    const { root, state } = await general()
    const previous = state.appearance
    root.findAll((node) => node.tag === 'input' && node.props.value === 'light')[0]!.fire('change')
    await flush()
    expect(root.textContent()).toContain('Preferences could not be persisted.')
    expect(root.textContent()).not.toContain('Saved.')
    expect(state.appearance).toBe(previous)
    root.findAll((node) => node.props.id === 'notification-previews')[0]!.fire('change', { target: { checked: false } })
    await flush()
    expect(odin.setNotifications).toHaveBeenCalledExactlyOnceWith({ previews: false })
    expect(state.notifications!.previews).toBe(true)
    expect(root.textContent()).not.toContain('Saved.')
  })
  it('keeps exactly nine primary destinations and working restart links and truthful Exit request', async () => {
    const { settings } = await import('../../src/renderer/src/stores/settings')
    const field = { path: 'attachments.retention_hours', label: 'Retention', description: '', type: 'integer', enum: null, constraints: {}, desired: 24, effective: 12, sensitivity: 'public', apply_handler: 'settings.set', apply_state: 'pending_restart', pending_restart: true }
    const schema = { revision: 'rev', fields: [field], status: { counts: {}, desired_revision: 'rev', effective_revision: null } }
    odin.settingsSchema = async () => ok(schema)
    odin.exitOdin = vi.fn(async () => ok({ accepted: true }))
    const focus = vi.fn(), scrollIntoView = vi.fn()
    ;(globalThis as any).document.getElementById = vi.fn(() => ({ focus, scrollIntoView }))
    mounted = mount((await import('../../src/renderer/src/views/Settings.vue')).default); await flush()
    const nav = mounted.root.findAll((node) => node.tag === 'button' && String(node.props.class).includes('settings-nav-item')).map((node) => node.textContent())
    expect(nav).toEqual(['General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and access', 'Work', 'Data and privacy'])
    mounted.root.button('Attachment retention').fire('click'); await flush()
    expect(focus).toHaveBeenCalled()
    expect(mounted.root.textContent()).toContain('Advanced settings')
    mounted.root.button('Exit Odin').fire('click'); await flush()
    expect(mounted.root.textContent()).toContain('Cleanup completion is not yet confirmed.')
    odin.exitOdin = async () => ({ ok: false, error: { message: 'Exit refused.' } })
    mounted.root.button('Exit Odin').fire('click'); await flush()
    expect(mounted.root.textContent()).toContain('Exit refused.')
    odin.exitOdin = async () => { throw new Error('private') }
    mounted.root.button('Exit Odin').fire('click'); await flush()
    expect(mounted.root.textContent()).toContain('Exit could not be requested.')
    mounted.root.button('← General').fire('click'); await flush()
    mounted.root.button('← Back to chat').fire('click')
    expect((await import('../../src/renderer/src/store')).state.view).toBe('chat')
    settings.notice = 'Outcome unknown.'; await flush()
    mounted.root.button('Refresh saved settings').fire('click'); await flush()
    expect(settings.notice).toBe('')
  })
  it('retains memory/records subsections when returning from the records view', async () => {
    for (const name of ['memoryList', 'listsList', 'knowledgeList', 'auditQuery', 'healthGet', 'logsSearch', 'turnStateList', 'computerStatus', 'observabilityStats', 'observabilityRisk', 'trajectoriesList', 'auditDiffs', 'auditFailures', 'usage']) odin[name] = async () => unavailable
    mounted = mount((await import('../../src/renderer/src/views/settings/DataPrivacy.vue')).default); await flush()
    mounted.root.button('Usage, logs and audit').fire('click'); await flush()
    expect(mounted.root.textContent()).toContain('Computer use')
    mounted.root.button('Memory and knowledge').fire('click'); await flush()
    expect(mounted.root.textContent()).toContain('Memory')
  })
  it('cancels queued quiet intent without rolling back the dispatched save', async () => {
    let land!: (value: unknown) => void
    odin.setNotifications = vi.fn(() => new Promise((resolve) => { land = resolve }))
    const { root } = await general()
    const input = root.findAll((node) => node.props.id === 'quiet-hours-start')[0]!
    input.fire('input', { target: { value: '23:00' } }); input.fire('keydown', { key: 'Enter' }); await flush()
    input.fire('input', { target: { value: '21:00' } }); input.fire('keydown', { key: 'Enter' }); await flush()
    root.button('Cancel').fire('click')
    land(ok({ notifications: { enabled: true, previews: true, muted: [], quietHours: { enabled: true, start: '23:00', end: '08:00' } } })); await flush()
    expect(odin.setNotifications).toHaveBeenCalledTimes(1)
    expect(input.value).toBe('23:00')
  })
  it('saves a newer deliberately submitted quiet value after the first receipt', async () => {
    const held: Array<(value: unknown) => void> = []
    odin.setNotifications = vi.fn(() => new Promise((resolve) => held.push(resolve)))
    const { root } = await general()
    const input = root.findAll((node) => node.props.id === 'quiet-hours-start')[0]!
    input.fire('input', { target: { value: '23:00' } }); input.fire('keydown', { key: 'Enter' }); await flush()
    input.fire('input', { target: { value: '21:00' } }); input.fire('keydown', { key: 'Enter' })
    held.shift()!(ok({ notifications: { enabled: true, previews: true, muted: [], quietHours: { enabled: true, start: '23:00', end: '08:00' } } })); await flush()
    expect(odin.setNotifications).toHaveBeenCalledTimes(2)
    expect(odin.setNotifications.mock.calls[1][0]).toEqual({ quietHours: { start: '21:00' } })
    held.shift()!({ ok: false, error: { message: 'Not persisted.' } }); await flush()
    expect(input.value).toBe('21:00')
    expect(root.textContent()).toContain('Not persisted.')
  })
  it('copies current engine facts but no provider/account details', async () => {
    const { state } = await import('../../src/renderer/src/store')
    const { status } = await import('../../src/renderer/src/stores/status')
    state.app.link = 'ready'; state.app.coreInstanceId = 'instance'; status.epoch = state.recoveryEpoch
    status.core = { version: '0.1.0.dev1', phase: 'degraded', core_instance_id: 'instance', capabilities: [], providers: [{ name: 'private-account', health: 'degraded' }] }
    odin.openSettingsFolder = async () => ({ ok: false, error: { message: 'Folder could not open.' } })
    const { root } = await general()
    root.button('Copy diagnostics').fire('click'); root.button('Open settings folder').fire('click'); await flush()
    expect(JSON.parse(odin.copyText.mock.calls[0][0])).toMatchObject({ engineBuild: '0.1.0.dev1', enginePhase: 'degraded' })
    expect(odin.copyText.mock.calls[0][0]).not.toContain('private-account')
    expect(root.textContent()).toContain('Folder could not open.')
    state.recoveryEpoch += 1
    root.button('Copy diagnostics').fire('click'); await flush()
    expect(JSON.parse(odin.copyText.mock.calls[1][0]).engineBuild).toBeNull()
  })
  it('matches the reviewed allowlist including one grouped model-profile owner', async () => {
    const manifest = await import('../../src/renderer/src/settings-presentation')
    const owners = JSON.parse(readFileSync('../docs/design/ui-v1-write-owners.json', 'utf8'))
    const paths = manifest.ADVANCED_FIELDS.map((entry) => entry.path)
    const nested = owners.advanced_allowlist.filter((path: string) => path.startsWith('openai_compatible.model_profiles.'))
    expect([...paths, ...nested].sort()).toEqual([...owners.advanced_allowlist].sort())
    expect(new Set(paths).size).toBe(paths.length)
    expect(manifest.isCuratedPath('openai_compatible.model_profiles.some-model.supported_efforts')).toBe(true)
    expect(manifest.isCuratedPath('new.unclassified')).toBe(false)
    expect(manifest.presentationFor('timezone')?.label).toBe('Time zone')
    expect(manifest.presentationFor('attachments.retention_hours')?.category).toBe('Data and retention')
    expect(manifest.presentationFor('sessions.context_budget_overrides.model')).toBeTruthy()
    expect(manifest.presentationFor('unknown')).toBeUndefined()
    expect(manifest.advancedMatches(manifest.ADVANCED_FIELDS[0]!, 'Codex budgets')).toBe(true)
    expect(manifest.advancedMatches(manifest.ADVANCED_FIELDS[0]!, 'not-present')).toBe(false)
    expect(manifest.restartFields([{ pending_restart: false, apply_state: 'unknown' }, { pending_restart: true }, { apply_state: 'pending_restart' }] as never)).toHaveLength(2)
  })
  it('keeps General curated, links Advanced, and copies only whitelist diagnostics', async () => {
    const { root, state } = await general()
    expect(root.findAll((node) => String(node.props.class).includes('schema-form'))).toHaveLength(0)
    root.button('Copy diagnostics').fire('click'); await flush()
    expect(JSON.parse(odin.copyText.mock.calls[0][0]).engineBuild).toBeNull()
    root.button('Open settings folder').fire('click'); await flush()
    expect(root.textContent()).toContain('Opened the settings folder.')
    root.button('Advanced settings').fire('click')
    expect(state.settingsSection).toBe('advanced')
  })
  it('reports build, folder and clipboard failures without claiming success', async () => {
    odin.getDesktopInfo = async () => unavailable
    odin.openSettingsFolder = async () => { throw new Error('private path') }
    odin.copyText = async () => ({ ok: false, error: { message: 'Clipboard unavailable.' } })
    const { root } = await general()
    root.button('Read build information again').fire('click')
    root.button('Open settings folder').fire('click'); root.button('Copy diagnostics').fire('click'); await flush()
    expect(root.textContent()).toContain('Clipboard unavailable.')
    expect(root.textContent()).toContain('The settings folder could not be opened.')
    expect(root.textContent()).not.toContain('private path')
  })
  it('handles absent/throwing build bridge and clipboard transport exceptions', async () => {
    delete odin.getDesktopInfo
    odin.copyText = async () => { throw new Error('secret transport') }
    const { root } = await general()
    root.button('Copy diagnostics').fire('click'); await flush()
    expect(root.textContent()).toContain('Desktop build information is unavailable.')
    expect(root.textContent()).toContain('Diagnostics could not be copied.')
  })
  it('serializes preferences and blocks queued intent after unknown failure', async () => {
    let land!: (value: unknown) => void
    odin.setAutostart = vi.fn(() => new Promise((resolve) => { land = resolve }))
    const { root, state } = await general()
    root.findAll((node) => node.props.id === 'start-at-login')[0]!.fire('change', { target: { checked: true } })
    root.findAll((node) => node.props.name === 'appearance' && node.props.value === 'light')[0]!.fire('change')
    await flush()
    expect(odin.setAppearance).not.toHaveBeenCalled()
    expect(root.textContent()).toContain('Saving')
    land({ ok: false, error: { message: 'Outcome unknown.' } }); await flush()
    expect(odin.setAppearance).not.toHaveBeenCalled()
    expect(state.autostart).toBe(false)
    expect(root.textContent()).toContain('Outcome unknown.')
    root.findAll((node) => node.props.name === 'appearance' && node.props.value === 'dark')[0]!.fire('change'); await flush()
    expect(odin.setAppearance).toHaveBeenCalledWith('dark')
    expect(root.textContent()).toContain('Saved.')
  })
  it('keeps newer quiet drafts while deduping Enter/blur and validates time', async () => {
    let land!: (value: unknown) => void
    odin.setNotifications = vi.fn(() => new Promise((resolve) => { land = resolve }))
    const { root } = await general()
    const input = root.findAll((node) => node.props.id === 'quiet-hours-start')[0]!
    input.fire('input', { target: { value: '23:00' } }); input.fire('keydown', { key: 'Enter' }); input.fire('blur'); await flush()
    expect(odin.setNotifications).toHaveBeenCalledTimes(1)
    input.fire('input', { target: { value: '21:00' } })
    land(ok({ notifications: { enabled: true, previews: true, muted: [], quietHours: { enabled: true, start: '23:00', end: '08:00' } } })); await flush()
    expect(input.value).toBe('21:00')
    input.fire('input', { target: { value: 'bad' } }); input.fire('blur'); await flush()
    expect(root.textContent()).toContain('Enter a time in HH:MM format.')
    expect(odin.setNotifications).toHaveBeenCalledTimes(1)
  })
  it('retains searchable staged map entries with concrete-child metadata', async () => {
    const { settings } = await import('../../src/renderer/src/stores/settings')
    settings.meta = { fields: [{ path: 'openai_compatible.model_profiles.demo.max_output_tokens' }] } as never
    mounted = mount((await import('../../src/renderer/src/views/settings/Advanced.vue')).default)
    expect(mounted.root.textContent()).toContain('Custom model profiles')
    expect(mounted.root.textContent()).toContain('Read-only')
    const input = mounted.root.find('input')!
    input.type('not-existing'); await flush()
    expect(mounted.root.textContent()).toContain('No matching Advanced settings')
    input.type('host'); await flush()
    expect(mounted.root.textContent()).toContain('explicit permission-change confirmation')
    settings.meta = null; await flush()
    expect(mounted.root.textContent()).toContain('Loading Advanced settings.')
    settings.unavailable = true; await flush()
    expect(mounted.root.textContent()).not.toContain('Loading Advanced settings.')
  })
})
