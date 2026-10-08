import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host, type Mounted } from './component-host'
import type { ConfigField } from '../../src/shared/api'
import { settingsControlId } from '../../src/renderer/src/settings-accessibility'
let mounted: Mounted | undefined
let bridge: Record<string, any>
const ok = (result: unknown) => ({ ok: true, result })
const make = (path: string, desired: unknown, owner = 'settings.set', type: string = typeof desired, extra = {}): ConfigField => ({ path, desired, effective: desired, type, enum: null, constraints: {}, sensitivity: 'public', apply_handler: owner, apply_state: 'applied', nullable: desired === null, configured: null, ...extra } as ConfigField)
const fields = () => [
  make('llm_provider.model', 'codex:first', 'models.main.set'), make('llm_provider.active_provider', 'codex', 'models.main.set'),
  make('openai_codex.reasoning_effort', 'high', 'providers.codex.set', 'string', { enum: ['low', 'high', 'xhigh'] }),
  make('openai_codex.enabled', true, 'providers.codex.set'), make('openai_codex.context_utilization', .8, 'providers.codex.set', 'number'),
  make('openai_compatible.enabled', false, 'providers.compat.set'), make('openai_compatible.base_url', 'https://example.test/v1', 'providers.compat.set'), make('openai_compatible.model', 'old', 'providers.compat.set'),
  make('openai_compatible.api_key', '[redacted]', 'providers.compat.set', 'string', { sensitivity: 'sensitive', secret_route: 'secrets.set', configured: true }),
  make('ollama.enabled', false, 'providers.ollama.set'), make('ollama.base_url', 'http://localhost:11434', 'providers.ollama.set'), make('ollama.model', 'old-local', 'providers.ollama.set'),
  make('agents.model', 'auto', 'models.agents.set'), make('agents.auto_model_allowlist', ['codex:first', { model: 'codex:second', reasoning_effort: 'high' }], 'models.agents.set', 'array'),
  make('agents.thinking_mode', null, 'models.agents.set', 'string', { enum: ['enabled', 'disabled'] }), make('agents.model_selection_hints', {}, 'models.agents.set', 'object'), make('agents.max_concurrent_agents', 3, 'settings.set', 'integer')
]
beforeEach(() => {
  vi.resetModules()
  bridge = {
    codexAccounts: vi.fn(async () => ok({ configured: true, accounts: [{ index: 0, email: 'person@example.test', is_current: true, quota: { primary: { used_percent: 0, window_minutes: 300, resets_at: 0 } } }] })),
    openrouterCatalogue: vi.fn(async () => ok({ recognized: true, models: [], quick_add: [] })),
    modelsStatus: vi.fn(async () => ok({ model_catalogue: { codex: ['first', 'second', 'new-second'].map((name) => ({ ref: `codex:${name}`, name, effort_capabilities: { values: name === 'first' ? ['low', 'high'] : ['high', 'xhigh'], restrictions_known: true, source: 'core_validation' } })) } })),
    settingsSchema: vi.fn(), status: vi.fn(async () => ({ ok: false, error: { code: 'unavailable', message: 'Not available' } })),
    providersCompatSet: vi.fn(), providersOllamaSet: vi.fn(), providersCodexSet: vi.fn(), settingsSet: vi.fn(), editLeaf: vi.fn(), secretsSet: vi.fn(), secretsClear: vi.fn()
  }
  ;(globalThis as any).window = { odin: bridge }
  ;(globalThis as any).document = { activeElement: null }
})
afterEach(() => { mounted?.unmount(); mounted = undefined })
async function models() {
  const { settings } = await import('../../src/renderer/src/stores/settings')
  const meta = { revision: 'rev-1', schema_version: 1, fields: fields(), status: { counts: {}, desired_revision: 'rev-1', effective_revision: null } }
  settings.meta = meta
  bridge.settingsSchema.mockImplementation(async () => ok(settings.meta))
  for (const name of ['providersCompatSet', 'providersOllamaSet', 'providersCodexSet', 'settingsSet']) bridge[name].mockImplementation(async ({ changes }: any) => {
    const changed = changes.map(({ path, value }: any) => ({ ...settings.meta!.fields.find((item) => item.path === path), desired: value, effective: value }))
    return ok({ revision: 'rev-2', fields: changed })
  })
  bridge.editLeaf.mockImplementation(async () => ok({ status: 'updated' }))
  bridge.secretsSet.mockImplementation(async () => ok({ status: 'stored' }))
  mounted = mount((await import('../../src/renderer/src/components/CodexAccounts.vue')).default); await flush()
  return { root: mounted.root, settings }
}
const control = (root: Host, id: string) => root.findAll((item) => item.props.id === id)[0]!
describe('UI v1 curated Models', () => {
  it('keeps context immediately after main, quota zero, explicit owners and no schema paths', async () => {
    const { root } = await models()
    expect(root.findAll((item) => item.tag === 'h3').map((item) => item.textContent()).slice(0, 5)).toEqual(['Main model', 'Context', 'Agents', 'Accounts and quota', 'Providers'])
    expect(root.textContent()).toContain('0% of the 5-hour limit used')
    expect(root.textContent()).not.toContain('llm_provider.model')
    expect(root.textContent()).not.toContain('Reset to default')
    expect(bridge.editLeaf).not.toHaveBeenCalled()
  })
  it('configures disabled providers without blur writes or enabling, saves both values once', async () => {
    const { root, settings } = await models()
    root.named('Configure OpenAI-compatible').fire('click'); await flush()
    control(root, settingsControlId('curated', 'openai_compatible.base_url')).type('https://new.test/v1')
    control(root, settingsControlId('curated', 'openai_compatible.model')).type('new-model'); await flush()
    expect(bridge.providersCompatSet).not.toHaveBeenCalled()
    root.button('Save OpenAI-compatible setup').fire('click'); await flush()
    expect(bridge.providersCompatSet).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'rev-1', changes: [{ path: 'openai_compatible.base_url', value: 'https://new.test/v1' }, { path: 'openai_compatible.model', value: 'new-model' }] })
    expect(settings.meta!.fields.find((item) => item.path === 'openai_compatible.enabled')!.desired).toBe(false)
  })
  it('preserves typing during a held provider receipt and keeps Cancel local', async () => {
    const { root } = await models()
    let settle!: (value: unknown) => void
    bridge.providersOllamaSet.mockImplementation(() => new Promise((resolve) => { settle = resolve }))
    root.named('Configure Ollama').fire('click'); await flush()
    const input = control(root, settingsControlId('curated', 'ollama.model'))
    input.type('first'); root.button('Save Ollama setup').fire('click'); await flush()
    input.type('newer'); await flush()
    settle(ok({ revision: 'rev-2', fields: [make('ollama.model', 'first', 'providers.ollama.set')] })); await flush()
    expect(input.value).toBe('newer')
    expect(root.textContent()).toContain('Unsaved changes')
    root.button('Cancel Ollama changes').fire('click'); await flush()
    expect(input.value).toBe('first')
    expect(bridge.providersOllamaSet).toHaveBeenCalledTimes(1)
  })
  it('submits main model and effort as one dedicated operation without silent downgrade', async () => {
    const { root } = await models()
    control(root, settingsControlId('curated', 'llm_provider.model')).fire('change', { target: { value: 'codex:second' } }); await flush()
    control(root, settingsControlId('curated', 'openai_codex.reasoning_effort')).fire('change', { target: { value: 'xhigh' } }); await flush()
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    root.button('Save main model').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.main.set', params: { model: 'codex:second', reasoning_effort: 'xhigh', expected_revision: 'rev-1' } })
  })
  it('uses projected per-model efforts and leaves incompatible drafts unsaved without downgrade', async () => {
    const { root } = await models()
    const effort = control(root, settingsControlId('curated', 'openai_codex.reasoning_effort'))
    expect(effort.findAll((item) => item.tag === 'option').map((item) => item.props.value)).toEqual(['low', 'high'])
    effort.fire('change', { target: { value: 'xhigh' } }); await flush()
    expect(effort.value).toBe('xhigh')
    expect(root.button('Save main model').props.disabled).toBe(true)
    root.button('Save main model').fire('click'); await flush()
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    expect(root.textContent()).toContain('not changed automatically')
  })
  it('retains mixed candidate policies and ranking, and does not send keystrokes', async () => {
    const { root } = await models()
    control(root, settingsControlId('curated', 'agents.auto_model_allowlist.1.model')).fire('change', { target: { value: 'codex:new-second' } })
    root.named('Move model 2 up').fire('click'); await flush()
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    root.button('Save agent policy').fire('click'); await flush()
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method: 'models.agents.set', params: { model: 'auto', auto_model_allowlist: [{ model: 'codex:new-second', reasoning_effort: 'high' }, 'codex:first'], expected_revision: 'rev-1' } })
  })
  it('stores keys only explicitly, never reads secrets or includes them in provider saves', async () => {
    const { root } = await models()
    root.named('Configure OpenAI-compatible').fire('click'); await flush()
    const key = control(root, settingsControlId('curated', 'openai_compatible.api_key'))
    expect(key.value).toBe('')
    expect(root.textContent()).not.toContain('[redacted]')
    key.type('new-key'); await flush()
    expect(bridge.secretsSet).not.toHaveBeenCalled()
    root.named('Replace OpenAI-compatible API key').fire('click'); await flush()
    expect(bridge.secretsSet).toHaveBeenCalledExactlyOnceWith({ path: 'openai_compatible.api_key', value: 'new-key' })
    expect(key.value).toBe('')
    expect(bridge.providersCompatSet).not.toHaveBeenCalled()
  })
  it('clears submitted write-only keys after a refused store without replay', async () => {
    bridge.secretsSet.mockResolvedValue({ ok: false, error: { code: 'secret_locked', message: 'Key store is locked.' } })
    const { root } = await models()
    root.named('Configure OpenAI-compatible').fire('click'); await flush()
    const key = control(root, settingsControlId('curated', 'openai_compatible.api_key'))
    key.type('failed-write-only-key'); await flush()
    root.named('Replace OpenAI-compatible API key').fire('click'); await flush()
    expect(bridge.secretsSet).toHaveBeenCalledExactlyOnceWith({ path: 'openai_compatible.api_key', value: 'failed-write-only-key' })
    expect(key.value).toBe('')
    expect(root.textContent()).not.toContain('failed-write-only-key')
    root.named('Replace OpenAI-compatible API key').fire('click'); await flush()
    expect(bridge.secretsSet).toHaveBeenCalledTimes(1)
  })
  it('rejects unknown grouped save and fences later provider intent without replay', async () => {
    const { root, settings } = await models()
    bridge.providersOllamaSet.mockResolvedValue({ ok: false, error: { code: 'outcome_unknown', message: 'Unknown', disposition: 'outcome_unknown' } })
    root.named('Configure Ollama').fire('click'); await flush()
    control(root, settingsControlId('curated', 'ollama.model')).type('new'); root.button('Save Ollama setup').fire('click'); await flush()
    expect(settings.unknownSave).toBe(true)
    root.button('Save Ollama setup').fire('click'); await flush()
    expect(bridge.providersOllamaSet).toHaveBeenCalledTimes(1)
    expect(control(root, settingsControlId('curated', 'ollama.model')).value).toBe('new')
  })
  it('serializes provider and secret writes, taking the revision settled by the previous owner', async () => {
    const { settings } = await models()
    const { saveFields, setSecret } = await import('../../src/renderer/src/stores/settings')
    let settle!: (answer: unknown) => void
    bridge.providersOllamaSet.mockImplementation(() => new Promise((resolve) => { settle = resolve }))
    const saving = saveFields([{ field: settings.meta!.fields.find((item) => item.path === 'ollama.model')!, value: 'new' }])
    const key = setSecret(settings.meta!.fields.find((item) => item.path === 'openai_compatible.api_key')!, 'new-key')
    await flush()
    expect(bridge.secretsSet).not.toHaveBeenCalled()
    settle(ok({ revision: 'rev-2', fields: [make('ollama.model', 'new', 'providers.ollama.set')] }))
    expect(await saving).toBe(true)
    expect(await key).toBe(true)
    expect(bridge.secretsSet).toHaveBeenCalledTimes(1)
    expect(settings.meta!.revision).toBe('rev-2')
  })
  it('fences a grouped authority change while queued and does not replay against new metadata', async () => {
    const { settings } = await models()
    const { saveFields } = await import('../../src/renderer/src/stores/settings')
    let settle!: (answer: unknown) => void
    bridge.providersOllamaSet.mockImplementation(() => new Promise((resolve) => { settle = resolve }))
    const first = saveFields([{ field: settings.meta!.fields.find((item) => item.path === 'ollama.model')!, value: 'new' }])
    const second = saveFields([{ field: settings.meta!.fields.find((item) => item.path === 'openai_compatible.model')!, value: 'new-compatible' }])
    await flush()
    settings.meta!.fields.find((item) => item.path === 'openai_compatible.model')!.constraints.max_length = 5
    settle(ok({ revision: 'rev-2', fields: [make('ollama.model', 'new', 'providers.ollama.set')] }))
    expect(await first).toBe(true)
    expect(await second).toBe(false)
    expect(bridge.providersCompatSet).not.toHaveBeenCalled()
  })
  it('never calls a successful model receipt Saved after its refresh fails or Odin changes', async () => {
    const { settings } = await models()
    const { saveModelSettings } = await import('../../src/renderer/src/stores/settings')
    bridge.settingsSchema.mockResolvedValue({ ok: false, error: { code: 'offline', message: 'Could not read settings.' } })
    expect(await saveModelSettings('models.main.set', { model: 'codex:new', reasoning_effort: 'high' })).toBe(false)
    expect(settings.fields['llm_provider.model']?.status).toBe('error')
    bridge.settingsSchema.mockImplementation(async () => { (await import('../../src/renderer/src/store')).state.recoveryEpoch += 1; return ok(settings.meta) })
    expect(await saveModelSettings('models.main.set', { model: 'codex:new', reasoning_effort: 'high' })).toBe(false)
    expect(settings.unknownSave).toBe(true)
    expect(settings.fields['llm_provider.model']?.status).toBe('error')
  })
  it('serializes image intent behind secrets and marks settlement after an epoch change unconfirmed', async () => {
    const { settings } = await models()
    const { setSecret, setImageIntent } = await import('../../src/renderer/src/stores/settings')
    settings.meta!.image_models_revision = 'image-rev'
    let settle!: (answer: unknown) => void
    bridge.secretsSet.mockImplementation(() => new Promise((resolve) => { settle = resolve }))
    bridge.imageModelIntent = vi.fn(async () => ok({ image_models_revision: 'image-next' }))
    const first = setSecret(settings.meta!.fields.find((item) => item.path === 'openai_compatible.api_key')!, 'new-key')
    const second = setImageIntent('image_model', 'pin')
    await flush(); expect(bridge.imageModelIntent).not.toHaveBeenCalled()
    settle(ok({ stored: true })); expect(await first).toBe(true); expect(await second).toBe(true)
    expect(bridge.imageModelIntent).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'image-rev', operations: { image_model: 'pin' } })
    bridge.imageModelIntent.mockImplementation(async () => { (await import('../../src/renderer/src/store')).state.recoveryEpoch += 1; return ok({ image_models_revision: 'image-next' }) })
    expect(await setImageIntent('image_model', 'follow')).toBe(false)
    expect(settings.fields['image.openai.image_model']?.status).toBe('error')
    expect(settings.unknownSave).toBe(true)
  })
  it('rejects out-of-order model choices and clears capabilities after failed refresh', async () => {
    let settle!: (answer: unknown) => void
    bridge.modelsStatus.mockImplementationOnce(() => new Promise((resolve) => { settle = resolve }))
    const { root } = await models()
    const effort = control(root, settingsControlId('curated', 'openai_codex.reasoning_effort'))
    root.button('Refresh model choices').fire('click'); await flush()
    expect(effort.findAll((item) => item.tag === 'option').map((item) => item.props.value)).toEqual(['low', 'high'])
    settle(ok({ model_catalogue: { codex: [{ ref: 'codex:first', effort_capabilities: { values: ['WRONG'], source: 'core_validation', restrictions_known: true } }] } })); await flush()
    expect(effort.textContent()).not.toContain('WRONG')
    bridge.modelsStatus.mockResolvedValue({ ok: false, error: { code: 'offline', message: 'Model choices offline' } })
    // Refresh remains available even after a successful read.
    root.button('Refresh model choices').fire('click'); await flush()
    expect(effort.props.disabled).toBe(true)
    expect(root.button('Save main model').props.disabled).toBe(true)
  })
})
