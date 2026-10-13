import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host, type Mounted } from './component-host'
import type { ConfigField } from '../../src/shared/api'
import { settingsControlId } from '../../src/renderer/src/settings-accessibility'

// The checklist of models automatic agent selection may use, as Odin's own descriptions and defaults present it.
let mounted: Mounted | undefined
let bridge: Record<string, any>
const ok = (result: unknown) => ({ ok: true, result })
const make = (path: string, desired: unknown, owner = 'settings.set', extra = {}): ConfigField => ({ path, desired, effective: desired, type: Array.isArray(desired) ? 'array' : typeof desired, enum: null, constraints: {}, sensitivity: 'public', apply_handler: owner, apply_state: 'applied', nullable: desired === null, configured: null, ...extra } as ConfigField)
const ASTRA = 'flagship: deepest reasoning for the hardest, highest-stakes work'
const SOL = 'default choice for complex coding, debugging, and multi-step agentic work'
const LUNA = 'cheapest GPT-6: focused, high-volume work with a clear goal'
const codexRow = (ref: string, builtin_hint: string, extra = {}) => ({ ref, name: ref, capability: 'reasoning', builtin_hint, agent_available: false, agent_unavailable_reason: 'not configured', effort_capabilities: { values: ['low', 'high'], restrictions_known: true, source: 'core_validation' }, ...extra })
function fields(agents: { model?: string; allowlist?: unknown[]; hints?: Record<string, string> } = {}, compat = false): ConfigField[] {
  return [
    make('llm_provider.model', 'gpt-6.1-sol', 'models.main.set'), make('openai_codex.enabled', true, 'providers.codex.set'),
    make('openai_compatible.enabled', compat, 'providers.compat.set'), make('openai_compatible.model', 'vendor/free', 'providers.compat.set'),
    make('ollama.enabled', false, 'providers.ollama.set'), make('ollama.model', 'local', 'providers.ollama.set'),
    make('agents.model', agents.model ?? 'auto', 'models.agents.set'), make('agents.auto_model_allowlist', agents.allowlist ?? [], 'models.agents.set'),
    make('agents.thinking_mode', null, 'models.agents.set', { type: 'string', enum: ['enabled', 'disabled'] }),
    make('agents.model_selection_hints', agents.hints ?? {}, 'models.agents.set', { type: 'object' })
  ]
}
beforeEach(() => {
  vi.resetModules()
  bridge = {
    codexAccounts: vi.fn(async () => ok({ configured: false, accounts: [] })),
    openrouterCatalogue: vi.fn(async () => ok({ recognized: false, models: [], quick_add: [] })),
    modelsStatus: vi.fn(async () => ok({
      agent_default_candidates: ['gpt-6-astra', 'gpt-6.1-sol', 'gpt-6-luna'],
      model_catalogue: {
        codex: [codexRow('gpt-6-astra', ASTRA), codexRow('gpt-6.1-sol', SOL), codexRow('gpt-6-luna', LUNA)],
        compat: [
          { ref: 'compat:vendor/free', name: 'vendor/free', capability: 'none', builtin_hint: '', agent_available: false, agent_unavailable_reason: 'free variant is not offered for ordinary agents' },
          { ref: 'compat:vendor/catalogue-only', name: 'vendor/catalogue-only', capability: 'none', builtin_hint: '' },
          { ref: 'compat:vendor/profiled', name: 'vendor/profiled', capability: 'none', builtin_hint: '', profile: { total_window_tokens: 200000 } },
          { ref: 'compat:vendor/hinted', name: 'vendor/hinted', capability: 'none', builtin_hint: 'Repo-wide reading', builtin_hint_source: 'profile', profile: { total_window_tokens: 200000 } }
        ]
      }
    })),
    settingsSchema: vi.fn(), status: vi.fn(async () => ({ ok: false, error: { code: 'unavailable', message: 'Unavailable' } })),
    // Electron copies every argument the way structuredClone does, and refuses a live Vue proxy the same way.
    editLeaf: vi.fn(async (request: unknown) => { structuredClone(request); return ok({ status: 'updated' }) })
  }
  ;(globalThis as any).window = { odin: bridge }
  ;(globalThis as any).document = { activeElement: null }
})
afterEach(() => { mounted?.unmount(); mounted = undefined })
async function models(agents?: Parameters<typeof fields>[0], compat = false) {
  const { settings } = await import('../../src/renderer/src/stores/settings')
  settings.meta = { revision: 'rev-1', schema_version: 1, fields: fields(agents, compat), status: { counts: {}, desired_revision: 'rev-1', effective_revision: null } } as any
  bridge.settingsSchema.mockImplementation(async () => ok(settings.meta))
  mounted = mount((await import('../../src/renderer/src/components/CodexAccounts.vue')).default); await flush()
  return { root: mounted.root, settings }
}
const id = (path: string) => settingsControlId(path.startsWith('agents.auto_model_allowlist.') ? 'curated-record' : 'curated', path)
const control = (root: Host, path: string) => root.findAll((node) => node.props.id === id(path))[0]!
const box = (root: Host, model: string) => control(root, `agents.auto_model_allowlist.${model}.chosen`)
const listed = (root: Host) => root.findAll((node) => node.tag === 'li' && typeof node.props['data-model'] === 'string')
  .map((node) => [node.props['data-model'], box(root, String(node.props['data-model'])).props.checked])
