// Actual stores and compiled views, using the real 6A response envelopes. No native/backend qualification claim.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Mounted } from './component-host'

const ok = (result: unknown) => ({ ok: true, result })
const refused = { ok: false, error: { code: 'capability_unavailable', message: 'Action unavailable', disposition: 'not_dispatched' } }
const readiness = { management_available: true, foreground_available: false, native_qualified: false, input_supported: false, dispatch: 'none', reason: 'foreground_binding_and_native_qualification_pending' }
const session = { session_id: 'real-session', generation: 7, state: 'quarantined', platform: 'x11', environment: 'isolated', app: 'drawing', input_supported: false, input_readiness: 'foreground_unavailable', recovery: { status: 'unknown', reason: 'owned_input_release_unproven', complete: false, unknown_release: true, receiver_release_verified: false } }
const health = (browser: unknown) => ({ overall: 'healthy', components: [], total: 0, healthy_count: 0, degraded_count: 0, down_count: 0, unconfigured_count: 0, checked_at: '', browser })
let bridge: Record<string, ReturnType<typeof vi.fn>>
let views: Mounted[]

beforeEach(() => {
  vi.resetModules()
  views = []
  bridge = Object.fromEntries(['auditQuery', 'auditVerify', 'usage', 'logsSearch', 'turnStateList', 'toolsList', 'toolsTimeoutsGet'].map((name) => [name, vi.fn(async () => refused)]))
  bridge.healthGet = vi.fn(async () => ok(health({ state: 'unavailable', ready: false, reason: 'Qualification failed', retry_available: true })))
  bridge.computerStatus = vi.fn(async () => ok({ session, readiness }))
  bridge.computerReconcile = vi.fn(async () => ok({ session, readiness }))
  vi.stubGlobal('window', { odin: bridge })
  vi.stubGlobal('document', { activeElement: null })
})
afterEach(() => {
  views.forEach((view) => view.unmount())
  vi.unstubAllGlobals()
})
async function view(name: 'Tools' | 'Records') {
  const mounted = mount((await import(`../../src/renderer/src/views/settings/${name}.vue`)).default)
  views.push(mounted)
  await flush()
  return mounted
}

describe('real browser health, not catalog availability', () => {
  it('shows failed qualification with next-use retry, and refresh only reads health', async () => {
    bridge.toolsList!.mockImplementation(async () => ok({ tools: [{ name: 'browser_read_page', description: 'Read', state: 'available', enabled: true, input_schema: {} }], disabled_count: 0 }))
    const v = await view('Tools')
    const panel = v.root.findAll((n) => n.props['aria-label'] === 'Browser runtime')[0]!
    expect(panel.textContent()).toContain('State: unavailable. Not ready.')
    expect(panel.textContent()).toContain('Reason: Qualification failed')
    expect(panel.textContent()).toContain('next browser tool use')
    expect(panel.textContent()).toContain('not browser readiness')
    expect(panel.findAll((n) => n.tag === 'button')).toHaveLength(1)
    panel.button('Refresh status').fire('click')
    await flush()
    expect(bridge.healthGet).toHaveBeenCalledTimes(2)
    expect(bridge.healthGet).toHaveBeenLastCalledWith({})
  })

  it.each([false, undefined])('does not invent retry when retry_available is %s', async (retry_available) => {
    bridge.healthGet!.mockImplementation(async () => ok(health({ state: 'disabled', ready: false, reason: null, retry_available })))
    const v = await view('Tools')
    expect(v.root.textContent()).toContain('No next-use retry is reported')
    expect(v.root.textContent()).not.toContain('can retry qualification')
  })

  it('reports ready only from health and does not call a next-use retry a launch', async () => {
    bridge.healthGet!.mockImplementation(async () => ok(health({ state: 'ready', ready: true, reason: null, retry_available: true })))
    const v = await view('Tools')
    expect(v.root.textContent()).toContain('Core reports ready.')
    expect(v.root.textContent()).not.toContain('can retry qualification')
  })

  it('plainly labels missing browser health instead of using fixture or catalog readiness', async () => {
    bridge.healthGet!.mockImplementation(async () => ok(health(undefined)))
    const v = await view('Tools')
    expect(v.root.textContent()).toContain('does not report browser runtime status')
    expect(v.root.textContent()).not.toContain('Core reports ready')
  })

  it('keeps a marked last read on failure and ignores older reads', async () => {
    const store = await import('../../src/renderer/src/stores/browser')
    await store.loadBrowserStatus()
    bridge.healthGet!.mockImplementation(async () => refused)
    const v = await view('Tools')
    expect(v.root.textContent()).toContain('Showing the last read.')
    const held: Array<(result: unknown) => void> = []
    bridge.healthGet!.mockImplementation(() => new Promise((resolve) => held.push(resolve)))
    const old = store.loadBrowserStatus()
    const newest = store.loadBrowserStatus()
    held[1]!(ok(health({ state: 'ready', ready: true, reason: null, retry_available: true })))
    await newest
    held[0]!(ok(health({ state: 'unavailable', ready: false, reason: 'old', retry_available: true })))
    await old
    expect(store.browser.status?.state).toBe('ready')
  })
})

