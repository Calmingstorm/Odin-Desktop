// The window's state store, driven through a fake bridge: snapshots, held events, control targets and receipts.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  AroundResult,
  AppState,
  Conversation,
  ConversationListItem,
  ConversationSnapshot,
  CoreEvent,
  LateReceipt,
  Message,
  Result,
  SearchResult
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
    reset: [] as Array<(r: { event_high: string }) => void>,
    open: [] as Array<(target: { conversationId: string; messageId: string }) => void>
  }
  const calls = {
    update: [] as Array<Record<string, unknown>>,
    remove: [] as Array<Record<string, unknown>>,
    reset: [] as Array<Record<string, unknown>>,
    markRead: [] as Array<Record<string, unknown>>,
    search: [] as Array<Record<string, unknown>>,
    around: [] as Array<Record<string, unknown>>,
    create: [] as Array<Record<string, unknown>>,
    submit: [] as Array<Record<string, unknown>>,
    snapshot: [] as unknown[],
    listMessages: [] as Array<Record<string, unknown>>,
    steer: [] as Array<Record<string, unknown>>,
    stop: [] as Array<Record<string, unknown>>,
    resume: [] as Array<Record<string, unknown>>
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
    submitResult: { ok: true, result: { disposition: 'accepted' } } as Result<{ disposition: string; request_id?: string; message_id?: string; reason?: string }>,
    holdSubmit: false,
    submissions: [] as Array<Deferred<Result<{ disposition: string; request_id?: string; message_id?: string; reason?: string }>>>,
    resumeResult: { ok: true, result: { disposition: 'admitted' } } as Result<{ disposition: 'admitted' | 'rejected'; reason?: string }>,
    notifications: { enabled: true, previews: true, quietHours: { enabled: false, start: '22:00', end: '08:00' }, muted: [] as string[] },
    updateResult: null as Result<{ conversation: Conversation }> | null,
    deleteResult: { ok: true, result: { disposition: 'deleted' } } as Result<{ disposition: string }>,
    searchResults: [] as Array<Deferred<Result<SearchResult>>>,
    createResult: null as Result<{ conversation: Conversation }> | null,
    /** When set, create answers wait here until the test releases them. */
    holdCreate: false,
    creates: [] as Array<Deferred<Result<{ conversation: Conversation }>>>,
    resetResult: null as Result<{ conversation: Conversation }> | null,
    /** When set, mark-read and around answers wait here until the test releases them. */
    holdMarkRead: false,
    markReads: [] as Array<Deferred<Result<{ conversation: Conversation }>>>,
    holdAround: false,
    arounds: [] as Array<Deferred<Result<AroundResult>>>,
    aroundResult: { ok: true, result: { items: [] as Message[], has_before: false, has_after: false } } as Result<AroundResult>,
    olderResult: { ok: true, result: { items: [] as Message[], has_more: false, watermark: '0' } } as Result<{
      items: Message[]
      has_more: boolean
      watermark: string
    }>
  }
  const api = {
    status: async () => ({ ok: true, result: { phase: 'ready', core_instance_id: 'core-1', version: 'test', capabilities: [], summary: 'Core core-1: ready.' } }),
    usage: async () => ({ ok: true, result: { period: '24h', tokens: { value: null, kind: 'unknown' }, context: { used: { value: null, kind: 'unknown' }, budget: { value: null, kind: 'unknown' } }, quota: [], summary: 'Usage unknown.' } }),
    reload: async () => ({ ok: true, result: { disposition: 'reloaded', summary: 'Context: none.' } }),
    getAppState: async (): Promise<AppState> => ({ link: 'ready', coreInstanceId: 'core-1', noTray: false, unreceipted: 0 }),
    getSettings: async () => ({ ok: true, result: { autostart: false, notifications: control.notifications } }),
    setConversationMuted: async (params: { conversation_id: string; muted: boolean }) => {
      const rest = control.notifications.muted.filter((id) => id !== params.conversation_id)
      control.notifications = { ...control.notifications, muted: params.muted ? [...rest, params.conversation_id] : rest }
      return { ok: true, result: { autostart: false, notifications: control.notifications } }
    },
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
    createConversation: (params: Record<string, unknown>) => {
      calls.create.push(params)
      const id = params.parent_id ? 'c-thread' : 'c-new'
      const answer: Result<{ conversation: Conversation }> = control.createResult ?? {
        ok: true,
        result: { conversation: { ...CONVERSATION, id, title: String(params.title ?? 'Chat'), parent_id: (params.parent_id as string) ?? null } }
      }
      if (!control.holdCreate) return Promise.resolve(answer)
      const next = deferred<Result<{ conversation: Conversation }>>()
      control.creates.push(next)
      return next.promise
    },
    updateConversation: async (params: Record<string, unknown>) => {
      calls.update.push(params)
      return control.updateResult ?? { ok: true, result: { conversation: { ...CONVERSATION, ...params, rev: Number(params.expected_rev) + 1 } } }
    },
    deleteConversation: async (params: Record<string, unknown>) => {
      calls.remove.push(params)
      return control.deleteResult
    },
    resetContext: async (params: Record<string, unknown>) => {
      calls.reset.push(params)
      if (control.resetResult) return control.resetResult
      return { ok: true, result: { conversation: { ...CONVERSATION, rev: Number(params.expected_rev) + 1 } } }
    },
    markRead: (params: Record<string, unknown>) => {
      calls.markRead.push(params)
      const answer: Result<{ conversation: Conversation }> = { ok: true, result: { conversation: { ...CONVERSATION, id: String(params.id), unread: 0 } } }
      if (!control.holdMarkRead) return Promise.resolve(answer)
      const next = deferred<Result<{ conversation: Conversation }>>()
      control.markReads.push(next)
      return next.promise
    },
    search: (params: Record<string, unknown>) => {
      calls.search.push(params)
      const next = deferred<Result<SearchResult>>()
      control.searchResults.push(next)
      return next.promise
    },
    messagesAround: (params: Record<string, unknown>) => {
      calls.around.push(params)
      if (!control.holdAround) return Promise.resolve(control.aroundResult)
      const next = deferred<Result<AroundResult>>()
      control.arounds.push(next)
      return next.promise
    },
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
    submit: (params: Record<string, unknown>) => {
      calls.submit.push(params)
      if (!control.holdSubmit) return Promise.resolve(control.submitResult)
      const next = deferred<typeof control.submitResult>()
      control.submissions.push(next)
      return next.promise
    },
    steer: async (params: Record<string, unknown>) => {
      calls.steer.push(params)
      return control.steerResult
    },
    stop: async (params: Record<string, unknown>) => {
      calls.stop.push(params)
      return control.stopResult
    },
    resumeRequest: async (params: Record<string, unknown>) => {
      calls.resume.push(params)
      return control.resumeResult
    },
    fetchArtifact: async () => ({ ok: true, result: { data: new Uint8Array(4) } }),
    checkArtifact: async () => ({ ok: true, result: { available: true } }),
    onEvent: (l: (e: CoreEvent) => void) => (listeners.event.push(l), () => undefined),
    onAppState: (l: (s: AppState) => void) => (listeners.appState.push(l), () => undefined),
    onReceipt: (l: (r: LateReceipt) => void) => (listeners.receipt.push(l), () => undefined),
    onReset: (l: (r: { event_high: string }) => void) => (listeners.reset.push(l), () => undefined),
    onOpenConversation: (l: (target: { conversationId: string; messageId: string }) => void) => (listeners.open.push(l), () => undefined)
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

/** Whether the window is visible and focused, as the store sees it through `document`. */
function setAttention(attentive: boolean): void {
  ;(globalThis as unknown as { document: unknown }).document = {
    visibilityState: attentive ? 'visible' : 'hidden',
    hasFocus: () => attentive,
    addEventListener: () => undefined,
    getElementById: () => null
  }
}
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
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge.api, addEventListener: () => undefined }
  // Vue looks for a real document when it loads, so the fake one goes in only afterwards.
  delete (globalThis as unknown as { document?: unknown }).document
  store = await import('../../src/renderer/src/store')
  setAttention(false)
})

