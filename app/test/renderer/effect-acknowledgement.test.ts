import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TerminalOutcome } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

type Store = typeof import('../../src/renderer/src/store')
let store: Store
let mounted: Mounted | undefined
let acknowledge: ReturnType<typeof vi.fn>
const unknown = { ok: false, error: { code: 'no_receipt', message: 'No receipt', disposition: 'outcome_unknown' } } as const
const outcome = (request_id = 'r1', generation = 1, unknown_effects = 1): TerminalOutcome => ({
  request_id, generation, outcome: 'cancelled', at: '2026-10-08T22:00:00Z', unknown_effects
})
beforeEach(async () => {
  vi.resetModules()
  acknowledge = vi.fn()
  vi.stubGlobal('window', { odin: { acknowledgeEffects: acknowledge }, addEventListener: vi.fn() })
  store = await import('../../src/renderer/src/store')
  store.state.app.link = 'ready'
  store.state.activeId = 'c1'
  store.state.views.c1 = {
    status: 'ready', hasData: true, epoch: 0, loadEpoch: 0, watermark: 1, loadToken: 1,
    held: [], messages: [], hasMore: false, loadingOlder: false, running: null, queued: [], recent: [],
    unresolved: [outcome(), outcome('r2', 2, 3)], tools: {}, controls: {}
  }
})
afterEach(() => { mounted?.unmount(); mounted = undefined; vi.unstubAllGlobals() })

