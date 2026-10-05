// The settings form, mounted with its real code and the real settings store over a fake bridge whose writes the test
// lands one at a time.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import type { ConfigField, ConfigMeta, Result } from '../../src/shared/api'
import { flush, mount, type Host } from './component-host'

type SettingsStore = typeof import('../../src/renderer/src/stores/settings')

function field(path: string, extra: Partial<ConfigField>): ConfigField {
  return {
    path, label: path, description: '', type: 'string', enum: null, constraints: {}, default: null, nullable: false,
    sensitivity: 'public', apply_mode: 'live_read', apply_handler: null, restart_reason: null, activation_policy: null,
    consumers: [], save_effect: '', runtime_effect: null, desired: null, effective: null, configured: true,
    pending_restart: false, apply_state: 'applied', ...extra
  }
}

let store: SettingsStore
let root: Host
/** What the core holds, by path. */
let core: Record<string, unknown>
let writes: Array<{ path: string; value: unknown }>
let landing: Array<() => void>
let revision: number

function meta(): ConfigMeta {
  return {
    schema_version: 1,
    revision: `rev-${revision}`,
    fields: [
      field('learning.enabled', { type: 'boolean', desired: core['learning.enabled'] }),
      field('timezone', { desired: core.timezone, default: 'UTC' }),
      field('discord.token', { sensitivity: 'sensitive', desired: core['discord.token'] !== undefined })
    ],
    status: { counts: {}, desired_revision: `rev-${revision}`, effective_revision: null },
    image_models: {},
    image_models_revision: 'img-1'
  } as unknown as ConfigMeta
}

/** A write the core applies when the test lands it. */
function held<T>(apply: () => T): Promise<Result<T>> {
  return new Promise((resolve) => landing.push(() => resolve({ ok: true, result: apply() })))
}

async function land(): Promise<void> {
  landing.shift()!()
  await flush()
}

beforeEach(async () => {
  vi.resetModules()
  core = { 'learning.enabled': false, timezone: 'Europe/Paris' }
  writes = []
  landing = []
  revision = 1
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      settingsSchema: async () => ({ ok: true, result: meta() }),
      settingsSet: (params: { changes: Array<{ path: string; value?: unknown; delete?: boolean }> }) => {
        const change = params.changes[0]!
        writes.push({ path: change.path, value: change.delete ? 'default' : change.value })
        return held(() => {
          core[change.path] = change.delete ? 'UTC' : change.value
          revision += 1
          return { revision: `rev-${revision}`, fields: meta().fields.filter((f) => f.path === change.path) }
        })
      },
      secretsSet: (params: { path: string; value: string }) => {
        writes.push({ path: params.path, value: params.value })
        return held(() => ((core[params.path] = params.value), { set: true }))
      }
    }
  }
  store = await import('../../src/renderer/src/stores/settings')
  await store.loadSettings()
  const SchemaForm = (await import('../../src/renderer/src/components/SchemaForm.vue')).default
  root = mount({ render: () => h(SchemaForm, { fields: store.settings.meta!.fields }) }).root
  await flush()
})

/** The field's own block in the form. */
const fieldBlock = (path: string): Host =>
  root.findAll((host) => String(host.props.class).split(' ').includes('field') && host.find('code')?.textContent() === path)[0]!
const input = (match: (host: Host) => boolean): Host => root.findAll((host) => host.tag === 'input' && match(host))[0]!
const checkbox = (): Host => input((host) => host.props.type === 'checkbox')
const text = (): Host => input((host) => host.props.type === 'text')
const secret = (): Host => input((host) => host.props.type === 'password')

describe('review round 4: the settings form never drops or erases what the user did', () => {
  it('saves a second choice made while the first is on its way (12.R4.1)', async () => {
    checkbox().fire('change', { target: { checked: true } })
    await flush()
    expect(fieldBlock('learning.enabled').button('Reset to default').props.disabled).toBe(true)
    checkbox().fire('change', { target: { checked: false } })
    await flush()
    await land()
    await land()
    expect(writes.map((w) => w.value)).toEqual([true, false])
    expect(core['learning.enabled']).toBe(false)
    expect(checkbox().props.checked).toBe(false)
  })

  it('keeps a value typed while a reset is on its way (12.2)', async () => {
    fieldBlock('timezone').button('Reset to default').fire('click')
    await flush()
    text().fire('input', { target: { value: 'Asia/Tokyo' } })
    await land()
    expect(core.timezone).toBe('UTC')
    expect(text().props.value).toBe('Asia/Tokyo')
  })

  it('writes a secret once for Enter and Save, and keeps a newer one typed during it (12.2)', async () => {
    secret().fire('input', { target: { value: 'value-a' } })
    await flush()
    secret().fire('keydown', { key: 'Enter' })
    fieldBlock('discord.token').button('Save').fire('click')
    secret().fire('input', { target: { value: 'value-b' } })
    await land()
    expect(writes.map((w) => w.value)).toEqual(['value-a'])
    expect(secret().props.value).toBe('value-b')
  })
})