describe('snapshots and held events', () => {
  it('records invocation start timing, preserves it only for the exact live snapshot binding, and does not invent it', async () => {
    const running = { request_id: 'run', generation: 1, started_at: '2026-10-03T00:00:00Z' }
    await start(snapshot({ watermark: '1', running }))
    // The engine's tool events carry request/invocation identity, but omit generation.
    emit(event(2, 'tool.started', { request_id: 'run', invocation_id: 'call', tool: 'run_command' }))
    expect(store.state.views.c1!.tools.run![0]).toMatchObject({ started_at: '2026-10-04T00:00:00Z', generation: 1 })
    // Replay cannot reset the observed invocation age.
    emit({ ...event(3, 'tool.started', { request_id: 'run', generation: 1, invocation_id: 'call', tool: 'run_command' }), at: '2026-10-04T01:00:00Z' })
    const tool = { invocation_id: 'call', tool: 'run_command', summary: '' }
    const refresh = store.retry()
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '4', running, tools: { run: [tool] } }))
    await refresh
    expect(store.state.views.c1!.tools.run![0]!.started_at).toBe('2026-10-04T00:00:00Z')
    const nextGeneration = store.retry()
    await until(() => bridge.control.snapshots.length === 3)
    bridge.control.snapshots[2]!.resolve(snapshot({ watermark: '5', running: { ...running, generation: 2 }, tools: { run: [tool] } }))
    await nextGeneration
    expect(store.state.views.c1!.tools.run![0]!.started_at).toBeUndefined()
  })

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

  it('shows a failed conversation list as an error, routes nothing, and Retry restarts the whole recovery', async () => {
    await start(snapshot({ watermark: '1' }))
    bridge.control.holdLists = true
    setApp({ ...READY, link: 'reconnecting' })
    setApp(READY)
    await until(() => bridge.control.lists.length === 1)
    bridge.control.lists[0]!.resolve({ ok: false, error: { code: 'storage_unavailable', message: 'Odin’s storage is unavailable.' } })
    await until(() => store.state.recoveryError !== undefined)
    expect(store.loadFailure()).toBe('Odin’s storage is unavailable.')
    expect(store.canAct('c1')).toBe(false)
    expect(await store.send('hello', 'queue')).toBe(false)
    expect(bridge.calls.submit).toHaveLength(0)

    void store.retry() // the list first, then the open conversation's snapshot
    await until(() => bridge.control.lists.length === 2)
    expect(store.loadFailure()).toBeUndefined()
    bridge.control.lists[1]!.resolve({ ok: true, result: { items: bridge.control.list, watermark: '9' } })
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '9' }))
    await until(() => store.canAct('c1'))
    expect(await store.send('hello', 'queue')).toBe(true)
  })

  it('shows a failed first load the same way, before anything was ever loaded', async () => {
    bridge.control.holdLists = true
    const done = store.init()
    await until(() => bridge.control.lists.length === 1)
    bridge.control.lists[0]!.resolve({ ok: false, error: { code: 'busy', message: 'Odin is starting.' } })
    await done
    expect(store.loadFailure()).toBe('Odin is starting.')
    void store.retry()
    await until(() => bridge.control.lists.length === 2)
    bridge.control.lists[1]!.resolve({ ok: true, result: { items: bridge.control.list, watermark: '1' } })
    await until(() => bridge.control.snapshots.length === 1)
    bridge.control.snapshots[0]!.resolve(snapshot({ watermark: '1' }))
    await until(() => store.canAct('c1'))
    expect(store.loadFailure()).toBeUndefined()
  })
})

describe('conversation management', () => {
  const other = { ...CONVERSATION, id: 'c2', title: 'Other' }

  it('renames with the current revision, and refreshes after a revision conflict', async () => {
    await start()
    expect(await store.renameConversation('c1', 'Plans')).toBe(true)
    expect(bridge.calls.update[0]).toMatchObject({ id: 'c1', expected_rev: 1, title: 'Plans' })
    expect(store.state.conversations[0]!.title).toBe('Plans')
    bridge.control.updateResult = { ok: false, error: { code: 'stale_binding', message: 'changed', disposition: 'stale_binding' } }
    expect(await store.renameConversation('c1', 'Again')).toBe(false)
    expect(store.state.notice).toMatch(/changed elsewhere/)
  })

  it('moves to another conversation when the open one is deleted elsewhere', async () => {
    bridge.control.list = [
      { ...CONVERSATION, activity: { running: null, queued: [] } },
      { ...other, activity: { running: null, queued: [] } }
    ]
    await start()
    emit({ ...event(5, 'conversation.deleted', {}), payload: { conversation_id: 'c1' } })
    expect(store.state.conversations.map((c) => c.id)).toEqual(['c2'])
    expect(store.state.views.c1).toBeUndefined()
    expect(store.state.activeId).toBe('c2')
  })

  it('keeps a conversation that refuses deletion because Odin is working in it', async () => {
    await start()
    bridge.control.deleteResult = { ok: false, error: { code: 'busy', message: 'Odin is working in this conversation. Stop it first.' } }
    expect(await store.deleteConversation('c1')).toBe(false)
    expect(store.state.conversations).toHaveLength(1)
    expect(store.state.notice).toMatch(/Stop it first/)
  })

  it('starts a thread from a message and opens it', async () => {
    await start(snapshot({ watermark: '3', messages: { items: [message('m1'), message('m2')], has_more: false } }))
    void store.startThread('c1', 'm1')
    await until(() => bridge.calls.create.length === 1)
    expect(bridge.calls.create[0]).toMatchObject({ parent_id: 'c1', from_message_id: 'm1' })
    await until(() => store.state.activeId === 'c-thread')
  })

  it('marks the open conversation read only while the window is in view', async () => {
    await start(snapshot({ watermark: '3', messages: { items: [message('m1')], has_more: false } }))
    emit(event(4, 'conversation.updated', { conversation: { ...CONVERSATION, unread: 2 } }))
    await new Promise((r) => setTimeout(r, 10))
    expect(bridge.calls.markRead).toHaveLength(0) // hidden window: nothing was seen
    setAttention(true)
    emit(event(5, 'conversation.updated', { conversation: { ...CONVERSATION, unread: 2 } }))
    await until(() => bridge.calls.markRead.length === 1)
    expect(bridge.calls.markRead[0]).toEqual({ id: 'c1', through_message_id: 'm1' })
  })
})

