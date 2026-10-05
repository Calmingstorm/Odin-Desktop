// The settings menu's state, driven through a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigField, ConfigMeta, Result } from '../../src/shared/api'

type SettingsStore = typeof import('../../src/renderer/src/stores/settings')

function field(path: string, extra: Partial<ConfigField> = {}): ConfigField {
  return {
    path, label: path, description: '', type: 'string', enum: null, constraints: {}, default: null, nullable: false,
    sensitivity: 'public', apply_mode: 'live_read', apply_handler: null, restart_reason: null, activation_policy: null,
    consumers: [], save_effect: '', runtime_effect: null, desired: 'a', effective: 'a', configured: false,
    pending_restart: false, apply_state: 'applied', ...extra
  }
}

let store: SettingsStore
let meta: ConfigMeta
let calls: {
  set: Array<Record<string, unknown>>
  edit: Array<Record<string, unknown>>
  schema: number
  shaped: Array<[string, Record<string, unknown>]>
  intent: Array<Record<string, unknown>>
  removed: number[]
}
let setAnswer: Result<{ revision: string; fields: ConfigField[] }> | null
let holdSchema = false
let heldSchema: Array<(answer: Result<ConfigMeta>) => void> = []
let accountsAnswer: Result<unknown>
let releaseRemove: (() => void) | null = null
let holdAccounts = false
let releaseAccounts: (() => void) | null = null
const account = (index: number, id: string) => ({ index, account_id: id, email: `${id}@example.com`, plan_type: 'pro' })

beforeEach(async () => {
  vi.resetModules()
  calls = { set: [], edit: [], schema: 0, shaped: [], intent: [], removed: [] }
  holdSchema = false
  heldSchema = []
  releaseRemove = null
  holdAccounts = false
  releaseAccounts = null
  accountsAnswer = { ok: true, result: { configured: true, accounts: [account(0, 'acct_1'), account(1, 'acct_2')] } }
  setAnswer = null
  meta = {
    schema_version: 1,
    revision: 'rev-1',
    fields: [
      field('timezone'),
      field('llm_provider.model', { apply_handler: 'models.main.set', apply_mode: 'live_apply' }),
      field('ollama.base_url', { apply_handler: 'providers.ollama.set', apply_mode: 'live_apply' }),
      field('image.openai.image_model', { desired: 'gpt-image-2.5-flare' })
    ],
    status: { counts: {}, desired_revision: 'rev-1', effective_revision: null },
    image_models: {
      image_model: { effective: 'gpt-image-2.5-flare', default: 'gpt-image-2.5-flare', status: 'follow' },
      outer_model: { effective: 'gpt-6-astra', default: 'gpt-6-astra', status: 'follow' }
    },
    image_models_revision: 'img-1'
  }
  const shaped = (name: string) => async (params: Record<string, unknown>) => {
    calls.shaped.push([name, params])
    return {
      ok: true,
      result: { revision: 'rev-2', fields: [field('ollama.base_url', { desired: 'http://gpu:11434', apply_handler: 'providers.ollama.set', apply_mode: 'live_apply' })] }
    }
  }
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      settingsSchema: () => {
        calls.schema += 1
        const answer: Result<ConfigMeta> = { ok: true, result: structuredClone(meta) }
        if (!holdSchema) return Promise.resolve(answer)
        return new Promise<Result<ConfigMeta>>((resolve) => heldSchema.push(resolve))
      },
      codexAccounts: () => {
        if (!holdAccounts) return Promise.resolve(accountsAnswer)
        return new Promise<Result<unknown>>((resolve) => (releaseAccounts = () => resolve(accountsAnswer)))
      },
      codexRemove: (params: { index: number }) => {
        calls.removed.push(params.index)
        return new Promise<Result<unknown>>((resolve) => (releaseRemove = () => resolve({ ok: true, result: { status: 'deleted' } })))
      },
      settingsSet: async (params: Record<string, unknown>) => {
        calls.set.push(params)
        return setAnswer ?? { ok: true, result: { revision: 'rev-2', fields: [field('timezone', { desired: 'Europe/Paris' })] } }
      },
      editLeaf: async (params: Record<string, unknown>) => {
        calls.edit.push(params)
        return { ok: true, result: { status: 'switched' } }
      },
      providersCodexSet: shaped('providers.codex.set'),
      providersAuxiliarySet: shaped('providers.auxiliary.set'),
      providersOllamaSet: shaped('providers.ollama.set'),
      providersCompatSet: shaped('providers.compat.set'),
      computerActivationSet: shaped('computer.activation.set'),
      imageModelIntent: async (params: Record<string, unknown>) => {
        calls.intent.push(params)
        return { ok: true, result: { image_models: meta.image_models, image_models_revision: 'img-2', revision: 'rev-2' } }
      }
    }
  }
  store = await import('../../src/renderer/src/stores/settings')
  await store.loadSettings()
})