describe('unknown-outcome acknowledgement', () => {
  it('keeps the warning until an authoritative receipt, disables duplicate clicks and scopes removal exactly', async () => {
    let resolve!: (answer: unknown) => void
    acknowledge.mockImplementation(() => new Promise((r) => { resolve = r }))
    const task = store.acknowledgeEffects('c1', outcome())
    expect(store.effectAcknowledgement('c1', outcome())?.status).toBe('sending')
    expect(store.state.views.c1!.unresolved).toHaveLength(2)
    await store.acknowledgeEffects('c1', outcome())
    expect(acknowledge).toHaveBeenCalledTimes(1)
    expect(acknowledge.mock.calls[0]![0]).toMatchObject({ conversation_id: 'c1', request_id: 'r1', generation: 1 })
    resolve({ ok: true, result: { disposition: 'acknowledged', remaining: 0 } })
    await task
    expect(store.state.views.c1!.unresolved.map((o) => o.request_id)).toEqual(['r2'])
  })

  it('never resends uncertain acknowledgements and settles a matching late receipt without hiding another generation', async () => {
    acknowledge.mockResolvedValue(unknown)
    await store.acknowledgeEffects('c1', outcome())
    const command = store.effectAcknowledgement('c1', outcome())!
    expect(command.status).toBe('awaiting-receipt')
    await store.acknowledgeEffects('c1', outcome())
    expect(acknowledge).toHaveBeenCalledTimes(1)
    store.applyReceipt({ id: command.commandId, settled: unknown })
    expect(store.state.views.c1!.unresolved).toHaveLength(2)
    store.applyReceipt({ id: 'another-command', settled: { ok: true, result: { disposition: 'acknowledged', remaining: 0 } } })
    expect(store.state.views.c1!.unresolved).toHaveLength(2)
    store.applyReceipt({ id: command.commandId, settled: { ok: true, result: { disposition: 'already_acknowledged', remaining: 0 } } })
    expect(store.state.views.c1!.unresolved.map((o) => o.request_id)).toEqual(['r2'])
  })

  it('retains failures for retry, and a rejected IPC promise remains unknown rather than replayable', async () => {
    acknowledge.mockResolvedValueOnce({ ok: false, error: { code: 'bad_request', message: 'Refused', disposition: 'not_dispatched' } })
    await store.acknowledgeEffects('c1', outcome())
    expect(store.effectAcknowledgement('c1', outcome())).toMatchObject({ status: 'failed', error: 'Refused' })
    const first = store.effectAcknowledgement('c1', outcome())!.commandId
    acknowledge.mockRejectedValueOnce(new Error('IPC disconnected'))
    await store.acknowledgeEffects('c1', outcome())
    expect(store.effectAcknowledgement('c1', outcome())).toMatchObject({ status: 'unknown' })
    expect(store.effectAcknowledgement('c1', outcome())!.commandId).not.toBe(first)
    await store.acknowledgeEffects('c1', outcome())
    expect(acknowledge).toHaveBeenCalledTimes(2)
    expect(store.state.views.c1!.unresolved).toHaveLength(2)
  })

  it('does not remove warnings from a newer recovery using an older receipt', async () => {
    acknowledge.mockResolvedValue(unknown)
    await store.acknowledgeEffects('c1', outcome())
    const command = store.effectAcknowledgement('c1', outcome())!
    store.state.recoveryEpoch = 1
    store.state.views.c1!.epoch = 1
    store.applyReceipt({ id: command.commandId, settled: { ok: true, result: { disposition: 'acknowledged', remaining: 0 } } })
    expect(store.state.views.c1!.unresolved).toHaveLength(2)
  })

  it('refuses stale/offline/missing targets and keeps malformed successful receipts unknown', async () => {
    await store.acknowledgeEffects('c1', outcome('missing'))
    store.state.app.link = 'reconnecting'
    await store.acknowledgeEffects('c1', outcome())
    expect(acknowledge).not.toHaveBeenCalled()
    store.state.app.link = 'ready'
    acknowledge.mockResolvedValue({ ok: true, result: { disposition: 'acknowledged', remaining: -1 } })
    await store.acknowledgeEffects('c1', outcome())
    expect(store.effectAcknowledgement('c1', outcome())?.status).toBe('unknown')
    expect(store.state.views.c1!.unresolved).toHaveLength(2)
  })

  it('updates a nonzero authoritative remaining count without pretending dismissal succeeded', async () => {
    acknowledge.mockResolvedValue({ ok: true, result: { disposition: 'acknowledged', remaining: 2 } })
    await store.acknowledgeEffects('c1', outcome())
    expect(store.state.views.c1!.unresolved[0]!.unknown_effects).toBe(2)
  })

  it('refreshes a not-found target without switching the active conversation or claiming acknowledgement', async () => {
    const conversation = { id: 'c1', title: 'Chat', rev: 1, parent_id: null, updated_at: '2026-10-08T22:00:00Z', unread: 0, archived: false }
    const snapshot = vi.fn(async () => ({ ok: true, result: {
      conversation, watermark: '2', messages: { items: [], has_more: false }, running: null,
      queued: [], recent: [], unresolved: [outcome()], tools: {}, controls: []
    } }))
    ;(window.odin as unknown as Record<string, unknown>).snapshotConversation = snapshot
    store.state.activeId = 'other'
    acknowledge.mockResolvedValue({ ok: true, result: { disposition: 'not_found', remaining: 0 } })
    await store.acknowledgeEffects('c1', outcome())
    await flush()
    expect(snapshot).toHaveBeenCalledExactlyOnceWith({ conversation_id: 'c1' })
    expect(store.state.activeId).toBe('other')
    expect(store.state.views.c1!.unresolved).toHaveLength(1)
  })

  it('clears pending acknowledgement only for the matching effects.resolved event', async () => {
    acknowledge.mockResolvedValue(unknown)
    await store.acknowledgeEffects('c1', outcome())
    const event = (seq: number, request_id: string, generation: number, remaining: number) => ({
      seq, cursor: String(seq), type: 'effects.resolved', entity: { kind: 'request', id: request_id },
      at: '2026-10-08T22:00:00Z', payload: { conversation_id: 'c1', request_id, generation, remaining }
    })
    store.applyEvent(event(2, 'r1', 2, 0))
    expect(store.effectAcknowledgement('c1', outcome())).toBeDefined()
    expect(store.state.views.c1!.unresolved).toHaveLength(2)
    store.applyEvent(event(3, 'r1', 1, 0))
    expect(store.effectAcknowledgement('c1', outcome())).toBeUndefined()
    expect(store.state.views.c1!.unresolved.map((o) => o.request_id)).toEqual(['r2'])
  })

  it('uses plain singular/plural status-bar copy and updates the badge after acknowledgement', async () => {
    const StatusBar = (await import('../../src/renderer/src/components/StatusBar.vue')).default
    store.state.views.c1!.unresolved = [outcome()]
    mounted = mount(StatusBar)
    await flush()
    expect(mounted.root.textContent()).toContain('1 action with an unknown outcome')
    store.state.views.c1!.unresolved.push(outcome('r2', 2, 3))
    await flush()
    expect(mounted.root.textContent()).toContain('4 actions with unknown outcomes')
    acknowledge.mockResolvedValue({ ok: true, result: { disposition: 'acknowledged', remaining: 0 } })
    await store.acknowledgeEffects('c1', outcome())
    await store.acknowledgeEffects('c1', outcome('r2', 2))
    await flush()
    expect(mounted.root.textContent()).not.toContain('unknown outcome')
  })
})