describe('search and jump', () => {
  it('applies only the latest search when an earlier one answers late', async () => {
    await start()
    void store.runSearch('first')
    void store.runSearch('second')
    await until(() => bridge.control.searchResults.length === 2)
    bridge.control.searchResults[1]!.resolve({ ok: true, result: { hits: [{ conversation_id: 'c1', message_id: 'm2', role: 'assistant', snippet: 'second', created_at: '2026-10-05T00:00:00Z' }], watermark: '9' } })
    await until(() => !store.state.search.loading)
    bridge.control.searchResults[0]!.resolve({ ok: true, result: { hits: [], watermark: '8' } })
    await new Promise((r) => setTimeout(r, 10))
    expect(store.state.search.hits.map((h) => h.snippet)).toEqual(['second'])
  })

  it('highlights a hit in loaded history, and opens a window around one outside it', async () => {
    await start(snapshot({ watermark: '3', messages: { items: [message('m5'), message('m6')], has_more: true } }))
    const hit = (id: string) => ({ conversation_id: 'c1', message_id: id, role: 'assistant' as const, snippet: id, created_at: '2026-10-05T00:00:00Z' })
    await store.jumpTo(hit('m6'))
    expect(store.state.highlightId).toBe('m6')
    expect(store.state.jump).toBeNull()
    expect(bridge.calls.around).toHaveLength(0)

    bridge.control.aroundResult = { ok: true, result: { items: [message('m1'), message('m2')], has_before: false, has_after: true } }
    await store.jumpTo(hit('m1'))
    expect(bridge.calls.around[0]).toMatchObject({ conversation_id: 'c1', message_id: 'm1' })
    expect(store.state.jump).toMatchObject({ conversationId: 'c1', messageId: 'm1', hasAfter: true })
    expect(store.state.views.c1!.messages.map((m) => m.id)).toEqual(['m5', 'm6']) // the live view is untouched
    store.backToLatest()
    expect(store.state.jump).toBeNull()
    expect(store.state.highlightId).toBeNull()
  })
  it('clears stale search results and pagination when search becomes unavailable', async () => {
    await start()
    store.state.search.hits = [
      { conversation_id: 'c1', message_id: 'm-old', role: 'assistant', snippet: 'stale', created_at: '2026-10-05T00:00:00Z' }
    ]
    store.state.search.nextCursor = 'old-cursor'
    void store.runSearch('fresh query')
    await until(() => bridge.control.searchResults.length === 1)
    bridge.control.searchResults[0]!.resolve({ ok: false, error: { code: 'capability_unavailable', message: 'Search is unavailable.', disposition: 'not_dispatched' } })
    await until(() => !store.state.search.loading)
    expect(store.state.search).toMatchObject({ query: 'fresh query', hits: [], nextCursor: null, unavailable: true, error: 'Search is unavailable in this core.' })
  })

  it('drops a failed around-message jump and keeps the live view intact', async () => {
    await start(snapshot({ watermark: '3', messages: { items: [message('m-latest')], has_more: false } }))
    bridge.control.aroundResult = { ok: false, error: { code: 'not_found', message: 'That message is no longer available.', disposition: 'not_dispatched' } }
    await store.jumpTo({ conversation_id: 'c1', message_id: 'm-gone', role: 'assistant', snippet: '', created_at: '2026-10-05T00:00:00Z' })
    expect(store.state.jump).toBeNull()
    expect(store.state.highlightId).toBeNull()
    expect(store.state.views.c1!.messages.map((m) => m.id)).toEqual(['m-latest'])
    expect(store.state.notice).toBe('That message is no longer available.')
  })
})

describe('history pagination failures', () => {
  it('does not request older history when the page is absent, exhausted, or already loading', async () => {
    await start(snapshot({ watermark: '3', messages: { items: [message('m1')], has_more: false } }))
    await store.loadOlder('missing')
    await store.loadOlder('c1')
    expect(bridge.calls.listMessages).toHaveLength(0)
    const view = store.state.views.c1!
    view.hasMore = true
    view.loadingOlder = true
    await store.loadOlder('c1')
    expect(bridge.calls.listMessages).toHaveLength(0)
  })

  it('preserves the current page and reports the error when older history cannot be fetched', async () => {
    const current = [message('m2'), message('m3')]
    await start(snapshot({ watermark: '3', messages: { items: current, has_more: true } }))
    bridge.control.olderResult = { ok: false, error: { code: 'storage_unavailable', message: 'History storage is unavailable.', disposition: 'not_dispatched' } }
    await store.loadOlder('c1')
    expect(bridge.calls.listMessages[0]).toMatchObject({ conversation_id: 'c1', before: 'm2', limit: 100 })
    expect(store.state.views.c1!.messages.map((m) => m.id)).toEqual(['m2', 'm3'])
    expect(store.state.views.c1!.loadingOlder).toBe(false)
    expect(store.state.notice).toBe('History storage is unavailable.')
  })
})

describe('commands and attachments', () => {
  it('matches commands by prefix and splits the argument', async () => {
    const commands = await import('../../src/renderer/src/commands')
    expect(commands.matchCommands('/st').map((c) => c.name)).toEqual(['stop', 'steer', 'status'])
    expect(commands.parseCommand('/steer use the other host')).toEqual({ name: 'steer', arg: 'use the other host' })
    expect(commands.parseCommand('/status')).toEqual({ name: 'status', arg: '' })
  })

  it('keeps /steer text in the box when nothing is running, and shows /status in the window only', async () => {
    await start()
    const commands = await import('../../src/renderer/src/commands')
    const steer = commands.COMMANDS.find((c) => c.name === 'steer')!
    expect(await steer.run('do it differently')).toBe(false)
    expect(store.state.notice).toMatch(/Nothing is running/)
    await commands.COMMANDS.find((c) => c.name === 'status')!.run('')
    // The core's own report, shown as a report (its Markdown rendered), never sent to Odin.
    expect(store.state.panel).toEqual({ title: 'Status', text: 'Core core-1: ready.', report: true })
    expect(bridge.calls.submit).toHaveLength(0) // nothing went to Odin as a message
  })

  it('sends attachments with a message, and refuses them on a steer', async () => {
    await start()
    const refs = [{ ref: 'a_1', add_to_knowledge: true }]
    expect(await store.send('', 'queue', refs)).toBe(true)
    expect(bridge.calls.submit[0]).toMatchObject({ conversation_id: 'c1', text: '', attachments: refs })
    emit(event(2, 'request.started', { request_id: 'r-run', generation: 1 }))
    expect(await store.send('look at this', 'steer', refs)).toBe(false)
    expect(store.state.notice).toMatch(/Choose Queue/)
    expect(bridge.calls.steer).toHaveLength(0)
  })
})

