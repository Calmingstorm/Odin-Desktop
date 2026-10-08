import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigField, ConfigMeta } from '../../src/shared/api'
import { flush, mount, type Host } from './component-host'

const ok = <T>(result: T) => ({ ok: true as const, result })
const ask = vi.fn(async (_request: unknown) => true)
vi.mock('../../src/renderer/src/dialog', () => ({ ask: (request: unknown) => ask(request) }))
let bridge: Record<string, ReturnType<typeof vi.fn>>
let fields: ConfigField[]
function field(path: string, type: ConfigField['type'] = 'boolean', desired: unknown = false, extra: Partial<ConfigField> = {}): ConfigField {
  return { path, section: path.split('.')[0]!, label: path, description: '', type, desired, effective: desired, default: desired, configured: true, sensitivity: 'public', apply_mode: 'hot', apply_handler: 'settings.set', apply_state: 'applied', constraints: {}, ...extra } as ConfigField
}
const meta = (): ConfigMeta => ({ revision: 'r1', fields }) as ConfigMeta
beforeEach(async () => {
  vi.resetModules()
  ask.mockReset().mockResolvedValue(true)
  fields = []
  bridge = {
    settingsSchema: vi.fn(async () => ok(meta())),
    settingsSet: vi.fn(async () => ok({ revision: 'r2', fields })),
    status: vi.fn(async () => ({ ok: false, error: { code: 'unavailable', message: 'offline' } })),
    secretsSet: vi.fn(async () => ok({ set: true })),
    secretsClear: vi.fn(async () => ok({ set: false })),
    toolsList: vi.fn(async () => ok({ tools: [{ name: 'read_file', description: 'Read a file.', enabled: true, state: 'available', input_schema: {} }], disabled_count: 0 })),
    toolsTimeoutsGet: vi.fn(async () => ok({ default_timeout: 30, overrides: { read_file: 10 } })),
    toolsTimeoutsSet: vi.fn(async () => ok({ default_timeout: 60, overrides: {} })),
    toolsSetEnabled: vi.fn(async () => ok({ tools: [], disabled_count: 1 })),
    computerStatus: vi.fn(async () => ok({ readiness: { management_available: true, foreground_available: false, native_qualified: false, input_supported: false, dispatch: 'none', reason: 'wayland_unavailable' }, session: null })),
    computerReconcile: vi.fn(async () => ok({ readiness: { management_available: true, foreground_available: false, dispatch: 'none', reason: 'quarantined' }, session: { session_id: 's1', generation: 3, state: 'quarantined', cleanup: { unknown_release: true }, recovery: { status: 'unknown', reason: 'owned_process_remaining', complete: false } } })),
    healthGet: vi.fn(async () => ok({ browser: { state: 'unconfigured', ready: false, reason: 'disabled' } })),
    memoryList: vi.fn(async () => ok({ global: { count: 0, keys: [] } })),
    memoryGet: vi.fn(async () => ok({ scope: 'global', entries: {} })),
    listsList: vi.fn(async () => ok({ items: [] })),
    knowledgeList: vi.fn(async () => ok([]))
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
  const store = await import('../../src/renderer/src/stores/settings')
  store.settings.meta = meta()
})
async function view(name: string) {
  const v = mount((await import(`../../src/renderer/src/views/settings/${name}.vue`)).default)
  await flush()
  return v
}
function input(root: Host, id: string): Host { return root.findAll((n) => n.props.id === id)[0]! }
async function install(next: ConfigField[]): Promise<void> {
  fields = next
  ;(await import('../../src/renderer/src/stores/settings')).settings.meta = meta()
}

describe('curated Tools', () => {
  it('reveals collapsed setup from restart links without enabling or saving', async () => {
    await install([field('browser.enabled'), field('email.enabled'), field('browser.cdp_url', 'string', ''), field('email.smtp.host', 'string', '')])
    const Tools = (await import('../../src/renderer/src/views/settings/Tools.vue')).default
    for (const [path, label] of [['browser.cdp_url', 'Existing browser address'], ['email.smtp.host', 'Outgoing mail server']]) {
      const v = mount(Tools, { reveal: `${path}:1` })
      await flush()
      expect(v.root.textContent()).toContain(label)
      expect(bridge.settingsSet).not.toHaveBeenCalled()
      v.unmount()
    }
  })
  it('keeps Configure actionable while disabled, excludes tuning, and never enables on opening setup', async () => {
    await install([field('tools.enabled'), field('browser.enabled'), field('email.enabled'), field('browser.cdp_url', 'string', ''), field('email.smtp.host', 'string', ''), field('email.smtp.port', 'integer', 587), field('email.max_body_chars', 'integer', 1000), field('computer.platform', 'string', 'x11')])
    const v = await view('Tools')
    v.root.named('Configure browser').fire('click')
    v.root.named('Configure email').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('Existing browser address')
    expect(v.root.textContent()).toContain('Outgoing mail server')
    expect(v.root.textContent()).not.toContain('Email body limit')
    expect(v.root.textContent()).not.toContain('computer.platform')
    const { settingsControlId } = await import('../../src/renderer/src/settings-accessibility')
    const address = input(v.root, settingsControlId('curated', 'email.smtp.host'))
    address.type('mail.example.org')
    address.fire('blur', { relatedTarget: null })
    address.fire('keydown', { key: 'Enter', preventDefault: () => undefined })
    await flush()
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    v.root.named('Save Outgoing mail server').fire('click')
    await flush()
    expect(bridge.settingsSet).toHaveBeenCalledWith({ expected_revision: 'r1', changes: [{ path: 'email.smtp.host', value: 'mail.example.org' }] })
  })

  it('uses real availability switches and actionable filter no-results', async () => {
    const v = await view('Tools')
    const toggle = v.root.findAll((n) => n.props.role === 'switch')[0]!
    expect(toggle.props['aria-label']).toBe('read_file on or off')
    toggle.fire('change', { target: { checked: false } })
    await flush()
    expect(bridge.toolsSetEnabled).toHaveBeenCalledWith({ name: 'read_file', enabled: false })
    input(v.root, 'tool-filter').type('not-a-tool')
    await flush()
    expect(v.root.textContent()).toContain('No matching tools.')
    v.root.button('Clear filter').fire('click')
    await flush()
    expect(v.setup.filter).toBe('')
  })

  it('retains consent, native unavailable guidance and unknown input-release quarantine', async () => {
    await install([field('computer.enabled')])
    bridge.computerStatus!.mockResolvedValue(ok({ readiness: { management_available: true, foreground_available: false, native_qualified: false, input_supported: false, dispatch: 'none', reason: 'wayland_unavailable' }, session: { session_id: 's1', generation: 3, state: 'quarantined', cleanup: { unknown_release: true }, recovery: { status: 'unknown', reason: 'controller_lost', complete: false } } }))
    const v = await view('Tools')
    expect(v.root.textContent()).toContain('not consent')
    expect(v.root.textContent()).toContain('Wayland input is not supported')
    expect(v.root.textContent()).toContain('Input release remains unverified.')
    v.root.named('Check recovery for session s1').fire('click')
    await flush()
    expect(bridge.computerReconcile).toHaveBeenCalledWith({ session_id: 's1', generation: 3 })
    expect(v.root.textContent()).toContain('quarantined')
    expect(v.root.textContent()).toContain('Input release remains unverified.')
    expect(bridge.settingsSet).not.toHaveBeenCalled()
  })

  it('cancels timeout drafts without writing', async () => {
    const v = await view('Tools')
    v.setup.defaultTimeout = '200'
    v.root.named('Cancel timeout changes').fire('click')
    await flush()
    expect(v.setup.defaultTimeout).toBe('30')
    expect(bridge.toolsTimeoutsSet).not.toHaveBeenCalled()
  })
})

describe('curated write-only email passwords', () => {
  it('blocks secret resubmission while a previous save outcome is unknown', async () => {
    const secret = field('email.smtp.password', 'string', null, { sensitivity: 'sensitive', secret_route: 'secrets.set', configured: true })
    await install([secret])
    ;(await import('../../src/renderer/src/stores/settings')).settings.unknownSave = true
    const v = mount((await import('../../src/renderer/src/components/settings/SecretControl.vue')).default, { field: secret, label: 'Outgoing mail password' })
    expect(v.root.find('input')!.props.disabled).toBe(true)
    v.root.find('input')!.type('must-not-submit')
    v.root.named('Replace outgoing mail password').fire('click')
    await flush()
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })

  it('stores only explicit intent, never reads back, preserves new typing and confirms removal', async () => {
    const secret = field('email.smtp.password', 'string', null, { sensitivity: 'sensitive', secret_route: 'secrets.set', configured: true })
    await install([secret])
    let settle!: (answer: unknown) => void
    bridge.secretsSet!.mockImplementationOnce(() => new Promise((resolve) => { settle = resolve }))
    const v = mount((await import('../../src/renderer/src/components/settings/SecretControl.vue')).default, { field: secret, label: 'Outgoing mail password', help: 'Store a new password.' })
    const password = v.root.find('input')!
    expect(password.value).toBe('')
    password.type('first-password')
    await flush()
    expect(bridge.secretsSet).not.toHaveBeenCalled()
    v.root.named('Replace outgoing mail password').fire('click')
    await flush()
    expect(password.value).toBe('')
    expect(password.props.disabled).toBe(false)
    password.type('new-unsaved-password')
    settle(ok({ set: true }))
    await flush()
    expect(bridge.secretsSet).toHaveBeenCalledExactlyOnceWith({ path: 'email.smtp.password', value: 'first-password' })
    expect(password.value).toBe('new-unsaved-password')
    expect(v.root.textContent()).not.toContain('first-password')
    ask.mockResolvedValueOnce(false)
    v.root.named('Remove outgoing mail password…').fire('click')
    await flush()
    expect(bridge.secretsClear).not.toHaveBeenCalled()
    v.root.named('Remove outgoing mail password…').fire('click')
    await flush()
    expect(bridge.secretsClear).toHaveBeenCalledExactlyOnceWith({ path: 'email.smtp.password' })
  })
})

describe('explicit browser access expansion', () => {
  it('confirms expansion, respects cancellation, and does not prompt on narrowing', async () => {
    await install([field('browser.allow_private_targets', 'array', ['127.0.0.1'])])
    const v = await view('Tools')
    v.root.named('Configure browser').fire('click')
    await flush()
    const textarea = v.root.find('textarea')!
    textarea.type('127.0.0.1\n192.168.1.13')
    await flush()
    ask.mockResolvedValueOnce(false)
    v.root.named('Save Private browser destinations').fire('click')
    await flush()
    expect(ask).toHaveBeenCalledWith(expect.objectContaining({ title: 'Change access policy?', confirmLabel: 'Save access changes', danger: true }))
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    v.root.named('Save Private browser destinations').fire('click')
    await flush()
    expect(bridge.settingsSet).toHaveBeenCalledWith({ expected_revision: 'r1', changes: [{ path: 'browser.allow_private_targets', value: ['127.0.0.1', '192.168.1.13'] }] })
    ask.mockClear()
    textarea.type('')
    await flush()
    v.root.named('Save Private browser destinations').fire('click')
    await flush()
    expect(ask).not.toHaveBeenCalled()
    expect(bridge.settingsSet).toHaveBeenCalledTimes(2)
  })
})

describe('Advanced allowlist', () => {
  it('reaches every allowlisted tuning field and structured container, never leftovers, and clears no-results', async () => {
    const { ADVANCED_FIELDS, ADVANCED_CATEGORIES } = await import('../../src/renderer/src/settings-presentation')
    await install([...ADVANCED_FIELDS.map((entry) => field(entry.path, 'integer', 30)), field('browser.default_timeout_ms', 'integer', 30)])
    const v = await view('Advanced')
    for (const entry of ADVANCED_FIELDS) expect(v.root.textContent()).toContain(entry.label)
    for (const category of ADVANCED_CATEGORIES) expect(v.root.textContent()).toContain(category)
    expect(v.root.textContent()).not.toContain('browser.default_timeout_ms')
    const search = v.root.findAll((n) => n.props.type === 'search')[0]!
    search.type('nothing-matches-this')
    await flush()
    expect(v.root.textContent()).toContain('No matching Advanced settings.')
    v.root.button('Clear search').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('Concurrent SSH commands')
  })
})

describe('Data and privacy nested state', () => {
  it('confirms one conversation deletion and respects Cancel without dispatch', async () => {
    const v = await view('DataPrivacy')
    ask.mockResolvedValueOnce(false)
    await (v.setup.removeConversation as (id: string, title: string) => Promise<void>)('private-id', 'My notes')
    expect(ask).toHaveBeenCalledWith(expect.objectContaining({ title: 'Delete this conversation?', message: '“My notes” and its messages are permanently deleted. Other conversations are not changed.', danger: true }))
  })

  it('retains scope management, conversations and policy without duplicate tuning', async () => {
    await install([field('learning.enabled'), field('sessions.archive_max_files', 'integer', 20), field('attachments.retention_hours', 'integer', 24)])
    const v = await view('DataPrivacy')
    expect(v.root.textContent()).toContain('Learning and search')
    expect(v.root.textContent()).toContain('Everywhere')
    v.root.named('Open Everywhere memory').fire('click')
    await flush()
    expect(bridge.memoryGet).toHaveBeenCalledWith({ scope: 'global' })
    v.root.button('Conversations').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('No conversations to show. Start a conversation in chat.')
    expect(v.root.textContent()).toContain('Archived conversation count')
    expect(v.root.textContent()).not.toContain('Attachment retention')
    expect(v.root.findAll((n) => n.tag === 'button' && n.textContent().includes('Export'))).toHaveLength(0)
  })
})
