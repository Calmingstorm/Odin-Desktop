import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import type { ConfigField, ConfigMeta } from '../../src/shared/api'
import SettingEditor from '../../src/renderer/src/components/settings/SettingEditor.vue'
import SettingsRow from '../../src/renderer/src/components/settings/SettingsRow.vue'
import SettingsSection from '../../src/renderer/src/components/settings/SettingsSection.vue'
import SettingsSwitch from '../../src/renderer/src/components/settings/SettingsSwitch.vue'
import { settingsControlId } from '../../src/renderer/src/settings-accessibility'
import { ask } from '../../src/renderer/src/dialog'
import { saveField, resetField, settings } from '../../src/renderer/src/stores/settings'
import { flush, mount, type Host, type Mounted } from './component-host'

// Real compiled components and shared FieldDrafts; only the network-facing store writes are held.
vi.mock('../../src/renderer/src/dialog', () => ({ ask: vi.fn() }))
vi.mock('../../src/renderer/src/stores/settings', async () => {
  const { reactive } = await import('vue')
  return {
    settings: reactive({ meta: null as ConfigMeta | null, fields: {} }),
    saveField: vi.fn(),
    resetField: vi.fn()
  }
})

function field(extra: Partial<ConfigField> = {}): ConfigField {
  return {
    path: 'timezone', label: 'Core label', description: 'Core description', type: 'string', enum: null,
    constraints: {}, default: 'UTC', nullable: false, sensitivity: 'public', apply_mode: 'live_read',
    apply_handler: null, restart_reason: null, activation_policy: null, consumers: [], save_effect: 'raw apply paragraph',
    runtime_effect: null, desired: 'UTC', effective: 'UTC', configured: true, pending_restart: false,
    apply_state: 'applied', ...extra
  }
}

let mounted: Mounted[]
let pending: Array<(success?: boolean) => void>
beforeEach(() => {
  mounted = []
  pending = []
  vi.clearAllMocks()
  settings.meta = { schema_version: 1, revision: '1', fields: [], status: { counts: {}, desired_revision: '1', effective_revision: '1' } }
  settings.fields = {}
  vi.mocked(saveField).mockImplementation((record, value) => {
    settings.fields[record.path] = { status: 'saving' }
    return new Promise((resolve) => pending.push((success = true) => {
      settings.fields[record.path] = success ? { status: 'saved' } : { status: 'error', message: 'The core rejected this value. Try again.' }
      if (success) settings.meta!.fields = settings.meta!.fields.map((f) => f.path === record.path ? { ...f, desired: value, effective: value, apply_state: 'applied' } : f)
      resolve(success)
    }))
  })
})
afterEach(() => mounted.forEach((m) => m.unmount()))
function editor(record = field(), extra: Record<string, unknown> = {}): Host {
  settings.meta!.fields = [record]
  const result = mount(SettingEditor, { field: record, label: 'Time zone', help: 'Choose your local time zone.', ...extra })
  mounted.push(result)
  return result.root
}
function key(input: Host, value: string): void {
  input.fire('keydown', { key: value, preventDefault: vi.fn() })
}
async function land(success = true): Promise<void> {
  pending.shift()!(success)
  await flush()
}

describe('shared settings building blocks', () => {
  it('renders semantic section and row slots without raw technical paragraphs', () => {
    const result = mount({ render: () => h(SettingsSection, { title: 'Time', description: 'Local preferences' }, {
      default: () => h(SettingsRow, { label: 'Time zone', description: 'Choose a region', controlId: 'zone', fullWidth: true }, {
        default: () => h('input', { id: 'zone' }), note: () => h('p', 'A useful note')
      })
    }) })
    mounted.push(result)
    expect(result.root.find('section')?.props.class).toBe('settings-section')
    expect(result.root.find('h3')?.textContent()).toBe('Time')
    expect(result.root.find('label')?.props.for).toBe('zone')
    expect(result.root.findAll((n) => String(n.props.class).includes('settings-card'))).toHaveLength(1)
    expect(result.root.findAll((n) => String(n.props.class).includes('settings-row-full-width'))).toHaveLength(1)
    expect(result.root.textContent()).toContain('A useful note')
  })

  it('uses a native labeled switch with attrs passthrough and only native change semantics', () => {
    const change = vi.fn()
    const result = mount(SettingsSwitch, { id: 'enable', label: 'Enable learning', checked: false,
      disabled: true, invalid: true, describedBy: 'enable-help', 'data-testid': 'native-switch', onChange: change })
    mounted.push(result)
    const input = result.root.find('input')!
    expect(input.props).toMatchObject({ id: 'enable', type: 'checkbox', role: 'switch', disabled: true,
      'aria-label': 'Enable learning', 'aria-describedby': 'enable-help', 'aria-invalid': true, 'data-testid': 'native-switch' })
    expect(input.props.onKeydown).toBeUndefined()
    input.fire('change', { target: { checked: true } })
    expect(change).toHaveBeenCalledWith(true)
  })
})