describe('results', () => {
  it('marks a file no longer available when the core says so', async () => {
    const reply: Message = { ...message('m-reply'), artifacts: [{ ref: 'f_1', name: 'notes.txt', mime: 'text/plain', size: 3, kind: 'file', available: true }] }
    await start(snapshot({ watermark: '1', messages: { items: [reply], has_more: false } }))
    emit(event(2, 'artifact.unavailable', { message_id: 'm-reply', ref: 'f_1', reason: 'expired' }))
    expect(store.state.views.c1!.messages[0]!.artifacts![0]!.available).toBe(false)
  })

  it('marks the file gone in a search window too', async () => {
    const old: Message = { ...message('m-old'), artifacts: [{ ref: 'f_9', name: 'old.txt', mime: 'text/plain', size: 3, kind: 'file', available: true }] }
    await start()
    bridge.control.aroundResult = { ok: true, result: { items: [old], has_before: false, has_after: true } }
    await store.jumpTo({ conversation_id: 'c1', message_id: 'm-old', role: 'assistant', snippet: '', created_at: '2026-10-05T00:00:00Z' })
    emit(event(2, 'artifact.unavailable', { message_id: 'm-old', ref: 'f_9', reason: 'expired' }))
    expect(store.state.jump!.items[0]!.artifacts![0]!.available).toBe(false)
  })
})

describe('typed resume submissions', () => {
  const original: Message = {
    ...message('m-original', 'user'), text: 'Finish the original work', request_id: 'r-original', client_submission_id: 's-original'
  }
  const suspended = { request_id: 'r-original', generation: 1, outcome: 'suspended' as const, unknown_effects: 0, at: original.created_at }
  const accepted = { ok: true as const, result: { disposition: 'accepted', request_id: 'r-original', message_id: 'm-original' } }

  async function preserved(): Promise<void> {
    await start(snapshot({ watermark: '1', messages: { items: [original], has_more: false }, recent: [suspended] }))
  }

  function failureNotice(id: string, submissionId: string): Message {
    return { ...message(id, 'notice'), text: "I couldn't resume the preserved work: checkpoint_unavailable. Nothing was resumed.",
      request_id: 'r-original', client_submission_id: submissionId }
  }

  it.each(['continue', 'resume'])('submits typed %s and applies generation 2 to the original request without a new user message', async (text) => {
    await preserved()
    bridge.control.holdSubmit = true
    const sending = store.send(text, 'queue')
    const id = String(bridge.calls.submit[0]!.client_submission_id)
    expect(store.state.pending).toEqual([{ client_submission_id: id, conversation_id: 'c1', text, status: 'sending' }])
    // The real RequestService response has the original IDs and NO generation. Only its event advances the view.
    emit(event(2, 'request.started', { request_id: 'r-original', generation: 2 }))
    bridge.control.submissions[0]!.resolve(accepted)
    expect(await sending).toBe(true)
    expect(store.state.pending).toEqual([])
    expect(store.state.views.c1!.running).toMatchObject({ request_id: 'r-original', generation: 2 })
    expect(store.state.views.c1!.messages).toEqual([original])
    expect(store.state.views.c1!.queued).toEqual([])
    expect(store.resumeTarget(store.state.views.c1)).toBeNull()
    expect(bridge.calls.resume).toEqual([]) // no second control or renderer-side interpretation
    expect(bridge.calls.submit).toHaveLength(1)
    expect(bridge.calls.submit[0]).toMatchObject({ text, conversation_id: 'c1' })
  })

  it('clears direct admission before request.started arrives, without inventing a generation from the answer', async () => {
    await preserved()
    bridge.control.submitResult = accepted
    expect(await store.send('continue', 'queue')).toBe(true)
    expect(store.state.pending).toEqual([])
    expect(store.state.views.c1!.running).toBeNull()
    expect(store.state.views.c1!.messages).toEqual([original])
    emit(event(2, 'request.started', { request_id: 'r-original', generation: 2 }))
    expect(store.state.views.c1!.running).toMatchObject({ request_id: 'r-original', generation: 2 })
    expect(store.state.views.c1!.messages).toEqual([original])
    expect(bridge.calls.submit).toHaveLength(1)
  })

  it('settles lost-ACK typed resume admission by receipt, even when the original message is outside the loaded page', async () => {
    await start(snapshot({ watermark: '1', recent: [suspended], messages: { items: [], has_more: true } }))
    bridge.control.submitResult = UNKNOWN
    expect(await store.send('continue', 'queue')).toBe(true)
    const id = String(bridge.calls.submit[0]!.client_submission_id)
    expect(store.state.pending[0]?.status).toBe('awaiting-receipt')
    receipt({ id, settled: UNKNOWN })
    expect(store.state.pending[0]?.status).toBe('unknown')
    receipt({ id, settled: accepted })
    expect(store.state.pending).toEqual([]) // the original message cannot carry this new submission ID
    expect(store.state.views.c1!.running).toBeNull() // admission is not an invented request.started event
    emit(event(2, 'request.started', { request_id: 'r-original', generation: 2 }))
    expect(store.state.views.c1!.running).toMatchObject({ request_id: 'r-original', generation: 2 })
    expect(store.state.views.c1!.messages).toEqual([])
    expect(bridge.calls.submit).toHaveLength(1)
    expect(bridge.calls.resume).toEqual([])
  })

  it.each(['rejected', 'outcome_unknown'])('keeps the engine committed notice when typed resume returns %s', async (disposition) => {
    await preserved()
    bridge.control.holdSubmit = true
    const sending = store.send('resume', 'queue')
    const id = String(bridge.calls.submit[0]!.client_submission_id)
    const committed = failureNotice('m-notice', id)
    emit(event(2, 'message.committed', { message: committed }))
    expect(store.state.pending).toEqual([]) // notice settles it before the awaited submission answer
    bridge.control.submissions[0]!.resolve({ ok: true, result: { ...accepted.result, disposition, reason: 'checkpoint_unavailable' } })
    expect(await sending).toBe(false)
    expect(store.state.pending).toEqual([])
    expect(store.state.views.c1!.messages).toEqual([original, committed])
    expect(store.state.views.c1!.running).toBeNull()
    expect(store.state.views.c1!.queued).toEqual([])
    expect(bridge.calls.submit).toHaveLength(1)
  })

  it('settles a failed resume notice after a lost ACK, before a late rejection arrives', async () => {
    await preserved()
    bridge.control.submitResult = UNKNOWN
    await store.send('continue', 'queue')
    const id = String(bridge.calls.submit[0]!.client_submission_id)
    const committed = failureNotice('m-failed', id)
    emit(event(2, 'message.committed', { message: committed }))
    expect(store.state.pending).toEqual([])
    receipt({ id, settled: { ok: true, result: { ...accepted.result, disposition: 'rejected' } } })
    expect(store.state.pending).toEqual([])
    expect(store.state.views.c1!.messages).toEqual([original, committed])
    expect(store.state.views.c1!.running).toBeNull()
    expect(bridge.calls.submit).toHaveLength(1)
  })

  it('settles a pending typed resume from a failure notice in a recovery snapshot, not just live events', async () => {
    await preserved()
    bridge.control.submitResult = UNKNOWN
    await store.send('resume', 'queue')
    const id = String(bridge.calls.submit[0]!.client_submission_id)
    const committed = failureNotice('m-recovered-notice', id)
    bridge.listeners.reset.forEach((l) => l({ event_high: '5' }))
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '5', messages: { items: [original, committed], has_more: false }, recent: [suspended] }))
    await until(() => store.state.views.c1?.hasData === true)
    expect(store.state.pending).toEqual([])
    expect(store.state.views.c1!.messages).toEqual([original, committed])
    expect(store.state.views.c1!.running).toBeNull()
    expect(bridge.calls.submit).toHaveLength(1)
  })

  it('settles a late failure answer before its committed notice arrives and still shows the notice', async () => {
    await preserved()
    bridge.control.submitResult = UNKNOWN
    await store.send('resume', 'queue')
    const id = String(bridge.calls.submit[0]!.client_submission_id)
    receipt({ id, settled: { ok: true, result: { ...accepted.result, disposition: 'rejected', reason: 'unknown_effects' } } })
    expect(store.state.pending).toEqual([])
    const committed = failureNotice('m-late-notice', id)
    emit(event(2, 'message.committed', { message: committed }))
    expect(store.state.views.c1!.messages).toEqual([original, committed])
    expect(store.state.views.c1!.running).toBeNull()
  })

  it.each(['continue', 'resume'])('keeps %s ordinary chat when the core has nothing to resume', async (text) => {
    await start()
    bridge.control.holdSubmit = true
    const sending = store.send(text, 'queue')
    const id = String(bridge.calls.submit[0]!.client_submission_id)
    const fresh = { ...message('m-fresh', 'user'), text, request_id: 'r-fresh', client_submission_id: id }
    emit(event(2, 'message.committed', { message: fresh }))
    emit(event(3, 'request.queued', { request_id: 'r-fresh', generation: 1 }))
    bridge.control.submissions[0]!.resolve({ ok: true, result: { disposition: 'accepted', request_id: 'r-fresh', message_id: 'm-fresh' } })
    expect(await sending).toBe(true)
    expect(store.state.pending).toEqual([])
    expect(store.state.views.c1!.messages).toEqual([fresh])
    expect(store.state.views.c1!.queued).toEqual([{ request_id: 'r-fresh', generation: 1, message_id: 'm-fresh' }])
    emit(event(4, 'request.started', { request_id: 'r-fresh', generation: 1 }))
    expect(store.state.views.c1!.running).toMatchObject({ request_id: 'r-fresh', generation: 1 })
    expect(bridge.calls.resume).toEqual([])
  })

  it('does not clear an unresolved submission on an unrelated notice or assistant message', async () => {
    await preserved()
    bridge.control.submitResult = UNKNOWN
    await store.send('continue', 'queue')
    const id = String(bridge.calls.submit[0]!.client_submission_id)
    emit(event(2, 'message.committed', { message: failureNotice('m-unrelated', 's-other') }))
    emit(event(3, 'message.committed', { message: { ...message('m-reply'), client_submission_id: id } }))
    expect(store.state.pending).toHaveLength(1)
    expect(store.state.pending[0]?.client_submission_id).toBe(id)
    receipt({ id, settled: accepted })
    expect(store.state.pending).toEqual([])
  })
})

