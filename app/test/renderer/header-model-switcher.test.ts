import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, Host, type Mounted } from './component-host'
import type { ConfigField } from '../../src/shared/api'

const ok = (result: unknown) => ({ ok: true, result })
const field = (path: string, desired: unknown): ConfigField => ({ path, desired, effective: desired, type: typeof desired, enum: null, constraints: {}, sensitivity: 'public', apply_handler: path === 'llm_provider.model' ? 'models.main.set' : 'providers.codex.set', apply_state: 'applied', nullable: false, configured: null } as ConfigField)
const row = (ref: string, values: string[] | null) => ({ ref, name: ref, effort_capabilities: { values, restrictions_known: values !== null, source: 'core_validation' } })
let mounted: Mounted | undefined, bridge: Record<string, any>, listeners: Record<string, any>, settings: any, state: any
const control = (id: string): Host => mounted!.root.findAll((node) => node.props.id === id)[0]!
beforeEach(async () => {
  vi.resetModules()
  listeners = {}
  vi.stubGlobal('document', { activeElement: null, addEventListener: vi.fn((name, fn) => { listeners[name] = fn }), removeEventListener: vi.fn((name) => { delete listeners[name] }) })
  bridge = {
    settingsSchema: vi.fn(async () => ok(settings.meta)),
    modelsStatus: vi.fn(async () => ok({ model_catalogue: { codex: [row('gpt-6.1-sol', ['low', 'high']), row('gpt-6-luna', ['high', 'xhigh'])], compat: [row('compat:no-effort', []), row('compat:unknown', null)], ollama: [row('ollama:local', [])] } })),
    editLeaf: vi.fn(async ({ params }: any) => { settings.meta.fields.find((item: ConfigField) => item.path === 'llm_provider.model').desired = params.model; return ok({ status: 'updated' }) }),
    status: vi.fn(async () => ({ ok: false, error: { code: 'unavailable', message: 'Unavailable' } })),
    usage: vi.fn(async () => ({ ok: false, error: { code: 'unavailable', message: 'Unavailable' } }))
  }
  vi.stubGlobal('window', { odin: bridge })
  ;({ settings } = await import('../../src/renderer/src/stores/settings'))
  ;({ state } = await import('../../src/renderer/src/store'))
  settings.meta = { revision: 'r1', schema_version: 1, status: { counts: {} }, fields: [field('llm_provider.model', 'gpt-6.1-sol'), field('openai_codex.enabled', true), field('openai_compatible.enabled', false), field('ollama.enabled', false), field('openai_codex.reasoning_effort', 'high'), field('openai_compatible.reasoning_effort', 'low')] }
  mounted = mount((await import('../../src/renderer/src/components/HeaderModelSwitcher.vue')).default, { model: { main: 'gpt-6.1-sol', effort: 'high', provider: 'codex' } })
  await flush()
})
afterEach(() => { mounted?.unmount(); mounted = undefined; vi.unstubAllGlobals() })
async function open(): Promise<void> { mounted!.root.named('Change main model and reasoning effort: gpt-6.1-sol · high').fire('click'); await flush() }
describe('header main model atomic switcher', () => {
  it('preserves an off saved selection but offers only enabled alternatives, cancel does not write', async () => {
    settings.meta.fields[0].desired = 'compat:no-effort'
    await open()
    expect(control('header-model').props.value).toBe('compat:no-effort')
    expect(control('header-model').options.map((node) => [node.props.value, node.props.disabled])).toEqual([['compat:no-effort', true], ['gpt-6.1-sol', false], ['gpt-6-luna', false]])
    expect(mounted!.root.textContent()).toContain('OpenAI-compatible is off. This saved selection is kept.')
    expect(mounted!.root.button('Save').props.disabled).toBe(true)
    mounted!.root.button('Cancel').fire('click'); await flush()
    expect(bridge.editLeaf).not.toHaveBeenCalled()
  })
  it('never picks an invalid effort automatically and disables unknown effort saves', async () => {
    settings.meta.fields.find((item: ConfigField) => item.path === 'openai_codex.reasoning_effort').desired = 'low'
    await open()
    control('header-model').fire('change', { target: { value: 'gpt-6-luna' } }); await flush()
    expect(control('header-effort').props.value).toBe('low')
    expect(control('header-effort').options[0]!.props.disabled).toBeDefined()
    expect(mounted!.root.button('Save').props.disabled).toBe(true)
    settings.meta.fields.find((item: ConfigField) => item.path === 'openai_compatible.enabled').desired = true
    control('header-model').fire('change', { target: { value: 'compat:unknown' } }); await flush()
    expect(control('header-effort').props.disabled).toBe(true)
    expect(mounted!.root.textContent()).toContain('Supported effort choices are not known')
    expect(mounted!.root.button('Save').props.disabled).toBe(true)
  })
  it('saves a model without effort capabilities with no invented effort argument', async () => {
    settings.meta.fields.find((item: ConfigField) => item.path === 'openai_compatible.enabled').desired = true
    await open(); control('header-model').fire('change', { target: { value: 'compat:no-effort' } }); await flush()
    expect(mounted!.root.findAll((node) => node.props.id === 'header-effort')).toHaveLength(0)
    mounted!.root.button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledWith({ method: 'models.main.set', params: { model: 'compat:no-effort', expected_revision: 'r1' } })
  })
  it('closes on Escape, outside click and core changes, unregistering listeners', async () => {
    await open()
    const preventDefault = vi.fn(), stopPropagation = vi.fn()
    listeners.keydown({ key: 'Escape', preventDefault, stopPropagation }); await flush()
    expect(preventDefault).toHaveBeenCalledOnce(); expect(stopPropagation).toHaveBeenCalledOnce()
    expect(mounted!.root.findAll((node) => node.props.role === 'dialog')).toHaveLength(0)
    await open(); listeners.pointerdown({ target: new Host('outside') }); await flush()
    expect(mounted!.root.findAll((node) => node.props.role === 'dialog')).toHaveLength(0)
    await open(); state.recoveryEpoch++; await flush()
    expect(mounted!.root.findAll((node) => node.props.role === 'dialog')).toHaveLength(0)
    mounted!.unmount(); mounted = undefined
    expect(listeners).toEqual({})
    expect(bridge.editLeaf).not.toHaveBeenCalled()
  })
  it('shows errors inline and keeps the draft for deliberate retry', async () => {
    bridge.editLeaf.mockResolvedValue({ ok: false, error: { code: 'validation', message: 'Rejected pair' } })
    await open(); mounted!.root.button('Save').fire('click'); await flush()
    expect(mounted!.root.findAll((node) => node.props.role === 'alert')[0]!.textContent()).toBe('Rejected pair')
    expect(control('header-model').props.value).toBe('gpt-6.1-sol')
    expect(bridge.editLeaf).toHaveBeenCalledOnce()
  })
  it('reports an unknown save outcome rather than a stale field error and never retries it', async () => {
    bridge.editLeaf.mockResolvedValue({ ok: false, error: { code: 'outcome_unknown', disposition: 'outcome_unknown', message: 'Old field message' } })
    await open(); mounted!.root.button('Save').fire('click'); await flush()
    expect(mounted!.root.findAll((node) => node.props.role === 'alert')[0]!.textContent()).toContain('The save outcome could not be confirmed')
    expect(bridge.editLeaf).toHaveBeenCalledOnce()
  })
  it('does not reopen a cancelled popup when its in-flight save settles', async () => {
    let resolve!: (value: unknown) => void
    bridge.editLeaf.mockImplementation(() => new Promise((done) => { resolve = done }))
    await open(); mounted!.root.button('Save').fire('click'); await flush()
    expect(mounted!.root.button('Saving…').props.disabled).toBe(true)
    mounted!.root.button('Cancel').fire('click'); await flush()
    resolve(ok({ status: 'updated' })); await flush()
    expect(mounted!.root.findAll((node) => node.props.role === 'dialog')).toHaveLength(0)
    expect(bridge.editLeaf).toHaveBeenCalledOnce()
  })
  it.each(['read-error', 'read-throw', 'no-method', 'settings-error', 'empty'])('reports %s without allowing a write', async (failure) => {
    if (failure === 'read-error') bridge.modelsStatus.mockResolvedValue({ ok: false, error: { message: 'Read failed' } })
    if (failure === 'read-throw') bridge.modelsStatus.mockRejectedValue(new Error('offline'))
    if (failure === 'no-method') delete bridge.modelsStatus
    if (failure === 'settings-error') bridge.settingsSchema.mockResolvedValue({ ok: false, error: { code: 'offline', message: 'Settings failed' } })
    if (failure === 'empty') bridge.modelsStatus.mockResolvedValue(ok({}))
    await open()
    expect(mounted!.root.button('Save').props.disabled).toBe(true)
    expect(mounted!.root.textContent()).toMatch(/unavailable|could not be read|failed/)
    expect(bridge.editLeaf).not.toHaveBeenCalled()
  })
  it('discards a read after the popup closes and toggles the chip without writing', async () => {
    let resolve!: (value: unknown) => void
    bridge.modelsStatus.mockImplementation(() => new Promise((done) => { resolve = done }))
    mounted!.root.named('Change main model and reasoning effort: gpt-6.1-sol · high').fire('click'); await flush()
    expect(mounted!.root.textContent()).toContain('Loading')
    mounted!.root.named('Change main model and reasoning effort: gpt-6.1-sol · high').fire('click'); await flush()
    resolve(ok({ model_catalogue: { codex: [row('gpt-6.1-sol', ['high'])] } })); await flush()
    expect(mounted!.root.findAll((node) => node.props.role === 'dialog')).toHaveLength(0)
  })
  it('uses filtered single-name options, model-valid efforts and the existing atomic owner', async () => {
    expect(mounted!.root.named('Change main model and reasoning effort: gpt-6.1-sol · high').textContent()).toBe('gpt-6.1-sol · high')
    await open()
    expect(control('header-model').options.map((node) => node.textContent())).toEqual(['gpt-6.1-sol', 'gpt-6-luna'])
    expect(control('header-effort').options.map((node) => node.props.value)).toEqual(['low', 'high'])
    control('header-model').fire('change', { target: { value: 'gpt-6-luna' } }); await flush()
    expect(control('header-effort').options.map((node) => node.props.value)).toEqual(['high', 'xhigh'])
    control('header-effort').fire('change', { target: { value: 'xhigh' } }); await flush()
    mounted!.root.button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.main.set', params: { model: 'gpt-6-luna', reasoning_effort: 'xhigh', expected_revision: 'r1' } })
    expect(mounted!.root.findAll((node) => node.props.role === 'dialog')).toHaveLength(0)
  })
})