describe('real computer management, never foreground admission', () => {
  it('renders actual nested session identity/readiness without flat enabled assumptions', async () => {
    const v = await view('Records')
    expect(v.root.textContent()).toContain('real-session')
    expect(v.root.textContent()).toContain('generation 7')
    expect(v.root.textContent()).toContain('Management: available')
    expect(v.root.textContent()).toContain('Foreground computer use is unavailable')
    expect(v.root.textContent()).toContain('Native input is not qualified or supported')
    expect(v.root.textContent()).toContain('Dispatch: none')
    expect(v.root.textContent()).toContain('Input release remains unverified')
    expect(v.root.textContent()).not.toContain('Off:')
    expect(v.root.findAll((n) => n.tag === 'button' && n.textContent() === 'Release…')).toHaveLength(0)
  })

  it('calls real reconcile directly with exact session generation and no acknowledgment or new prompt', async () => {
    const v = await view('Records')
    v.root.button('Reconcile').fire('click')
    await flush()
    expect(bridge.computerReconcile).toHaveBeenCalledExactlyOnceWith({ session_id: 'real-session', generation: 7 })
    const { dialog } = await import('../../src/renderer/src/dialog')
    expect(dialog.current).toBeNull()
    expect(v.root.textContent()).toContain('Input release and cleanup remain unverified')
    expect(v.root.textContent()).not.toContain('Released:')
  })

  it('shows no-session readiness without inventing a release verdict or enabled state', async () => {
    bridge.computerStatus!.mockImplementation(async () => ok({ session: null, readiness }))
    const v = await view('Records')
    expect(v.root.textContent()).toContain('No computer-use session is reported')
    expect(v.root.textContent()).toContain('not proof of input release or cleanup')
    expect(v.root.findAll((n) => n.tag === 'button' && n.textContent() === 'Reconcile')).toHaveLength(0)
    const store = await import('../../src/renderer/src/stores/records')
    expect(await store.reconcileComputer(store.records.computer!)).toBe(false)
    expect(bridge.computerReconcile).not.toHaveBeenCalled()
  })

  it('retains valid status/readiness when only the action is refused', async () => {
    bridge.computerReconcile!.mockImplementation(async () => refused)
    const v = await view('Records')
    v.root.button('Reconcile').fire('click')
    await flush()
    const store = await import('../../src/renderer/src/stores/records')
    expect(store.records.computer).toEqual({ session, readiness })
    expect(store.records.unavailable.computer).toBe(false)
    expect(bridge.computerStatus).toHaveBeenCalledTimes(1)
    expect(v.root.textContent()).toContain('Action unavailable')
    expect(v.root.textContent()).toContain('real-session')
    expect(v.root.textContent()).toContain('Dispatch: none')
  })

  it('does not dispatch reconciliation when management is unavailable', async () => {
    bridge.computerStatus!.mockImplementation(async () => ok({ session, readiness: { ...readiness, management_available: false, reason: 'computer_storage_unavailable' } }))
    const v = await view('Records')
    expect(v.root.button('Reconcile').props.disabled).toBe(true)
    const store = await import('../../src/renderer/src/stores/records')
    expect(await store.reconcileComputer(store.records.computer!)).toBe(false)
    expect(bridge.computerReconcile).not.toHaveBeenCalled()
  })

  it('closed or complete recovery with unknown release never becomes a clean outcome', async () => {
    bridge.computerReconcile!.mockImplementation(async () => ok({ readiness, session: { ...session, state: 'closed', recovery: { ...session.recovery, status: 'absence_verified', complete: true } } }))
    const v = await view('Records')
    v.root.button('Reconcile').fire('click')
    await flush()
    expect(v.root.textContent()).toContain('Input release remains unverified')
    expect(v.root.textContent()).toContain('Input release and cleanup remain unverified')
    expect(v.root.textContent()).not.toContain('Reconciled: Odin verified')
  })

  it('a verified absence outcome is not input qualification and missing recovery proves nothing', async () => {
    const store = await import('../../src/renderer/src/stores/records')
    expect(store.reconcileOutcome({ readiness, session: { ...session, state: 'closed', recovery: { status: 'absence_verified', reason: 'runtime_absent', complete: true } } } as never)).toContain('does not qualify foreground or native input')
    expect(store.reconcileOutcome({ readiness, session: { ...session, recovery: undefined } } as never)).toContain('recorded no recovery')
  })

  it('preserves uncertainty from actual cleanup receipts even when recovery records absence verified', async () => {
    const result = { readiness, session: { ...session, state: 'closed', cleanup: { unknown_release: true, receiver_release_verified: false }, recovery: { status: 'absence_verified', reason: 'runtime_absent', complete: true } } }
    bridge.computerStatus!.mockImplementation(async () => ok(result))
    const v = await view('Records')
    expect(v.root.textContent()).toContain('Input release remains unverified')
    const store = await import('../../src/renderer/src/stores/records')
    expect(store.reconcileOutcome(result as never)).toContain('Input release and cleanup remain unverified')
    expect(store.reconcileOutcome(result as never)).not.toContain('Reconciled: Odin verified')
  })

  it('keeps a real unknown command bound and accepts its late result without replay or cleanup claim', async () => {
    bridge.computerReconcile!.mockImplementation(async () => ({ ok: false, error: { code: 'outcome_unknown', message: 'Waiting', disposition: 'outcome_unknown', command_id: 'real-reconcile-1' } }))
    const v = await view('Records')
    v.root.button('Reconcile').fire('click')
    await flush()
    const store = await import('../../src/renderer/src/stores/records')
    expect(await store.reconcileComputer(store.records.computer!)).toBe(false)
    expect(bridge.computerReconcile).toHaveBeenCalledTimes(1)
    expect(v.root.button('Reconcile').props.disabled).toBe(true)
    const mainStore = await import('../../src/renderer/src/store')
    mainStore.applyReceipt({ id: 'real-reconcile-1', settled: ok({ readiness, session: { ...session, state: 'closed' } }) } as never)
    await flush()
    const { management } = await import('../../src/renderer/src/stores/management')
    expect(management.busy['computer:real-session']).toBe(false)
    expect(v.root.textContent()).toContain('Input release and cleanup remain unverified')
    expect(bridge.computerReconcile).toHaveBeenCalledTimes(1)
  })

  it('an older status read cannot overwrite a received reconciliation outcome', async () => {
    const store = await import('../../src/renderer/src/stores/records')
    await store.loadComputer()
    let release!: (answer: unknown) => void
    bridge.computerStatus!.mockImplementation(() => new Promise((resolve) => { release = resolve }))
    const old = store.loadComputer()
    const reconciled = { readiness, session: { ...session, state: 'closed' } }
    bridge.computerReconcile!.mockImplementation(async () => ok(reconciled))
    await store.reconcileComputer(store.records.computer!)
    release(ok({ session, readiness }))
    await old
    expect(store.records.computer).toEqual(reconciled)
  })
})