describe('guarded resume', () => {
  const interrupted = { request_id: 'r1', generation: 1, outcome: 'interrupted' as const, unknown_effects: 0, at: '2026-10-04T00:00:00Z' }

  it('offers the latest interrupted or suspended request, and nothing while work runs or after it completed', async () => {
    await start(snapshot({ watermark: '1', recent: [interrupted] }))
    const view = store.state.views.c1!
    expect(store.resumeTarget(view)).toEqual({ outcome: interrupted, blocked: null })
    emit(event(2, 'request.started', { request_id: 'r2', generation: 1 }))
    expect(store.resumeTarget(view)).toBeNull()
    emit(event(3, 'request.completed', { request_id: 'r2', generation: 1, unknown_effects: 0 }))
    expect(store.resumeTarget(view)).toBeNull() // a later outcome replaced it
    emit(event(4, 'request.suspended', { request_id: 'r3', generation: 2, unknown_effects: 0 }))
    expect(store.resumeTarget(view)?.outcome.request_id).toBe('r3')
  })

  it('explains, instead of offering, a resume blocked by unknown effects, and offers it once they are reconciled', async () => {
    const unknown = { ...interrupted, unknown_effects: 2 }
    await start(snapshot({ watermark: '1', recent: [unknown], unresolved: [unknown] }))
    expect(store.resumeTarget(store.state.views.c1!)?.blocked).toMatch(/couldn't confirm/)
    emit(event(2, 'effects.resolved', { request_id: 'r1', generation: 1, remaining: 1 }))
    expect(store.resumeTarget(store.state.views.c1!)?.blocked).toMatch(/couldn't confirm/)
    emit(event(3, 'effects.resolved', { request_id: 'r1', generation: 1, remaining: 0 }))
    expect(store.resumeTarget(store.state.views.c1!)?.blocked).toBeNull()
  })

  it('binds the exact request and generation, sends once, and shows the core refusing', async () => {
    await start(snapshot({ watermark: '1', recent: [interrupted] }))
    bridge.control.resumeResult = { ok: true, result: { disposition: 'rejected', reason: 'Odin is working in this conversation.' } }
    await store.resume('c1', interrupted)
    expect(bridge.calls.resume).toEqual([
      { control_command_id: expect.any(String), conversation_id: 'c1', request_id: 'r1', generation: 1 }
    ])
    expect(store.state.resumes['r1:1']).toEqual({ status: 'rejected', reason: 'Odin is working in this conversation.' })
    bridge.control.resumeResult = { ok: true, result: { disposition: 'admitted' } }
    await store.resume('c1', interrupted)
    expect(store.state.resumes['r1:1']).toEqual({ status: 'admitted' })
    await store.resume('c1', interrupted) // admitted already: never a second resume
    expect(bridge.calls.resume).toHaveLength(2)
  })
})

describe('search highlights', () => {
  it('ends when the user sends a message or opens another conversation, so the view follows new messages again', async () => {
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    store.state.highlightId = 'm1'
    await store.send('hello', 'queue')
    expect(store.state.highlightId).toBeNull()
    store.state.highlightId = 'm1'
    await store.select('c1')
    expect(store.state.highlightId).toBe('m1') // staying in the same conversation keeps it
    void store.select('c2')
    expect(store.state.highlightId).toBeNull()
  })
})

describe('notifications', () => {
  it('loads the settings, mutes and unmutes one conversation, and opens the one a notification was for', async () => {
    await start()
    expect(store.state.notifications?.previews).toBe(true)
    expect(store.isMuted('c1')).toBe(false)
    await store.setMuted('c1', true)
    expect(store.isMuted('c1')).toBe(true)
    await store.setMuted('c1', false)
    expect(store.isMuted('c1')).toBe(false)
    store.state.activeId = null
    bridge.listeners.open.forEach((l) => l({ conversationId: 'c1', messageId: 'm1' }))
    expect(store.state.activeId).toBe('c1')
  })
})

describe('review round 1: conversation commands are confirmed once', () => {
  it('never retries a lost thread as a second thread; its late receipt adds it without moving the view', async () => {
    await start()
    bridge.control.createResult = UNKNOWN
    await store.startThread('c1')
    await store.startThread('c1')
    expect(bridge.calls.create).toHaveLength(1)
    const commandId = bridge.calls.create[0]!.command_id as string
    expect(commandId).toMatch(/^[0-9a-f-]{36}$/)
    receipt({ id: commandId, settled: { ok: true, result: { conversation: { ...CONVERSATION, id: 'c-thread', title: 'Thread: Chat', parent_id: 'c1' } } } })
    expect(store.state.conversations.map((c) => c.id)).toContain('c-thread')
    expect(store.state.activeId).toBe('c1')
    expect(store.state.notice).toMatch(/ready/)
    bridge.control.createResult = null
    await store.startThread('c1') // confirmed, so another thread may be made
    expect(bridge.calls.create).toHaveLength(2)
  })

  it('holds a second reset of the same conversation until the first is confirmed', async () => {
    await start()
    bridge.control.resetResult = UNKNOWN
    await store.resetContext('c1')
    await store.resetContext('c1')
    expect(bridge.calls.reset).toHaveLength(1)
  })
})

describe('review round 1: deletions stay deleted', () => {
  const listItem = (id: string, title = id) => ({ ...CONVERSATION, id, title, activity: { running: null, queued: [] } })

  it('a list asked for before a deletion cannot bring the conversation back', async () => {
    bridge.control.list = [listItem('c1'), listItem('c2')]
    await start()
    bridge.control.updateResult = { ok: false, error: { code: 'stale_binding', message: 'changed', disposition: 'not_dispatched' } }
    bridge.control.holdLists = true
    await store.renameConversation('c1', 'Renamed') // the conflict refreshes the list
    await until(() => bridge.control.lists.length === 1)
    emit(event(5, 'conversation.deleted', { conversation_id: 'c2' }))
    bridge.control.lists[0]!.resolve({ ok: true, result: { items: [listItem('c1'), listItem('c2')], watermark: '4' } })
    await new Promise((r) => setTimeout(r, 10))
    expect(store.state.conversations.map((c) => c.id)).toEqual(['c1'])
  })

  it('a full list removes a conversation deleted while the window missed it, but keeps one created since', async () => {
    bridge.control.list = [listItem('c1'), listItem('c2')]
    await start()
    bridge.control.list = [listItem('c1')]
    bridge.control.listWatermark = '20'
    bridge.control.updateResult = { ok: false, error: { code: 'stale_binding', message: 'changed', disposition: 'not_dispatched' } }
    bridge.control.holdLists = true
    await store.renameConversation('c1', 'Renamed')
    await until(() => bridge.control.lists.length === 1)
    await store.newConversation() // created while the list was on its way
    bridge.control.lists[0]!.resolve({ ok: true, result: { items: [listItem('c1')], watermark: '20' } })
    await new Promise((r) => setTimeout(r, 10))
    expect(store.state.conversations.map((c) => c.id).sort()).toEqual(['c-new', 'c1'])
  })

  it('drops search results from a deleted conversation', async () => {
    await start()
    store.state.search.hits = [
      { conversation_id: 'c2', message_id: 'm9', role: 'assistant', snippet: 'gone', created_at: '2026-10-05T00:00:00Z' },
      { conversation_id: 'c1', message_id: 'm1', role: 'assistant', snippet: 'kept', created_at: '2026-10-05T00:00:00Z' }
    ]
    emit(event(2, 'conversation.deleted', { conversation_id: 'c2' }))
    expect(store.state.search.hits.map((h) => h.conversation_id)).toEqual(['c1'])
  })
})

describe('review round 1: unread follows what is on screen', () => {
  it('marks nothing read while a search window shows older messages, and reads once back at the latest', async () => {
    setAttention(true)
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    bridge.control.aroundResult = { ok: true, result: { items: [message('m0')], has_before: false, has_after: true } }
    await store.jumpTo({ conversation_id: 'c1', message_id: 'm0', role: 'assistant', snippet: '', created_at: '2026-10-05T00:00:00Z' })
    expect(store.state.jump?.messageId).toBe('m0')
    const before = bridge.calls.markRead.length
    emit(event(2, 'conversation.updated', { conversation: { ...CONVERSATION, unread: 2, rev: 2 } }))
    expect(bridge.calls.markRead).toHaveLength(before)
    store.backToLatest()
    await until(() => bridge.calls.markRead.length === before + 1)
  })

  it('marks a cached unread conversation read when it is opened', async () => {
    bridge.control.list = [
      { ...CONVERSATION, activity: { running: null, queued: [] } },
      { ...CONVERSATION, id: 'c2', title: 'Two', activity: { running: null, queued: [] } }
    ]
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    emit(event(2, 'conversation.updated', { conversation: { ...CONVERSATION, unread: 3, rev: 2 } }))
    const opening = store.select('c2')
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '2', conversation: { ...CONVERSATION, id: 'c2' } }))
    await opening
    setAttention(true)
    const before = bridge.calls.markRead.length
    await store.select('c1')
    await until(() => bridge.calls.markRead.length === before + 1)
    expect(bridge.calls.markRead[before]).toMatchObject({ id: 'c1', through_message_id: 'm1' })
  })

  it('reads once more after a read in flight when more arrived meanwhile', async () => {
    setAttention(true)
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    bridge.control.holdMarkRead = true
    emit(event(2, 'conversation.updated', { conversation: { ...CONVERSATION, unread: 1, rev: 2 } }))
    await until(() => bridge.control.markReads.length === 1)
    emit(event(3, 'message.committed', { message: message('m2') }))
    emit(event(4, 'conversation.updated', { conversation: { ...CONVERSATION, unread: 2, rev: 3 } }))
    emit(event(5, 'conversation.updated', { conversation: { ...CONVERSATION, unread: 3, rev: 4 } }))
    bridge.control.markReads[0]!.resolve({ ok: true, result: { conversation: { ...CONVERSATION, unread: 2, rev: 4 } } })
    await until(() => bridge.control.markReads.length === 2)
    expect(bridge.calls.markRead[1]).toMatchObject({ through_message_id: 'm2' })
    bridge.control.markReads[1]!.resolve({ ok: true, result: { conversation: { ...CONVERSATION, unread: 0, rev: 5 } } })
    await new Promise((r) => setTimeout(r, 10))
    expect(bridge.control.markReads).toHaveLength(2)
  })
})

