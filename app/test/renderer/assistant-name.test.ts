// The chat names the assistant after the active personality; the app's own name stays Odin.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AppState, Conversation, ConversationSnapshot, CoreStatus, Personality, Result } from '../../src/shared/api'
import { flush, heldFrames, Host, mount, type Mounted } from './component-host'

// Message.vue's Markdown sanitizer needs a real DOM; the label under test doesn't.
vi.mock('../../src/renderer/src/markdown', () => ({ renderMarkdown: (text: string) => `<p>${text}</p>`, plainTextOf: (text: string) => text }))

const core: CoreStatus = { phase: 'ready', core_instance_id: 'real-core', version: 'test', capabilities: ['status.get', 'events.subscribe'] }
const app: AppState = { link: 'ready', coreInstanceId: core.core_instance_id, noTray: false, unreceipted: 0 }
const conversation: Conversation = { id: 'chat', title: 'Chat', rev: 1, parent_id: null, updated_at: '', unread: 0, archived: false }
const snapshot: ConversationSnapshot = {
  conversation, watermark: '0', messages: { items: [], has_more: false }, running: null, queued: [], recent: [], unresolved: [], tools: {}, controls: []
}

function personality(preset: string, extra: Partial<Personality> = {}): Personality {
  return {
    preset, custom_name: '', custom_identity: '', custom_voice: '',
    presets: {
      odin: { name: 'Odin, the All-Father', identity: 'i', voice: 'v' },
      professional: { name: 'Mimir', identity: 'i', voice: 'v' },
      'clippy-astra': { name: 'Clippy', identity: 'i', voice: 'v' }
    },
    builtin_presets: ['odin', 'professional'], user_presets: ['clippy-astra'], ...extra
  }
}

let mounted: Mounted[]
let api: Record<string, ReturnType<typeof vi.fn>>

