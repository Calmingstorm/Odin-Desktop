import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConfigMeta, Result } from '../../src/shared/api'
import { flush, mount, type Host, type Mounted } from './component-host'

let root: Host
let mounted: Mounted
let schemaCalls = 0
const localNotifications = { enabled: true, previews: true, muted: [], quietHours: { enabled: false, start: '22:00', end: '08:00' } }
const localAutostart = vi.fn(async (enabled: boolean) => ({ ok: true, result: { autostart: enabled, notifications: localNotifications } }))
const localNotify = vi.fn(async (change: { enabled?: boolean }) => ({ ok: true, result: { notifications: { ...localNotifications, ...change } } }))

beforeEach(async () => {
  vi.resetModules()
  schemaCalls = 0
  localAutostart.mockClear()
  localNotify.mockClear()
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      settingsSchema: async (): Promise<Result<ConfigMeta>> => {
        schemaCalls++
        return { ok: false, error: { code: 'capability_unavailable', message: 'internal protocol text', disposition: 'not_dispatched' } }
      },
      codexAccounts: async () => ({ ok: false, error: { code: 'capability_unavailable', message: 'internal protocol text', disposition: 'not_dispatched' } }),
      setAutostart: localAutostart,
      setNotifications: localNotify
    }
  }
  const Settings = (await import('../../src/renderer/src/views/Settings.vue')).default
  const { state } = await import('../../src/renderer/src/store')
  state.notifications = localNotifications
  mounted = mount(Settings)
  root = mounted.root
  await flush()
})

afterEach(() => mounted.unmount())

describe('settings on a core without configuration capabilities', () => {
  it('keeps existing settings navigation visible and reports the unavailable surface plainly', async () => {
    const navButtons = () => root.findAll((host) => host.tag === 'button' && String(host.props.class).includes('settings-nav-item'))
    expect(navButtons().length).toBeGreaterThan(2)
    expect(root.textContent()).toContain('Start Odin when you log in')
    expect(root.textContent()).toContain('Local app settings')
    expect(root.textContent()).toContain('Core settings are unavailable in this core.')
    expect(root.textContent()).not.toContain('internal protocol text')

    const inputs = root.findAll((host) => host.tag === 'input')
    inputs[0]!.fire('change', { target: { checked: true } })
    inputs[1]!.fire('change', { target: { checked: false } })
    await flush()
    const { state } = await import('../../src/renderer/src/store')
    expect(localAutostart).toHaveBeenCalledWith(true)
    expect(localNotify).toHaveBeenCalledWith({ enabled: false })
    expect(state.autostart).toBe(true)
    expect(state.notifications?.enabled).toBe(false)

    for (const section of navButtons().map((button) => button.textContent().trim())) {
      navButtons().find((button) => button.textContent().trim() === section)!.fire('click')
      await flush()
      expect(root.textContent()).toContain('Core settings are unavailable in this core.')
      expect(root.textContent()).not.toContain('Try again')
    }

    navButtons().find((button) => button.textContent().trim() === 'Models and providers')!.fire('click')
    await flush()
    expect(root.textContent()).toContain('Codex accounts are unavailable in this core.')
    expect(root.textContent()).not.toContain('internal protocol text')
    expect(schemaCalls).toBe(1)
  })

  it('clears stale schema and account data and hides account actions when unavailable', async () => {
    const { settings, loadSettings, loadCodex } = await import('../../src/renderer/src/stores/settings')
    settings.meta = { schema_version: 1, revision: 'stale', fields: [], status: { counts: {}, desired_revision: 'stale', effective_revision: null }, image_models: { image_model: { effective: 'fixture-secret', default: 'fixture-secret', status: 'follow' }, outer_model: { effective: 'x', default: 'x', status: 'follow' } }, image_models_revision: 'stale' } as never
    settings.codex.status = { configured: true, accounts: [{ index: 0, account_id: 'stale-account', email: 'stale@example.com', plan_type: 'pro' }] } as never
    await loadSettings()
    await loadCodex()
    root.findAll((host) => host.tag === 'button' && String(host.props.class).includes('settings-nav-item'))
      .find((button) => button.textContent().trim() === 'Models and providers')!.fire('click')
    await flush()
    expect(settings.meta).toBeNull()
    expect(settings.codex.status).toBeNull()
    expect(root.textContent()).not.toContain('fixture-secret')
    expect(root.textContent()).not.toContain('stale@example.com')
    expect(root.textContent()).toContain('Codex accounts are unavailable in this core.')
    expect(root.textContent()).not.toContain('internal protocol text')
    expect(root.textContent()).not.toContain('Try again')
  })
})
