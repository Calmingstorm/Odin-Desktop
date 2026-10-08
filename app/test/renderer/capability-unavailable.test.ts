// Real compiled screens over the named bridge. Step 1 refuses methods, not data-shaped substitutes.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AppState, Conversation, ConversationSnapshot, CoreStatus, Result } from '../../src/shared/api'
import { flush, heldFrames, Host, mount, type Mounted } from './component-host'

const refused = <T>(): Result<T> => ({ ok: false, error: { code: 'capability_unavailable', message: 'Service is not available yet', disposition: 'not_dispatched' } })
const core: CoreStatus = { phase: 'ready', core_instance_id: 'real-core', version: 'step1-test', capabilities: ['status.get', 'events.subscribe', 'runtime.shutdown'] }
const app: AppState = { link: 'ready', coreInstanceId: core.core_instance_id, noTray: false, unreceipted: 0 }
const conversation: Conversation = { id: 'cached', title: 'Old fixture title', rev: 1, parent_id: null, updated_at: '', unread: 0, archived: false }
const snapshot: ConversationSnapshot = {
  conversation, watermark: '0', messages: { items: [], has_more: false }, running: null, queued: [], recent: [], unresolved: [], tools: {}, controls: []
}

let store: typeof import('../../src/renderer/src/store')
let api: ReturnType<typeof bridge>
let mounted: Mounted[]

function bridge() {
  return {
    getAppState: vi.fn(async () => app),
    getSettings: vi.fn(async () => ({ ok: true, result: { autostart: false, notifications: null } })),
    listConversations: vi.fn(async (): Promise<Result<{ items: never[]; watermark: string }>> => refused()),
    createConversation: vi.fn(async () => refused()),
    snapshotConversation: vi.fn(async (): Promise<Result<ConversationSnapshot>> => refused()),
    status: vi.fn(async (): Promise<Result<CoreStatus>> => ({ ok: true, result: core })),
    usage: vi.fn(async () => refused()),
    search: vi.fn(async () => refused()),
    workList: vi.fn(async () => refused()),
    getDraft: vi.fn(async () => ({ ok: true, result: { text: 'retained draft' } })),
    onEvent: vi.fn(), onAppState: vi.fn((_listener: (state: AppState) => void) => undefined), onReceipt: vi.fn(), onReset: vi.fn(), onOpenConversation: vi.fn()
  }
}

