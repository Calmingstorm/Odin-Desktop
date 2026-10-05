// The window's state store, driven through a fake bridge: snapshots, held events, control targets and receipts.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  AppState,
  Conversation,
  ConversationListItem,
  ConversationSnapshot,
  CoreEvent,
  LateReceipt,
  Message,
  Result
} from '../../src/shared/api'

type Store = typeof import('../../src/renderer/src/store')

const CONVERSATION: Conversation = {
  id: 'c1',
  title: 'Chat',
  rev: 1,
  parent_id: null,
  updated_at: '2026-10-04T00:00:00Z',
  unread: 0,
  archived: false
}

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

const UNKNOWN = { ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown' } } as const

function message(id: string, role: Message['role'] = 'assistant'): Message {
  return { id, role, text: id, created_at: '2026-10-04T00:00:00Z' }
}

function snapshot(fields: Partial<ConversationSnapshot> & { watermark: string }): Result<ConversationSnapshot> {
  return {
    ok: true,
    result: {
      conversation: CONVERSATION,
      messages: { items: [], has_more: false },
      running: null,
      queued: [],
      recent: [],
      unresolved: [],
      tools: {},
      controls: [],
      ...fields
    }
  }
}

function event(seq: number, type: string, payload: Record<string, unknown>): CoreEvent {
  return {
    seq,
    cursor: String(seq),
    type,
    entity: { kind: 'test', id: String(seq) },
    at: '2026-10-04T00:00:00Z',
    payload: { conversation_id: 'c1', ...payload }
  }
}

function fakeBridge() {
  const listeners = {
    event: [] as Array<(e: CoreEvent) => void>,
    appState: [] as Array<(s: AppState) => void>,
    receipt: [] as Array<(r: LateReceipt) => void>,
    reset: [] as Array<(r: { event_high: string }) => void>
  }
  const calls = {
    submit: [] as Array<Record<string, unknown>>,
    snapshot: [] as unknown[],
    listMessages: [] as Array<Record<string, unknown>>,
    steer: [] as Array<Record<string, unknown>>,
    stop: [] as Array<Record<string, unknown>>
  }
  const control = {
    list: [{ ...CONVERSATION, activity: { running: null, queued: [] } }] as ConversationListItem[],
    listWatermark: '0',
    /** When set, list answers wait here until the test releases them. */
    holdLists: false,
    lists: [] as Array<Deferred<Result<{ items: ConversationListItem[]; watermark: string }>>>,
    snapshots: [] as Array<Deferred<Result<ConversationSnapshot>>>,
    steerResult: { ok: true, result: { disposition: 'queued' } } as Result<{ disposition: string }>,
    stopResult: { ok: true, result: { disposition: 'requested' } } as Result<{ disposition: string }>,
    olderResult: { ok: true, result: { items: [] as Message[], has_more: false, watermark: '0' } } as Result<{
      items: Message[]
      has_more: boolean
      watermark: string
    }>
  }
  const api = {
    status: async () => ({ ok: true, result: { phase: 'ready', core_instance_id: 'core-1', version: 'test', capabilities: [] } }),
    getAppState: async (): Promise<AppState> => ({ link: 'ready', coreInstanceId: 'core-1', noTray: false, unreceipted: 0 }),
    getSettings: async () => ({ ok: true, result: { autostart: false } }),
    setAutostart: async (enabled: boolean) => ({ ok: true, result: { autostart: enabled } }),
    listConversations: () => {
      const answer: Result<{ items: ConversationListItem[]; watermark: string }> = {
        ok: true,
        result: { items: control.list, watermark: control.listWatermark }
      }
      if (!control.holdLists) return Promise.resolve(answer)
      const next = deferred<Result<{ items: ConversationListItem[]; watermark: string }>>()
      control.lists.push(next)
      return next.promise
    },
    createConversation: async () => ({ ok: true, result: { conversation: CONVERSATION } }),
    snapshotConversation: (params: unknown) => {
      calls.snapshot.push(params)
      const next = deferred<Result<ConversationSnapshot>>()
      control.snapshots.push(next)
      return next.promise
    },
    listMessages: async (params: Record<string, unknown>) => {
      calls.listMessages.push(params)
      return control.olderResult
    },
    submit: async (params: Record<string, unknown>) => {
      calls.submit.push(params)
      return { ok: true, result: { disposition: 'accepted' } }
    },
    steer: async (params: Record<string, unknown>) => {
      calls.steer.push(params)
      return control.steerResult
    },
    stop: async (params: Record<string, unknown>) => {
      calls.stop.push(params)
      return control.stopResult
    },
    onEvent: (l: (e: CoreEvent) => void) => (listeners.event.push(l), () => undefined),
    onAppState: (l: (s: AppState) => void) => (listeners.appState.push(l), () => undefined),
    onReceipt: (l: (r: LateReceipt) => void) => (listeners.receipt.push(l), () => undefined),
    onReset: (l: (r: { event_high: string }) => void) => (listeners.reset.push(l), () => undefined)
  }
  return { api, listeners, calls, control }
}

let store: Store
let bridge: ReturnType<typeof fakeBridge>

async function until(check: () => boolean): Promise<void> {
  for (let i = 0; i < 500; i++) {
    if (check()) return
    await new Promise((r) => setTimeout(r, 2))
  }
  throw new Error('timed out waiting for condition')
}

const emit = (e: CoreEvent): void => bridge.listeners.event.forEach((l) => l(e))
const receipt = (r: LateReceipt): void => bridge.listeners.receipt.forEach((l) => l(r))

/** Starts the store and answers its first snapshot with `first`. */
async function start(first: Result<ConversationSnapshot> = snapshot({ watermark: '1' })): Promise<void> {
  const done = store.init()
  await until(() => bridge.control.snapshots.length === 1)
  bridge.control.snapshots[0]!.resolve(first)
  await done
}

beforeEach(async () => {
  vi.resetModules()
  bridge = fakeBridge()
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge.api }
  store = await import('../../src/renderer/src/store')
})

