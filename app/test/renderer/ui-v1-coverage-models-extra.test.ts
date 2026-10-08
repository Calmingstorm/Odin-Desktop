import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, Host, type Mounted } from './component-host'
import type { ConfigField } from '../../src/shared/api'
import { settingsControlId } from '../../src/renderer/src/settings-accessibility'

let mounted: Mounted | undefined
let bridge: Record<string, any>
const ok = (result: unknown) => ({ ok: true, result })
const make = (path: string, desired: unknown, owner = 'settings.set', extra = {}): ConfigField => ({ path, desired, effective: desired, type: typeof desired, enum: null, constraints: {}, sensitivity: 'public', apply_handler: owner, apply_state: 'applied', nullable: desired === null, configured: null, ...extra } as ConfigField)
const fields = () => [
  make('llm_provider.model', 'gpt-6.1-sol', 'models.main.set'),
  make('openai_codex.enabled', true, 'providers.codex.set'),
  make('openai_codex.reasoning_effort', 'high', 'providers.codex.set', { enum: ['low', 'high'] }),
  make('openai_codex.context_utilization', 60, 'providers.codex.set', { type: 'integer', constraints: { minimum: 30, maximum: 100 } }),
  make('openai_codex.agent_reasoning_effort', 'high', 'providers.codex.set'),
  make('openai_codex.auxiliary.model', 'gpt-6.1-sol', 'providers.codex.set'),
  make('openai_codex.auxiliary.enabled', false, 'providers.codex.set'),
  make('openai_compatible.enabled', true, 'providers.compat.set'),
  make('openai_compatible.model', 'deepseek-v4-flash', 'providers.compat.set'),
  make('openai_compatible.base_url', 'https://example.test/v1', 'providers.compat.set'),
  make('openai_compatible.reasoning_effort', 'high', 'providers.compat.set', { enum: ['low', 'high'] }),
  make('openai_compatible.api_key', null, 'providers.compat.set', { type: 'string', sensitivity: 'sensitive', secret_route: 'secrets.set', configured: true }),
  make('ollama.enabled', false, 'providers.ollama.set'), make('ollama.model', 'local', 'providers.ollama.set'),
  make('agents.model', 'auto', 'models.agents.set'),
  make('agents.auto_model_allowlist', ['gpt-6.1-sol', { model: 'compat:reasoner', reasoning_effort: 'high' }], 'models.agents.set', { type: 'array' }),
  make('agents.thinking_mode', null, 'models.agents.set', { type: 'string', enum: ['enabled', 'disabled'] }),
  make('agents.model_selection_hints', {}, 'models.agents.set', { type: 'object' }),
  make('image.openai.enabled', true), make('image.openai.outer_model', 'gpt-image-host'), make('image.openai.image_model', 'gpt-image')
]
beforeEach(() => {
  vi.resetModules()
  // v-show changes each fake DOM element's display, just as it does in a browser.
  Object.defineProperty(Host.prototype, 'style', { configurable: true, get() { return ((this as any)._style ??= { display: '' }) } })
  bridge = {
    codexAccounts: vi.fn(async () => ok({ configured: false, accounts: [] })),
    openrouterCatalogue: vi.fn(async () => ok({ recognized: false, models: [], quick_add: [] })),
    modelsStatus: vi.fn(async () => ok({ model_catalogue: { codex: [{ ref: 'gpt-6.1-sol', capability: 'reasoning', effort_capabilities: { values: ['low', 'high'], restrictions_known: true, source: 'core_validation' } }], compat: [
      { ref: 'compat:deepseek-v4-flash', capability: 'thinking', effort_capabilities: { values: [], restrictions_known: true, source: 'core_validation' } },
      { ref: 'compat:reasoner', capability: 'reasoning', effort_capabilities: { values: ['low', 'high'], restrictions_known: true, source: 'core_validation' } },
      { ref: 'compat:unknown', capability: 'unknown', effort_capabilities: { values: null, restrictions_known: false, source: 'unknown' } }
    ] } })),
    settingsSchema: vi.fn(), status: vi.fn(async () => ({ ok: false, error: { code: 'unavailable', message: 'Unavailable' } })),
    providersCompatSet: vi.fn(), providersCodexSet: vi.fn(), providersOllamaSet: vi.fn(), settingsSet: vi.fn(),
    editLeaf: vi.fn(async () => ok({ status: 'updated' })), secretsSet: vi.fn(async () => ok({ stored: true })), secretsClear: vi.fn(async () => ok({ cleared: true })), imageModelIntent: vi.fn(async () => ok({ image_models_revision: 'next' }))
  }
  ;(globalThis as any).window = { odin: bridge }
  ;(globalThis as any).document = { activeElement: null }
})
afterEach(() => { mounted?.unmount(); mounted = undefined })
async function models(custom?: (items: ConfigField[]) => void, props?: Record<string, unknown>) {
  const { settings } = await import('../../src/renderer/src/stores/settings')
  const items = fields(); custom?.(items)
  settings.meta = { revision: 'rev-1', schema_version: 1, fields: items, status: { counts: {}, desired_revision: 'rev-1', effective_revision: null }, image_models_revision: 'image-1', image_models: { outer_model: { status: 'follow', default: 'host-default', effective: 'host-default' }, image_model: { status: 'pin', default: 'image-default', effective: 'custom-image' } } } as any
  bridge.settingsSchema.mockImplementation(async () => ok(settings.meta))
  for (const name of ['providersCompatSet', 'providersCodexSet', 'providersOllamaSet', 'settingsSet']) bridge[name].mockImplementation(async ({ changes }: any) => ok({ revision: 'rev-2', fields: changes.map(({ path, value }: any) => ({ ...settings.meta!.fields.find((item) => item.path === path), desired: value, effective: value })) }))
  mounted = mount((await import('../../src/renderer/src/components/CodexAccounts.vue')).default, props); await flush()
  return { root: mounted.root, settings }
}
const control = (root: Host, id: string) => root.findAll((node) => node.props.id === id)[0]!
const choose = (root: Host, path: string, value: string) => control(root, settingsControlId('curated', path)).fire('change', { target: { value } })
describe('Models canonical references, ownership and negative paths', () => {
  it('renders untouched restart-time unknown provider settings without warning or fabricated applied values', async () => {
    const { root, settings } = await models((items) => {
      for (const item of items) Object.assign(item, { apply_state: 'unknown', effective: null })
    })
    expect(control(root, settingsControlId('curated', 'openai_codex.reasoning_effort')).value).toBe('high')
    expect(root.textContent()).not.toMatch(/running value (?:is|differs)|Check the connection/i)
    expect(settings.meta!.fields.every((item) => item.apply_state === 'unknown' && item.effective === null)).toBe(true)
    for (const method of ['editLeaf', 'providersCodexSet', 'providersCompatSet', 'providersOllamaSet', 'settingsSet']) expect(bridge[method]).not.toHaveBeenCalled()
  })
  it('labels automatic agent effort plainly and preserves its canonical immediate owner', async () => {
    const { root } = await models()
    const select = control(root, settingsControlId('curated', 'openai_codex.agent_reasoning_effort'))
    expect(select.findAll((node) => node.tag === 'option' && node.props.value === 'auto').map((node) => node.textContent())).toEqual(['Automatic'])
    expect(root.textContent()).toContain('Automatic lets Odin choose the effort for each task.')
    expect(root.textContent()).not.toContain('Fixed effort must work')
    select.fire('change', { target: { value: 'auto' } }); await flush()
    expect(bridge.providersCodexSet).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'rev-1', changes: [{ path: 'openai_codex.agent_reasoning_effort', value: 'auto' }] })
  })
  it('restart links reveal and focus unique curated provider, auxiliary, agent and image controls', async () => {
    const { settings } = await models()
    mounted!.unmount()
    const { state } = await import('../../src/renderer/src/store')
    const { presentationFor } = await import('../../src/renderer/src/settings-presentation')
    const paths = ['ollama.model', 'openai_compatible.api_key', 'openai_codex.enabled', 'openai_codex.auxiliary.model', 'openai_codex.auxiliary.enabled', 'agents.model', 'agents.auto_model_allowlist', 'agents.thinking_mode', 'agents.model_selection_hints', 'image.openai.image_model']
    for (const path of paths) settings.meta!.fields.find((item) => item.path === path)!.pending_restart = true
    state.settingsSection = 'models'
    const focused: string[] = []
    const opened: Host[] = []
    const adapt = (node: Host | null): any => node && ({
      tagName: node.tag.toUpperCase(), parentElement: adapt(node.parent),
      set open(value: boolean) { if (value) opened.push(node) },
      focus: () => focused.push(String(node.props.id)), scrollIntoView: vi.fn()
    })
    ;(globalThis as any).document = { activeElement: null, getElementById: (id: string) => adapt(mounted!.root.findAll((node) => node.props.id === id)[0] ?? null) }
    mounted = mount((await import('../../src/renderer/src/views/Settings.vue')).default); await flush()
    for (const path of paths) {
      const heading = presentationFor(path)!.label
      mounted.root.button(heading).fire('click'); await flush()
      const id = settingsControlId('curated', path)
      expect(mounted.root.findAll((node) => node.props.id === id), path).toHaveLength(1)
      expect(focused.at(-1), path).toBe(id)
    }
    expect(opened.some((node) => node.tag === 'details')).toBe(true)
    expect(bridge.providersCompatSet).not.toHaveBeenCalled()
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    expect(bridge.secretsSet).not.toHaveBeenCalled()
  })
  it('cancels main drafts, selects a fixed agent model and handles a rejected catalogue read', async () => {
    const { root } = await models()
    choose(root, 'openai_codex.reasoning_effort', 'low'); await flush()
    control(root, 'main-model-actions').button('Cancel').fire('click'); await flush()
    expect(control(root, settingsControlId('curated', 'openai_codex.reasoning_effort')).value).toBe('high')
    choose(root, 'agents.model', 'fixed'); await flush()
    control(root, settingsControlId('curated', 'agents.model')).fire('change', { target: { value: 'compat:reasoner' } }); await flush()
    control(root, 'agent-model-actions').button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.agents.set', params: { model: 'compat:reasoner', expected_revision: 'rev-1' } })
    bridge.modelsStatus.mockRejectedValue(new Error('test-only transport failure'))
    root.button('Refresh model choices').fire('click'); await flush()
    expect(root.textContent()).toContain('Model choices could not be read. Try again.')
    expect(bridge.editLeaf).toHaveBeenCalledTimes(1)
  })
  it('saves bare Codex with dependent effort and intersects bare candidate efforts', async () => {
    const { root } = await models()
    expect(control(root, settingsControlId('curated', 'agents.auto_model_allowlist.0.thinking_mode')).props.disabled).toBe(true)
    choose(root, 'openai_codex.reasoning_effort', 'low'); await flush()
    control(root, 'main-model-actions').button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.main.set', params: { model: 'gpt-6.1-sol', reasoning_effort: 'low', expected_revision: 'rev-1' } })
    choose(root, 'openai_codex.agent_reasoning_effort', 'low'); await flush()
    expect(bridge.providersCodexSet).toHaveBeenCalledWith({ expected_revision: 'rev-1', changes: [{ path: 'openai_codex.agent_reasoning_effort', value: 'low' }] })
  })
  it('confirms disabling the active bare Codex provider and keeps cancellation local', async () => {
    const { root } = await models()
    control(root, settingsControlId('curated', 'openai_codex.enabled')).fire('change', { target: { checked: false } }); await flush()
    const { dialog } = await import('../../src/renderer/src/dialog')
    expect(dialog.current?.title).toBe('Disable Codex?')
    dialog.current!.resolve(null); await flush(); expect(bridge.providersCodexSet).not.toHaveBeenCalled()
    control(root, settingsControlId('curated', 'openai_codex.enabled')).fire('change', { target: { checked: false } }); await flush(); dialog.current!.resolve(true); await flush()
    expect(bridge.providersCodexSet).toHaveBeenCalledWith({ expected_revision: 'rev-1', changes: [{ path: 'openai_codex.enabled', value: false }] })
  })
  it('saves non-effort thinking models without a fabricated effort or silent downgrade', async () => {
    const { root } = await models()
    choose(root, 'llm_provider.model', 'compat:deepseek-v4-flash'); await flush()
    expect(root.findAll((node) => node.props.id === settingsControlId('curated', 'openai_compatible.reasoning_effort'))).toHaveLength(0)
    expect(control(root, 'main-model-actions').button('Save').props.disabled).toBe(false)
    control(root, 'main-model-actions').button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.main.set', params: { model: 'compat:deepseek-v4-flash', expected_revision: 'rev-1' } })
  })
  it('warns about unknown effort capabilities without blocking canonical validation', async () => {
    const { root } = await models()
    choose(root, 'llm_provider.model', 'compat:unknown'); await flush()
    expect(root.textContent()).toContain('Supported effort choices are not known')
    expect(control(root, 'main-model-actions').button('Save').props.disabled).toBe(false)
    control(root, 'main-model-actions').button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledWith({ method: 'models.main.set', params: { model: 'compat:unknown', reasoning_effort: 'high', expected_revision: 'rev-1' } })
  })
  it('preserves unsent main effort while provider group saves only its owned address', async () => {
    const { root } = await models((items) => { items.find((item) => item.path === 'llm_provider.model')!.desired = 'compat:reasoner' })
    choose(root, 'openai_compatible.reasoning_effort', 'low'); root.named('Configure OpenAI-compatible').fire('click'); await flush()
    control(root, settingsControlId('curated', 'openai_compatible.base_url')).type('https://new.test/v1')
    root.button('Save OpenAI-compatible setup').fire('click'); await flush()
    expect(bridge.providersCompatSet).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'rev-1', changes: [{ path: 'openai_compatible.base_url', value: 'https://new.test/v1' }] })
    expect(control(root, settingsControlId('curated', 'openai_compatible.reasoning_effort')).value).toBe('low')
    expect(control(root, 'main-model-actions').button('Save').props.disabled).toBe(false)
  })
  it('blocks blank and incompatible automatic candidates, edits mixed policy, and cancels locally', async () => {
    const { root } = await models()
    root.button('Add automatic candidate').fire('click'); await flush()
    control(root, 'agent-model-actions').button('Save').fire('click'); await flush()
    expect(root.textContent()).toContain('Enter a model for every automatic candidate')
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    control(root, settingsControlId('curated', 'agents.auto_model_allowlist.2.model')).fire('change', { target: { value: 'gpt-6.1-sol' } })
    control(root, settingsControlId('curated', 'agents.auto_model_allowlist.2.reasoning_effort')).fire('change', { target: { value: 'unsupported' } }); await flush()
    control(root, 'agent-model-actions').button('Save').fire('click'); await flush()
    expect(root.textContent()).toContain('Choose supported reasoning efforts')
    control(root, settingsControlId('curated', 'agents.auto_model_allowlist.2.reasoning_effort')).fire('change', { target: { value: 'low' } })
    control(root, settingsControlId('curated', 'agents.auto_model_allowlist.1.thinking_mode')).fire('change', { target: { value: 'enabled' } }); await flush()
    root.named('Move model 1 down').fire('click'); await flush()
    root.named('Remove model 3').fire('click'); await flush()
    control(root, 'agent-model-actions').button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledWith({ method: 'models.agents.set', params: { model: 'auto', auto_model_allowlist: [{ model: 'compat:reasoner', reasoning_effort: 'high', thinking_mode: 'enabled' }, 'gpt-6.1-sol'], expected_revision: 'rev-1' } })
    choose(root, 'agents.model', 'main'); await flush(); control(root, 'agent-model-actions').button('Cancel').fire('click'); await flush()
    expect(control(root, settingsControlId('curated', 'agents.model')).value).toBe('auto')
  })
  it('validates agent JSON locally and saves explicit thinking/hints together', async () => {
    const { root } = await models()
    control(root, settingsControlId('curated', 'agents.model_selection_hints')).type('{bad'); await flush()
    root.button('Save agent options').fire('click'); await flush()
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    expect(root.textContent()).toContain('JSON')
    root.button('Cancel agent options').fire('click'); await flush()
    control(root, settingsControlId('curated', 'agents.model_selection_hints')).type('{"purpose":"analysis"}')
    control(root, settingsControlId('curated', 'agents.thinking_mode')).fire('change', { target: { value: 'enabled' } }); await flush()
    root.button('Save agent options').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledWith({ method: 'models.agents.set', params: { model: 'auto', thinking_mode: 'enabled', model_selection_hints: { purpose: 'analysis' }, expected_revision: 'rev-1' } })
  })
  it('reveals provider setup, enforces missing secret route and confirms removals', async () => {
    const { root, settings } = await models(undefined, { reveal: 'openai_compatible.api_key' })
    const key = settings.meta!.fields.find((item) => item.path === 'openai_compatible.api_key')!
    key.secret_route = null; await flush()
    expect(control(root, settingsControlId('curated', 'openai_compatible.api_key')).props.disabled).toBe(true)
    root.named('Remove OpenAI-compatible API key').fire('click'); await flush()
    expect(bridge.secretsClear).not.toHaveBeenCalled()
    key.secret_route = 'secrets.set'; await flush()
    root.named('Remove OpenAI-compatible API key').fire('click'); await flush()
    const { dialog } = await import('../../src/renderer/src/dialog')
    dialog.current!.resolve(null); await flush(); expect(bridge.secretsClear).not.toHaveBeenCalled()
    root.named('Remove OpenAI-compatible API key').fire('click'); await flush(); dialog.current!.resolve(true); await flush()
    expect(bridge.secretsClear).toHaveBeenCalledExactlyOnceWith({ path: key.path })
  })
  it('captures exact secret authority across a queue and refuses missing routes', async () => {
    const { settings } = await models()
    const { saveFields, setSecret, clearSecret } = await import('../../src/renderer/src/stores/settings')
    const key = settings.meta!.fields.find((item) => item.path === 'openai_compatible.api_key')!
    key.secret_route = null
    expect(await setSecret(key, 'test-only')).toBe(false); expect(await clearSecret(key)).toBe(false)
    key.secret_route = 'secrets.set'
    let settle!: (answer: unknown) => void
    bridge.providersOllamaSet.mockImplementation(() => new Promise((resolve) => { settle = resolve }))
    const first = saveFields([{ field: settings.meta!.fields.find((item) => item.path === 'ollama.model')!, value: 'new-local' }])
    const store = setSecret(key, 'test-only'); const clear = clearSecret(key); await flush()
    key.secret_route = null
    settle(ok({ revision: 'rev-2', fields: [] })); expect(await first).toBe(true)
    expect(await store).toBe(false); expect(await clear).toBe(false)
    expect(bridge.secretsSet).not.toHaveBeenCalled(); expect(bridge.secretsClear).not.toHaveBeenCalled()
  })
  it('saves auxiliary group and explicitly changes follow/pin image intent', async () => {
    const { root } = await models()
    control(root, settingsControlId('curated', 'openai_codex.auxiliary.model')).type('gpt-6-luna'); control(root, settingsControlId('curated', 'openai_codex.auxiliary.enabled')).fire('change', { target: { checked: true } }); await flush()
    root.button('Save auxiliary model').fire('click'); await flush()
    expect(bridge.providersCodexSet).toHaveBeenCalledWith({ expected_revision: 'rev-1', changes: [{ path: 'openai_codex.auxiliary.model', value: 'gpt-6-luna' }, { path: 'openai_codex.auxiliary.enabled', value: true }] })
    expect(root.textContent()).toContain('Following default: host-default')
    expect(root.textContent()).toContain('Pinned: custom-image')
    root.button('Pin current value').fire('click'); await flush(); root.button('Follow default').fire('click'); await flush()
    expect(bridge.imageModelIntent.mock.calls.map(([input]: any[]) => input)).toEqual([{ expected_revision: 'image-1', operations: { outer_model: 'pin' } }, { expected_revision: 'image-1', operations: { image_model: 'follow' } }])
  })
})
