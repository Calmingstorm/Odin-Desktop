// The message list's scrolling, mounted with its real code and the real store over a fake bridge.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

const HIT_TOP = 150

beforeEach(async () => {
  vi.resetModules()
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

afterEach(() => mounted.unmount())

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
  it('keeps confirmed Stop and consumed Steer receipts after their run ends', async () => {
    const view = store.state.views.c1!
    view.controls.stop = { control_command_id: 'stop', kind: 'stop', request_id: 'ended', generation: 1, status: 'confirmed' }
    view.controls.steer = { control_command_id: 'steer', kind: 'steer', request_id: 'ended', generation: 1, status: 'consumed' }
    await flush()
    expect(mounted.root.textContent()).toContain('confirmed by Odin')
    expect(mounted.root.textContent()).toContain('Odin has read it')
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
