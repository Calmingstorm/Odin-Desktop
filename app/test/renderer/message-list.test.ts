// The message list's scrolling, mounted with its real code and the real store over a fake bridge.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toRaw } from 'vue'
import type { Conversation, ConversationSnapshot, CoreEvent, Message, Result } from '../../src/shared/api'
import { flush, heldFrames, mount, type Host, type Mounted } from './component-host'

vi.mock('../../src/renderer/src/components/Message.vue', async () => {
  const { h } = await import('vue')
  return { default: { props: ['message'], render: (self: { message: Message }) => h('article', self.message.text) } }
})
vi.mock('../../src/renderer/src/components/ResumeBanner.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/ToolActivity.vue', async () => {
  const { h } = await import('vue')
  return { default: { props: ['entries', 'requestId'], render: (self: { entries: unknown[]; requestId: string }) =>
    h('aside', { 'data-request': self.requestId }, `${self.entries.length} receipts`) } }
})

type Store = typeof import('../../src/renderer/src/store')

function conversation(id: string): Conversation {
  return { id, title: id, rev: 1, parent_id: null, updated_at: '2026-10-05T00:00:00Z', unread: 0, archived: false }
}

function message(id: string): Message {
  return { id, role: 'assistant', text: id, created_at: '2026-10-05T00:00:00Z' }
}

function snapshot(id: string): Result<ConversationSnapshot> {
  return {
    ok: true,
    result: {
      conversation: conversation(id),
      watermark: '1',
      messages: { items: Array.from({ length: 50 }, (_, i) => message(`${id}-${i}`)), has_more: false },
      running: null,
      queued: [],
      recent: [],
      unresolved: [],
      tools: {},
      controls: []
    }
  }
}

let store: Store
let mounted: Mounted
let scroller: Host
let frames: ReturnType<typeof heldFrames>
/** Snapshots held back by conversation, until the test releases them. */
let held: Map<string, (answer: Result<ConversationSnapshot>) => void>
let deliverEvent: (event: CoreEvent) => void
let resize: () => void
let observed: unknown[]
let disconnected: ReturnType<typeof vi.fn>

const HIT_TOP = 150

beforeEach(async () => {
  vi.resetModules()
  observed = []
  disconnected = vi.fn()
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { resize = callback }
    observe(target: unknown) { observed.push(toRaw(target)) }
    disconnect = disconnected
  })
  held = new Map()
  const api = {
    getAppState: async () => ({ link: 'ready', coreInstanceId: 'core-1', noTray: false, unreceipted: 0 }),
    getSettings: async () => ({ ok: true, result: { autostart: false, notifications: { enabled: true } } }),
    listConversations: async () => ({
      ok: true,
      result: { items: ['c1', 'c2'].map((id) => ({ ...conversation(id), activity: { running: null, queued: [] } })), watermark: '1' }
    }),
    snapshotConversation: (params: { conversation_id: string }) =>
      params.conversation_id === 'c2' && held.has('hold-c2')
        ? new Promise((resolve) => held.set('c2', resolve))
        : Promise.resolve(snapshot(params.conversation_id)),
    messagesAround: async () => ({ ok: true, result: { items: [message('old')], has_before: true, has_after: true } }),
    markRead: async (params: { id: string }) => ({ ok: true, result: { conversation: conversation(params.id) } }),
    onEvent: (listener: (event: CoreEvent) => void) => { deliverEvent = listener; return () => undefined },
    onAppState: () => () => undefined,
    onReceipt: () => () => undefined,
    onReset: () => () => undefined,
    onOpenConversation: () => () => undefined
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: api, addEventListener: () => undefined }
  store = await import('../../src/renderer/src/store')
  // A search result's message sits HIT_TOP down the list: scrolling it into view puts it there.
  ;(globalThis as unknown as { document: unknown }).document = {
    visibilityState: 'hidden',
    hasFocus: () => false,
    addEventListener: () => undefined,
    activeElement: null,
    getElementById: () => ({ scrollIntoView: () => (scroller.scrollTop = HIT_TOP) })
  }
  frames = heldFrames()
  await store.init()
  const MessageList = (await import('../../src/renderer/src/components/MessageList.vue')).default
  mounted = mount(MessageList)
  scroller = mounted.root.find('section')!
  scroller.scrollHeight = 5000
  scroller.clientHeight = 500
  await flush()
})