describe('review round 1: search navigation is fenced', () => {
  const hit = (snippet: string) => ({ conversation_id: 'c1', message_id: 'm1', role: 'assistant' as const, snippet, created_at: '2026-10-05T00:00:00Z' })

  it('never lets an older answer to the same words replace a newer one', async () => {
    await start()
    void store.runSearch('logs')
    void store.runSearch('logs')
    await until(() => bridge.control.searchResults.length === 2)
    bridge.control.searchResults[1]!.resolve({ ok: true, result: { hits: [hit('newer')], watermark: '2' } })
    bridge.control.searchResults[0]!.resolve({ ok: true, result: { hits: [hit('older')], watermark: '1' } })
    await new Promise((r) => setTimeout(r, 10))
    expect(store.state.search.hits.map((h) => h.snippet)).toEqual(['newer'])
  })

  it('never lets a late jump land after going back to the latest', async () => {
    await start()
    bridge.control.holdAround = true
    const jumping = store.jumpTo({ ...hit('old'), message_id: 'm-old' })
    await until(() => bridge.control.arounds.length === 1)
    store.backToLatest()
    bridge.control.arounds[0]!.resolve({ ok: true, result: { items: [message('m-old')], has_before: false, has_after: true } })
    await jumping
    expect(store.state.jump).toBeNull()
    expect(store.state.highlightId).toBeNull()
  })

  it('ends a highlight when another conversation opens', async () => {
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    await store.jumpTo(hit('here'))
    expect(store.state.highlightId).toBe('m1')
    void store.select('c2')
    expect(store.state.highlightId).toBeNull()
  })
})

