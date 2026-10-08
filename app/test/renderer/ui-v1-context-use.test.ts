import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { flush, mount, type Mounted } from './component-host'
import type { ConfigField } from '../../src/shared/api'

const writes = vi.hoisted(() => ({ save: vi.fn(), reset: vi.fn() }))
let settings: any
vi.mock('../../src/renderer/src/stores/settings', () => ({ get settings() { return settings }, saveField: writes.save, resetField: writes.reset }))
let mounted: Mounted | undefined
const make = (extra: Partial<ConfigField> = {}): ConfigField => ({ path: 'openai_codex.context_utilization', desired: 60, effective: 60, type: 'integer', enum: null, constraints: { minimum: 30, maximum: 100 }, sensitivity: 'public', apply_handler: 'providers.codex.set', apply_state: 'applied', nullable: false, configured: null, ...extra } as ConfigField)
beforeEach(() => {
  vi.clearAllMocks()
  settings = reactive({ meta: { fields: [] }, fields: {} })
  writes.save.mockImplementation(async (field: ConfigField, value: unknown) => { settings.meta.fields = [{ ...field, desired: value }]; settings.fields[field.path] = { status: 'saved' }; return true })
})
afterEach(() => { mounted?.unmount(); mounted = undefined })
async function editor(field = make(), inMeta = true) {
  if (inMeta) settings.meta.fields = [field]
  mounted = mount((await import('../../src/renderer/src/components/settings/ContextUse.vue')).default, { field }); await flush()
  const root = mounted.root
  return { root, input: root.findAll((node) => node.tag === 'input')[0]! }
}
describe('Context percent editor', () => {
  it('formats canonical bounds and keeps input changes explicit, validates and cancels locally', async () => {
    const { root, input } = await editor()
    expect(root.textContent()).toContain('30% to 100%')
    expect(input.props['aria-describedby']).toContain('-description')
    input.type('101'); await flush()
    expect(writes.save).not.toHaveBeenCalled()
    root.button('Save').fire('click'); await flush()
    expect(root.textContent()).toContain('The highest is 100')
    expect(input.props['aria-invalid']).toBe(true)
    root.button('Cancel').fire('click'); await flush()
    expect(input.value).toBe('60')
    expect(root.findAll((node) => node.tag === 'button')).toHaveLength(0)
    input.type('90'); await flush(); root.button('Save').fire('click'); await flush()
    expect(writes.save).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ path: 'openai_codex.context_utilization' }), 90)
    expect(root.textContent()).toContain('Saved.')
  })
  it.each([
    [{ minimum: 40 }, 'At least 40%'], [{ maximum: 85 }, 'At most 85%'], [{}, 'Valid range unavailable']
  ])('does not invent absent bounds: %j', async (constraints, description) => {
    const { root, input } = await editor(make({ type: 'number', constraints: constraints as ConfigField['constraints'] }))
    expect(root.textContent()).toContain(description)
    expect(input.props.step).toBe('any')
  })
  it.each(['invalid', 'drift'] as const)('keeps %s state actionable without a readiness claim', async (apply_state) => {
    const { root } = await editor(make({ apply_state }), false)
    expect(root.textContent()).toContain(apply_state === 'invalid' ? 'This saved value is invalid' : 'The running value differs')
  })
  it('omits unknown applied-value warnings on untouched context settings', async () => {
    const { root, input } = await editor(make({ apply_state: 'unknown', effective: null }))
    expect(input.props.disabled).toBe(false)
    expect(root.textContent()).not.toMatch(/running value|Ready/i)
    expect(root.findAll((node) => node.props.class === 'warn')).toHaveLength(0)
    expect(writes.save).not.toHaveBeenCalled()
  })
  it.each([
    { apply_handler: 'unknown.owner' }, { type: 'string' }, { sensitivity: 'sensitive' }
  ] as Partial<ConfigField>[])('refuses unsupported field metadata %j', async (extra) => {
    const { root, input } = await editor(make(extra))
    expect(input.props.disabled).toBe(true)
    input.type('90'); await flush()
    expect(root.textContent()).toContain('Editing is unavailable')
    expect(root.findAll((node) => node.tag === 'button')).toHaveLength(0)
    expect(writes.save).not.toHaveBeenCalled()
  })
  it('preserves a newer draft during a held save, prevents duplicate dispatch and surfaces refused writes', async () => {
    const { root, input } = await editor()
    let settle!: (answer: boolean) => void
    writes.save.mockImplementationOnce(async () => { settings.fields['openai_codex.context_utilization'] = { status: 'saving' }; return new Promise<boolean>((resolve) => { settle = resolve }) })
    input.type('80'); await flush(); root.button('Save').fire('click'); await flush()
    expect(root.textContent()).toContain('Saving…')
    expect(root.button('Save').props.disabled).toBe(true)
    root.button('Save').fire('click'); await flush()
    expect(writes.save).toHaveBeenCalledTimes(1)
    input.type('90'); await flush()
    settings.fields['openai_codex.context_utilization'] = { status: 'error', message: 'Save unconfirmed. Refresh settings.' }
    settle(false); await flush()
    expect(input.value).toBe('90')
    expect(root.textContent()).toContain('Save unconfirmed')
  })
  it('commits on Enter/blur once, ignores IME and cancel-button blur intent', async () => {
    const { root, input } = await editor()
    const preventDefault = vi.fn()
    input.type('80'); await flush()
    input.fire('keydown', { key: 'Enter', isComposing: true, preventDefault }); await flush()
    input.fire('keydown', { key: 'ArrowDown', preventDefault }); await flush()
    input.fire('blur', { relatedTarget: { dataset: { settingsDraftAction: 'cancel' } } }); await flush()
    expect(writes.save).not.toHaveBeenCalled()
    input.fire('keydown', { key: 'Enter', isComposing: false, preventDefault }); await flush()
    input.fire('blur', { relatedTarget: null }); await flush()
    expect(writes.save).toHaveBeenCalledTimes(1)
    expect(preventDefault).toHaveBeenCalledOnce()
    input.type('90'); await flush(); input.fire('blur', { relatedTarget: null }); await flush()
    expect(writes.save).toHaveBeenCalledTimes(2)
    input.type('95'); await flush(); input.fire('blur', { relatedTarget: { dataset: { settingsDraftAction: 'save' } } }); await flush()
    root.button('Cancel').fire('click'); await flush()
    expect(input.value).toBe('90')
  })
  it('serializes newer Enter intent after the first receipt without replaying its blur', async () => {
    const { input } = await editor()
    let settle!: (answer: boolean) => void
    writes.save.mockImplementationOnce(async () => { settings.fields['openai_codex.context_utilization'] = { status: 'saving' }; return new Promise<boolean>((resolve) => { settle = resolve }) })
    const preventDefault = vi.fn()
    input.type('80'); await flush(); input.fire('keydown', { key: 'Enter', preventDefault }); await flush()
    input.fire('blur', { relatedTarget: null }); await flush()
    input.type('90'); await flush(); input.fire('keydown', { key: 'Enter', preventDefault }); await flush()
    expect(writes.save).toHaveBeenCalledTimes(1)
    settings.meta.fields = [make({ desired: 80 })]
    settings.fields['openai_codex.context_utilization'] = { status: 'saved' }
    settle(true); await flush()
    expect(writes.save.mock.calls.map(([, value]) => value)).toEqual([80, 90])
    expect(input.value).toBe('90')
  })
})
