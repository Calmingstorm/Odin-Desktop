// Actual MessageList/ResumeBanner wiring over the store. These prove rendering, not native focus or AT-SPI.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Conversation, ConversationSnapshot, CoreEvent, Message, Result } from '../../src/shared/api'
import { flush, heldFrames, mount, type Mounted } from './component-host'

vi.mock('../../src/renderer/src/components/Message.vue', async () => {
  const { h } = await import('vue')
  return { default: { props: ['message'], render: (self: { message: Message }) =>
    h('article', { 'data-role': self.message.role }, self.message.text) } }
})
vi.mock('../../src/renderer/src/components/ToolActivity.vue', () => ({ default: { render: () => null } }))

type Store = typeof import('../../src/renderer/src/store')
const conversation: Conversation = { id: 'c1', title: 'Resume chat', rev: 1, parent_id: null,
  updated_at: '2026-10-06T00:00:00Z', unread: 0, archived: false }
const original: Message = { id: 'm-original', role: 'user', text: 'Complete the original request',
  created_at: conversation.updated_at, request_id: 'r-original', client_submission_id: 's-original' }
const suspended = { request_id: 'r-original', generation: 1, outcome: 'suspended' as const,
  unknown_effects: 0, at: conversation.updated_at }
const accepted = { ok: true as const, result: { disposition: 'accepted', request_id: 'r-original', message_id: 'm-original' } }
const unknown = { ok: false as const, error: { code: 'no_receipt', message: 'No receipt yet', disposition: 'outcome_unknown' as const } }

let store: Store
let mounted: Mounted
let submit: ReturnType<typeof vi.fn>

function event(seq: number, type: string, payload: Record<string, unknown>): CoreEvent {
  return { seq, cursor: String(seq), type, entity: { kind: 'request', id: 'r-original' },
    at: conversation.updated_at, payload: { conversation_id: 'c1', ...payload } }
}

beforeEach(async () => {
  vi.resetModules()
  delete (globalThis as unknown as { document?: unknown }).document
  submit = vi.fn(async (_params: Record<string, unknown>) => unknown)
  const snapshot: ConversationSnapshot = { conversation, watermark: '1', messages: { items: [original], has_more: false },
    running: null, queued: [], recent: [suspended], unresolved: [], tools: {}, controls: [] }
  const api = {
    submit,
    getAppState: async () => ({ link: 'ready', coreInstanceId: 'core-1', noTray: false, unreceipted: 0 }),
    getSettings: async () => ({ ok: true, result: { autostart: false, notifications: { enabled: true } } }),
    listConversations: async () => ({ ok: true, result: { items: [conversation], watermark: '1' } }),
    snapshotConversation: async (): Promise<Result<ConversationSnapshot>> => ({ ok: true, result: snapshot }),
    onEvent: () => () => undefined, onAppState: () => () => undefined,
    onReceipt: () => () => undefined, onReset: () => () => undefined, onOpenConversation: () => () => undefined
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: api, addEventListener: () => undefined }
  store = await import('../../src/renderer/src/store')
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null, visibilityState: 'hidden',
    hasFocus: () => false, addEventListener: () => undefined, getElementById: () => null }
  heldFrames()
  await store.init()
  mounted = mount((await import('../../src/renderer/src/components/MessageList.vue')).default)
  await flush()
})

afterEach(() => mounted.unmount())

describe('typed resume renderer', () => {
  it('explains both typed triggers while preserving the accessible resume button and status region', () => {
    expect(mounted.root.textContent()).toContain('Typing “continue” or “resume” also resumes preserved work.')
    const button = mounted.root.button('Resume')
    expect(button.props['aria-label']).toBe('Resume the last task')
    expect(button.props['aria-disabled']).toBe(false)
    expect(mounted.root.findAll((node) => node.props.role === 'status' && node.props['aria-atomic'] === 'true').length).toBeGreaterThan(0)
    expect(mounted.root.textContent()).not.toContain('ordinary message in this core')
  })

  it.each(['continue', 'resume'])('removes the optimistic %s bubble after lost-ACK admission and shows only the original request', async (text) => {
    expect(await store.send(text, 'queue')).toBe(true)
    await flush()
    expect(mounted.root.findAll((node) => node.tag === 'article' && node.props.class === 'msg user pending')).toHaveLength(1)
    const id = String(submit.mock.calls[0]![0].client_submission_id)
    store.applyReceipt({ id, settled: accepted })
    store.applyEvent(event(2, 'request.started', { request_id: 'r-original', generation: 2 }))
    await flush()
    expect(mounted.root.findAll((node) => node.tag === 'article' && node.props.class === 'msg user pending')).toEqual([])
    expect(mounted.root.findAll((node) => node.props['data-role'] === 'user')).toHaveLength(1)
    expect(mounted.root.textContent()).toContain(original.text)
    expect(mounted.root.textContent()).toContain('Odin is working…')
    expect(mounted.root.textContent()).not.toContain('Typing “continue”')
    expect(store.state.views.c1!.running).toMatchObject({ request_id: 'r-original', generation: 2 })
    expect(submit).toHaveBeenCalledTimes(1)
  })

  it('renders the actual engine failure notice instead of a stuck optimistic bubble or fabricated assistant reply', async () => {
    await store.send('continue', 'queue')
    await flush()
    const id = String(submit.mock.calls[0]![0].client_submission_id)
    const committed: Message = { id: 'm-notice', role: 'notice', text: 'The preserved checkpoint expired. Nothing was resumed.',
      created_at: conversation.updated_at, request_id: 'r-original', client_submission_id: id }
    store.applyEvent(event(2, 'message.committed', { message: committed }))
    await flush()
    expect(store.state.pending).toEqual([])
    expect(mounted.root.findAll((node) => node.tag === 'article' && node.props.class === 'msg user pending')).toEqual([])
    expect(mounted.root.findAll((node) => node.props['data-role'] === 'notice').map((node) => node.textContent())).toEqual([committed.text])
    expect(mounted.root.findAll((node) => node.props['data-role'] === 'assistant')).toEqual([])
    expect(mounted.root.findAll((node) => node.props['data-role'] === 'user')).toHaveLength(1)
    expect(store.state.views.c1!.running).toBeNull()
    expect(submit).toHaveBeenCalledTimes(1)
  })

  it('keeps resume unknown/failure feedback in accessible status and alert regions', async () => {
    store.state.resumes['r-original:1'] = { status: 'unknown', commandId: 'control-original' }
    await flush()
    expect(mounted.root.button('Resume').props['aria-disabled']).toBe(true)
    expect(mounted.root.findAll((node) => node.props.role === 'status').some((node) => node.textContent().includes('Resume outcome unknown'))).toBe(true)
    store.state.resumes['r-original:1'] = { status: 'failed', reason: 'Resume rejected by Odin.' }
    await flush()
    expect(mounted.root.findAll((node) => node.props.role === 'alert').map((node) => node.textContent())).toEqual(['Resume rejected by Odin.'])
    expect(mounted.root.button('Resume').props['aria-disabled']).toBe(false)
  })
})