describe('review round 2: lists, commands, search and jumps', () => {
  const listItem = (id: string, title = id) => ({ ...CONVERSATION, id, title, activity: { running: null, queued: [] } })
  const conflict = { ok: false, error: { code: 'stale_binding', message: 'changed', disposition: 'not_dispatched' } } as const
  const oldHit = (conversation_id: string) => ({ conversation_id, message_id: 'm-old', role: 'assistant' as const, snippet: '', created_at: '2026-10-05T00:00:00Z' })

  it('an older complete list answering after a newer one removes nothing, and later updates still apply', async () => {
    bridge.control.list = [listItem('c1')]
    await start()
    bridge.control.updateResult = conflict
    bridge.control.holdLists = true
    await store.renameConversation('c1', 'A') // each conflict refreshes the list
    await store.renameConversation('c1', 'B')
    await until(() => bridge.control.lists.length === 2)
    bridge.control.lists[1]!.resolve({ ok: true, result: { items: [listItem('c1'), listItem('c2')], watermark: '20' } })
    await until(() => store.state.conversations.some((c) => c.id === 'c2'))
    bridge.control.lists[0]!.resolve({ ok: true, result: { items: [listItem('c1')], watermark: '10' } })
    await new Promise((r) => setTimeout(r, 10))
    expect(store.state.conversations.map((c) => c.id)).toEqual(['c1', 'c2'])
    emit(event(21, 'conversation.updated', { conversation: { ...CONVERSATION, id: 'c2', title: 'Renamed', rev: 2 } }))
    expect(store.state.conversations.find((c) => c.id === 'c2')?.title).toBe('Renamed')
  })

  it('a conversation missing from a complete list comes back when a newer event shows it', async () => {
    bridge.control.list = [listItem('c1'), listItem('c2')]
    await start()
    bridge.control.list = [listItem('c1')]
    bridge.control.listWatermark = '20'
    bridge.control.updateResult = conflict
    await store.renameConversation('c1', 'A')
    await until(() => !store.state.conversations.some((c) => c.id === 'c2'))
    emit(event(21, 'conversation.updated', { conversation: { ...CONVERSATION, id: 'c2', title: 'Still here', rev: 2 } }))
    expect(store.state.conversations.map((c) => c.id)).toContain('c2')
  })

  it('two quick Thread clicks while the first is on its way make one thread', async () => {
    await start()
    bridge.control.holdCreate = true
    const first = store.startThread('c1')
    await store.startThread('c1')
    expect(bridge.calls.create).toHaveLength(1)
    expect(store.state.notice).toMatch(/hasn't confirmed/)
    bridge.control.creates[0]!.resolve({ ok: true, result: { conversation: { ...CONVERSATION, id: 'c-thread', title: 'Thread: Chat', parent_id: 'c1' } } })
    await first
    expect(store.state.conversations.filter((c) => c.parent_id === 'c1').map((c) => c.id)).toEqual(['c-thread'])
  })

  it('a search answered after a deletion never shows the deleted conversation, on any page', async () => {
    await start()
    const hitIn = (conversation_id: string, message_id = `m-${conversation_id}`) => ({ ...oldHit(conversation_id), message_id, snippet: 'logs' })
    void store.runSearch('logs')
    await until(() => bridge.control.searchResults.length === 1)
    emit(event(10, 'conversation.deleted', { conversation_id: 'c2' }))
    bridge.control.searchResults[0]!.resolve({ ok: true, result: { hits: [hitIn('c2'), hitIn('c1')], watermark: '9', next_cursor: 'p2' } })
    await until(() => !store.state.search.loading)
    expect(store.state.search.hits.map((h) => h.conversation_id)).toEqual(['c1'])
    void store.moreResults()
    await until(() => bridge.control.searchResults.length === 2)
    bridge.control.searchResults[1]!.resolve({ ok: true, result: { hits: [hitIn('c2', 'm-c2-b'), hitIn('c1', 'm-c1-b')], watermark: '9' } })
    await until(() => !store.state.search.loading)
    expect(store.state.search.hits.map((h) => h.message_id)).toEqual(['m-c1', 'm-c1-b'])
  })

  it('a jump ended while its conversation is still loading never lands', async () => {
    bridge.control.list = [listItem('c1'), listItem('c2')]
    await start()
    const jumping = store.jumpTo(oldHit('c2'))
    await until(() => bridge.control.snapshots.length === 2)
    store.backToLatest()
    bridge.control.snapshots[1]!.resolve(
      snapshot({ watermark: '2', conversation: { ...CONVERSATION, id: 'c2' }, messages: { items: [message('m-new')], has_more: true } })
    )
    await jumping
    expect(bridge.calls.around).toHaveLength(0)
    expect(store.state.jump).toBeNull()
    expect(store.state.highlightId).toBeNull()
  })

  it('opening an old search hit leaves newer unread replies unread, loading or cached', async () => {
    setAttention(true)
    bridge.control.list = [listItem('c1'), { ...listItem('c2'), unread: 5 }]
    await start()
    bridge.control.aroundResult = { ok: true, result: { items: [message('m-old')], has_before: false, has_after: true } }
    const jumping = store.jumpTo(oldHit('c2'))
    await until(() => bridge.control.snapshots.length === 2)
    bridge.control.snapshots[1]!.resolve(
      snapshot({ watermark: '2', conversation: { ...CONVERSATION, id: 'c2', unread: 5 }, messages: { items: [message('m-new')], has_more: true } })
    )
    await jumping
    expect(store.state.jump?.messageId).toBe('m-old')
    expect(bridge.calls.markRead).toHaveLength(0)
    // Now cached: going elsewhere and jumping back into the same old window still reads nothing.
    await store.select('c1')
    await store.jumpTo(oldHit('c2'))
    expect(store.state.jump?.conversationId).toBe('c2')
    expect(bridge.calls.markRead).toHaveLength(0)
    expect(store.state.conversations.find((c) => c.id === 'c2')?.unread).toBe(5)
  })
})

describe('review round 2: a file that is gone leaves the window', () => {
  it("drops the window's copy of an image when the core says it is gone, loaded conversation or not", async () => {
    await start()
    const { images } = await import('../../src/renderer/src/artifacts')
    const shown = images.acquire({ ref: 'r-img', name: 'a.png', mime: 'image/png', size: 4, kind: 'image', available: true })
    await shown.url
    shown.release()
    expect(images.cached().map(([ref]) => ref)).toEqual(['r-img'])
    emit(event(9, 'artifact.unavailable', { conversation_id: 'c-elsewhere', message_id: 'm9', ref: 'r-img' }))
    expect(images.cached()).toEqual([])
  })
})

describe('review round 2: an unconfirmed resume is never sent again', () => {
  const interrupted = { request_id: 'r1', generation: 1, outcome: 'interrupted' as const, unknown_effects: 0, at: '2026-10-04T00:00:00Z' }

  it('holds an unanswered resume under its first command until its receipt settles it', async () => {
    await start(snapshot({ watermark: '1', recent: [interrupted] }))
    bridge.control.resumeResult = UNKNOWN
    await store.resume('c1', interrupted)
    await store.resume('c1', interrupted)
    expect(bridge.calls.resume).toHaveLength(1)
    const commandId = String(bridge.calls.resume[0]!.control_command_id)
    expect(store.state.resumes['r1:1']).toEqual({ status: 'unknown', commandId })
    receipt({ id: commandId, settled: UNKNOWN })
    expect(store.state.resumes['r1:1']?.status).toBe('unknown')
    receipt({ id: commandId, settled: { ok: true, result: { disposition: 'admitted' } } })
    expect(store.state.resumes['r1:1']).toEqual({ status: 'admitted' })
    expect(bridge.calls.resume).toHaveLength(1)
  })
})

describe('review round 2: a notification opens the news', () => {
  it('shows the latest messages and reads them, even with a search window open in that conversation', async () => {
    setAttention(true)
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    bridge.control.aroundResult = { ok: true, result: { items: [message('m-old')], has_before: false, has_after: true } }
    await store.jumpTo({ conversation_id: 'c1', message_id: 'm-old', role: 'assistant', snippet: '', created_at: '2026-10-05T00:00:00Z' })
    expect(store.state.jump?.messageId).toBe('m-old')
    emit(event(2, 'message.committed', { message: message('m2') }))
    emit(event(3, 'conversation.updated', { conversation: { ...CONVERSATION, unread: 1, rev: 2 } }))
    const before = bridge.calls.markRead.length
    bridge.listeners.open.forEach((l) => l({ conversationId: 'c1', messageId: 'm2' }))
    await until(() => bridge.calls.markRead.length === before + 1)
    expect(store.state.jump).toBeNull()
    expect(store.state.highlightId).toBe('m2')
    expect(bridge.calls.markRead[before]).toMatchObject({ id: 'c1', through_message_id: 'm2' })
  })

  it('opens an older notification message, not a newer reply that arrived before the click', async () => {
    await start(snapshot({ watermark: '3', messages: { items: [message('m-latest')], has_more: true } }))
    bridge.control.aroundResult = { ok: true, result: { items: [message('m-notified')], has_before: true, has_after: true } }
    bridge.listeners.open.forEach((l) => l({ conversationId: 'c1', messageId: 'm-notified' }))
    await until(() => store.state.highlightId === 'm-notified')
    expect(store.state.jump?.messageId).toBe('m-notified')
    expect(bridge.calls.around.at(-1)).toMatchObject({ conversation_id: 'c1', message_id: 'm-notified' })
    expect(store.state.views.c1?.messages.at(-1)?.id).toBe('m-latest')
  })
})

describe('review round 3: going to the latest messages scrolls there', () => {
  it('signals the message list on a notification click and on Back to latest', async () => {
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    const before = store.state.latestScroll
    await store.openLatest('c1')
    expect(store.state.latestScroll).toBe(before + 1)
    store.backToLatest()
    expect(store.state.latestScroll).toBe(before + 2)
  })
})


describe('review round 4: a late open at the latest messages yields to newer navigation', () => {
  it("doesn't ask for a scroll when the user moved on while its snapshot loaded (11.R4.2)", async () => {
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    bridge.control.list.push({ ...CONVERSATION, id: 'c2', title: 'Other', activity: { running: null, queued: [] } })
    const opening = store.openLatest('c2')
    await until(() => bridge.control.snapshots.length === 2)
    await store.select('c1')
    await store.jumpTo({ conversation_id: 'c1', message_id: 'm1', role: 'assistant', snippet: '', created_at: '2026-10-05T00:00:00Z' })
    const before = store.state.latestScroll
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '1', conversation: { ...CONVERSATION, id: 'c2' } }))
    await opening
    expect(store.state.latestScroll).toBe(before)
    expect(store.state.activeId).toBe('c1')
    expect(store.state.highlightId).toBe('m1')
  })

  it('yields to a search in the same conversation while its snapshot loads', async () => {
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    bridge.control.list.push({ ...CONVERSATION, id: 'c2', title: 'Other', activity: { running: null, queued: [] } })
    bridge.control.aroundResult = { ok: true, result: { items: [message('m-old')], has_before: false, has_after: true } }
    const opening = store.openLatest('c2')
    await until(() => bridge.control.snapshots.length === 2)
    await store.jumpTo({ conversation_id: 'c2', message_id: 'm-old', role: 'assistant', snippet: '', created_at: '2026-10-05T00:00:00Z' })
    expect(store.state.highlightId).toBe('m-old')
    const before = store.state.latestScroll
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '1', conversation: { ...CONVERSATION, id: 'c2' } }))
    await opening
    expect(store.state.latestScroll).toBe(before)
    expect(store.state.jump?.messageId).toBe('m-old')
  })

  it("doesn't ask for a scroll when its conversation was deleted while the snapshot loaded", async () => {
    await start(snapshot({ watermark: '1', messages: { items: [message('m1')], has_more: false } }))
    bridge.control.list.push({ ...CONVERSATION, id: 'c2', title: 'Other', activity: { running: null, queued: [] } })
    bridge.control.holdCreate = true // the replacement conversation stays on its way
    const opening = store.openLatest('c2')
    await until(() => bridge.control.snapshots.length === 2)
    emit(event(5, 'conversation.deleted', { conversation_id: 'c1' }))
    emit(event(6, 'conversation.deleted', { conversation_id: 'c2' }))
    expect(store.state.activeId).toBeNull()
    const before = store.state.latestScroll
    bridge.control.snapshots[1]!.resolve(snapshot({ watermark: '1', conversation: { ...CONVERSATION, id: 'c2' } }))
    await opening
    expect(store.state.latestScroll).toBe(before)
  })
})