beforeEach(() => {
  vi.resetModules()
  mounted = []
  api = {
    getAppState: vi.fn(async () => app),
    getSettings: vi.fn(async () => ({ ok: true, result: { autostart: false, notifications: null } })),
    listConversations: vi.fn(async () => ({ ok: true, result: { items: [conversation], watermark: '0' } })),
    snapshotConversation: vi.fn(async (): Promise<Result<ConversationSnapshot>> => ({ ok: true, result: snapshot })),
    status: vi.fn(async () => ({ ok: true, result: core })),
    getDraft: vi.fn(async () => ({ ok: true, result: { text: '' } })),
    personalityGet: vi.fn(async () => ({ ok: true, result: personality('clippy-astra') })),
    onEvent: vi.fn(), onAppState: vi.fn(), onReceipt: vi.fn(), onReset: vi.fn(), onOpenConversation: vi.fn()
  }
  vi.stubGlobal('window', { odin: api, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  vi.stubGlobal('document', { addEventListener: vi.fn(), visibilityState: 'hidden', hasFocus: () => false, activeElement: null })
  vi.stubGlobal('Document', class {})
  vi.stubGlobal('ShadowRoot', class {})
  Object.assign(Host.prototype, {
    addEventListener(this: Host, event: string, listener: unknown) { this.props[`on${event[0]!.toUpperCase()}${event.slice(1)}`] = listener },
    removeEventListener() {}, focus() {}, getRootNode() { return document }
  })
  heldFrames()
})

afterEach(() => {
  for (const view of mounted) view.unmount()
  vi.unstubAllGlobals()
})

describe('assistantName', () => {
  it("uses the personality's name up to its first comma, and Odin otherwise", async () => {
    const { assistantName } = await import('../../src/renderer/src/assistant-name')
    expect(assistantName(null)).toBe('Odin')
    expect(assistantName(personality('odin'))).toBe('Odin')
    expect(assistantName(personality('professional'))).toBe('Mimir')
    expect(assistantName(personality('clippy-astra'))).toBe('Clippy')
    expect(assistantName(personality('custom', { custom_name: 'Hal' }))).toBe('Hal')
    expect(assistantName(personality('custom'))).toBe('Odin')
    expect(assistantName(personality('gone'))).toBe('Odin')
  })
})

describe('the chat with a saved personality active', () => {
  it('names the assistant in the empty chat, the composer and its replies', async () => {
    const store = await import('../../src/renderer/src/store')
    await store.init()
    const view = async (name: string, props?: Record<string, unknown>) => {
      const component = await import(`../../src/renderer/src/components/${name}.vue`)
      const screen = mount(component.default, props)
      mounted.push(screen)
      await flush()
      return screen
    }
    const list = await view('MessageList')
    expect(api.personalityGet).toHaveBeenCalled()
    expect(list.root.textContent()).toContain('Ask Clippy anything.')
    const composer = await view('Composer')
    expect(composer.root.find('textarea')!.props.placeholder).toBe('Message Clippy… (/ for commands)')
    const reply = await view('Message', {
      message: { id: 'm1', role: 'assistant', text: 'It looks like you are writing a test.', created_at: '2026-10-08T00:00:00Z' },
      conversationId: 'chat'
    })
    expect(reply.root.textContent()).toContain('Clippy')
    expect(reply.root.textContent()).not.toContain('Odin')
  })

  it('keeps the default name when the personality cannot be read', async () => {
    api.personalityGet!.mockRejectedValueOnce(new Error('no bridge method'))
    const store = await import('../../src/renderer/src/store')
    await store.init()
    const component = await import('../../src/renderer/src/components/MessageList.vue')
    const list = mount(component.default)
    mounted.push(list)
    await flush()
    expect(list.root.textContent()).toContain('Ask Odin anything.')
  })
})

describe('the chat name follows the connected core', () => {
  const ready = (coreInstanceId: string): AppState => ({ link: 'ready', coreInstanceId, noTray: false, unreceipted: 0 })
  const start = async () => {
    const store = await import('../../src/renderer/src/store')
    // The chat view's module registers the personality's ready listener before the store starts.
    const list = await import('../../src/renderer/src/components/MessageList.vue')
    await store.init()
    const view = mount(list.default)
    mounted.push(view)
    await flush()
    return { store, view, push: api.onAppState!.mock.calls[0]![0] as (state: AppState) => void }
  }

  it('reads the personality again when the core becomes ready, after a read that failed during startup', async () => {
    api.getAppState!.mockResolvedValue({ link: 'connecting', coreInstanceId: null, noTray: false, unreceipted: 0 })
    api.personalityGet!.mockResolvedValueOnce({ ok: false, error: { code: 'not_connected', message: 'Odin is not connected yet.', disposition: 'not_dispatched' } })
    const { view, push } = await start()
    expect(view.root.textContent()).not.toContain('Clippy')
    push(ready('real-core'))
    await flush()
    expect(view.root.textContent()).toContain('Ask Clippy anything.')
  })

  it("keeps the newer core's personality when a read from the previous core answers late", async () => {
    const late: Array<(answer: unknown) => void> = []
    const deferred = () => new Promise((resolve) => { late.push(resolve) })
    api.personalityGet!.mockImplementationOnce(deferred).mockImplementationOnce(deferred)
    const { view, push } = await start()
    expect(late).toHaveLength(2)
    push(ready('core-2'))
    await flush()
    expect(view.root.textContent()).toContain('Ask Clippy anything.')
    for (const resolve of late) resolve({ ok: true, result: personality('professional') })
    await flush()
    expect(view.root.textContent()).toContain('Ask Clippy anything.')
    expect(view.root.textContent()).not.toContain('Mimir')
  })

  it('names the assistant while it works', async () => {
    const running = { request_id: 'r1', generation: 1, started_at: '2026-10-08T00:00:00Z' }
    api.snapshotConversation!.mockResolvedValue({ ok: true, result: { ...snapshot, running } })
    const { view } = await start()
    expect(view.root.textContent()).toContain('Clippy is working…')
  })

  it('names the assistant in the resume banner', async () => {
    const suspended = { request_id: 'r0', generation: 1, outcome: 'suspended', unknown_effects: 0, at: '' }
    api.snapshotConversation!.mockResolvedValue({ ok: true, result: { ...snapshot, recent: [suspended] } })
    await start()
    const banner = mount((await import('../../src/renderer/src/components/ResumeBanner.vue')).default, { conversationId: 'chat' })
    mounted.push(banner)
    await flush()
    expect(banner.root.textContent()).toContain('Ask Clippy to resume from any preserved progress.')
  })

  it('names the assistant in live announcements', async () => {
    const { activePersonality } = await import('../../src/renderer/src/assistant-name')
    const { chatAnnouncement } = await import('../../src/renderer/src/chat-announcements')
    activePersonality.value = personality('clippy-astra')
    const idle = { running: null, stopping: false, terminal: null, outcome: null, queued: 0, consumed: [], steerQueued: [], unknown: [] }
    expect(chatAnnouncement(idle, { ...idle, running: 'r1', steerQueued: ['s1'] })).toBe('Clippy is working. Steer queued for Clippy to read.')
    expect(chatAnnouncement({ ...idle, running: 'r1', steerQueued: ['s1'] }, { ...idle, running: 'r1', consumed: ['s1'] })).toBe('Clippy has read the steer.')
  })
})