describe('snapshots and held events', () => {
  it('never lets an older snapshot erase a newer committed message', async () => {
    const done = store.init()
    await until(() => bridge.control.snapshots.length === 1)
    emit(event(5, 'message.committed', { message: message('m-new') }))
    bridge.control.snapshots[0]!.resolve(snapshot({ watermark: '4' }))
    await done
    expect(store.state.views.c1!.messages.map((m) => m.id)).toEqual(['m-new'])
  })

  it('drops held events the snapshot already covers', async () => {
    const done = store.init()
    await until(() => bridge.control.snapshots.length === 1)
    emit(event(5, 'message.committed', { message: message('m-new') }))
    bridge.control.snapshots[0]!.resolve(snapshot({ watermark: '5', messages: { items: [message('m-new')], has_more: false } }))
    await done
    expect(store.state.views.c1!.messages.map((m) => m.id)).toEqual(['m-new'])
  })

  it('on reset, drops the old projection and the answer to the superseded snapshot request', async () => {
    const done = store.init()
    await until(() => bridge.control.snapshots.length === 1)
    bridge.listeners.reset.forEach((l) => l({ event_high: '9' }))
    bridge.control.snapshots[0]!.resolve(snapshot({ watermark: '3', messages: { items: [message('m-stale')], has_more: false } }))
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '9', messages: { items: [message('m-fresh')], has_more: false } }))
    await done
    await until(() => store.state.views.c1?.hasData === true)
    expect(store.state.views.c1!.messages.map((m) => m.id)).toEqual(['m-fresh'])
  })

  it('restores the running request, queued follow-ups, controls and unknown effects exactly', async () => {
    await start(
      snapshot({
        watermark: '20',
        running: { request_id: 'r-run', generation: 2, started_at: '2026-10-04T00:00:00Z' },
        queued: [{ request_id: 'r-q', generation: 1, message_id: 'm-q' }],
        recent: [{ request_id: 'r-old', generation: 1, outcome: 'interrupted', unknown_effects: 2, at: '2026-10-04T00:00:00Z' }],
        controls: [{ control_command_id: 'k-1', kind: 'steer', request_id: 'r-run', generation: 2, disposition: 'queued', sequence: 1 }]
      })
    )
    const view = store.state.views.c1!
    expect(view.queued.map((q) => q.request_id)).toEqual(['r-q'])
    expect(view.recent[0]).toMatchObject({ outcome: 'interrupted', unknown_effects: 2 })
    expect(store.steersFor('c1', 'r-run', 2).map((s) => s.status)).toEqual(['queued'])
    await store.stop()
    expect(bridge.calls.stop[0]).toMatchObject({ request_id: 'r-run', generation: 2 })
  })

  it('loads older history when the core says there is more', async () => {
    await start(snapshot({ watermark: '9', messages: { items: [message('m3'), message('m4')], has_more: true } }))
    bridge.control.olderResult = { ok: true, result: { items: [message('m1'), message('m2')], has_more: false, watermark: '9' } }
    await store.loadOlder('c1')
    expect(bridge.calls.listMessages[0]).toMatchObject({ conversation_id: 'c1', before: 'm3' })
    expect(store.state.views.c1!.messages.map((m) => m.id)).toEqual(['m1', 'm2', 'm3', 'm4'])
    expect(store.state.views.c1!.hasMore).toBe(false)
  })
})

