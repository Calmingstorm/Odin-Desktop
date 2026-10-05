// The message list's scrolling, mounted with its real code and the real store over a fake bridge.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Conversation, ConversationSnapshot, Message, Result } from '../../src/shared/api'
import { flush, heldFrames, mount, type Host, type Mounted } from './component-host'

vi.mock('../../src/renderer/src/components/Message.vue', async () => {
  const { h } = await import('vue')
  return { default: { props: ['message'], render: (self: { message: Message }) => h('article', self.message.text) } }
})
vi.mock('../../src/renderer/src/components/ResumeBanner.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/ToolActivity.vue', () => ({ default: { render: () => null } }))

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
    onEvent: () => () => undefined,
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
