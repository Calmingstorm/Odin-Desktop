// Structural regression coverage only. The Electron keyboard/axe suite qualifies actual focus and the AX tree.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import type { ConfigField } from '../../src/shared/api'
import { flush, mount, type Host } from './component-host'
import { settingsControlId } from '../../src/renderer/src/settings-accessibility'

const field = (path: string, extra: Partial<ConfigField> = {}): ConfigField => ({
  path, label: path, description: 'Description', type: 'string', enum: null, constraints: {}, default: null,
  nullable: false, sensitivity: 'public', apply_mode: 'live_read', apply_handler: null, restart_reason: null,
  activation_policy: null, consumers: [], save_effect: 'Saved for new requests.', runtime_effect: null,
  desired: 'saved', effective: 'saved', configured: true, pending_restart: false, apply_state: 'applied', ...extra
})

beforeEach(() => { vi.resetModules() })

function descriptions(root: Host, control: Host): Host[] {
  return String(control.props['aria-describedby']).split(' ').map((id) => {
    const found = root.findAll((node) => node.props.id === id)
    expect(found, `description ${id}`).toHaveLength(1)
    return found[0]!
  })
}

describe('P3.4 settings field semantics', () => {
  it('uses distinct IDs for paths that previously collapsed, including punctuation', () => {
    expect(settingsControlId('field', 'a.b')).not.toBe(settingsControlId('field', 'a-b'))
    expect(settingsControlId('field', 'a%2Eb')).not.toBe(settingsControlId('field', 'a.b'))
  })

  it('links every editor to its visible label, help, effect and relevant field error', async () => {
    const store = await import('../../src/renderer/src/stores/settings')
    const fields = [field('a.b'), field('a-b', { type: 'boolean', desired: true }),
      field('choices', { enum: ['saved'] }), field('object', { type: 'object', desired: {} }),
      field('secret', { sensitivity: 'sensitive', desired: true })]
    store.settings.fields['a.b'] = { status: 'error', message: 'Check this value.' }
    const Form = (await import('../../src/renderer/src/components/SchemaForm.vue')).default
    const { root, unmount } = mount(Form, { fields })
    await flush()
    const controls = root.findAll((node) => ['input', 'select', 'textarea'].includes(node.tag))
    expect(controls).toHaveLength(fields.length)
    for (const control of controls) {
      const labels = root.findAll((node) => node.tag === 'label' && node.props.for === control.props.id)
      expect(labels).toHaveLength(1)
      expect(labels[0]!.textContent()).toBeTruthy()
      expect(descriptions(root, control).map((node) => node.textContent())).toContain('Description')
      expect(control.props['aria-invalid']).toBe(control.props.id === settingsControlId('field', 'a.b'))
    }
    expect(descriptions(root, controls[0]!).map((node) => node.textContent())).toContain('Check this value.')
    expect(root.findAll((node) => node.tag === 'input' && node.props.type === 'password')[0]!.props.value).toBe('')
    expect(root.findAll((node) => node.tag === 'button' && node.textContent() === 'Save')[0]!.props['aria-label']).toBe('Save secret')
    unmount()
  })

  it('marks a rejected numeric draft invalid without rendering its value as error text', async () => {
    const store = await import('../../src/renderer/src/stores/settings')
    const f = field('timeout', { type: 'integer', desired: 5, constraints: { minimum: 1 } })
    store.settings.meta = { fields: [f] } as never
    const Form = (await import('../../src/renderer/src/components/SchemaForm.vue')).default
    const { root, unmount } = mount({ render: () => h(Form, { fields: [f] }) })
    root.find('input')!.fire('input', { target: { value: '0' } })
    root.find('input')!.fire('keydown', { key: 'Enter' })
    await flush()
    expect(root.find('input')!.props['aria-invalid']).toBe(true)
    expect(descriptions(root, root.find('input')!).map((node) => node.textContent())).toContain('The lowest is 1.')
    unmount()
  })

  it('includes the visible reset text in its contextual accessible name', async () => {
    const Form = (await import('../../src/renderer/src/components/SchemaForm.vue')).default
    const { root, unmount } = mount(Form, { fields: [field('timezone', { label: 'Timezone' })] })
    await flush()
    const reset = root.button('Reset to default')
    expect(reset.props['aria-label']).toBe('Reset to default: Timezone')
    expect(String(reset.props['aria-label'])).toContain(reset.textContent().trim())
    unmount()
  })
})