describe('control targets', () => {
  it('never lets a queued follow-up become the Stop or Steer target', async () => {
    await start()
    emit(event(2, 'request.started', { request_id: 'r-run', generation: 1 }))
    emit(event(3, 'request.queued', { request_id: 'r-q1', generation: 1, message_id: 'm1' }))
    emit(event(4, 'request.queued', { request_id: 'r-q2', generation: 1, message_id: 'm2' }))
    await store.stop()
    expect(bridge.calls.stop[0]).toMatchObject({ request_id: 'r-run', generation: 1 })
    await store.send('use the other host', 'steer')
    expect(bridge.calls.steer[0]).toMatchObject({ request_id: 'r-run' })

    emit(event(5, 'request.cancelled', { request_id: 'r-run', generation: 1, unknown_effects: 0 }))
    emit(event(6, 'request.started', { request_id: 'r-q1', generation: 1 }))
    const view = store.state.views.c1!
    expect(view.running?.request_id).toBe('r-q1')
    expect(view.queued.map((q) => q.request_id)).toEqual(['r-q2'])
  })

  it('keeps an unconfirmed steer under its first ID and never reports it as undelivered', async () => {
    await start()
    emit(event(2, 'request.started', { request_id: 'r-run', generation: 1 }))
    bridge.control.steerResult = UNKNOWN
    expect(await store.send('check the logs', 'steer')).toBe(true) // the text leaves the composer
    expect(bridge.calls.steer).toHaveLength(1)
    const id = String(bridge.calls.steer[0]!.control_command_id)
    expect(store.steersFor('c1', 'r-run', 1)[0]).toMatchObject({ control_command_id: id, status: 'awaiting-receipt' })
    expect(store.state.notice).not.toMatch(/not delivered/i)

    receipt({ id, settled: { ok: true, result: { disposition: 'queued' } } })
    expect(store.steersFor('c1', 'r-run', 1)[0]!.status).toBe('queued')
    emit(event(3, 'control.receipt', { request_id: 'r-run', generation: 1, control_command_id: id, kind: 'steer', disposition: 'consumed' }))
    expect(store.steersFor('c1', 'r-run', 1)[0]!.status).toBe('consumed')
    receipt({ id, settled: { ok: true, result: { disposition: 'queued' } } })
    expect(store.steersFor('c1', 'r-run', 1)[0]!.status).toBe('consumed') // a stale receipt never moves it back
    expect(bridge.calls.steer).toHaveLength(1)
  })

  it('keeps the text in the composer when a steer definitely was not delivered', async () => {
    await start()
    emit(event(2, 'request.started', { request_id: 'r-run', generation: 1 }))
    bridge.control.steerResult = { ok: false, error: { code: 'not_connected', message: 'Odin is not connected yet.', disposition: 'not_dispatched' } }
    expect(await store.send('check the logs', 'steer')).toBe(false)
    expect(store.steersFor('c1', 'r-run', 1)).toHaveLength(0)
    expect(store.state.notice).toMatch(/not delivered/i)
  })

  it('sends one Stop per running task while it is unconfirmed', async () => {
    await start()
    emit(event(2, 'request.started', { request_id: 'r-run', generation: 1 }))
    bridge.control.stopResult = UNKNOWN
    await store.stop()
    await store.stop()
    expect(bridge.calls.stop).toHaveLength(1)
    expect(store.stopPending('r-run', 1)).toBe(true)
  })

  it('binds a pending Stop to its generation, and a reset replaces the core’s control projection', async () => {
    await start(
      snapshot({
        watermark: '5',
        running: { request_id: 'r-run', generation: 1, started_at: '2026-10-04T00:00:00Z' },
        controls: [{ control_command_id: 'old-stop', kind: 'stop', request_id: 'r-run', generation: 1, disposition: 'requested' }]
      })
    )
    expect(store.stopPending('r-run', 1)).toBe(true)
    bridge.listeners.reset.forEach((l) => l({ event_high: '20' }))
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve(
      snapshot({ watermark: '20', running: { request_id: 'r-run', generation: 2, started_at: '2026-10-04T00:00:00Z' }, controls: [] })
    )
    await until(() => store.state.views.c1?.hasData === true)
    expect(store.state.views.c1!.running?.generation).toBe(2)
    expect(store.stopPending('r-run', 2)).toBe(false)
    expect(store.stopPending('r-run', 1)).toBe(false)
    await store.stop()
    expect(bridge.calls.stop[0]).toMatchObject({ request_id: 'r-run', generation: 2 })
  })
})

