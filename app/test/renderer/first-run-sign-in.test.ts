import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CoreStatus, FirstRunStatus, Result } from '../../src/shared/api'
import { flush, mount, type Host, type Mounted } from './component-host'

// First open with Codex chosen and no account: the chat's setup banner is where signing in happens.
const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const signInNeeded: FirstRunStatus = { state: 'fresh', reason: 'provider_not_configured', keyring_unavailable: false, provider: 'codex', credential_present: false }
const core = (first_run?: FirstRunStatus): CoreStatus => ({ phase: 'ready', core_instance_id: 'test-core', version: 'test', capabilities: [], first_run })
const mounts: Mounted[] = []
let bridge: Record<string, ReturnType<typeof vi.fn>>
let store: typeof import('../../src/renderer/src/store')
let statuses: typeof import('../../src/renderer/src/stores/status')
let settingsStore: typeof import('../../src/renderer/src/stores/settings')
let message: { focus: ReturnType<typeof vi.fn> }

beforeEach(async () => {
  vi.resetModules()
  bridge = {
    status: vi.fn(async () => ok(core(signInNeeded))),
    usage: vi.fn(async () => ({ ok: false, error: { code: 'unavailable', message: 'Unavailable' } })),
    settingsSchema: vi.fn(async () => ok({ schema_version: 1, revision: 'r1', fields: [], status: { counts: {}, desired_revision: 'r1', effective_revision: 'r1', keyring_error: null } })),
    codexAccounts: vi.fn(async () => ok({ configured: false, accounts: [] })),
    codexLoginBegin: vi.fn(async () => ok({ login_id: '00000000-0000-4000-8000-000000000000', user_code: 'CODE-1234', interval: 3600, verify_url: 'https://auth.example/device' })),
    codexLoginPoll: vi.fn(async () => ok({ status: 'pending' })),
    copyText: vi.fn(async () => ok({})), codexOpenVerification: vi.fn(async () => ok({})),
    getSetupReminderHidden: vi.fn(async () => ok({ hidden: false })),
    setSetupReminderHidden: vi.fn(async (hidden: boolean) => ok({ hidden }))
  }
  message = { focus: vi.fn() }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null, body: {}, querySelector: vi.fn((selector: string) => selector === 'textarea[aria-label="Message"]' ? message : null) }
  store = await import('../../src/renderer/src/store')
  statuses = await import('../../src/renderer/src/stores/status')
  settingsStore = await import('../../src/renderer/src/stores/settings')
  store.state.app = { ...store.state.app, link: 'ready', coreInstanceId: 'test-core' }
  store.state.view = 'chat'
  await store.loadSetupReminder()
  await statuses.refreshStatus()
})
afterEach(() => {
  settingsStore.stopLogin()
  for (const v of mounts.splice(0)) v.unmount()
})

async function banner(): Promise<Mounted> {
  const v = mount((await import('../../src/renderer/src/components/FirstRunBanner.vue')).default, { dismissible: true })
  mounts.push(v)
  await flush()
  return v
}
const section = (v: Mounted) => v.root.find('section')
const buttons = (v: Mounted) => v.root.findAll((node) => node.tag === 'button').map((node) => node.textContent().trim())
const live = (v: Mounted): Host => v.root.findAll((node) => node.props.role === 'status')[0]!
async function become(first_run: FirstRunStatus): Promise<void> {
  bridge.status!.mockResolvedValue(ok(core(first_run)))
  await statuses.refreshStatus()
  await flush()
}

