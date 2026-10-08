// Source-only component-host tests. Every bridge answer is local; no renderer/browser or network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result } from '../../src/shared/api'
import { flush, Host, mount, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const refused = (): Result<never> => ({ ok: false, error: { code: 'capability_unavailable', message: 'Not implemented in this core.' } })
const unknown = (id: string): Result<never> => ({ ok: false, error: {
  code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: id
} })
function deferred<T>() {
  let resolve!: (result: T) => void
  return { promise: new Promise<T>((done) => { resolve = done }), resolve: (result: T) => resolve(result) }
}
const catalogue = () => ({
  recognized: true, fetched_at: '2026-10-05T00:00:00Z', stale: true, refresh_error: 'Offline; cached catalogue',
  models: [{ id: 'author/model', name: 'Model', profile: { context: 12345 }, source: 'catalogue', conflict: null,
    endpoints: [], agent_eligible: false, reason: 'Not eligible for agent use' }],
  quick_add: ['compat:author/model'], routing: { provider: 'automatic' }, measured_cache: null
})
let mounted: Mounted | undefined
let descriptor: PropertyDescriptor | undefined
let bridge: Record<string, ReturnType<typeof vi.fn>>
beforeEach(() => {
  vi.resetModules()
  bridge = {
    openrouterCatalogue: vi.fn(async () => ok(catalogue())),
    openrouterEndpoints: vi.fn(async ({ model }) => ok({ model, endpoints: [{ provider_name: 'Provider' }], effective_profile: { source: 'endpoint' } })),
    openrouterSelect: vi.fn(async ({ model, provider_tag }) => ok({ model, provider_tag: provider_tag || null, profile: {}, effective_profile: {} })),
    providersCompatDiagnostic: vi.fn(async () => ok({ configured: true, provider: 'compat', model: 'author/model', health: { healthy: false, error: 'offline' }, stats: {} })),
    codexAccounts: vi.fn(async () => ok({ configured: true, accounts: [{ index: 0, account_id: 'acct', email: 'person@example.com', is_current: true, expired: true }] })),
    codexRefresh: vi.fn(async () => ok({ status: 'refreshed', email: 'person@example.com', expired: false }))
    ,settingsSchema: vi.fn(async () => ok({ revision: 'rev-router', fields: [], status: { counts: {}, desired_revision: 'rev-router', effective_revision: null } }))
  }
  vi.stubGlobal('window', { odin: bridge })
  vi.stubGlobal('document', { activeElement: null })
  vi.stubGlobal('Document', class Document {})
  vi.stubGlobal('ShadowRoot', class ShadowRoot {})
  descriptor = Object.getOwnPropertyDescriptor(Host.prototype, 'getRootNode')
  Object.defineProperty(Host.prototype, 'getRootNode', { configurable: true, value: () => document })
})
afterEach(() => {
  mounted?.unmount()
  mounted = undefined
  if (descriptor) Object.defineProperty(Host.prototype, 'getRootNode', descriptor)
  vi.unstubAllGlobals()
})
async function router() {
  await (await import('../../src/renderer/src/stores/settings')).loadSettings()
  mounted = mount((await import('../../src/renderer/src/components/OpenRouterAdmin.vue')).default)
  await flush()
  return mounted.root
}
async function codex() {
  const { settings } = await import('../../src/renderer/src/stores/settings')
  settings.meta = { revision: 'rev-router', schema_version: 1, fields: [{ path: 'openai_compatible.enabled', type: 'boolean', desired: false, enum: null, constraints: {}, sensitivity: 'public', apply_handler: 'providers.compat.set', apply_state: 'dormant' } as any], status: { counts: {}, desired_revision: 'rev-router', effective_revision: null } }
  mounted = mount((await import('../../src/renderer/src/components/CodexAccounts.vue')).default)
  await flush()
  mounted.root.named('Configure OpenAI-compatible').fire('click')
  await flush()
  return mounted.root
}
const field = (root: Host, id: string) => root.findAll((host) => host.props.id === id)[0]!
async function receipt(id: string, answer: Result<unknown>) {
  ;(await import('../../src/renderer/src/store')).applyReceipt({ id, settled: answer })
  await flush()
}

describe('OpenRouter honest minimum', () => {
  it('renders core catalogue, eligibility, routing and cache without invented measurements', async () => {
    const root = await router()
    expect(bridge.openrouterCatalogue).toHaveBeenCalledWith({})
    expect(root.textContent()).toContain('Offline; cached catalogue')
    expect(root.textContent()).toContain('Not eligible for agent use')
    expect(root.textContent()).toContain('compat:author/model')
    expect(root.textContent()).toContain('"context": 12345')
    expect(root.textContent()).not.toContain('cache hit rate')
    expect(bridge.openrouterSelect).not.toHaveBeenCalled()
  })

  it('reads endpoints and preserves an unhealthy diagnostic as data', async () => {
    const root = await router()
    field(root, 'openrouter-model').type('author/model')
    await flush()
    root.button('Read endpoints').fire('click')
    root.button('Read compatibility diagnostic').fire('click')
    await flush()
    expect(bridge.openrouterEndpoints).toHaveBeenCalledWith({ model: 'author/model' })
    expect(bridge.providersCompatDiagnostic).toHaveBeenCalledWith({})
    expect(root.textContent()).toContain('"source": "endpoint"')
    expect(root.textContent()).toContain('"healthy": false')
    expect(root.textContent()).toContain('"error": "offline"')
    expect(bridge.openrouterSelect).not.toHaveBeenCalled()
  })

  it('invalidates old endpoint reads when the model field changes', async () => {
    const result = deferred<Result<unknown>>()
    bridge.openrouterEndpoints!.mockImplementation(() => result.promise)
    const root = await router()
    field(root, 'openrouter-model').type('author/model')
    await flush()
    root.button('Read endpoints').fire('click')
    await flush()
    field(root, 'openrouter-model').type('author/other')
    await flush()
    result.resolve(ok({ model: 'author/model', endpoints: ['OLD-ENDPOINT'] }))
    await flush()
    expect(root.textContent()).not.toContain('OLD-ENDPOINT')
  })

  it('locks selection on an unknown outcome and accepts its late receipt without sending twice', async () => {
    bridge.openrouterSelect!.mockResolvedValue(unknown('select-1'))
    const root = await router()
    field(root, 'openrouter-model').type(' author/model ')
    field(root, 'openrouter-provider').type(' provider-pin ')
    await flush()
    root.find('form')!.fire('submit', { preventDefault: () => undefined })
    await flush()
    expect(bridge.openrouterSelect).toHaveBeenCalledWith({ model: 'author/model', provider_tag: 'provider-pin', expected_revision: 'rev-router' })
    expect(root.button('Save routing').props.disabled).toBe(true)
    root.find('form')!.fire('submit', { preventDefault: () => undefined })
    await flush()
    expect(bridge.openrouterSelect).toHaveBeenCalledTimes(1)
    expect(root.textContent()).toContain("It's never sent twice")
    await receipt('select-1', ok({ model: 'author/model', provider_tag: 'provider-pin', profile: {}, effective_profile: {} }))
    expect(root.textContent()).toContain('Saved routing for author/model; provider provider-pin.')
    expect(root.button('Save routing').props.disabled).toBe(false)
    expect(bridge.openrouterCatalogue).toHaveBeenCalledTimes(2)
  })

  it('blank pin explicitly requests automatic routing and invalid IDs do not dispatch', async () => {
    const root = await router()
    field(root, 'openrouter-model').type('not-a-model-id')
    await flush()
    root.find('form')!.fire('submit', { preventDefault: () => undefined })
    expect(bridge.openrouterSelect).not.toHaveBeenCalled()
    field(root, 'openrouter-model').type('author/model')
    await flush()
    root.find('form')!.fire('submit', { preventDefault: () => undefined })
    await flush()
    expect(bridge.openrouterSelect).toHaveBeenCalledWith({ model: 'author/model', provider_tag: '', expected_revision: 'rev-router' })
    expect(root.textContent()).toContain('provider automatic.')
  })

  it('clears a previously shown catalogue on refusal and preserves non-capability failures verbatim', async () => {
    const root = await router()
    expect(root.textContent()).toContain('compat:author/model')
    bridge.openrouterCatalogue!.mockResolvedValue(refused())
    root.button('Reload catalogue').fire('click')
    await flush()
    expect(root.textContent()).not.toContain('compat:author/model')
    expect(root.textContent()).toContain('OpenRouter catalogue is unavailable.')
    bridge.providersCompatDiagnostic!.mockResolvedValue({ ok: false, error: { code: 'offline', message: 'Compatibility provider timed out' } })
    root.button('Read compatibility diagnostic').fire('click')
    await flush()
    expect(root.textContent()).toContain('Compatibility provider timed out')
    expect(root.textContent()).not.toContain('Compatibility provider diagnostic is unavailable')
  })

  it('makes a late selection refusal explicit and does not permit retries of an unavailable command', async () => {
    bridge.openrouterSelect!.mockResolvedValue(unknown('refused-select'))
    const root = await router()
    field(root, 'openrouter-model').type('author/model')
    await flush()
    root.find('form')!.fire('submit', { preventDefault: () => undefined })
    await flush()
    await receipt('refused-select', refused())
    expect(root.textContent()).toContain('OpenRouter selection is unavailable.')
    expect(root.button('Save routing').props.disabled).toBe(true)
    expect(bridge.openrouterSelect).toHaveBeenCalledTimes(1)
  })

  it('capability refusals clear catalogue data without concealing existing Codex accounts', async () => {
    bridge.openrouterCatalogue!.mockResolvedValue(refused())
    bridge.codexRefresh!.mockResolvedValue(refused())
    const root = await codex()
    expect(root.textContent()).toContain('OpenRouter catalogue is unavailable.')
    expect(root.textContent()).toContain('person@example.com')
    root.button('Refresh sign-in').fire('click')
    await flush()
    expect(root.textContent()).toContain('Codex sign-in refresh is unavailable.')
    expect(root.textContent()).toContain('person@example.com')
    expect(root.button('Rename').props.disabled).toBe(false)
    expect(root.button('Refresh sign-in').props.disabled).toBe(true)
  })

  it('old bridge methods missing are explicit and leave the Codex panel intact', async () => {
    delete bridge.openrouterCatalogue
    delete bridge.codexRefresh
    const root = await codex()
    root.button('Refresh sign-in').fire('click')
    await flush()
    expect(root.textContent()).toContain('OpenRouter catalogue is unavailable.')
    expect(root.textContent()).toContain('Codex sign-in refresh is unavailable.')
    expect(root.textContent()).toContain('person@example.com')
  })
})

describe('Codex per-account refresh', () => {
  it('sends an integer index and rereads accounts after the confirmed refresh', async () => {
    const root = await codex()
    root.button('Refresh sign-in').fire('click')
    await flush()
    expect(bridge.codexRefresh).toHaveBeenCalledWith({ index: 0 })
    expect(bridge.codexAccounts).toHaveBeenCalledTimes(2)
    expect(root.textContent()).toContain('Sign-in refreshed for person@example.com.')
    expect(root.button('Refresh sign-in').props.disabled).toBe(false)
  })

  it('holds all index-sensitive account controls until the late refresh receipt and reread', async () => {
    bridge.codexRefresh!.mockResolvedValue(unknown('refresh-1'))
    const root = await codex()
    root.button('Refresh sign-in').fire('click')
    await flush()
    expect(root.button('Remove…').props.disabled).toBe(true)
    expect(root.button('Add account').props.disabled).toBe(true)
    expect(bridge.codexAccounts).toHaveBeenCalledTimes(1)
    root.button('Refresh sign-in').fire('click')
    await flush()
    expect(bridge.codexRefresh).toHaveBeenCalledTimes(1)
    await receipt('refresh-1', ok({ status: 'refreshed', email: 'person@example.com', expired: false }))
    expect(bridge.codexAccounts).toHaveBeenCalledTimes(2)
    expect(root.button('Remove…').props.disabled).toBe(false)
    expect(root.textContent()).toContain('Sign-in refreshed for person@example.com.')
  })

  it('keeps account indices locked when the post-command accounts read fails', async () => {
    const root = await codex()
    bridge.codexAccounts!.mockResolvedValue({ ok: false, error: { code: 'offline', message: 'Read unavailable' } })
    root.button('Refresh sign-in').fire('click')
    await flush()
    expect(root.button('Remove…').props.disabled).toBe(true)
    expect(root.textContent()).toContain("couldn't be refreshed")
    expect(root.textContent()).toContain('Sign-in refreshed for person@example.com.')
  })

  it('a late refresh refusal does not disable the existing accounts capability', async () => {
    bridge.codexRefresh!.mockResolvedValue(unknown('refused-refresh'))
    const root = await codex()
    root.button('Refresh sign-in').fire('click')
    await flush()
    await receipt('refused-refresh', refused())
    expect(root.textContent()).toContain('Codex sign-in refresh is unavailable.')
    expect(root.textContent()).toContain('person@example.com')
    expect(root.button('Rename').props.disabled).toBe(false)
    expect(root.button('Refresh sign-in').props.disabled).toBe(true)
  })
})
