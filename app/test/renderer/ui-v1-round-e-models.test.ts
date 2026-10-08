import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host, type Mounted } from './component-host'
import type { ConfigField } from '../../src/shared/api'
import { catalogueModelLabel, catalogueRows, modelEffortPath, modelOptions, modelProvider, modelSelectionNote, type ModelRow } from '../../src/renderer/src/model-picker'
import { settingsControlId } from '../../src/renderer/src/settings-accessibility'

const field = (path: string, desired: unknown): ConfigField => ({ path, desired, effective: desired, type: Array.isArray(desired) ? 'array' : typeof desired, enum: null, constraints: {}, sensitivity: 'public', apply_handler: path.startsWith('agents.') ? 'models.agents.set' : path === 'llm_provider.model' ? 'models.main.set' : 'providers.codex.set', apply_state: 'applied', nullable: false, configured: null } as ConfigField)
const rows: ModelRow[] = [
  { ref: 'gpt-6.1-sol', name: 'gpt-6.1-sol', effort_capabilities: { values: ['high'], restrictions_known: true, source: 'core_validation' } },
  { ref: 'gpt-6-luna', name: 'Quick', effort_capabilities: { values: ['low', 'high'], restrictions_known: true, source: 'core_validation' } },
  { ref: 'compat:flash', name: 'Flash', effort_capabilities: { values: [], restrictions_known: true, source: 'core_validation' } },
  { ref: 'ollama:local', name: 'Local' }
]
const enabled = () => [field('openai_codex.enabled', true), field('openai_compatible.enabled', false), field('ollama.enabled', false)]
let mounted: Mounted | undefined
beforeEach(() => vi.resetModules())
afterEach(() => { mounted?.unmount(); mounted = undefined; vi.unstubAllGlobals() })
const control = (root: Host, path: string) => root.findAll((node) => node.props.id === settingsControlId('curated', path))[0]!
describe('Round E shared model picker eligibility and labels', () => {
  it('deduplicates references, displays identical names once, keeps a genuinely different name', () => {
    expect(catalogueRows({ model_catalogue: { codex: [...rows, rows[0]!, { ref: '' }, {} as ModelRow] } })).toEqual(rows)
    expect(catalogueRows({})).toEqual([])
    expect(catalogueModelLabel(rows[0]!)).toBe('gpt-6.1-sol')
    expect(catalogueModelLabel(rows[1]!)).toBe('Quick · gpt-6-luna')
    expect(catalogueModelLabel({ ref: 'plain' })).toBe('plain')
    expect(catalogueModelLabel({ ref: 'plain', name: '  plain  ' })).toBe('plain')
  })
  it('keeps only enabled choices with one disabled saved selection, never guesses enablement', () => {
    expect(modelOptions(rows, enabled(), 'compat:flash').map((row) => [row.ref, row.disabled])).toEqual([['compat:flash', true], ['gpt-6.1-sol', false], ['gpt-6-luna', false]])
    expect(modelOptions(rows, [], 'gpt-6.1-sol')).toEqual([{ ref: 'gpt-6.1-sol', label: 'gpt-6.1-sol', disabled: true }])
    expect(modelOptions(rows, enabled(), 'missing')[0]).toEqual({ ref: 'missing', label: 'missing', disabled: true })
    expect(modelOptions(rows, enabled(), '')[0]).toEqual({ ref: '', label: 'Choose a model', disabled: true })
    expect(modelSelectionNote('compat:flash', rows, enabled())).toContain('OpenAI-compatible is off')
    expect(modelSelectionNote('ollama:local', rows, enabled())).toContain('Ollama is off')
    expect(modelSelectionNote('missing', rows, enabled())).toContain('not in the current choices')
    expect(modelSelectionNote('gpt-6.1-sol', rows, enabled())).toBe('')
    expect(modelSelectionNote('', rows, enabled())).toBe('')
  })
  it('uses provider-specific effort paths without inventing unsupported efforts', () => {
    expect(modelProvider('gpt-6.1-sol')).toBe('codex')
    expect(modelProvider('compat:flash')).toBe('compat')
    expect(modelProvider('ollama:local')).toBe('ollama')
    expect(modelEffortPath('gpt-6.1-sol', rows)).toBe('openai_codex.reasoning_effort')
    expect(modelEffortPath('compat:flash', rows)).toBe('')
    expect(modelEffortPath('compat:unknown', rows)).toBe('openai_compatible.reasoning_effort')
    expect(modelEffortPath('ollama:local', rows)).toBe('')
  })
  it('applies the same filtering to main, fixed agent, automatic candidates, preserving saved off choices', async () => {
    const ok = (result: unknown) => ({ ok: true, result })
    const bridge = { modelsStatus: vi.fn(async () => ok({ model_catalogue: { codex: rows } })), codexAccounts: vi.fn(async () => ok({ configured: false, accounts: [] })), openrouterCatalogue: vi.fn(async () => ok({ recognized: false, models: [], quick_add: [] })), settingsSchema: vi.fn(), editLeaf: vi.fn(), status: vi.fn(async () => ok({})), usage: vi.fn(async () => ok({})) }
    vi.stubGlobal('window', { odin: bridge }); vi.stubGlobal('document', { activeElement: null })
    const { settings } = await import('../../src/renderer/src/stores/settings')
    settings.meta = { revision: 'r1', schema_version: 1, fields: [...enabled(), field('llm_provider.model', 'compat:flash'), field('openai_codex.reasoning_effort', 'high'), field('agents.model', 'ollama:local'), field('agents.auto_model_allowlist', ['compat:flash', 'gpt-6.1-sol']), field('agents.thinking_mode', null)], status: { counts: {}, desired_revision: 'r1', effective_revision: null } }
    bridge.settingsSchema.mockImplementation(async () => ok(settings.meta))
    mounted = mount((await import('../../src/renderer/src/components/CodexAccounts.vue')).default); await flush()
    const root = mounted.root
    expect(control(root, 'llm_provider.model').options.map((node) => [node.props.value, node.props.disabled])).toEqual([['compat:flash', true], ['gpt-6.1-sol', false], ['gpt-6-luna', false]])
    expect(control(root, 'agents.model').options.map((node) => [node.props.value, node.props.disabled])).toEqual([['ollama:local', true], ['gpt-6.1-sol', false], ['gpt-6-luna', false]])
    expect(root.textContent()).toContain('OpenAI-compatible is off. This saved selection is kept.')
    expect(root.textContent()).toContain('Ollama is off. This saved selection is kept.')
    control(root, 'agents.model.mode').fire('change', { target: { value: 'auto' } }); await flush()
    expect(control(root, 'agents.auto_model_allowlist.0.model').options.map((node) => [node.props.value, node.props.disabled])).toEqual([['compat:flash', true], ['gpt-6.1-sol', false], ['gpt-6-luna', false]])
    expect(control(root, 'agents.auto_model_allowlist.1.model').options.map((node) => node.props.value)).toEqual(['gpt-6.1-sol', 'gpt-6-luna'])
    root.button('Add automatic candidate').fire('click'); await flush()
    expect(control(root, 'agents.auto_model_allowlist.2.model').options.map((node) => node.props.value)).toEqual(['', 'gpt-6.1-sol', 'gpt-6-luna'])
    bridge.editLeaf.mockResolvedValue(ok({ status: 'updated' }))
    control(root, 'agents.auto_model_allowlist.2.model').fire('change', { target: { value: 'gpt-6-luna' } }); await flush()
    root.findAll((node) => node.props.id === 'agent-model-actions')[0]!.button('Save').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledWith({ method: 'models.agents.set', params: { model: 'auto', auto_model_allowlist: ['compat:flash', 'gpt-6.1-sol', 'gpt-6-luna'], expected_revision: 'r1' } })
    expect(settings.meta.fields.find((item) => item.path === 'llm_provider.model')?.desired).toBe('compat:flash')
  })
})