describe('saving a setting', () => {
  it('saves through settings.set with the revision it was read at, and shows the records the core returned', async () => {
    expect(await store.saveField(store.settings.meta!.fields[0]!, 'Europe/Paris')).toBe(true)
    expect(calls.set).toEqual([{ expected_revision: 'rev-1', changes: [{ path: 'timezone', value: 'Europe/Paris' }] }])
    expect(store.settings.meta!.revision).toBe('rev-2')
    expect(store.settings.meta!.fields[0]!.desired).toBe('Europe/Paris')
    expect(store.settings.fields.timezone).toEqual({ status: 'saved' })
  })

  it("saves a field Odin applies through a dedicated method through that method, then rereads Odin's records", async () => {
    const before = calls.schema
    expect(await store.saveField(store.settings.meta!.fields[1]!, 'gpt-6-luna')).toBe(true)
    expect(calls.edit).toEqual([{ method: 'models.main.set', params: { model: 'gpt-6-luna' } }])
    expect(calls.set).toEqual([])
    expect(calls.schema).toBe(before + 1)
  })

  it('reloads and says so when settings changed elsewhere, instead of overwriting them', async () => {
    setAnswer = { ok: false, error: { code: 'stale_binding', message: 'settings changed', disposition: 'stale_binding' } }
    const before = calls.schema
    expect(await store.saveField(store.settings.meta!.fields[0]!, 'Europe/Paris')).toBe(false)
    expect(calls.schema).toBe(before + 1)
    expect(store.settings.fields.timezone?.message).toMatch(/changed elsewhere/)
  })

  it('shows the field the core refused, with its reason', async () => {
    setAnswer = { ok: false, error: { code: 'bad_request', message: 'timezone: must be text', disposition: 'not_dispatched' } }
    expect(await store.saveField(store.settings.meta!.fields[0]!, 'x')).toBe(false)
    expect(store.settings.fields.timezone).toEqual({ status: 'error', message: 'timezone: must be text' })
  })
})

describe('review round 2: each field saves through the method that owns it', () => {
  it("saves a provider field through its owner's settings-shaped method, with settings.set's params", async () => {
    const ollama = store.settings.meta!.fields.find((f) => f.path === 'ollama.base_url')!
    expect(await store.saveField(ollama, 'http://gpu:11434')).toBe(true)
    expect(calls.shaped).toEqual([
      ['providers.ollama.set', { expected_revision: 'rev-1', changes: [{ path: 'ollama.base_url', value: 'http://gpu:11434' }] }]
    ])
    expect(calls.set).toEqual([])
    expect(store.settings.meta!.revision).toBe('rev-2')
    await store.resetField(store.settings.meta!.fields.find((f) => f.path === 'ollama.base_url')!)
    expect(calls.shaped[1]).toEqual(['providers.ollama.set', { expected_revision: 'rev-2', changes: [{ path: 'ollama.base_url', delete: true }] }])
  })

  it("pins or follows an image model with the intent's own revision, then rereads the records", async () => {
    const before = calls.schema
    expect(await store.setImageIntent('image_model', 'pin')).toBe(true)
    expect(calls.intent).toEqual([{ expected_revision: 'img-1', operations: { image_model: 'pin' } }])
    expect(calls.schema).toBe(before + 1)
  })
})

