import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigField, ConfigMeta, Result } from '../../src/shared/api'

type Store = typeof import('../../src/renderer/src/stores/settings')
type App = typeof import('../../src/renderer/src/store')
const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const failure = (code = 'rejected', disposition?: string): Result<never> => ({ ok: false, error: { code, message: 'Deliberate refusal', ...(disposition ? { disposition } : {}) } })
const field = (path: string, owner: string | null = 'settings.set', extra: Partial<ConfigField> = {}): ConfigField => ({
  path, label: path, description: '', type: 'string', enum: null, constraints: {}, default: null, nullable: false,
  sensitivity: 'public', apply_mode: 'live_read', apply_handler: owner, restart_reason: null, activation_policy: null,
  consumers: [], save_effect: '', runtime_effect: null, desired: 'old', effective: 'old', configured: false,
  pending_restart: false, apply_state: 'applied', ...extra
})
function deferred<T>() {
  let resolve!: (answer: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
let store: Store
let app: App
let meta: ConfigMeta
let bridge: Record<'settingsSchema' | 'status' | 'usage' | 'providersOllamaSet' | 'settingsSet' | 'editLeaf' | 'secretsSet' | 'secretsClear', ReturnType<typeof vi.fn>>
beforeEach(async () => {
  vi.resetModules()
  meta = { schema_version: 1, revision: 'r1', fields: [field('ollama.model', 'providers.ollama.set'), field('ollama.base_url', 'providers.ollama.set'), field('timezone'), field('llm_provider.model', 'models.main.set'), field('agents.model', 'models.agents.set')], status: { counts: {}, desired_revision: 'r1', effective_revision: null } }
  bridge = {
    settingsSchema: vi.fn(async () => ok(structuredClone(meta))),
    status: vi.fn(async () => failure('unavailable')), usage: vi.fn(async () => failure('unavailable')),
    providersOllamaSet: vi.fn(async ({ changes }) => ok({ revision: 'r2', fields: changes.map(({ path, value }: { path: string; value: unknown }) => ({ ...meta.fields.find((item) => item.path === path)!, desired: value, effective: value })) })),
    settingsSet: vi.fn(async () => ok({ revision: 'r2', fields: [] })), editLeaf: vi.fn(async () => ok({ status: 'updated' })),
    secretsSet: vi.fn(async () => ok({ status: 'stored' })), secretsClear: vi.fn(async () => ok({ status: 'cleared' }))
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
  store = await import('../../src/renderer/src/stores/settings')
  app = await import('../../src/renderer/src/store')
  await store.loadSettings()
})
const current = (path: string) => store.settings.meta!.fields.find((item) => item.path === path)!
const group = () => [{ field: current('ollama.model'), value: 'new' }, { field: current('ollama.base_url'), value: 'http://local.test:11434' }]

describe('UI v1 grouped settings write authority and settlement', () => {
  it('adopts one multi-field owner receipt and gives the next queued command its new revision', async () => {
    const saved = store.saveFields(group())
    const command = vi.fn(async () => ok({ status: 'done' }))
    const queued = store.settingsCommand(command)
    expect(await saved).toBe(true)
    expect(await queued).toEqual(ok({ status: 'done' }))
    expect(bridge.providersOllamaSet).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'r1', changes: [{ path: 'ollama.model', value: 'new' }, { path: 'ollama.base_url', value: 'http://local.test:11434' }] })
    expect(command).toHaveBeenCalledExactlyOnceWith('r2')
    expect(current('ollama.model').desired).toBe('new')
    expect(store.settings.fields['ollama.base_url']).toEqual({ status: 'saved' })
  })
  it('routes a uniform generic group through settingsSet and ignores unrelated receipt records', async () => {
    bridge.settingsSet.mockResolvedValue(ok({ revision: 'r3', fields: [field('unadvertised.path')] }))
    expect(await store.saveFields([{ field: current('timezone'), value: 'UTC' }])).toBe(true)
    expect(bridge.settingsSet).toHaveBeenCalledExactlyOnceWith({ expected_revision: 'r1', changes: [{ path: 'timezone', value: 'UTC' }] })
    expect(store.settings.meta!.fields.some((item) => item.path === 'unadvertised.path')).toBe(false)
    expect(store.settings.meta!.revision).toBe('r3')
  })
  it.each(['missing-meta', 'empty', 'missing-field', 'secret', 'unsupported', 'dedicated', 'changed-authority', 'mixed-owners'])('blocks %s before any grouped mutation', async (reason) => {
    let changes = group()
    if (reason === 'missing-meta') store.settings.meta = null
    if (reason === 'empty') changes = []
    if (reason === 'missing-field') store.settings.meta!.fields.splice(0, 1)
    if (reason === 'secret') { current('ollama.model').sensitivity = 'sensitive'; changes = group() }
    if (reason === 'unsupported') { current('ollama.model').apply_handler = 'unsupported.owner'; changes = group() }
    if (reason === 'dedicated') changes = [{ field: current('llm_provider.model'), value: 'codex:new' }]
    if (reason === 'changed-authority') changes[0]!.field = { ...changes[0]!.field, constraints: { max_length: 20 } }
    if (reason === 'mixed-owners') changes.push({ field: current('timezone'), value: 'UTC' })
    expect(await store.saveFields(changes)).toBe(false)
    expect(bridge.providersOllamaSet).not.toHaveBeenCalled()
    expect(bridge.settingsSet).not.toHaveBeenCalled()
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    expect(store.settings.unknownSave).toBe(false)
  })
  it('reloads on stale group receipt and marks every member rejected without replay', async () => {
    bridge.providersOllamaSet.mockResolvedValue(failure('stale_binding'))
    expect(await store.saveFields(group())).toBe(false)
    expect(bridge.settingsSchema).toHaveBeenCalledTimes(2)
    for (const path of ['ollama.model', 'ollama.base_url']) expect(store.settings.fields[path]).toEqual({ status: 'error', message: 'Settings changed elsewhere. Check, then save again.' })
    expect(current('ollama.model').desired).toBe('old')
    expect(bridge.providersOllamaSet).toHaveBeenCalledOnce()
  })
  it('reports definite group refusal while fencing queued command intent only', async () => {
    bridge.providersOllamaSet.mockResolvedValue(failure())
    const saving = store.saveFields(group())
    const command = vi.fn(async () => ok({}))
    const queued = store.settingsCommand(command)
    expect(await saving).toBe(false)
    expect(await queued).toMatchObject({ ok: false, error: { code: 'stale_binding' } })
    expect(command).not.toHaveBeenCalled()
    expect(store.settings.fields['ollama.model']).toEqual({ status: 'error', message: 'Deliberate refusal' })
    expect(store.settings.unknownSave).toBe(false)
    expect(await store.settingsCommand(command)).toEqual(ok({}))
  })
  it('treats a thrown group transport as unknown without dispatching the already queued group', async () => {
    bridge.providersOllamaSet.mockRejectedValue(new Error('lost transport'))
    const first = store.saveFields(group())
    const second = store.saveFields(group())
    expect(await first).toBe(false)
    expect(await second).toBe(false)
    expect(bridge.providersOllamaSet).toHaveBeenCalledOnce()
    expect(store.settings.unknownSave).toBe(true)
    expect(store.settings.notice).toContain('Refresh, check')
  })
  it.each(['no_receipt', 'outcome_unknown', 'unknown'])('keeps %s blocked until a successful explicit refresh', async (code) => {
    bridge.providersOllamaSet.mockResolvedValue(failure(code))
    expect(await store.saveFields(group())).toBe(false)
    expect(store.settings.unknownSave).toBe(true)
    await store.loadSettings()
    expect(store.settings.unknownSave).toBe(true)
    expect(await store.saveFields(group())).toBe(false)
    expect(bridge.providersOllamaSet).toHaveBeenCalledOnce()
    await store.loadSettings(true)
    expect(store.settings.unknownSave).toBe(false)
    expect(store.settings.notice).toBe('')
  })
  it.each(['receipt', 'status-refresh'])('rejects old-core grouped success at %s', async (phase) => {
    const held = deferred<Result<any>>()
    if (phase === 'receipt') bridge.providersOllamaSet.mockReturnValue(held.promise)
    else bridge.status.mockReturnValue(held.promise)
    const saving = store.saveFields(group())
    await vi.waitFor(() => expect(phase === 'receipt' ? bridge.providersOllamaSet : bridge.status).toHaveBeenCalledOnce())
    app.state.app.coreInstanceId = 'replacement'
    held.resolve(phase === 'receipt' ? ok({ revision: 'old-core-r2', fields: [field('ollama.model', 'providers.ollama.set', { desired: 'old-core' })] }) : failure('unavailable'))
    expect(await saving).toBe(false)
    expect(store.settings.unknownSave).toBe(true)
    for (const path of ['ollama.model', 'ollama.base_url']) expect(store.settings.fields[path]?.status).toBe('error')
    if (phase === 'receipt') expect(store.settings.meta!.revision).toBe('r1')
  })
  it('captures shape before queuing and refuses changed authority after an earlier receipt', async () => {
    const held = deferred<Result<unknown>>()
    const first = store.settingsCommand(() => held.promise)
    const queued = store.saveFields(group())
    await Promise.resolve()
    current('ollama.model').nullable = true
    held.resolve(ok({}))
    await first
    expect(await queued).toBe(false)
    expect(bridge.providersOllamaSet).not.toHaveBeenCalled()
    expect(store.settings.notice).toContain('settings changed')
  })
})

describe('UI v1 dedicated model writes', () => {
  it.each(['models.main.set', 'models.agents.set'] as const)('uses %s once with the current revision then reloads authoritative fields', async (method) => {
    meta.revision = 'authoritative-r2'
    expect(await store.saveModelSettings(method, { model: 'new', expected_revision: 'forged' })).toBe(true)
    expect(bridge.editLeaf).toHaveBeenCalledExactlyOnceWith({ method, params: { model: 'new', expected_revision: 'r1' } })
    expect(store.settings.meta!.revision).toBe('authoritative-r2')
    expect(store.settings.fields[method === 'models.main.set' ? 'llm_provider.model' : 'agents.model']).toEqual({ status: 'saved' })
  })
  it.each(['missing', 'owner', 'shape'])('refuses %s model binding without sending draft intent', async (reason) => {
    const pending = store.saveModelSettings('models.main.set', { model: 'new' })
    if (reason === 'missing') store.settings.meta = null
    else if (reason === 'owner') current('llm_provider.model').apply_handler = 'settings.set'
    else current('llm_provider.model').enum = ['old']
    expect(await pending).toBe(false)
    expect(bridge.editLeaf).not.toHaveBeenCalled()
    expect(store.settings.fields['llm_provider.model']?.status).toBe('error')
  })
  it.each(['stale_binding', 'rejected', 'unconfirmed'])('handles %s dedicated receipt without adopting a success', async (code) => {
    bridge.editLeaf.mockResolvedValue(failure(code, code === 'unconfirmed' ? 'outcome_unknown' : undefined))
    expect(await store.saveModelSettings('models.agents.set', { model: 'new' })).toBe(false)
    expect(store.settings.fields['agents.model']?.status).toBe('error')
    expect(bridge.settingsSchema).toHaveBeenCalledTimes(code === 'stale_binding' ? 2 : 1)
    expect(store.settings.unknownSave).toBe(code === 'unconfirmed')
  })
  it.each(['read_error', 'unavailable'])('does not claim model saved when authoritative refresh is %s', async (code) => {
    bridge.settingsSchema.mockResolvedValue(failure(code))
    expect(await store.saveModelSettings('models.main.set', { model: 'new' })).toBe(false)
    expect(store.settings.fields['llm_provider.model']).toEqual({ status: 'error', message: 'Saved settings could not be refreshed. Check them before relying on this change.' })
  })
  it.each(['receipt', 'status-refresh'])('fences model settlement after core replacement at %s', async (phase) => {
    const held = deferred<Result<any>>()
    if (phase === 'receipt') bridge.editLeaf.mockReturnValue(held.promise)
    else bridge.status.mockReturnValue(held.promise)
    const saving = store.saveModelSettings('models.main.set', { model: 'new' })
    await vi.waitFor(() => expect(phase === 'receipt' ? bridge.editLeaf : bridge.status).toHaveBeenCalledOnce())
    app.state.recoveryEpoch += 1
    held.resolve(phase === 'receipt' ? ok({ status: 'updated' }) : failure('unavailable'))
    expect(await saving).toBe(false)
    expect(store.settings.unknownSave).toBe(true)
    expect(store.settings.fields['llm_provider.model']?.status).toBe('error')
  })
})

describe('UI v1 settings-affecting management command fence', () => {
  it.each(['unknown', 'missing', 'replacement'])('blocks a command with %s authority before dispatch', async (reason) => {
    const run = vi.fn(async () => ok({}))
    const pending = store.settingsCommand(run)
    if (reason === 'unknown') store.settings.unknownSave = true
    else if (reason === 'missing') store.settings.meta = null
    else app.state.app.coreInstanceId = 'replacement'
    expect(await pending).toMatchObject({ ok: false, error: { code: 'stale_binding' } })
    expect(run).not.toHaveBeenCalled()
  })
  it('turns thrown command transport into unknown outcome and blocks already queued group intent', async () => {
    const run = vi.fn(async () => { throw new Error('transport disappeared') })
    const pending = store.settingsCommand(run)
    const next = store.saveFields(group())
    expect(await pending).toMatchObject({ ok: false, error: { code: 'outcome_unknown', disposition: 'outcome_unknown' } })
    expect(await next).toBe(false)
    expect(store.settings.unknownSave).toBe(true)
    expect(bridge.providersOllamaSet).not.toHaveBeenCalled()
  })
  it('rejects an old-core command receipt and never invokes the queued command', async () => {
    const held = deferred<Result<unknown>>()
    const first = store.settingsCommand(() => held.promise)
    const later = vi.fn(async () => ok({}))
    const next = store.settingsCommand(later)
    await Promise.resolve()
    app.state.recoveryEpoch += 1
    held.resolve(ok({}))
    expect(await first).toMatchObject({ ok: false, error: { code: 'outcome_unknown' } })
    expect(await next).toMatchObject({ ok: false, error: { code: 'stale_binding' } })
    expect(later).not.toHaveBeenCalled()
    expect(store.settings.unknownSave).toBe(true)
  })
})