afterEach(() => { mounted.unmount(); vi.unstubAllGlobals() })

/** Delivers frames until the scroll in progress, if any, is done. */
async function settle(): Promise<void> {
  for (let i = 0; i < 70 && frames.pending(); i++) await frames.deliver()
  expect(frames.pending()).toBe(0)
}

async function searchHit(conversationId: string): Promise<void> {
  await store.jumpTo({ conversation_id: conversationId, message_id: 'old', role: 'assistant', snippet: '', created_at: '' })
  await flush()
}

describe('scrolling to the latest messages', () => {
  it('keeps reader keyboard navigation unpinned while unrelated keys do not cancel following', async () => {
    await settle()
    scroller.fire('keydown', { key: 'Shift' })
    scroller.scrollHeight = 8000; resize(); await flush(); await settle()
    expect(scroller.scrollTop).toBe(7500)
    scroller.fire('keydown', { key: 'PageUp' })
    scroller.scrollTop = 2000; scroller.fire('scrollPassive')
    scroller.scrollHeight = 10000; resize(); await flush(); await settle()
    expect(scroller.scrollTop).toBe(2000)
  })

  it.each(['wheelPassive', 'pointerdown'])('keeps following after %s at the bottom without a scroll event', async (input) => {
    await settle()
    scroller.fire(input, { deltaY: 120 })
    // A downward wheel at the boundary or a Copy click produces no scroll event.
    scroller.scrollHeight = 8000
    resize()
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(7500)
  })

  it('preserves the reading anchor when older messages load and retains the exhausted-history control', async () => {
    await settle()
    let land!: (answer: Result<{ items: Message[]; has_more: boolean }>) => void
    const listMessages = vi.fn(() => new Promise<Result<{ items: Message[]; has_more: boolean }>>((resolve) => { land = resolve }))
    Object.assign(window.odin, { listMessages })
    store.state.views.c1!.hasMore = true; await flush()
    scroller.fire('pointerdown'); scroller.scrollTop = 900; scroller.fire('scrollPassive')
    const button = mounted.root.named('Load older messages')
    const loading = button.fire('click'); await flush()
    expect(mounted.root.named('Loading… older messages').props['aria-disabled']).toBe(true)
    button.fire('click'); await flush()
    expect(listMessages).toHaveBeenCalledExactlyOnceWith({ conversation_id: 'c1', before: 'c1-0', limit: 100 })
    scroller.scrollHeight = 6500
    land({ ok: true, result: { items: [message('earlier')], has_more: false } })
    await loading; await flush(); await settle()
    expect(scroller.scrollTop).toBe(2400)
    expect(store.state.views.c1!.messages[0]!.id).toBe('earlier')
    const exhausted = mounted.root.named('All older messages loaded')
    expect(exhausted.props['aria-disabled']).toBe(true)
    exhausted.fire('click'); await flush()
    expect(listMessages).toHaveBeenCalledTimes(1)
  })

  it('shows local unknown receipts, detailed active steers, unresolved effects and queued follow-ups', async () => {
    const view = store.state.views.c1!
    view.running = { request_id: 'active', generation: 1, started_at: '2026-10-05T00:00:00Z' }
    view.queued = [{ request_id: 'follow-up', generation: 1, message_id: 'follow-up-message' }]
    view.unresolved = [{ request_id: 'uncertain', generation: 1, at: '2026-10-05T00:00:00Z', outcome: 'failed', unknown_effects: 2 }]
    store.state.pending.push({ client_submission_id: 'pending', conversation_id: 'c1', text: 'Uncertain submission', status: 'unknown' })
    for (const status of ['consumed', 'queued', 'unknown'] as const) store.state.controls.push({ control_command_id: status, kind: 'steer', conversation_id: 'c1', request_id: 'active', generation: 1, status, text: `Steer ${status}`, detail: 'Receipt detail' })
    store.state.controls.push({ control_command_id: 'active-stop', kind: 'stop', conversation_id: 'c1', request_id: 'active', generation: 1, status: 'unknown' })
    await flush()
    expect(mounted.root.textContent()).toContain('1 follow-up queued')
    expect(mounted.root.textContent()).toContain('Odin has read it: Receipt detail')
    expect(mounted.root.textContent()).toContain('waiting for Odin to read it: Receipt detail')
    expect(mounted.root.textContent()).toContain('outcome unknown; it will not be sent again: Receipt detail')
    expect(mounted.root.textContent()).toContain('2 actions with an unknown outcome. They will not be repeated.')
    expect(mounted.root.findAll((node) => node.props['aria-label'] === 'Control receipts')[0]!.textContent()).toContain('Stopoutcome unknown; it will not be sent again')
    await settle()
  })

  it('observes inner content and follows late image/file layout after initial scrolling settles', async () => {
    await settle()
    expect(observed).toContain(scroller)
    expect(observed).toContain(mounted.root.findAll((n) => n.props.class === 'message-content')[0])
    for (const growth of [8000, 12000]) {
      scroller.scrollHeight = growth
      resize()
      await flush()
      await settle()
      expect(scroller.scrollTop).toBe(growth - 500)
      scroller.fire('scrollPassive')
    }
  })

  it('never follows late growth after reader scroll-up, even during an active end scroll', async () => {
    await settle()
    await store.openLatest('c1')
    await flush()
    scroller.fire('wheelPassive', { deltaY: -100 })
    scroller.scrollTop = 1000
    scroller.fire('scrollPassive')
    const before = scroller.scrolls.length
    scroller.scrollHeight = 12000
    resize()
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(1000)
    expect(scroller.scrolls.length).toBe(before)
  })

  it('pins again when the reader scrolls back to the end', async () => {
    await settle()
    scroller.fire('wheelPassive', { deltaY: -100 })
    scroller.scrollTop = 1000
    scroller.fire('scrollPassive')
    scroller.scrollTop = 4500
    scroller.fire('scrollPassive')
    scroller.scrollHeight = 8000
    resize()
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(7500)
  })

  it('does not repin a highlighted search result when images grow', async () => {
    await settle()
    await searchHit('c1')
    await settle()
    scroller.scrollHeight = 9000
    resize()
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(HIT_TOP)
  })

  it('preserves follow intent when End is pressed at the already settled bottom', async () => {
    await settle()
    scroller.fire('keydown', { key: 'End', ctrlKey: true })
    await flush()
    await settle()
    scroller.scrollHeight = 8000
    resize()
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(7500)
  })

  it('ignores browser layout scroll events while pinned, before a content observer fires', async () => {
    await settle()
    scroller.scrollHeight = 8000
    scroller.scrollTop = 4600
    scroller.fire('scrollPassive')
    resize()
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(7500)
  })

  it('retains tool-publication authors through history snapshots and committed frames', async () => {
    const artifact = { ref: 'image', name: 'Image', mime: 'image/png', size: 10, kind: 'image' as const, available: true }
    const first: Message = { ...message('authored-history'), role: 'notice', author: 'odin', request_id: 'r1', artifacts: [artifact] }
    const answer = snapshot('c2')
    if (!answer.ok) throw new Error('fixture snapshot must succeed')
    answer.result.messages.items = [first]
    held.set('hold-c2', () => undefined)
    const opening = store.select('c2')
    await flush()
    held.get('c2')!(answer)
    await opening
    await flush()
    expect(store.state.views.c2!.messages[0]).toEqual(first)
    const second: Message = { ...first, id: 'authored-live', request_id: 'r2' }
    deliverEvent({ seq: 3, cursor: '3', type: 'message.committed', entity: { kind: 'message', id: second.id },
      at: second.created_at, payload: { conversation_id: 'c2', message: second } })
    await flush()
    expect(store.state.views.c2!.messages.at(-1)).toEqual(second)
    await settle()
  })

  it('starts following the new conversation after leaving a scrolled-up conversation', async () => {
    await settle()
    scroller.scrollTop = 1000
    scroller.fire('scrollPassive')
    await store.select('c2')
    await flush()
    await settle()
    scroller.scrollHeight = 9000
    resize()
    await flush()
    await settle()
    expect(store.state.activeId).toBe('c2')
    expect(scroller.scrollTop).toBe(8500)
  })

  it('keeps following with history focused after the reader returns to the end', async () => {
    await settle()
    const doc = document as unknown as { activeElement: unknown }
    doc.activeElement = scroller
    Object.assign(scroller, { contains: (element: unknown) => element === scroller })
    scroller.fire('pointerdown')
    scroller.scrollTop = 4400
    scroller.fire('scrollPassive')
    scroller.scrollTop = 4500
    scroller.fire('scrollPassive')
    scroller.scrollHeight = 8000
    resize()
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(7500)
  })

  it('shows Stop and Steer only for the live request and generation, then removes both when it ends', async () => {
    const view = store.state.views.c1!
    view.running = { request_id: 'ended', generation: 1, started_at: '2026-10-05T00:00:00Z' }
    view.controls.stop = { control_command_id: 'stop', kind: 'stop', request_id: 'ended', generation: 1, status: 'confirmed' }
    view.controls.steer = { control_command_id: 'steer', kind: 'steer', request_id: 'ended', generation: 1, status: 'consumed' }
    store.state.controls.push({ control_command_id: 'wrong-generation', kind: 'stop', conversation_id: 'c1', request_id: 'ended', generation: 2, status: 'unknown' })
    await flush()
    expect(mounted.root.textContent()).toContain('confirmed by Odin')
    expect(mounted.root.textContent()).toContain('Odin has read it')
    expect(mounted.root.textContent()).not.toContain('outcome unknown; it will not be sent again')
    view.running = null
    await flush()
    expect(mounted.root.textContent()).not.toContain('confirmed by Odin')
    expect(mounted.root.textContent()).not.toContain('Odin has read it')
    // Local command history is retained for late receipts/idempotency, but not displayed as chat history.
    expect(store.state.controls).toHaveLength(1)
    await settle()
  })

  it('does not resurrect local controls when a fresh snapshot has no running task or controls', async () => {
    store.state.controls.push({ control_command_id: 'local-stop', kind: 'stop', conversation_id: 'c1', request_id: 'ended', generation: 1, status: 'confirmed' },
      { control_command_id: 'local-steer', kind: 'steer', conversation_id: 'c1', request_id: 'ended', generation: 1, status: 'consumed' })
    await store.openLatest('c1'); await flush()
    expect(store.state.views.c1!.controls).toEqual({})
    expect(mounted.root.textContent()).not.toContain('confirmed by Odin')
    expect(mounted.root.textContent()).not.toContain('Odin has read it')
    await settle()
  })

  it('keeps a bare stopped outcome until that request gets an assistant reply, not an unrelated reply or notice', async () => {
    const view = store.state.views.c1!
    view.recent.push({ request_id: 'stopped', generation: 1, outcome: 'cancelled', unknown_effects: 0, at: '2026-10-05T00:00:00Z' })
    view.messages.push({ ...message('notice'), role: 'notice', request_id: 'stopped' })
    await flush()
    expect(mounted.root.textContent()).toContain('The task was stopped.')
    view.messages.push({ ...message('reply'), request_id: 'stopped', text: 'Task stopped by user. The current step completed.' })
    await flush()
    expect(mounted.root.textContent()).not.toContain('The task was stopped.')
    expect(mounted.root.textContent()).toContain('Task stopped by user.')
    await settle()
  })

  it('keeps unresolved effects visible while dismissing and waiting for a late confirmation', async () => {
    const view = store.state.views.c1!
    view.unresolved = [{ request_id: 'unknown', generation: 1, outcome: 'failed', unknown_effects: 1, at: '2026-10-05T00:00:00Z' }]
    let answer!: (value: unknown) => void
    const acknowledgeEffects = vi.fn(() => new Promise((resolve) => { answer = resolve }))
    Object.assign(window.odin, { acknowledgeEffects })
    await flush()
    expect(mounted.root.textContent()).toContain('1 action with an unknown outcome. It will not be repeated.')
    const pending = mounted.root.button('Dismiss').fire('click')
    await flush()
    expect(mounted.root.button('Dismissing…').props.disabled).toBe(true)
    expect(view.unresolved).toHaveLength(1)
    answer({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown' } })
    await pending; await flush()
    expect(mounted.root.button('Waiting for confirmation').props.disabled).toBe(true)
    expect(view.unresolved).toHaveLength(1)
    expect(acknowledgeEffects).toHaveBeenCalledTimes(1)
    store.applyEvent({ seq: 2, cursor: '2', type: 'effects.resolved', entity: { kind: 'request', id: 'unknown' },
      at: '2026-10-05T00:00:00Z', payload: { conversation_id: 'c1', request_id: 'unknown', generation: 1, remaining: 0 } })
    await flush()
    expect(mounted.root.textContent()).not.toContain('1 action with an unknown outcome')
  })
  it('ticks the stopping working line from tool.started and falls back when the tool settles', async () => {
    vi.useFakeTimers()
    try {
      vi.setSystemTime(new Date('2026-10-05T00:01:10Z'))
      const view = store.state.views.c1!
      view.running = { request_id: 'stopping-task', generation: 3, started_at: '2026-10-04T00:00:00Z' }
      store.state.controls.push({ control_command_id: 'stop', conversation_id: 'c1', kind: 'stop', request_id: 'stopping-task', generation: 3, status: 'requested' })
      store.applyEvent({ seq: 2, cursor: '2', type: 'tool.started', entity: { kind: 'request', id: 'stopping-task' }, at: '2026-10-05T00:00:00Z',
        payload: { conversation_id: 'c1', request_id: 'stopping-task', generation: 3, invocation_id: 'call', tool: 'run_command', summary: 'run_command' } })
      await flush()
      expect(mounted.root.textContent()).toContain('Stopping… waiting for run_command to finish (1:10)')
      await vi.advanceTimersByTimeAsync(1000); await flush()
      expect(mounted.root.textContent()).toContain('Stopping… waiting for run_command to finish (1:11)')
      store.applyEvent({ seq: 3, cursor: '3', type: 'tool.settled', entity: { kind: 'request', id: 'stopping-task' }, at: '2026-10-05T00:01:11Z',
        payload: { conversation_id: 'c1', request_id: 'stopping-task', generation: 3, invocation_id: 'call', outcome: 'success' } })
      await flush()
      const line = mounted.root.findAll((node) => node.props.class === 'working-line')[0]!
      expect(line.textContent()).toBe('Stopping…')
      expect(vi.getTimerCount()).toBe(0)
    } finally { vi.useRealTimers() }
    await settle()
  })

  it('keeps tool receipts after failure without inventing an assistant reply', async () => {
    const view = store.state.views.c1!
    view.running = { request_id: 'failed-task', generation: 1, started_at: '2026-10-05T00:00:00Z' }
    view.tools['failed-task'] = [{ invocation_id: 'actual-call', tool: 'run_command', summary: 'run_command', outcome: 'failure' }]
    await flush()
    expect(mounted.root.findAll((h) => h.tag === 'aside' && h.props['data-request'] === 'failed-task')).toHaveLength(1)
    store.applyEvent({ seq: 2, cursor: '2', type: 'request.failed', entity: { kind: 'request', id: 'failed-task' },
      at: '2026-10-05T00:00:00Z', payload: { conversation_id: 'c1', request_id: 'failed-task', generation: 1, unknown_effects: 0 } })
    await flush()
    expect(mounted.root.findAll((h) => h.tag === 'aside' && h.props['data-request'] === 'failed-task')).toHaveLength(1)
    expect(view.messages.some((m) => m.request_id === 'failed-task' && m.role === 'assistant')).toBe(false)
    expect(mounted.root.textContent()).toContain('The task failed.')
    await settle()
  })
  it('follows the end while it moves, and stops once it holds still', async () => {
    await settle()
    await store.openLatest('c1')
    await flush()
    for (const height of [8000, 11000, 15000]) {
      scroller.scrollHeight = height
      await frames.deliver()
    }
    await settle()
    expect(scroller.scrollTop).toBe(14500)
  })

  it('goes back to the end from a search window', async () => {
    await settle()
    await searchHit('c1')
    expect(scroller.scrollTop).toBe(HIT_TOP)
    store.backToLatest()
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(4500)
  })
})

describe('review round 4: a newer navigation owns the view', () => {
  it('keeps a search result in view when it lands during a scroll to the end (11.R4.1)', async () => {
    await settle()
    await store.openLatest('c1')
    await flush()
    expect(frames.pending()).toBe(1) // the scroll to the end waits for its next frame
    await searchHit('c1')
    expect(store.state.highlightId).toBe('old')
    expect(scroller.scrollTop).toBe(HIT_TOP)
    await settle()
    expect(scroller.scrollTop).toBe(HIT_TOP)
  })

  it("doesn't scroll a conversation the user moved on to when a late notification lands (11.R4.2)", async () => {
    await settle()
    held.set('hold-c2', () => undefined)
    const opening = store.openLatest('c2')
    await flush()
    await settle()
    await store.select('c1')
    await flush()
    await settle()
    await searchHit('c1')
    expect(scroller.scrollTop).toBe(HIT_TOP)
    held.get('c2')!(snapshot('c2'))
    await opening
    await flush()
    await settle()
    expect(store.state.activeId).toBe('c1')
    expect(store.state.highlightId).toBe('old')
    expect(scroller.scrollTop).toBe(HIT_TOP)
  })

  it('stops scrolling when the list goes away', async () => {
    await settle()
    await store.openLatest('c1')
    await flush()
    mounted.unmount()
    expect(disconnected).toHaveBeenCalledOnce()
    const before = scroller.scrolls.length
    scroller.scrollHeight = 9000
    await settle()
    expect(scroller.scrolls.length).toBe(before)
    mounted = mount({ render: () => null }) // afterEach unmounts whatever is mounted
  })
})

describe('accessibility: stable, quiet history', () => {
  it('does not render unpublished assistant drafts; only message.committed enters the history', async () => {
    const rejected = 'REJECTED-ASSISTANT-DRAFT-SECRET'
    const base = { entity: { kind: 'conversation', id: 'c1' }, at: '2026-10-05T00:00:00Z' }
    deliverEvent({ ...base, seq: 2, cursor: '2', type: 'reply.draft', payload: { conversation_id: 'c1', text: rejected } })
    await flush()
    expect(mounted.root.textContent()).not.toContain(rejected)
    const committed = { ...message('accepted'), text: 'Accepted finished reply.' }
    deliverEvent({ ...base, seq: 3, cursor: '3', type: 'message.committed', payload: { conversation_id: 'c1', message: committed } })
    await flush()
    expect(mounted.root.textContent()).toContain(committed.text)
    expect(mounted.root.textContent()).not.toContain(rejected)
  })
  it('does not pull a reader away from older messages when committed history grows', async () => {
    await settle()
    scroller.scrollTop = 1000
    const before = scroller.scrolls.length
    store.state.views.c1!.messages.push(message('new-committed'))
    await flush()
    await settle()
    expect(scroller.scrollTop).toBe(1000)
    expect(scroller.scrolls.length).toBe(before)
  })

  it('keeps the history region and committed messages mounted during recovery', async () => {
    await settle()
    const articles = mounted.root.findAll((h) => h.tag === 'article')
    store.state.loaded = false
    store.state.views.c1!.status = 'loading'
    await flush()
    expect(mounted.root.find('section')).toBe(scroller)
    expect(scroller.props.id).toBe('conversation-history')
    expect(scroller.props.tabindex).toBe('0')
    expect(scroller.props['aria-label']).toBe('Conversation history')
    expect(mounted.root.findAll((h) => h.tag === 'article')).toEqual(articles)
    expect(mounted.root.textContent()).toContain('displayed history remains available')
  })

  it('has no live transcript region and announces only structural state', async () => {
    expect(scroller.props['aria-live']).toBeUndefined()
    const status = mounted.root.findAll((h) => h.props.class === 'chat-announcement')[0]!
    store.state.views.c1!.running = { request_id: 'r', generation: 1, started_at: '2026-10-05T00:00:00Z' }
    await flush()
    expect(status.textContent()).toBe('Odin is working.')
    store.state.views.c1!.messages.push({ ...message('committed'), text: 'COMMITTED-REPLY' })
    await flush()
    expect(status.textContent()).not.toContain('COMMITTED-REPLY')
  })
})

describe('a jumped-to message taller than the view', () => {
  it('opens at its start, where reading begins; a shorter one stays centred', async () => {
    await settle()
    const doc = (globalThis as unknown as { document: { getElementById: unknown } }).document
    const original = doc.getElementById
    const placements: unknown[] = []
    try {
      for (const offsetHeight of [2000, 120]) {
        doc.getElementById = () => ({ offsetHeight, scrollIntoView: (options: unknown) => placements.push(options) })
        store.state.highlightId = null
        await flush()
        await searchHit('c1')
        await settle()
      }
    } finally {
      doc.getElementById = original
    }
    // The view is 500 px high: 2,000 px opens at the start, 120 px is centred.
    expect(placements).toEqual([{ block: 'start' }, { block: 'center' }])
  })
})

describe('a jumped-to message that has never rendered here (review #87)', () => {
  /** A target known only by its 120 px estimate until it renders at 3,000 px. */
  function unrendered(placements: unknown[]) {
    const target = { isConnected: true, height: 120, get offsetHeight() { return this.height },
      scrollIntoView: (options: unknown) => placements.push(options) }
    return target
  }

  it('moves to its start once it renders taller than the view', async () => {
    await settle()
    const doc = (globalThis as unknown as { document: { getElementById: unknown } }).document
    const original = doc.getElementById
    const placements: unknown[] = []
    const target = unrendered(placements)
    try {
      doc.getElementById = () => target
      await searchHit('c1')
      expect(placements).toEqual([{ block: 'center' }]) // only the estimate is known yet
      target.height = 3000 // brought into view, it renders at its real size
      await settle()
    } finally {
      doc.getElementById = original
    }
    expect(placements).toEqual([{ block: 'center' }, { block: 'start' }])
  })

  it('does not mistake programmatic scroll events between highlight frames for reader input', async () => {
    await settle()
    const doc = document as unknown as { getElementById: unknown }
    const original = doc.getElementById
    const placements: unknown[] = []
    const target = unrendered(placements)
    try {
      doc.getElementById = () => target
      await searchHit('c1')
      expect(placements).toEqual([{ block: 'center' }])
      // Browser scrollIntoView/layout emits scroll, without a wheel, key or pointer action.
      scroller.fire('scrollPassive')
      target.height = 3000
      await settle()
    } finally { doc.getElementById = original }
    expect(placements).toEqual([{ block: 'center' }, { block: 'start' }])
  })

  it('keeps a short one centred while the messages above it render', async () => {
    await settle()
    const doc = (globalThis as unknown as { document: { getElementById: unknown } }).document
    const original = doc.getElementById
    const placements: unknown[] = []
    // Centring puts it 220 px down the 500 px view.
    const target = { isConnected: true, offsetHeight: 60, top: 0,
      getBoundingClientRect() { return { top: this.top } },
      scrollIntoView(options: unknown) { placements.push(options); this.top = 220 } }
    Object.assign(scroller, { getBoundingClientRect: () => ({ top: 0 }) })
    try {
      doc.getElementById = () => target
      await searchHit('c1')
      expect(placements).toEqual([{ block: 'center' }])
      target.top = 40 // the estimated blocks above it rendered at their real, smaller heights
      await settle()
    } finally {
      doc.getElementById = original
    }
    expect(placements).toEqual([{ block: 'center' }, { block: 'center' }])
    expect(target.top).toBe(220)
  })

  it('leaves the view alone when the reader scrolled before it rendered', async () => {
    await settle()
    const doc = (globalThis as unknown as { document: { getElementById: unknown } }).document
    const original = doc.getElementById
    const placements: unknown[] = []
    const target = unrendered(placements)
    try {
      doc.getElementById = () => target
      await searchHit('c1')
      scroller.fire('pointerdown') // the reader took the view
      target.height = 3000
      await settle()
    } finally {
      doc.getElementById = original
    }
    expect(placements).toEqual([{ block: 'center' }])
  })
})

describe('day dividers (1.0.5 L3)', () => {
  it('heads each day\'s first message, so an evening and the next morning read as two days', async () => {
    const odin = (globalThis as unknown as { window: { odin: Record<string, unknown> } }).window.odin
    const at = (id: string, created_at: string): Message => ({ id, role: 'assistant', text: id, created_at })
    const base = (snapshot('c2') as { result: ConversationSnapshot }).result
    odin.snapshotConversation = async () => ({ ok: true, result: { ...base, messages: { items: [
      at('evening', '2026-10-08T22:20:00'), at('late', '2026-10-08T23:59:00'), at('morning', '2026-10-09T07:39:00')
    ], has_more: false } } })
    await store.select('c2'); await flush()
    const nodes = scroller.findAll((node) => node.tag === 'article' || node.props.class === 'day-divider')
    expect(nodes.map((node) => (node.tag === 'article' ? node.textContent() : 'day'))).toEqual(
      ['day', 'evening', 'late', 'day', 'morning'])
  })
})