describe('recovery windows', () => {
  it('routes nothing while the open conversation is being rebuilt, and keeps the draft', async () => {
    await start(snapshot({ watermark: '5', running: { request_id: 'r-run', generation: 1, started_at: '2026-10-04T00:00:00Z' } }))
    bridge.listeners.reset.forEach((l) => l({ event_high: '20' }))
    await until(() => bridge.control.snapshots.length === 2)
    expect(store.canAct('c1')).toBe(false)
    expect(await store.send('change the plan', 'steer')).toBe(false) // the draft stays in the composer
    await store.stop()
    expect(bridge.calls.submit).toHaveLength(0)
    expect(bridge.calls.steer).toHaveLength(0)
    expect(bridge.calls.stop).toHaveLength(0)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '20', running: { request_id: 'r-run', generation: 1, started_at: '2026-10-04T00:00:00Z' } }))
    await until(() => store.canAct('c1'))
    expect(await store.send('change the plan', 'steer')).toBe(true)
    expect(bridge.calls.steer).toHaveLength(1)
    expect(bridge.calls.submit).toHaveLength(0)
  })

  it('routes nothing before the first snapshot of a conversation arrives', async () => {
    const done = store.init()
    await until(() => bridge.control.snapshots.length === 1)
    expect(await store.send('hello', 'queue')).toBe(false)
    expect(bridge.calls.submit).toHaveLength(0)
    bridge.control.snapshots[0]!.resolve(snapshot({ watermark: '1' }))
    await done
    expect(await store.send('hello', 'queue')).toBe(true)
  })

  it('keeps unknown effects listed after any number of later successful tasks', async () => {
    await start()
    emit(event(2, 'request.interrupted', { request_id: 'r-unknown', generation: 1, unknown_effects: 1 }))
    for (let n = 0; n < 25; n++) emit(event(3 + n, 'request.completed', { request_id: `r-ok-${n}`, generation: 1, unknown_effects: 0 }))
    const view = store.state.views.c1!
    expect(view.recent).toHaveLength(20)
    expect(view.unresolved).toEqual([expect.objectContaining({ request_id: 'r-unknown', unknown_effects: 1 })])
    emit(event(40, 'effects.resolved', { request_id: 'r-unknown', generation: 1, remaining: 0 }))
    expect(view.unresolved).toHaveLength(0)
  })

  it('keeps every unresolved outcome a snapshot reports, however many there are', async () => {
    const unresolved = Array.from({ length: 30 }, (_, n) => ({
      request_id: `r-u${n}`,
      generation: 1,
      outcome: 'interrupted' as const,
      unknown_effects: 1,
      at: '2026-10-04T00:00:00Z'
    }))
    await start(snapshot({ watermark: '9', unresolved }))
    expect(store.state.views.c1!.unresolved).toHaveLength(30)
  })

  it('rebuilds the sidebar activity of other conversations from the list after a reset', async () => {
    const other = { ...CONVERSATION, id: 'c2', title: 'Other' }
    bridge.control.list = [
      { ...CONVERSATION, activity: { running: null, queued: [] } },
      { ...other, activity: { running: { request_id: 'r-other', generation: 1 }, queued: [] } }
    ]
    bridge.control.listWatermark = '3'
    await start()
    expect(store.isBusy('c2')).toBe(true)
    // During the missing interval r-other ended and r-new started; only the reloaded list can say so.
    bridge.control.list = [
      { ...CONVERSATION, activity: { running: null, queued: [] } },
      { ...other, activity: { running: { request_id: 'r-new', generation: 1 }, queued: [] } }
    ]
    bridge.control.listWatermark = '20'
    bridge.listeners.reset.forEach((l) => l({ event_high: '20' }))
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '20' }))
    await until(() => store.state.views.c1?.hasData === true)
    expect(store.state.busy.c2).toEqual(['r-new'])
    const c2Event = (seq: number, type: string, requestId: string): CoreEvent => ({
      ...event(seq, type, {}),
      payload: { conversation_id: 'c2', request_id: requestId, generation: 1, unknown_effects: 0 }
    })
    emit(c2Event(21, 'request.completed', 'r-other'))
    expect(store.isBusy('c2')).toBe(true)
    emit(c2Event(22, 'request.completed', 'r-new'))
    expect(store.isBusy('c2')).toBe(false)
  })
})