describe('review round 3: accounts are acted on by who they are', () => {
  it("stays locked until the refreshed list is in, then refuses an action meant for an account that moved", async () => {
    await store.loadCodex()
    const shown = store.settings.codex.status!.accounts[0]!
    const removing = store.removeAccount(shown)
    await store.removeAccount(shown) // a second confirmed click while the first is on its way
    expect(calls.removed).toEqual([0])
    accountsAnswer = { ok: true, result: { configured: true, accounts: [account(0, 'acct_2')] } }
    holdAccounts = true
    releaseRemove!()
    await new Promise((r) => setTimeout(r, 0))
    await store.removeAccount(shown) // answered, but the refreshed list isn't in yet
    expect(calls.removed).toEqual([0])
    releaseAccounts!()
    await removing
    expect(store.settings.codex.busy).toBe(false)
    await store.removeAccount(shown) // the dialog still showed the first account at index 0
    expect(calls.removed).toEqual([0])
    expect(store.settings.codex.notes.acct_1).toMatch(/accounts changed/)
  })

  it('keeps every account control locked when the list could not be refreshed', async () => {
    await store.loadCodex()
    const shown = store.settings.codex.status!.accounts[1]!
    const removing = store.removeAccount(shown)
    accountsAnswer = { ok: false, error: { code: 'unavailable', message: 'core restarting', disposition: 'not_dispatched' } }
    releaseRemove!()
    await removing
    expect(store.settings.codex.stale).toBe(true)
    await store.removeAccount(store.settings.codex.status!.accounts[0]!)
    expect(calls.removed).toEqual([1])
  })
})

describe('review round 3: settings stay the newest the window has seen', () => {
  it('never lets an older read replace a newer one or an adopted answer', async () => {
    holdSchema = true
    void store.loadSettings()
    meta = { ...meta, revision: 'rev-9' }
    void store.loadSettings()
    heldSchema[1]!({ ok: true, result: structuredClone(meta) })
    await new Promise((r) => setTimeout(r, 0))
    heldSchema[0]!({ ok: true, result: { ...structuredClone(meta), revision: 'rev-1' } })
    await new Promise((r) => setTimeout(r, 0))
    expect(store.settings.meta!.revision).toBe('rev-9')
    void store.loadSettings() // still on its way when a save lands
    holdSchema = false
    await store.saveField(store.settings.meta!.fields[0]!, 'Europe/Paris')
    heldSchema[2]!({ ok: true, result: { ...structuredClone(meta), revision: 'rev-older' } })
    await new Promise((r) => setTimeout(r, 0))
    expect(store.settings.meta!.revision).toBe('rev-2')
  })

  it("rereads the image model's follow or pin after its value is saved", async () => {
    const image = store.settings.meta!.fields.find((f) => f.path === 'image.openai.image_model')!
    const before = calls.schema
    await store.saveField(image, 'gpt-image-3')
    expect(calls.schema).toBe(before + 1)
  })
})


describe('review round 4: an older account list never comes back', () => {
  it("can't restore indexes a removal shifted, so the wrong account is never removed (12.1)", async () => {
    await store.loadCodex()
    const shown = store.settings.codex.status!.accounts[0]!
    holdAccounts = true
    const olderRead = store.loadCodex() // read before the removal, answered after it
    const releaseOlder = releaseAccounts!
    holdAccounts = false
    const removing = store.removeAccount(shown)
    accountsAnswer = { ok: true, result: { configured: true, accounts: [account(0, 'acct_2')] } }
    releaseRemove!()
    await removing
    expect(store.settings.codex.status!.accounts.map((a) => a.account_id)).toEqual(['acct_2'])
    accountsAnswer = { ok: true, result: { configured: true, accounts: [account(0, 'acct_1'), account(1, 'acct_2')] } }
    releaseOlder()
    await olderRead
    expect(store.settings.codex.status!.accounts.map((a) => a.account_id)).toEqual(['acct_2'])
    await store.removeAccount(shown) // the dialog still showed the first account at index 0
    expect(calls.removed).toEqual([0])
  })

  it('keeps the controls locked when only a read from before the action answers', async () => {
    await store.loadCodex()
    holdAccounts = true
    const olderRead = store.loadCodex()
    const releaseOlder = releaseAccounts!
    const removing = store.removeAccount(store.settings.codex.status!.accounts[1]!)
    releaseOlder() // answers while the removal is still on its way
    await olderRead
    expect(store.settings.codex.stale).toBe(true)
    holdAccounts = false
    releaseRemove!()
    await removing
    expect(store.settings.codex.stale).toBe(false)
  })

  it("tells accounts apart by email when the core's ID is empty", async () => {
    const anonymous = (index: number, email: string) => ({ index, account_id: '', email, plan_type: 'pro' })
    accountsAnswer = { ok: true, result: { configured: true, accounts: [anonymous(0, 'a@example.com')] } }
    await store.loadCodex()
    const shown = store.settings.codex.status!.accounts[0]!
    accountsAnswer = { ok: true, result: { configured: true, accounts: [anonymous(0, 'b@example.com')] } }
    await store.loadCodex()
    await store.removeAccount(shown)
    expect(calls.removed).toEqual([])
    expect(store.accountIdentity(shown)).toBe('a@example.com')
  })
})