describe('SettingEditor writes only deliberate drafts', () => {
  it('keeps newer typing after a deferred save and deduplicates Enter then blur', async () => {
    const root = editor()
    const input = root.find('input')!
    expect(input.props.id).toBe(settingsControlId('curated', 'timezone'))
    expect(root.find('label')?.props.for).toBe(input.props.id)
    input.type('Europe/Paris')
    await flush()
    expect(root.textContent()).toContain('Unsaved changes')
    key(input, 'Enter')
    input.fire('blur')
    await flush()
    expect(root.textContent()).toContain('Saving')
    input.type('Asia/Tokyo')
    await land()
    expect(saveField).toHaveBeenCalledTimes(1)
    expect(input.props.value).toBe('Asia/Tokyo')
    expect(root.textContent()).toContain('Unsaved changes')
    expect(root.textContent()).not.toContain('Saved')
    root.button('Save').fire('click')
    await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ path: 'timezone' }), 'Asia/Tokyo')
    expect(root.textContent()).toContain('Saved')
    expect(root.textContent()).not.toContain('Unsaved changes')
    expect(root.textContent()).not.toContain('timezone')
    expect(root.textContent()).not.toContain('raw apply paragraph')
    expect(resetField).not.toHaveBeenCalled()
  })

  it('commits short text on blur but Cancel does not blur-save or reset to defaults', async () => {
    const root = editor(field({ desired: 'Europe/Paris' }))
    const input = root.find('input')!
    input.type('Asia/Tokyo')
    await flush()
    input.fire('blur', { relatedTarget: { dataset: { settingsDraftAction: 'cancel' } } })
    root.button('Cancel').fire('click')
    await flush()
    expect(input.props.value).toBe('Europe/Paris')
    expect(saveField).not.toHaveBeenCalled()
    expect(resetField).not.toHaveBeenCalled()
    input.type('America/New_York')
    input.fire('blur')
    await land()
    expect(saveField).toHaveBeenCalledTimes(1)
  })

  it('cancels queued intent without pretending an in-flight save was undone', async () => {
    const root = editor()
    const input = root.find('input')!
    input.type('Europe/Paris')
    key(input, 'Enter')
    input.type('Asia/Tokyo')
    key(input, 'Enter')
    await flush()
    root.button('Cancel').fire('click')
    await land()
    expect(saveField).toHaveBeenCalledTimes(1)
    expect(input.props.value).toBe('Europe/Paris')
    expect(root.textContent()).not.toContain('Unsaved changes')
  })

  it('does not silently drain a queued draft after a failed write', async () => {
    const root = editor()
    const input = root.find('input')!
    input.type('Europe/Paris')
    key(input, 'Enter')
    input.type('Asia/Tokyo')
    key(input, 'Enter')
    await land(false)
    expect(saveField).toHaveBeenCalledTimes(1)
    expect(input.props.value).toBe('Asia/Tokyo')
    expect(root.textContent()).toContain('Try again')
    expect(root.textContent()).toContain('Unsaved changes')
    root.button('Save').fire('click')
    await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ path: 'timezone' }), 'Asia/Tokyo')
  })

  it('never saves long text on input, Enter, or blur; explicit Save and Cancel own it', async () => {
    const root = editor(field({ path: 'personality.text', desired: 'Original' }), { editor: 'long' })
    const area = root.find('textarea')!
    area.type('First line\nSecond line')
    await flush()
    expect(area.props.onBlur).toBeUndefined()
    expect(area.props.onKeydown).toBeUndefined()
    expect(saveField).not.toHaveBeenCalled()
    root.button('Cancel').fire('click')
    await flush()
    expect(area.props.value).toBe('Original')
    area.type('New text')
    await flush()
    root.button('Save').fire('click')
    await land()
    expect(saveField).toHaveBeenCalledWith(expect.objectContaining({ path: 'personality.text' }), 'New text')
  })

  it('saves boolean and enum only on deliberate change', async () => {
    const root = editor(field({ type: 'boolean', desired: false }))
    expect(saveField).not.toHaveBeenCalled()
    const input = root.find('input')!
    expect(input.props.role).toBe('switch')
    input.fire('change', { target: { checked: true } })
    await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'boolean' }), true)
    const selectRoot = editor(field({ path: 'choice', desired: 'a', enum: ['a', 'b'] }))
    const select = selectRoot.find('select')!
    expect(select.options.map((option) => option.props.value)).toEqual(['a', 'b'])
    expect(saveField).toHaveBeenCalledTimes(1)
    select.fire('change', { target: { value: 'b' } })
    await land()
    expect(saveField).toHaveBeenCalledTimes(2)
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ path: 'choice' }), 'b')
  })

  it('retains deliberate switch choices made while the first save is pending', async () => {
    const root = editor(field({ type: 'boolean', desired: false }))
    const input = root.find('input')!
    input.fire('change', { target: { checked: true } })
    input.fire('change', { target: { checked: false } })
    await land()
    expect(saveField).toHaveBeenCalledTimes(2)
    await land()
    expect(input.props.checked).toBe(false)
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'boolean' }), false)
  })

  it('does not visually substitute the first enum option for an unsupported saved value', async () => {
    const root = editor(field({ enum: ['a', 'b'], desired: 'removed', apply_state: 'invalid' }))
    const select = root.find('select')!
    expect(select.props.value).toBe('removed')
    expect(select.options[0]!.props).toMatchObject({ value: 'removed', disabled: '' })
    expect(select.options[0]!.textContent()).toContain('Choose a supported value')
    expect(saveField).not.toHaveBeenCalled()
    select.fire('change', { target: { value: 'a' } })
    await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ enum: ['a', 'b'] }), 'a')
  })

  it('uses numeric core constraints, reports local invalid drafts and gives a retry after core errors', async () => {
    const root = editor(field({ type: 'integer', desired: 3, constraints: { minimum: 1, maximum: 8 } }))
    const input = root.find('input')!
    expect(input.props).toMatchObject({ type: 'number', min: 1, max: 8, step: 1 })
    input.type('99')
    key(input, 'Enter')
    await flush()
    expect(saveField).not.toHaveBeenCalled()
    expect(input.props['aria-invalid']).toBe(true)
    expect(root.textContent()).toContain('The highest is 8')
    const errorNode = root.findAll((n) => String(n.props.class).includes('settings-editor-error'))[0]!
    expect(input.props['aria-describedby']).toContain(errorNode.props.id)
    input.type('4')
    key(input, 'Enter')
    await land(false)
    expect(root.textContent()).toContain('The core rejected this value. Try again.')
    expect(input.props.value).toBe('4')
    root.button('Save').fire('click')
    await land()
    expect(saveField).toHaveBeenCalledTimes(2)
    expect(root.textContent()).toContain('Saved')
  })

  it('shows actionable invalid and drift states without a Ready promise', () => {
    for (const apply_state of ['invalid', 'drift'] as const) {
      const root = editor(field({ apply_state }))
      expect(root.textContent()).not.toContain('Ready')
      expect(root.find('input')).toBeDefined()
      expect(root.textContent()).toMatch(/Correct it|Check the value/)
      if (apply_state === 'invalid') expect(root.find('input')!.props['aria-invalid']).toBe(true)
    }
  })

  it('keeps unknown running values editable without a warning or readiness promise', () => {
    const root = editor(field({ apply_state: 'unknown', effective: null }))
    expect(root.find('input')).toBeDefined()
    expect(root.textContent()).not.toMatch(/running value|Check the connection|Ready/i)
    expect(root.findAll((node) => node.props.class === 'settings-help')).toHaveLength(0)
  })

  it('respects short text constraints and ignores IME Enter', async () => {
    const root = editor(field({ constraints: { min_length: 3, max_length: 6 } }))
    const input = root.find('input')!
    expect(input.props).toMatchObject({ minlength: 3, maxlength: 6 })
    input.type('aa')
    input.fire('keydown', { key: 'Enter', isComposing: true, preventDefault: vi.fn() })
    await flush()
    expect(saveField).not.toHaveBeenCalled()
    expect(root.textContent()).not.toContain('characters')
    key(input, 'Enter')
    await flush()
    expect(root.textContent()).toContain('at least 3 characters')
    input.type('Too long for the core')
    key(input, 'Enter')
    await flush()
    expect(root.textContent()).toContain('no more than 6 characters')
    expect(saveField).not.toHaveBeenCalled()
  })

  it('uses structured metadata for a long JSON draft without copying routes', async () => {
    const root = editor(field({ type: 'object', desired: { enabled: true } }))
    const area = root.find('textarea')!
    area.type('{"enabled":false}')
    await flush()
    root.button('Save').fire('click')
    await land()
    expect(saveField).toHaveBeenCalledWith(expect.objectContaining({ type: 'object' }), { enabled: false })
  })

  it('does not invent edits for unknown metadata or fields owned by dedicated controls', () => {
    const unknown = editor(field({ type: 'future-shape' }))
    expect(unknown.find('input')).toBeUndefined()
    expect(unknown.textContent()).toContain('Editing is unavailable')
    expect(unknown.textContent()).not.toContain('Ready')
    const readonly = editor(field({ apply_handler: 'future.dedicated.method', desired: 'Managed elsewhere' }))
    expect(readonly.find('input')).toBeUndefined()
    expect(readonly.textContent()).toContain('Read-only here')
    expect(readonly.textContent()).toContain('Managed elsewhere')
    expect(saveField).not.toHaveBeenCalled()
  })

  it('never shows secret values or a generic write control', () => {
    const root = editor(field({ sensitivity: 'sensitive', desired: 'private-value', effective: 'also-private' }))
    expect(root.find('input')).toBeUndefined()
    expect(root.find('textarea')).toBeUndefined()
    expect(root.textContent()).not.toContain('private')
    expect(root.textContent()).toContain('Secret support unavailable')
    expect(root.textContent()).toContain('dedicated secret controls')
    expect(saveField).not.toHaveBeenCalled()
  })

  it('stages explicitly saved short fields without blur or change writes', async () => {
    const root = editor(field({ path: 'email.smtp.host', desired: 'old.example' }), { commit: 'explicit' })
    const input = root.find('input')!
    input.type('new.example'); key(input, 'Enter'); input.fire('blur'); await flush()
    expect(saveField).not.toHaveBeenCalled()
    root.button('Save').fire('click'); await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ path: 'email.smtp.host' }), 'new.example')
  })

  it('edits structured budget rows explicitly and preserves newer drafts', async () => {
    const root = editor(field({ path: 'sessions.context_budget_overrides', type: 'object', desired: { model: 100 } }))
    expect(root.find('textarea')).toBeUndefined()
    const input = root.findAll((node) => node.tag === 'input')[0]!
    input.type('200'); await flush()
    expect(input.props.onBlur).toBeUndefined(); expect(input.props.onKeydown).toBeUndefined()
    expect(saveField).not.toHaveBeenCalled()
    root.button('Save').fire('click'); input.type('300'); await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ path: 'sessions.context_budget_overrides' }), { model: 200 })
    expect(root.findAll((node) => node.tag === 'input')[0]!.props.value).toBe(300)
    expect(root.textContent()).toContain('Unsaved changes')
    root.button('Save').fire('click'); await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.anything(), { model: 300 })
  })

  it('does not save invalid structured drafts and requires policy confirmation', async () => {
    const root = editor(field({ path: 'openai_codex.context_budget_overrides', type: 'object', desired: { model: 100 } }))
    root.findAll((node) => node.tag === 'input')[0]!.type('not a number'); await flush()
    root.button('Save').fire('click'); await flush()
    expect(saveField).not.toHaveBeenCalled()
    expect(root.textContent()).toContain('Enter a whole number')
    const policy = editor(field({ path: 'tools.governor.host_overrides', type: 'object', desired: { server: 'strict' } }))
    vi.mocked(ask).mockResolvedValue(null)
    policy.findAll((node) => node.tag === 'input')[0]!.type(''); await flush()
    policy.button('Save').fire('click'); await flush()
    expect(ask).toHaveBeenCalledTimes(1)
    expect(saveField).not.toHaveBeenCalled()
    vi.mocked(ask).mockResolvedValue(true)
    policy.button('Save').fire('click'); await flush(); await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ path: 'tools.governor.host_overrides' }), { server: '' })
  })

  it('asks before mail verification exceptions and fences changed revisions during confirmation', async () => {
    const root = editor(field({ path: 'email.tls_verify', type: 'boolean', desired: true }))
    let confirm!: (answer: true | null) => void
    vi.mocked(ask).mockImplementation(() => new Promise((resolve) => { confirm = resolve }))
    root.find('input')!.fire('change', { target: { checked: false } }); await flush()
    expect(saveField).not.toHaveBeenCalled()
    expect(ask).toHaveBeenCalledWith(expect.objectContaining({ danger: true }))
    settings.meta!.revision = '2'
    confirm(true); await flush()
    expect(saveField).not.toHaveBeenCalled()
    expect(root.textContent()).toContain('Settings changed')
    root.button('Cancel').fire('click'); await flush()
    expect(root.find('input')!.props.checked).toBe(true)
  })

  it('never confirms a newer draft in place of the one shown in the access dialog', async () => {
    const root = editor(field({ path: 'email.allowed_attachment_dirs', type: 'array', desired: ['/saved'], default: [] }))
    let confirm!: (answer: true | null) => void
    vi.mocked(ask).mockImplementation(() => new Promise((resolve) => { confirm = resolve }))
    root.find('textarea')!.type('/saved\n/new'); await flush()
    root.button('Save').fire('click'); await flush()
    root.find('textarea')!.type('/saved\n/different'); await flush()
    confirm(true); await flush()
    expect(saveField).not.toHaveBeenCalled()
    expect(root.find('textarea')!.props.value).toBe('/saved\n/different')
    expect(root.textContent()).toContain('Unsaved changes')
  })

  it('edits profile records using member constraints and preserves other records', async () => {
    const profile = { total_window_tokens: 1000, max_output_tokens: 100, supports_reasoning: true }
    const record = field({ path: 'openai_compatible.model_profiles', type: 'object', desired: { first: profile, second: profile }, apply_handler: 'providers.compat.set' })
    const root = editor(record)
    settings.meta!.fields.push(
      field({ path: 'openai_compatible.model_profiles.first.total_window_tokens', type: 'integer', desired: 1000, constraints: { minimum: 1 } }),
      field({ path: 'openai_compatible.model_profiles.first.max_output_tokens', type: 'integer', desired: 100, constraints: { minimum: 1 } }),
      field({ path: 'openai_compatible.model_profiles.first.supports_reasoning', type: 'boolean', desired: true })
    )
    await flush()
    expect(root.find('textarea')).toBeUndefined()
    const input = root.findAll((node) => node.tag === 'input' && node.props.type === 'number')[0]!
    expect(input.props.min).toBe(1)
    input.type('0'); await flush(); root.button('Save').fire('click'); await flush()
    expect(saveField).not.toHaveBeenCalled()
    expect(root.textContent()).toContain('The lowest is 1')
    input.type('2000'); await flush(); root.button('Save').fire('click'); await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ apply_handler: 'providers.compat.set' }), {
      first: { ...profile, total_window_tokens: 2000 }, second: profile
    })
    expect(root.textContent()).not.toContain('total_window_tokens')
    expect(root.textContent()).not.toContain('supports_reasoning')
  })

  it('adds, removes and cancels budget records without hidden saves', async () => {
    const root = editor(field({ path: 'sessions.context_budget_overrides', type: 'object', desired: {} }))
    expect(root.textContent()).toContain('No entries yet')
    root.find('input')!.type('new-model'); await flush(); root.button('Add entry').fire('click'); await flush()
    expect(root.textContent()).toContain('new-model')
    expect(root.textContent()).toContain('Enter a whole number')
    root.findAll((node) => node.tag === 'input' && node.props.type === 'number')[0]!.type('500'); await flush()
    root.findAll((node) => node.tag === 'input' && node.props.type === 'text')[0]!.type('new-model'); await flush()
    root.button('Add entry').fire('click'); await flush()
    expect(root.textContent()).toContain('Enter a new, unique name')
    root.button('Remove entry').fire('click'); await flush()
    expect(saveField).not.toHaveBeenCalled()
    root.find('input')!.type('another-model'); await flush(); root.button('Add entry').fire('click'); await flush()
    root.button('Cancel').fire('click'); await flush()
    expect(root.textContent()).toContain('No entries yet')
    expect(root.textContent()).not.toContain('Enter a whole number')
  })

  it('does not invent member schemas for empty custom profiles', async () => {
    const root = editor(field({ path: 'openai_compatible.model_profiles', type: 'object', desired: {} }))
    expect(root.button('Add entry').props.disabled).toBe(true)
    expect(saveField).not.toHaveBeenCalled()
  })

  it('creates the first profile from authoritative member facts without child records', async () => {
    const root = editor(field({ path: 'openai_compatible.model_profiles', type: 'object', desired: {}, apply_handler: 'providers.compat.set', record_members: [
      { path: 'openai_compatible.model_profiles.total_window_tokens', type: 'integer', enum: null, constraints: { minimum: 1 }, default: null, nullable: false, sensitivity: 'public' },
      { path: 'openai_compatible.model_profiles.max_output_tokens', type: 'integer', enum: null, constraints: { minimum: 1 }, default: null, nullable: false, sensitivity: 'public' }
    ] }))
    expect(root.button('Add entry').props.disabled).toBe(false)
    root.find('input')!.type('first-model'); await flush(); root.button('Add entry').fire('click'); await flush()
    const inputs = root.findAll((node) => node.tag === 'input' && node.props.type === 'number')
    inputs[0]!.type('1000'); inputs[1]!.type('100'); await flush()
    root.button('Save').fire('click'); await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.objectContaining({ apply_handler: 'providers.compat.set' }), { 'first-model': { total_window_tokens: 1000, max_output_tokens: 100 } })
  })

  it('stages a new profile with all member controls and validates required numeric members', async () => {
    const root = editor(field({ path: 'openai_compatible.model_profiles', type: 'object', desired: {} }))
    settings.meta!.fields.push(
      field({ path: 'openai_compatible.model_profiles.sample.total_window_tokens', type: 'integer', constraints: { minimum: 1 }, desired: 100 }),
      field({ path: 'openai_compatible.model_profiles.sample.max_output_tokens', type: 'integer', constraints: { minimum: 1 }, desired: 10 }),
      field({ path: 'openai_compatible.model_profiles.sample.selection_hint', nullable: true, desired: null }),
      field({ path: 'openai_compatible.model_profiles.sample.supports_thinking_mode', type: 'boolean', desired: false }),
      field({ path: 'openai_compatible.model_profiles.sample.supported_efforts', type: 'array', default: [], desired: ['low'] }),
      field({ path: 'openai_compatible.model_profiles.sample.supports_reasoning', type: 'string', enum: ['yes', 'no'], desired: 'no' })
    )
    await flush(); root.find('input')!.type('new-model'); await flush(); root.button('Add entry').fire('click'); await flush()
    expect(root.textContent()).toContain('Enter a number')
    const numbers = root.findAll((node) => node.tag === 'input' && node.props.type === 'number')
    numbers[0]!.type('200'); await flush(); numbers[1]!.type('20'); await flush()
    root.findAll((node) => node.tag === 'input' && node.props.type === 'checkbox')[0]!.fire('change', { target: { checked: true } }); await flush()
    root.find('textarea')!.type('low\nhigh'); await flush()
    root.find('select')!.fire('change', { target: { value: 'yes' } }); await flush()
    root.button('Save').fire('click'); await land()
    expect(saveField).toHaveBeenLastCalledWith(expect.anything(), { 'new-model': {
      total_window_tokens: 200, max_output_tokens: 20, supports_thinking_mode: true, supported_efforts: ['low', 'high'], supports_reasoning: 'yes'
    } })
  })
})