describe('reconnect recovery', () => {
  const READY: AppState = { link: 'ready', coreInstanceId: 'core-1', noTray: false, unreceipted: 0 }
  const setApp = (app: AppState): void => bridge.listeners.appState.forEach((l) => l(app))
  const live = { request_id: 'r-live', generation: 1, started_at: '2026-10-04T00:00:00Z' }

  it('routes nothing on a same-core reconnect until the refreshed snapshot applies, then targets the live task', async () => {
    await start(snapshot({ watermark: '1' }))
    expect(store.canAct('c1')).toBe(true)
    bridge.control.holdLists = true
    setApp({ ...READY, link: 'reconnecting' })
    expect(store.canAct('c1')).toBe(false)
    setApp(READY)
    await until(() => bridge.control.lists.length === 1)
    expect(store.canAct('c1')).toBe(false) // the retained projection is from before the outage
    expect(await store.send('change the plan', 'steer')).toBe(false) // the draft stays in the composer
    await store.stop()
    expect([bridge.calls.submit, bridge.calls.steer, bridge.calls.stop].map((c) => c.length)).toEqual([0, 0, 0])

    // A task started during the outage: the list and the snapshot both say so.
    bridge.control.lists[0]!.resolve({
      ok: true,
      result: { items: [{ ...CONVERSATION, activity: { running: { request_id: 'r-live', generation: 1 }, queued: [] } }], watermark: '20' }
    })
    await until(() => bridge.control.snapshots.length === 2)
    expect(store.canAct('c1')).toBe(false)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '20', running: live }))
    await until(() => store.canAct('c1'))
    expect(await store.send('change the plan', 'steer')).toBe(true)
    expect(bridge.calls.submit).toHaveLength(0)
    expect(bridge.calls.steer[0]).toMatchObject({ request_id: 'r-live', generation: 1 })
  })

  it('treats a changed core as a new recovery even when the link never looked down', async () => {
    await start(snapshot({ watermark: '1' }))
    setApp({ ...READY, coreInstanceId: 'core-2' })
    expect(store.canAct('c1')).toBe(false)
    await until(() => bridge.control.snapshots.length === 2)
    expect(await store.send('hello', 'queue')).toBe(false)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '3' }))
    await until(() => store.canAct('c1'))
    expect(await store.send('hello', 'queue')).toBe(true)
    expect(bridge.calls.submit).toHaveLength(1)
  })

  it('holds events that arrive during recovery and applies those above the snapshot watermark', async () => {
    await start(snapshot({ watermark: '1' }))
    setApp({ ...READY, link: 'reconnecting' })
    setApp(READY)
    await until(() => bridge.control.snapshots.length === 2)
    // Caught-up events, one already covered by the snapshot and one after it.
    emit(event(20, 'request.queued', { request_id: 'r-old', generation: 1, message_id: 'm-old' }))
    emit(event(21, 'request.started', { request_id: 'r-live', generation: 1 }))
    expect(store.canAct('c1')).toBe(false)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '20' }))
    await until(() => store.canAct('c1'))
    const view = store.state.views.c1!
    expect(view.running?.request_id).toBe('r-live')
    expect(view.queued).toHaveLength(0) // event 20 was already reflected in the snapshot
    await store.stop()
    expect(bridge.calls.stop[0]).toMatchObject({ request_id: 'r-live', generation: 1 })
  })

  it('never lets an answer from an earlier recovery restore authority', async () => {
    await start(snapshot({ watermark: '1' }))
    setApp({ ...READY, link: 'reconnecting' })
    setApp(READY)
    await until(() => bridge.control.snapshots.length === 2)
    // A second outage starts before the first recovery's snapshot is answered.
    setApp({ ...READY, link: 'reconnecting' })
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '10' }))
    await new Promise((r) => setTimeout(r, 20))
    expect(store.canAct('c1')).toBe(false)
    setApp(READY)
    await until(() => bridge.control.snapshots.length === 3)
    expect(store.canAct('c1')).toBe(false)
    bridge.control.snapshots[2]!.resolve(snapshot({ watermark: '30', running: live }))
    await until(() => store.canAct('c1'))
    expect(store.state.views.c1!.running?.request_id).toBe('r-live')
  })

  it('shows a failed recovery snapshot as an error, routes nothing, and Retry restores authority', async () => {
    await start(snapshot({ watermark: '1' }))
    setApp({ ...READY, link: 'reconnecting' })
    setApp(READY)
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve({ ok: false, error: { code: 'busy', message: 'Odin is busy right now.', disposition: 'not_dispatched' } })
    await until(() => store.state.loadErrors.c1 !== undefined)
    expect(store.state.loadErrors.c1).toBe('Odin is busy right now.')
    expect(store.canAct('c1')).toBe(false)
    expect(await store.send('hello', 'queue')).toBe(false)
    expect(bridge.calls.submit).toHaveLength(0)

    void store.retry()
    await until(() => bridge.control.snapshots.length === 3)
    expect(store.state.loadErrors.c1).toBeUndefined() // in flight again, not failed
    bridge.control.snapshots[2]!.resolve(snapshot({ watermark: '5' }))
    await until(() => store.canAct('c1'))
    expect(await store.send('hello', 'queue')).toBe(true)
  })

  it('reloads a conversation selected while its in-flight load belongs to an earlier recovery', async () => {
    const other = { ...CONVERSATION, id: 'c2', title: 'Other' }
    bridge.control.list = [
      { ...CONVERSATION, activity: { running: null, queued: [] } },
      { ...other, activity: { running: null, queued: [] } }
    ]
    await start(snapshot({ watermark: '1' }))
    void store.select('c2') // its first load is held
    await until(() => bridge.control.snapshots.length === 2)
    await store.select('c1')
    setApp({ ...READY, link: 'reconnecting' })
    setApp(READY)
    await until(() => bridge.control.snapshots.length === 3)
    bridge.control.snapshots[2]!.resolve(snapshot({ watermark: '10' }))
    await until(() => store.canAct('c1'))

    void store.select('c2') // its in-flight load is from before the outage, so it must load again
    await until(() => bridge.control.snapshots.length === 4)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '2', conversation: other })) // the old answer
    bridge.control.snapshots[3]!.resolve(snapshot({ watermark: '11', conversation: other }))
    await until(() => store.canAct('c2'))
    expect(store.state.views.c2!.epoch).toBe(store.state.recoveryEpoch)
  })
})