beforeEach(async () => {
  vi.resetModules()
  mounted = []
  api = bridge()
  vi.stubGlobal('window', { odin: api, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  vi.stubGlobal('document', { addEventListener: vi.fn(), visibilityState: 'hidden', hasFocus: () => false, activeElement: null })
  vi.stubGlobal('Document', class {})
  vi.stubGlobal('ShadowRoot', class {})
  // Vue's native form directives expect this tiny DOM surface; keep its input listeners on the real host nodes.
  Object.assign(Host.prototype, {
    addEventListener(this: Host, event: string, listener: unknown) { this.props[`on${event[0]!.toUpperCase()}${event.slice(1)}`] = listener },
    removeEventListener() {}, focus() {}, getRootNode() { return document }
  })
  heldFrames()
  store = await import('../../src/renderer/src/store')
})

afterEach(() => {
  for (const screen of mounted) screen.unmount()
  vi.unstubAllGlobals()
})

async function screen(name: string): Promise<Mounted> {
  const component = await import(`../../src/renderer/src/components/${name}.vue`)
  const view = mount(component.default)
  mounted.push(view)
  await flush()
  return view
}

describe('step-1 capability refusals in mounted renderer screens', () => {
  it('scopes settings refusal copy without changing global copy or diagnostic failures', async () => {
    const { settingsUnavailableText, settingsResultMessage, unavailableText, resultMessage } = await import('../../src/renderer/src/capability')
    expect(settingsUnavailableText('Knowledge')).toBe('Knowledge is unavailable.')
    expect(settingsUnavailableText('Settings')).toBe('Settings are unavailable.')
    expect(settingsUnavailableText('Codex accounts')).toBe('Codex accounts are unavailable.')
    expect(settingsResultMessage(refused(), 'Knowledge')).toBe('Knowledge is unavailable.')
    expect(unavailableText('Chat')).toBe('Chat is unavailable in this core.')
    expect(resultMessage(refused(), 'Chat')).toBe('Chat is unavailable in this core.')
    expect(settingsResultMessage({ ok: true, result: [] }, 'Knowledge')).toBe('')
    expect(settingsResultMessage({ ok: false, error: { code: 'read_failed', message: 'Original diagnostic: metadata unavailable' } }, 'Knowledge')).toBe('Original diagnostic: metadata unavailable')
  })

  it('does not replace a pushed ready state with an older initial app-state reply', async () => {
    let answer!: (value: AppState) => void
    api.getAppState.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve }))
    const initializing = store.init()
    await flush()
    const pushed = api.onAppState.mock.calls[0]![0]
    pushed(app)
    await flush()
    answer({ ...app, link: 'connecting', coreInstanceId: null })
    await initializing
    expect(store.state.app).toEqual(app)
    expect(store.state.conversationsUnavailable).toBe(true)
  })

  it('settles the sidebar and chat, discards cached core data, and shows no loading, bug or fabricated first chat', async () => {
    store.state.conversations = [conversation]
    store.state.activeId = conversation.id
    const sidebar = await screen('ConversationList')
    const chat = await screen('MessageList')
    await store.init()
    await flush()
    expect(sidebar.root.textContent()).toContain('Conversations are unavailable in this core.')
    expect(chat.root.textContent()).toContain('Chat is unavailable in this core.')
    expect(sidebar.root.textContent()).not.toContain('Old fixture title')
    expect(chat.root.textContent()).not.toMatch(/Loading|Couldn.t load|Ask Odin anything/)
    expect(store.state.loaded).toBe(true)
    expect(store.state.activeId).toBeNull()
    expect(api.createConversation).not.toHaveBeenCalled()
    await sidebar.root.named('New conversation').fire('click')
    expect(api.createConversation).toHaveBeenCalledTimes(1)
    expect(store.state.notice).toBe('Conversations are unavailable in this core.')
    expect(store.state.conversations).toEqual([])
  })

  it('disables sending and attaching but permits report commands when chat is unavailable', async () => {
    await store.init()
    const composer = await screen('Composer')
    expect(composer.root.textContent()).toContain('Chat is unavailable in this core.')
    expect(composer.root.textContent()).toContain('Sending messages and attachments is unavailable.')
    expect(composer.root.named('Send').props.disabled).toBe(true)
    expect(composer.root.named('Attach files').props.disabled).toBe(true)
    expect(composer.root.find('textarea')!.props.disabled).toBe(false)
    expect(composer.root.textContent()).not.toMatch(/Loading|Couldn.t load|Retry/)
    composer.setup.text = '/status'
    await flush()
    composer.root.find('form')!.fire('submit', { preventDefault() {} })
    await flush()
    expect(store.state.panel?.text).toContain('Version: step1-test')
    expect(store.state.conversations).toEqual([])
    expect(composer.root.named('Send').props.disabled).toBe(true)
    composer.setup.text = '/usage'
    await flush()
    composer.root.find('form')!.fire('submit', { preventDefault() {} })
    await flush()
    const statusStore = await import('../../src/renderer/src/stores/status')
    await statusStore.refreshStatus()
    const statusBar = await screen('StatusBar')
    expect(statusBar.root.textContent()).toContain('Usage is unavailable in this core.')
    expect(composer.root.textContent()).not.toContain('Usage is unavailable in this core.')
    expect(store.state.notice).toBe('Usage is unavailable in this core.')
  })

  it('handles snapshot unavailability separately from list refusal and keeps the local draft', async () => {
    store.state.app = app
    store.state.loaded = true
    store.state.conversations = [conversation]
    store.state.activeId = conversation.id
    await store.loadConversation(conversation.id)
    const chat = await screen('MessageList')
    const composer = await screen('Composer')
    expect(chat.root.textContent()).toContain('Chat is unavailable in this core.')
    expect(composer.root.named('Send').props.disabled).toBe(true)
    expect(store.canAct(conversation.id)).toBe(false)
    const drafts = await import('../../src/renderer/src/stores/composer')
    expect(drafts.box.text).toBe('retained draft')
    expect(chat.root.textContent()).not.toMatch(/Loading|Couldn.t load/)
  })

  it('submits a query through the mounted search form and never mistakes refusal for no matches', async () => {
    const search = await screen('SearchPanel')
    search.setup.query = 'some words'
    search.root.find('form')!.fire('submit', { preventDefault() {} })
    await flush()
    expect(api.search).toHaveBeenCalledWith({ query: 'some words', limit: 20 })
    expect(search.root.textContent()).toContain('Search is unavailable in this core.')
    expect(search.root.textContent()).not.toMatch(/Searching|No matches|Service is not available yet/)
    expect(search.root.findAll((node) => node.props.role === 'alert')).toEqual([])
    expect(store.state.search.loading).toBe(false)
  })

  it('refuses Work without falsely saying nothing is running or showing cached items', async () => {
    const workStore = await import('../../src/renderer/src/stores/work')
    workStore.work.items = [{ kind: 'agent', id: 'fixture', title: 'Cached agent', state: 'running', detail: '', actions: ['stop'] }]
    const work = await screen('WorkPanel')
    await work.root.button('Refresh').fire('click')
    await flush()
    expect(work.root.textContent()).toContain('Work (agents, tasks, loops, processes, workflows and schedules) is unavailable in this core.')
    expect(work.root.textContent()).not.toMatch(/Nothing is running|Cached agent|Service is not available yet/)
    expect(work.root.findAll((node) => node.props.role === 'alert')).toEqual([])
    expect(workStore.activeCount()).toBe(0)
  })

  it('shows real status version and phase, visible usage unavailability, and a field-based status report', async () => {
    store.state.app = app
    const statusStore = await import('../../src/renderer/src/stores/status')
    const status = await screen('StatusBar')
    await statusStore.refreshStatus()
    await flush()
    expect(status.root.textContent()).toContain('Core step1-test · ready')
    expect(status.root.textContent()).toContain('Usage is unavailable in this core.')
    await status.root.button('Core step1-test · ready').fire('click')
    expect(store.state.panel?.text).toBe('Core real-core\nVersion: step1-test\nPhase: ready\nCapabilities: status.get, events.subscribe, runtime.shutdown')
    const { COMMANDS } = await import('../../src/renderer/src/commands')
    await COMMANDS.find((command) => command.name === 'usage')!.run('24h')
    expect(store.state.notice).toBe('Usage is unavailable in this core.')
    expect(status.root.textContent()).not.toContain('undefined')
  })

  it('still treats genuine load failures as errors, and clears unavailability on a supported recovery', async () => {
    api.listConversations.mockResolvedValueOnce({ ok: false, error: { code: 'internal', message: 'Database unavailable', disposition: 'not_dispatched' } })
    await store.init()
    const chat = await screen('MessageList')
    expect(chat.root.textContent()).toContain("Couldn't load from Odin: Database unavailable")
    expect(chat.root.button('Retry')).toBeDefined()
    expect(store.state.conversationsUnavailable).toBe(false)
    // First retry gives the capability refusal, a later supported core restores the real snapshot.
    await store.retry()
    expect(store.state.conversationsUnavailable).toBe(true)
    api.listConversations.mockResolvedValueOnce({ ok: true, result: { items: [conversation] as never[], watermark: '0' } })
    api.snapshotConversation.mockResolvedValueOnce({ ok: true, result: snapshot })
    const ready = api.onAppState.mock.calls[0]![0] as (next: AppState) => void
    ready({ ...app, link: 'reconnecting' })
    ready({ ...app, coreInstanceId: 'later-core' })
    await flush()
    expect(store.state.conversationsUnavailable).toBe(false)
    expect(store.canAct(conversation.id)).toBe(true)
    expect(chat.root.textContent()).toContain('Ask Odin anything.')
  })
})
