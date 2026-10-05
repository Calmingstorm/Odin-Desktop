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
let calls: { set: Array<Record<string, unknown>>; edit: Array<Record<string, unknown>>; schema: number }
let setAnswer: Result<{ revision: string; fields: ConfigField[] }> | null

beforeEach(async () => {
  vi.resetModules()
  calls = { set: [], edit: [], schema: 0 }
  setAnswer = null
  meta = {
    schema_version: 1,
    revision: 'rev-1',
    fields: [field('timezone'), field('llm_provider.model', { apply_handler: 'models.main.set', apply_mode: 'live_apply' })],
    status: { counts: {}, desired_revision: 'rev-1', effective_revision: null }
  }
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      settingsSchema: async () => {
        calls.schema += 1
        return { ok: true, result: structuredClone(meta) }
      },
      settingsSet: async (params: Record<string, unknown>) => {
        calls.set.push(params)
        return setAnswer ?? { ok: true, result: { revision: 'rev-2', fields: [field('timezone', { desired: 'Europe/Paris' })] } }
      },
      editLeaf: async (params: Record<string, unknown>) => {
        calls.edit.push(params)
        return { ok: true, result: { status: 'switched' } }
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