describe('P3.4 general and provider controls', () => {
  it('has one explicit label for each quiet-hours control, and reports notification failures', async () => {
    const store = await import('../../src/renderer/src/store')
    store.state.notifications = { enabled: true, previews: false, muted: [], quietHours: { enabled: true, start: '22:00', end: '07:00' } }
    const setNotifications = vi.fn(async () => ({ ok: false, error: { message: 'Could not save notifications.' } }))
    ;(globalThis as unknown as { window: unknown }).window = { odin: { setNotifications } }
    const General = (await import('../../src/renderer/src/views/settings/General.vue')).default
    const { root, unmount } = mount(General)
    for (const [id, text] of [['quiet-hours-enabled', 'Quiet hours'], ['quiet-hours-start', 'Quiet hours start'], ['quiet-hours-end', 'Quiet hours end']]) {
      const control = root.findAll((node) => node.props.id === id)[0]!
      expect(control).toBeTruthy()
      expect(root.findAll((node) => node.tag === 'label' && node.props.for === id).map((node) => node.textContent())).toEqual([text])
    }
    root.findAll((node) => node.props.id === 'quiet-hours-start')[0]!.fire('change', { target: { value: '23:00' } })
    expect(setNotifications).not.toHaveBeenCalled()
    root.findAll((node) => node.props.id === 'quiet-hours-start')[0]!.fire('blur')
    await flush()
    expect(setNotifications).toHaveBeenCalledWith({ quietHours: { start: '23:00' } })
    expect(root.findAll((node) => node.props.role === 'status').map((node) => node.textContent())).toContain('Could not save notifications.')
    unmount()
  })

  it('keeps sign-in codes out of live announcements and hides completed codes and device identifiers', async () => {
    ;(globalThis as unknown as { window: unknown }).window = { odin: {
      codexAccounts: async () => ({ ok: true, result: { configured: true, accounts: [] } }),
      copyText: vi.fn(async () => ({ ok: true, result: {} }))
    } }
    const store = await import('../../src/renderer/src/stores/settings')
    const Panel = (await import('../../src/renderer/src/components/CodexAccounts.vue')).default
    const { root, unmount } = mount(Panel)
    await flush()
    store.settings.codex.login = { code: 'ABCD-1234', url: 'https://example.com/login', loginId: 'opaque-local-login-handle',
      interval: 5, status: 'waiting' }
    await flush()
    expect(root.find('code')!.textContent()).toBe('ABCD-1234')
    expect(root.textContent()).not.toContain('opaque-local-login-handle')
    expect(root.findAll((node) => node.props.role === 'status').every((node) => !node.textContent().includes('ABCD-1234'))).toBe(true)
    root.button('Copy sign-in code').fire('click')
    await flush()
    expect(root.textContent()).toContain('Sign-in code copied.')
    store.settings.codex.login.status = 'done'
    store.settings.codex.login.message = 'Account added.'
    await flush()
    expect(root.textContent()).not.toContain('ABCD-1234')
    expect(root.findAll((node) => node.props.role === 'status').map((node) => node.textContent())).toContain('Account added.')
    unmount()
  })

  it('uses ordinary navigation buttons with a current section, not tabs without arrow-key behavior', async () => {
    const refused = async () => ({ ok: false, error: { code: 'capability_unavailable', message: 'Unavailable', disposition: 'not_dispatched' } })
    ;(globalThis as unknown as { window: unknown }).window = { odin: {
      settingsSchema: async () => ({ ok: true, result: { fields: [], status: { keyring_error: null } } }),
      memoryList: refused, listsList: refused, knowledgeList: refused,
      auditQuery: refused, usage: refused, healthGet: refused, logsSearch: refused, turnStateList: refused, computerStatus: refused
    } }
    const Settings = (await import('../../src/renderer/src/views/Settings.vue')).default
    const { root, unmount } = mount(Settings)
    await flush()
    expect(root.find('main')!.props['aria-label']).toBe('Settings')
    expect(root.find('h1')!.textContent()).toBe('Settings')
    expect(root.find('h2')!.props.id).toBe('settings-section-title')
    expect(root.find('nav')!.props['aria-label']).toBe('Settings sections')
    expect(root.button('General').props['aria-current']).toBe('page')
    expect(root.findAll((node) => node.tag === 'button' && String(node.props.class).includes('settings-nav-item')).map((node) => node.textContent().trim())).toEqual([
      'General', 'Models and providers', 'Personality', 'Tools', 'Skills', 'MCP servers', 'Hosts and access', 'Work', 'Data and privacy'
    ])
    expect(root.findAll((node) => node.props.role === 'tab')).toHaveLength(0)
    expect(root.findAll((node) => node.props['aria-label'] === 'General settings content')).toHaveLength(1)
    root.button('Data and privacy').fire('click')
    await flush()
    expect(root.findAll((node) => node.tag === 'nav' && node.props['aria-label'] === 'Data and privacy subsections')).toHaveLength(1)
    expect(root.button('Memory and knowledge').props['aria-current']).toBe('page')
    root.button('Usage, logs and audit').fire('click')
    await flush()
    expect(root.button('Usage, logs and audit').props['aria-current']).toBe('page')
    root.button('General').fire('click')
    await flush()
    root.button('Advanced settings').fire('click')
    await flush()
    expect(root.find('h2')!.textContent()).toBe('Advanced settings')
    expect(root.findAll((node) => node.props['aria-label'] === 'Advanced settings settings content')).toHaveLength(1)
    unmount()
  })
})
