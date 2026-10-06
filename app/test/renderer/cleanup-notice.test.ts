// Real Vue component behavior on the plain-object renderer, not graphical focus qualification.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AppState, CleanupWarning, Result } from '../../src/shared/api'
import { flush, mount } from './component-host'

const warning = (id = 'notice-1'): CleanupWarning => ({ id, at: '2026-10-05T23:00:00Z', records: [
  { at: '2026-10-05T22:00:00Z', reason: 'Process containment unknown', processOutcome: 'unknown', shutdownAccepted: false, unsaved: true, unreceipted: 3 },
  { at: '2026-10-05T22:30:00Z', reason: '<script>Retained earlier uncertainty</script>', shutdownAccepted: true, unsaved: false, unreceipted: 0 }
] })
const app = (): AppState => ({ link: 'ready', coreInstanceId: 'core', noTray: false, unreceipted: 3, cleanupWarning: warning() })

async function fixture() {
  const store = await import('../../src/renderer/src/store')
  store.state.app = app()
  const acknowledge = vi.fn<(id: string) => Promise<Result<AppState>>>()
  vi.stubGlobal('window', { odin: { acknowledgeCleanup: acknowledge } })
  const Component = (await import('../../src/renderer/src/components/CleanupNotice.vue')).default
  const mounted = mount(Component)
  return { ...mounted, state: store.state, acknowledge }
}

describe('persistent nonmodal cleanup notice', () => {
  beforeEach(() => { vi.resetModules(); vi.unstubAllGlobals() })

  it('renders every reason and timestamp, truthful details, and exactly one acknowledgment action', async () => {
    const { root, unmount } = await fixture()
    expect(root.findAll((node) => node.tag === 'li')).toHaveLength(2)
    for (const record of warning().records) {
      expect(root.textContent()).toContain(record.reason)
      expect(root.textContent()).toContain(record.at)
    }
    expect(root.findAll((node) => node.tag === 'time').map((node) => node.props.datetime)).toEqual([
      warning().at, ...warning().records.map((record) => record.at)
    ])
    expect(root.textContent()).toContain('Shutdown accepted: no')
    expect(root.textContent()).toContain('Unsaved state: no')
    expect(root.textContent()).toContain('Awaiting receipt: 0')
    expect(root.textContent()).toContain('No effects are labelled undone. No work is replayed. Acknowledgment only archives this notice; resource quarantine and reconciliation remain unchanged.')
    expect(root.findAll((node) => node.tag === 'button')).toHaveLength(1)
    expect(root.button('Acknowledge').props.autofocus).toBeUndefined()
    expect(root.findAll((node) => node.tag === 'dialog' || node.props.role === 'dialog' || Boolean(node.props['aria-modal']))).toHaveLength(0)
    expect(root.find('script')).toBeUndefined()
    expect(root.find('section')?.props['aria-labelledby']).toBe(root.find('h2')?.props.id)
    unmount()
  })

  it('changes only app state, and only after successful acknowledgment of the current token', async () => {
    const { root, state, acknowledge, unmount } = await fixture()
    let finish!: (result: Result<AppState>) => void
    acknowledge.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    const original = state.app
    const conversations = state.conversations
    root.button('Acknowledge').fire('click')
    await flush()
    expect(state.app).toBe(original)
    expect(root.button('Acknowledge').props.disabled).toBe(true)
    root.button('Acknowledge').fire('click')
    expect(acknowledge).toHaveBeenCalledExactlyOnceWith('notice-1')
    const result = { ...app(), cleanupWarning: null }
    finish({ ok: true, result })
    await flush()
    expect(state.app).toEqual(result)
    expect(state.conversations).toBe(conversations)
    expect(root.find('section')).toBeUndefined()
    unmount()
  })

  it('keeps the warning and app state on a stale-token rejection and displays its error', async () => {
    const { root, state, acknowledge, unmount } = await fixture()
    const original = state.app
    acknowledge.mockResolvedValue({ ok: false, error: { code: 'conflict', message: 'This cleanup notice has changed.' } })
    root.button('Acknowledge').fire('click')
    await flush()
    expect(state.app).toBe(original)
    expect(root.findAll((node) => node.props.role === 'status').map((node) => node.textContent())).toEqual(['This cleanup notice has changed.'])
    expect(root.button('Acknowledge').props.disabled).toBe(false)
    unmount()
  })

  it('leaves uncertainty visible if the bridge fails', async () => {
    const { root, state, acknowledge, unmount } = await fixture()
    const original = state.app
    acknowledge.mockRejectedValue(new Error('transport failure'))
    root.button('Acknowledge').fire('click')
    await flush()
    expect(state.app).toBe(original)
    expect(root.textContent()).toContain('Could not acknowledge cleanup. The notice remains unchanged.')
    unmount()
  })

  it('never erases a newer pushed warning with an older successful response', async () => {
    const { root, state, acknowledge, unmount } = await fixture()
    let finish!: (result: Result<AppState>) => void
    acknowledge.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    root.button('Acknowledge').fire('click')
    state.app = { ...app(), cleanupWarning: warning('notice-2') }
    finish({ ok: true, result: { ...app(), cleanupWarning: null } })
    await flush()
    expect(state.app.cleanupWarning?.id).toBe('notice-2')
    expect(root.find('section')).toBeTruthy()
    unmount()
  })

  it('remains present when navigating chat and settings, but not with a null or absent warning', async () => {
    const { root, state, unmount } = await fixture()
    state.view = 'settings'
    await flush()
    expect(root.textContent()).toContain('Process containment unknown')
    state.view = 'chat'
    await flush()
    expect(root.find('section')).toBeTruthy()
    state.app.cleanupWarning = null
    await flush()
    expect(root.find('section')).toBeUndefined()
    delete state.app.cleanupWarning
    await flush()
    expect(root.find('section')).toBeUndefined()
    unmount()
  })
})