const state = (root: Host) => root.findAll((node) => node.props['data-testid'] === 'agent-candidates-state')[0]!.textContent().trim()
const save = async (root: Host) => { root.findAll((node) => node.props.id === 'agent-model-actions')[0]!.button('Save').fire('click'); await flush() }

describe('Automatic agent candidates', () => {
  it("starts from Odin's default: every default model ticked in order, each with Odin's description", async () => {
    const { root } = await models({ model: '' })
    control(root, 'agents.model').fire('change', { target: { value: 'auto' } }); await flush()
    expect(listed(root)).toEqual([['gpt-6-astra', true], ['gpt-6.1-sol', true], ['gpt-6-luna', true]])
    expect(state(root)).toBe("Using Odin's default: 3 models. Untick a model to choose your own.")
    for (const [model, text] of [['gpt-6-astra', ASTRA], ['gpt-6.1-sol', SOL], ['gpt-6-luna', LUNA]] as const) {
      expect(root.findAll((node) => node.props['data-testid'] === `candidate-description-${model}`)[0]!.textContent()).toContain(text)
    }
    // Automatic with nothing chosen is a complete choice: the default list is not written out.
    await save(root)
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.agents.set', params: { model: 'auto', expected_revision: 'rev-1' } })
    expect(root.textContent()).not.toContain('could not be confirmed')
  })

  it('writes the rest of the default out when one is unticked, and keeps the last model ticked', async () => {
    const { root } = await models()
    box(root, 'gpt-6.1-sol').fire('change', { target: { checked: false } }); await flush()
    expect(listed(root)).toEqual([['gpt-6-astra', true], ['gpt-6-luna', true], ['gpt-6.1-sol', false]])
    expect(state(root)).toBe('2 of 3 models ticked.')
    box(root, 'gpt-6-astra').fire('change', { target: { checked: false } }); await flush()
    expect(box(root, 'gpt-6-luna').props.disabled).toBe(true)
    expect(root.textContent()).toContain('At least one model stays ticked.')
    box(root, 'gpt-6-luna').fire('change', { target: { checked: false } }); await flush()
    expect(listed(root)[0]).toEqual(['gpt-6-luna', true])
    // Back to the default: nothing to save.
    root.findAll((node) => node.props['data-testid'] === 'agent-candidates-reset')[0]!.fire('click'); await flush()
    expect(root.findAll((node) => node.props.id === 'agent-model-actions')).toHaveLength(0)
    box(root, 'gpt-6.1-sol').fire('change', { target: { checked: false } }); await flush()
    root.named('Move gpt-6-luna up').fire('click'); await flush()
    await save(root)
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.agents.set', params: { model: 'auto', auto_model_allowlist: ['gpt-6-luna', 'gpt-6-astra'], expected_revision: 'rev-1' } })
    expect(root.textContent()).not.toContain('could not be confirmed')
    expect(root.textContent()).toContain('Saved.')
  })

  it("sends a saved list as plain data, and goes back to Odin's default with an empty one", async () => {
    const { root } = await models({ allowlist: [{ model: 'gpt-6-luna', reasoning_effort: 'high', thinking_mode: null }, 'gpt-6-astra'] })
    expect(listed(root)).toEqual([['gpt-6-luna', true], ['gpt-6-astra', true], ['gpt-6.1-sol', false]])
    box(root, 'gpt-6.1-sol').fire('change', { target: { checked: true } }); await flush()
    control(root, 'agents.auto_model_allowlist.gpt-6.1-sol.reasoning_effort').fire('change', { target: { value: 'low' } }); await flush()
    await save(root)
    expect(bridge.editLeaf).toHaveBeenLastCalledWith({ method: 'models.agents.set', params: { model: 'auto', auto_model_allowlist: [{ model: 'gpt-6-luna', reasoning_effort: 'high', thinking_mode: null }, 'gpt-6-astra', { model: 'gpt-6.1-sol', reasoning_effort: 'low' }], expected_revision: 'rev-1' } })
    expect(root.textContent()).not.toContain('could not be confirmed')
    root.findAll((node) => node.props['data-testid'] === 'agent-candidates-reset')[0]!.fire('click'); await flush()
    expect(state(root)).toContain("Using Odin's default")
    await save(root)
    expect(bridge.editLeaf).toHaveBeenLastCalledWith({ method: 'models.agents.set', params: { model: 'auto', auto_model_allowlist: [], expected_revision: 'rev-1' } })
  })

  it("marks your own description, and editing back to Odin's text stores none", async () => {
    const { root } = await models({ hints: { 'gpt-6-luna': 'My cheap worker' } })
    const luna = root.findAll((node) => node.props['data-testid'] === 'candidate-description-gpt-6-luna')[0]!
    expect(luna.textContent()).toContain('My cheap worker')
    expect(luna.textContent()).toContain('Your description')
    expect(luna.textContent()).not.toContain(LUNA)
    root.named('Edit the description of gpt-6-astra').fire('click'); await flush()
    const astra = () => control(root, 'agents.auto_model_allowlist.gpt-6-astra.description')
    expect(astra().props.value).toBe(ASTRA)
    astra().type(`  ${ASTRA}  `); await flush()
    expect(root.findAll((node) => node.props.id === 'agent-model-actions')).toHaveLength(0)
    astra().type('Hardest problems only'); await flush()
    root.named("Use Odin's description for gpt-6-luna").fire('click'); await flush()
    await save(root)
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.agents.set', params: { model: 'auto', model_selection_hints: { 'gpt-6-astra': 'Hardest problems only' }, expected_revision: 'rev-1' } })
  })

  it("lets Odin's own reason, not missing setup, block a model, and offers only set-up compatible models", async () => {
    const { root } = await models({}, true)
    // Codex rows say "not configured" until sign-in: still choosable.
    expect(box(root, 'gpt-6-astra').props.disabled).toBe(false)
    expect(box(root, 'compat:vendor/free').props.disabled).toBe(true)
    expect(root.textContent()).toContain("Can't run agents: free variant is not offered for ordinary agents")
    expect(box(root, 'compat:vendor/profiled').props.disabled).toBe(false)
    expect(root.findAll((node) => node.props.id === id('agents.auto_model_allowlist.compat:vendor/catalogue-only.chosen'))).toHaveLength(0)
    expect(root.findAll((node) => node.props['data-testid'] === 'candidate-description-compat:vendor/profiled')[0]!.textContent()).toContain('Odin has no description for this model.')
  })

  it("shows a profile's own description as the model's, and offers it back after an override", async () => {
    const { root } = await models({ allowlist: ['compat:vendor/hinted'], hints: { 'compat:vendor/hinted': 'Mine' } }, true)
    const text = () => root.findAll((node) => node.props['data-testid'] === 'candidate-description-compat:vendor/hinted')[0]!.textContent()
    expect(text()).toContain('Mine')
    root.named("Use the profile's description for compat:vendor/hinted").fire('click'); await flush()
    expect(text()).toContain('Repo-wide reading')
    expect(text()).toContain('From its profile')
    await save(root)
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.agents.set', params: { model: 'auto', model_selection_hints: {}, expected_revision: 'rev-1' } })
  })

  it('reads the model choices again when a compatible profile is saved, so a new model is offered', async () => {
    const { root, settings } = await models({}, true)
    const reads = bridge.modelsStatus.mock.calls.length
    const status = (await bridge.modelsStatus()).result
    status.model_catalogue.compat.push({ ref: 'compat:vendor/new', name: 'vendor/new', capability: 'none', builtin_hint: '', profile: { total_window_tokens: 200000 } })
    bridge.modelsStatus.mockClear(); bridge.modelsStatus.mockResolvedValue(ok(status))
    expect(root.findAll((node) => node.props.id === id('agents.auto_model_allowlist.compat:vendor/new.chosen'))).toHaveLength(0)
    // What Save routing does: settings reload with the new profile.
    settings.meta = { ...settings.meta!, revision: 'rev-2', fields: [...settings.meta!.fields, make('openai_compatible.model_profiles.vendor/new.max_output_tokens', 4096, 'providers.compat.set')] } as any
    await flush(); await flush()
    expect(reads).toBeGreaterThan(0)
    expect(bridge.modelsStatus).toHaveBeenCalledTimes(1)
    expect(box(root, 'compat:vendor/new').props.checked).toBe(false)
  })

  it('keeps each model to one line, with its details on demand', async () => {
    const { root } = await models()
    const panel = () => control(root, 'agents.auto_model_allowlist.gpt-6-astra.details')
    expect(root.named('Details for gpt-6-astra').props['aria-expanded']).toBe(false)
    expect(panel().style.display).toBe('none')
    // The row shows the description on one line, whole on hover, and the effort for a ticked model.
    const summary = root.findAll((node) => node.props.class === 'candidate-summary')[0]!
    expect(summary.props.title).toBe(ASTRA)
    expect(control(root, 'agents.auto_model_allowlist.gpt-6-astra.reasoning_effort').props['aria-label']).toBe('Reasoning effort for gpt-6-astra')
    root.named('Details for gpt-6-astra').fire('click'); await flush()
    expect(root.named('Details for gpt-6-astra').props['aria-expanded']).toBe(true)
    expect(panel().style.display).not.toBe('none')
    // Editing the description keeps its details open, even if the toggle is pressed.
    root.named('Edit the description of gpt-6-astra').fire('click'); await flush()
    root.named('Details for gpt-6-astra').fire('click'); await flush()
    expect(panel().style.display).not.toBe('none')
    // An unticked model has no effort or order controls.
    box(root, 'gpt-6-luna').fire('change', { target: { checked: false } }); await flush()
    expect(root.findAll((node) => node.props.id === id('agents.auto_model_allowlist.gpt-6-luna.reasoning_effort'))).toHaveLength(0)
    expect(root.findAll((node) => node.props['aria-label'] === 'Move gpt-6-luna up')).toHaveLength(0)
  })

  it("falls back to the Codex catalogue when the core doesn't report its default", async () => {
    const status = (await bridge.modelsStatus()).result
    delete status.agent_default_candidates
    bridge.modelsStatus.mockResolvedValue(ok(status))
    const { root } = await models()
    expect(listed(root)).toEqual([['gpt-6-astra', true], ['gpt-6.1-sol', true], ['gpt-6-luna', true]])
  })
})