describe('Sign in from the first-run banner', () => {
  it('invites a Codex profile with no account to sign in where it is, with the other ways forward beside it', async () => {
    const v = await banner()
    expect(section(v)?.props['data-kind']).toBe('sign-in')
    expect(live(v).textContent()).toContain('Sign in to start chatting')
    expect(buttons(v)).toEqual(['Sign in with ChatGPT', 'Use another provider', 'Import from Odin', 'Set up later'])
    // The banner is no longer one live region: only its status part is.
    expect(section(v)?.props.role).toBeUndefined()
  })

  it('runs the one device sign-in in the banner, never announcing the code, and holds Set up later while it waits', async () => {
    const v = await banner()
    v.root.button('Sign in with ChatGPT').fire('click'); await flush()
    expect(bridge.codexLoginBegin).toHaveBeenCalledTimes(1)
    expect(settingsStore.settings.codex.login?.status).toBe('waiting')
    const signIn = v.root.findAll((node) => node.props['data-testid'] === 'codex-sign-in')[0]!
    expect(signIn.textContent()).toContain('CODE-1234')
    expect(signIn.textContent()).toContain('https://auth.example/device')
    for (const region of v.root.findAll((node) => node.props.role === 'status')) expect(region.textContent()).not.toContain('CODE-1234')
    expect(buttons(v)).not.toContain('Sign in with ChatGPT')
    expect(v.root.button('Set up later').props.disabled).toBe(true)
    v.root.button('Stop waiting').fire('click'); await flush()
    expect(v.root.button('Set up later').props.disabled).toBe(false)
    expect(buttons(v)).toContain('Sign in with ChatGPT')
    expect(bridge.setSetupReminderHidden).not.toHaveBeenCalled()
  })

  it('holds Set up later while a sign-in is still starting, so a late start never polls out of sight', async () => {
    let start!: (value: unknown) => void
    bridge.codexLoginBegin!.mockImplementationOnce(() => new Promise((resolve) => { start = resolve }))
    const v = await banner()
    v.root.button('Sign in with ChatGPT').fire('click'); await flush()
    expect(settingsStore.settings.codex.beginning).toBe(true)
    expect(v.root.button('Set up later').props.disabled).toBe(true)
    start(ok({ login_id: '00000000-0000-4000-8000-000000000000', user_code: 'CODE-1234', interval: 3600, verify_url: 'https://auth.example/device' })); await flush()
    expect(settingsStore.settings.codex.login?.status).toBe('waiting')
    expect(v.root.button('Set up later').props.disabled).toBe(true)
    expect(bridge.setSetupReminderHidden).not.toHaveBeenCalled()
  })

  it('goes once the core is ready after a sign-in started here, and gives the message box focus', async () => {
    const v = await banner()
    v.root.button('Sign in with ChatGPT').fire('click'); await flush()
    settingsStore.settings.codex.login = { ...settingsStore.settings.codex.login!, status: 'done', message: 'Signed in as person@example.test.' }
    // Signed in but not yet adopted: still a notice, never "ready".
    await become({ state: 'saved', reason: 'provider_identity_not_adopted', keyring_unavailable: false, provider: 'codex', credential_present: true })
    expect(section(v)?.props['data-state']).toBe('saved')
    expect(message.focus).not.toHaveBeenCalled()
    await become({ state: 'effective-ready', reason: 'provider_effective', keyring_unavailable: false, provider: 'codex', credential_present: true })
    expect(section(v)).toBeUndefined()
    expect(message.focus).toHaveBeenCalledTimes(1)
  })

  it('leaves focus alone when the user has moved on before the core was ready', async () => {
    const v = await banner()
    v.root.button('Sign in with ChatGPT').fire('click'); await flush()
    ;(document as unknown as { activeElement: unknown }).activeElement = { tagName: 'INPUT' }
    await become({ state: 'effective-ready', reason: 'provider_effective', keyring_unavailable: false, provider: 'codex', credential_present: true })
    expect(section(v)).toBeUndefined()
    expect(message.focus).not.toHaveBeenCalled()
  })

  it('sends another provider and importing to their own place in Settings', async () => {
    const v = await banner()
    v.root.button('Use another provider').fire('click'); await flush()
    expect([store.state.view, store.state.settingsSection, store.state.settingsTarget]).toEqual(['settings', 'models', 'providers'])
    store.state.view = 'chat'; store.state.settingsTarget = ''; await flush()
    v.root.button('Import from Odin').fire('click'); await flush()
    expect([store.state.view, store.state.settingsSection, store.state.settingsTarget]).toEqual(['settings', 'general', 'importer'])
  })

  it('keeps the general invitation when Codex is not the provider, its credential is stored, or the core does not say', async () => {
    const v = await banner()
    for (const first_run of [
      { ...signInNeeded, provider: 'compat' as const },
      { ...signInNeeded, state: 'incomplete' as const, reason: 'provider_configuration_incomplete' as const, credential_present: true },
      { state: 'fresh' as const, reason: 'provider_not_configured' as const, keyring_unavailable: false }
    ]) {
      await become(first_run)
      expect(section(v)?.props['data-kind']).toBe('invitation')
      expect(buttons(v)).toContain('Open Models and providers')
      expect(buttons(v)).not.toContain('Sign in with ChatGPT')
    }
  })
})

describe('Settings opened for a destination', () => {
  function element() {
    return { focus: vi.fn(), scrollIntoView: vi.fn() }
  }
  async function settingsView() {
    for (const name of ['General', 'Hosts', 'Mcp', 'Personality', 'Skills', 'Tools', 'Work', 'Advanced', 'DataPrivacy']) {
      vi.doMock(`../../src/renderer/src/views/settings/${name}.vue`, () => ({ default: { render: () => null } }))
    }
    vi.doMock('../../src/renderer/src/components/CodexAccounts.vue', () => ({ default: { render: () => null } }))
    const v = mount((await import('../../src/renderer/src/views/Settings.vue')).default)
    mounts.push(v)
    return v
  }
  afterEach(() => {
    for (const name of ['General', 'Hosts', 'Mcp', 'Personality', 'Skills', 'Tools', 'Work', 'Advanced', 'DataPrivacy']) vi.doUnmock(`../../src/renderer/src/views/settings/${name}.vue`)
    vi.doUnmock('../../src/renderer/src/components/CodexAccounts.vue')
  })

  it('waits for the destination to render, then scrolls to it and moves focus there, once', async () => {
    const providers = element()
    const found: Record<string, unknown> = {}
    const back = { focus: vi.fn() }
    Object.assign(document, { getElementById: vi.fn((id: string) => found[id] ?? null), querySelector: vi.fn(() => back) })
    store.openSettings('models', 'providers')
    await settingsView(); await flush()
    // Not rendered yet, and settings are still loading: keep the destination.
    expect(store.state.settingsTarget).toBe('providers')
    found['settings-target-providers'] = providers
    settingsStore.settings.meta = { ...(settingsStore.settings.meta ?? {}), revision: 'r2' } as never
    await flush()
    expect(providers.scrollIntoView).toHaveBeenCalledTimes(1)
    expect(providers.focus).toHaveBeenCalledTimes(1)
    expect(store.state.settingsTarget).toBe('')
    expect(back.focus).not.toHaveBeenCalled()
  })

  it('gives up on a destination when settings fail to load, leaving focus on Back', async () => {
    const back = { focus: vi.fn() }
    Object.assign(document, { getElementById: vi.fn(() => null), querySelector: vi.fn(() => back) })
    bridge.settingsSchema!.mockResolvedValue({ ok: false, error: { code: 'internal', message: 'Settings failed' } })
    store.openSettings('general', 'importer')
    await settingsView(); await flush(); await flush()
    expect(store.state.settingsTarget).toBe('')
    expect(back.focus).toHaveBeenCalledTimes(1)
  })
})
