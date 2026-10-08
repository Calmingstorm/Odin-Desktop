import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import type { ConfigField, ConfigMeta } from '../../src/shared/api'
import SettingEditor from '../../src/renderer/src/components/settings/SettingEditor.vue'
import SettingsRow from '../../src/renderer/src/components/settings/SettingsRow.vue'
import SettingsSection from '../../src/renderer/src/components/settings/SettingsSection.vue'
import SettingsSwitch from '../../src/renderer/src/components/settings/SettingsSwitch.vue'
import { settingsControlId } from '../../src/renderer/src/settings-accessibility'
import { saveField, resetField, settings } from '../../src/renderer/src/stores/settings'
import { flush, mount, type Host, type Mounted } from './component-host'

// Real compiled components and shared FieldDrafts; only the network-facing store writes are held.
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

  it('shows actionable invalid, drift and unknown states without a Ready promise', () => {
    for (const apply_state of ['invalid', 'drift', 'unknown'] as const) {
      const root = editor(field({ apply_state }))
      expect(root.textContent()).not.toContain('Ready')
      expect(root.find('input')).toBeDefined()
      expect(root.textContent()).toMatch(/Correct it|Check the value|Check the core connection/)
      if (apply_state === 'invalid') expect(root.find('input')!.props['aria-invalid']).toBe(true)
    }
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
    expect(unknown.textContent()).toContain('metadata is unsupported')
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
})
