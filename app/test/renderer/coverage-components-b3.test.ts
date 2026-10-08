// Real compiled components on the object renderer. Host shims model DOM decisions,
// not native browser focus/accessibility proof. Only IPC/store and leaf boundaries are mocked.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h, reactive } from 'vue'
import { flush, Host, mount, type Mounted } from './component-host'

// Teleport's placement is a browser boundary; keep its children on the object renderer.
vi.mock('vue', async (original) => {
  const actual = await original<typeof import('vue')>()
  const teleport = actual.Teleport as any
  return { ...actual, Teleport: { ...teleport, process(...args: any[]) {
    args[1].props = { ...args[1].props, to: args[2], disabled: true }
    return teleport.process(...args)
  } } }
})
// The real Markdown parser still runs. Sanitizer security has its own browser tests.
vi.mock('dompurify', () => ({ default: { sanitize: (html: string) => html } }))

let mounted: Mounted[] = []
let state: any
let status: any
let api: any
let actions: any
let dialogModule: any
let completionModule: any
let doc: any
let shell: Host
let background: Host
let acquired: any[]
let acquire: ReturnType<typeof vi.fn>
let commands: any[]

function matches(node: Host, selector: string): boolean {
  return selector.split(',').some((part) => {
    const s = part.trim()
    if (s === '[role="menuitem"]') return node.props.role === 'menuitem'
    if (s === '[tabindex="0"]') return node.props.tabindex === '0' || node.props.tabindex === 0
    if (s.startsWith('textarea[')) return node.tag === 'textarea' && node.props['aria-label'] === 'Message'
    const [tag, cls] = s.replace(':not(:disabled)', '').split('.')
    return (!tag || node.tag === tag) && (!cls || String(node.props.class ?? '').split(' ').includes(cls)) &&
      (!s.includes(':not(:disabled)') || !node.props.disabled)
  })
}

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  mounted = []
  shell = new Host('div'); shell.props.class = 'shell'
  background = new Host('main'); background.parent = shell; shell.children.push(background)
  doc = { body: shell, querySelector: vi.fn(), getElementById: vi.fn() }
  let focused: Host | null = background
  Object.defineProperty(doc, 'activeElement', { get: () => focused && !(focused as any).isConnected ? shell : focused, set: (v) => { focused = v } })
  Object.defineProperties(Host.prototype, {
    __v_skip: { configurable: true, value: true },
    isConnected: { configurable: true, get(this: Host) { return this === shell || Boolean((this.parent as any)?.isConnected) } },
    nextElementSibling: { configurable: true, get(this: Host) { return this.parent?.children[this.parent.children.indexOf(this) + 1] } },
    previousElementSibling: { configurable: true, get(this: Host) { return this.parent?.children[this.parent.children.indexOf(this) - 1] } }
  })
  Object.assign(Host.prototype, {
    focus(this: Host) { doc.activeElement = this },
    select: vi.fn(),
    contains(this: Host, node: Host) { return this === node || this.findAll((n) => n === node).length > 0 },
    closest(this: Host, selector: string): Host | null { return matches(this, selector) ? this : (this.parent as any)?.closest(selector) ?? null },
    querySelectorAll(this: Host, selector: string) { return this.findAll((n) => matches(n, selector)) },
    querySelector(this: Host, selector: string) { return this.findAll((n) => matches(n, selector))[0] ?? null },
    getBoundingClientRect() { return { bottom: 40, right: 240 } },
    offsetHeight: 180
  })
  vi.stubGlobal('document', doc)
  vi.stubGlobal('HTMLElement', Host)
  api = Object.fromEntries(['copyText', 'checkReleases', 'openRelease', 'toolDetail', 'toolOutput', 'trajectoriesList', 'trajectoriesRead', 'trajectoriesSearch', 'trajectoriesMessage'].map((name) => [name, vi.fn(async () => ({ ok: true, result: {} }))]))
  vi.stubGlobal('window', { odin: api, innerHeight: 600, innerWidth: 800 })
  state = reactive({ app: { link: 'ready', appVersion: '1.0.0' }, views: {}, resumes: {}, activeId: 'c1', conversations: [], showArchived: false, conversationsUnavailable: false, search: { open: false } })
  actions = Object.fromEntries(['deleteConversation', 'renameConversation', 'resetContext', 'setArchived', 'setMuted', 'startThread', 'select', 'newConversation', 'resume'].map((name) => [name, vi.fn(async () => undefined)]))
  Object.assign(actions, { isMuted: vi.fn(() => false), isBusy: vi.fn(() => false), canAct: vi.fn(() => true), resumeKey: vi.fn((outcome) => `${outcome.request_id}:${outcome.generation}`), resumeTarget: vi.fn((view) => view?.target ?? null) })
  vi.doMock('../../src/renderer/src/store', () => ({ state, ...actions }))
  status = reactive({ core: null, usage: null })
  vi.doMock('../../src/renderer/src/stores/status', () => ({ status }))
  commands = [{ name: 'status', run: vi.fn() }, { name: 'usage', run: vi.fn() }]
  vi.doMock('../../src/renderer/src/commands', () => ({ COMMANDS: commands }))
  for (const name of ['FileCard', 'ReportViewer', 'CompletionResult']) {
    vi.doMock(`../../src/renderer/src/components/${name}.vue`, () => ({ default: { props: ['artifact', 'resource'], setup: (props: any) => () => h('div', { 'data-leaf': name, 'data-ref': props.artifact?.ref }, props.artifact?.name ?? props.resource) } }))
  }
  acquired = []
  acquire = vi.fn((artifact) => { const handle = { url: Promise.resolve(`blob:${artifact.ref}`), release: vi.fn() }; acquired.push(handle); return handle })
  vi.doMock('../../src/renderer/src/artifacts', () => ({ images: { acquire }, showsInline: (artifact: any) => artifact.kind === 'image' }))
  vi.doMock('../../src/renderer/src/dialog', async (original) => { const actual = await original<typeof import('../../src/renderer/src/dialog')>(); return { ...actual, ask: vi.fn(actual.ask) } })
  dialogModule = await import('../../src/renderer/src/dialog')
  completionModule = { completion: reactive({}) as any, readCompletion: vi.fn(async (_resource, operation, _label) => operation()) }
  vi.doMock('../../src/renderer/src/stores/completion', () => completionModule)
})

afterEach(() => {
  for (const view of mounted.reverse()) view.unmount()
  vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks()
})

async function screen(name: string, props?: Record<string, unknown>) {
  const view = mount((await import(`../../src/renderer/src/components/${name}.vue`)).default, props)
  view.root.parent = shell; shell.children.push(view.root)
  mounted.push(view)
  await flush()
  return view
}
function cls(root: Host, name: string): Host { return root.findAll((n) => String(n.props.class ?? '').split(' ').includes(name))[0]! }
function focus(node: Host) { (node as any).focus() }
function key(node: Host, value: string, shiftKey = false) {
  const preventDefault = vi.fn(); const stopPropagation = vi.fn()
  const event = { target: node, currentTarget: node, key: value, shiftKey, preventDefault, stopPropagation }
  const handlers = node.props.onKeydown
  for (const handler of Array.isArray(handlers) ? handlers : [handlers]) (handler as (event: unknown) => void)(event)
  return { preventDefault, stopPropagation }
}
const conversation = { id: 'c1', title: 'Original', updated_at: '2026-10-06T10:00:00Z', archived: false, unread: 0 }

describe('B3 attachment and confirmation behavior', () => {
  it('formats byte/KB/MB upload states, emits knowledge changes, and transfers removal focus', async () => {
    const items = reactive([
      { id: 'a', name: 'tiny.txt', size: 5, sent: 0, status: 'ready', addToKnowledge: false },
      { id: 'b', name: 'large.png', size: 2 * 1024 * 1024, sent: 2048, status: 'uploading', previewUrl: 'blob:preview' },
      { id: 'c', name: '', size: 1024, status: 'failed', error: 'Upload refused' }
    ])
    const knowledge = vi.fn()
    const remove = vi.fn((id) => { items.splice(items.findIndex((a) => a.id === id), 1) })
    const view = await screen('AttachmentTray', { items, onRemove: remove, onKnowledge: knowledge })
    expect(view.root.textContent()).toContain('5 B')
    expect(view.root.textContent()).toContain('2 KB of 2.0 MB')
    expect(view.root.textContent()).toContain('Upload refused')
    expect(view.root.textContent()).toContain('FILE')
    expect(view.root.find('progress')!.props.max).toBe(2 * 1024 * 1024)
    const checkbox = view.root.find('input')!; checkbox.checked = true; checkbox.fire('change')
    expect(knowledge).toHaveBeenCalledWith('a', true)
    const first = view.root.named('Remove tiny.txt'); const next = view.root.named('Remove large.png'); focus(first)
    await first.fire('click', { currentTarget: first }); await flush()
    expect(remove).toHaveBeenCalledWith('a'); expect(doc.activeElement).toBe(next)
    const message = new Host('textarea'); message.parent = shell; doc.querySelector.mockReturnValue(message)
    // Removing the final item uses the composer rather than a disconnected sibling.
    items.splice(1); await flush(); focus(next)
    await next.fire('click', { currentTarget: next }); await flush()
    expect(doc.activeElement).toBe(message)
  })

  it('confirms prompts, traps both Tab directions, makes background inert, and restores the opener', async () => {
    const view = await screen('ConfirmDialog')
    const opener = background; focus(opener)
    const answer = dialogModule.ask({ title: 'Rename', message: 'Enter a title', confirmLabel: 'Save', danger: true, input: { value: 'Before', label: 'Title', maxLength: 40 } })
    await flush()
    expect((background as any).inert).toBe(true)
    const input = view.root.find('input')!; expect(doc.activeElement).toBe(input); expect(input.value).toBe('Before'); expect(input.props.maxlength).toBe(40)
    const backdrop = cls(view.root, 'dialog-backdrop'); const save = view.root.button('Save')
    focus(save); expect(key(backdrop, 'Tab').preventDefault).toHaveBeenCalled(); expect(doc.activeElement).toBe(input)
    expect(key(backdrop, 'Tab', true).preventDefault).toHaveBeenCalled(); expect(doc.activeElement).toBe(save)
    expect(key(backdrop, 'Enter').preventDefault).not.toHaveBeenCalled()
    input.type('After'); view.root.find('form')!.fire('submit', { preventDefault() {} })
    expect(await answer).toBe('After'); await flush()
    expect((background as any).inert).toBe(false); expect(doc.activeElement).toBe(opener)
    expect(view.root.find('form')).toBeUndefined()
  })

  it('confirms boolean dialogs and cancels via button/backdrop/Escape, including unmount cleanup', async () => {
    const view = await screen('ConfirmDialog')
    let answer = dialogModule.ask({ title: 'Proceed?', message: '', confirmLabel: 'Proceed' }); await flush()
    expect(doc.activeElement).toBe(view.root.button('Proceed'))
    view.root.find('form')!.fire('submit', { preventDefault() {} }); expect(await answer).toBe(true); await flush()
    for (const mode of ['button', 'backdrop', 'escape']) {
      answer = dialogModule.ask({ title: 'Cancel?', message: '', confirmLabel: 'Proceed', input: { value: '', label: 'Name' } }); await flush()
      const backdrop = cls(view.root, 'dialog-backdrop')
      if (mode === 'button') view.root.button('Cancel').fire('click')
      else if (mode === 'backdrop') backdrop.fire('click', { target: backdrop, currentTarget: backdrop })
      else key(backdrop, 'Escape')
      expect(await answer).toBe(null); await flush()
    }
    const pending = dialogModule.ask({ title: 'Open', message: '', confirmLabel: 'Proceed' }); await flush()
    expect((background as any).inert).toBe(true)
    view.unmount(); mounted.splice(mounted.indexOf(view), 1)
    expect((background as any).inert).toBe(false)
    dialogModule.dialog.current.resolve(null); await pending
  })
})

describe('B3 conversation controls', () => {
  it('clamps menu position, navigates keyboard items and closes without swallowing Tab/activation', async () => {
    const close = vi.fn()
    const view = await screen('ConversationMenu', { conversation, top: 999, left: -20, onClose: close })
    const menu = view.root.findAll((n) => n.props.role === 'menu')[0]!
    expect(menu.props.style).toMatchObject({ top: '412px', left: '8px' })
    const items = menu.findAll((n) => n.props.role === 'menuitem')
    expect(doc.activeElement).toBe(items[0])
    key(menu, 'ArrowUp'); expect(doc.activeElement).toBe(items[5])
    key(menu, 'ArrowDown'); expect(doc.activeElement).toBe(items[0])
    key(menu, 'End'); expect(doc.activeElement).toBe(items[5])
    key(menu, 'Home'); expect(doc.activeElement).toBe(items[0])
    expect(key(menu, 'Enter').stopPropagation).not.toHaveBeenCalled()
    expect(key(menu, 'Tab').preventDefault).not.toHaveBeenCalled(); expect(close).toHaveBeenCalledTimes(1)
    key(menu, 'Escape'); expect(close).toHaveBeenCalledTimes(2)
    cls(view.root, 'menu-backdrop').fire('click'); expect(close).toHaveBeenCalledTimes(3)
  })

  it('runs only confirmed/changed conversation actions and flips mute/archive intent', async () => {
    const close = vi.fn()
    const view = await screen('ConversationMenu', { conversation, top: 20, left: 250, onClose: close })
    for (const title of [null, '', '  Original ', '  New title  ']) {
      dialogModule.ask.mockResolvedValueOnce(title)
      await view.root.button('Rename…').fire('click')
    }
    expect(actions.renameConversation).toHaveBeenCalledExactlyOnceWith('c1', 'New title')
    await view.root.button('New thread from here').fire('click'); expect(actions.startThread).toHaveBeenCalledWith('c1')
    await view.root.button('Mute notifications').fire('click'); expect(actions.setMuted).toHaveBeenCalledWith('c1', true)
    actions.isMuted.mockReturnValue(true)
    await view.root.button('Mute notifications').fire('click'); expect(actions.setMuted).toHaveBeenLastCalledWith('c1', false)
    await view.root.button('Archive').fire('click'); expect(actions.setArchived).toHaveBeenCalledWith('c1', true)
    for (const label of ['Reset context…', 'Delete…']) {
      dialogModule.ask.mockResolvedValueOnce(null); await view.root.button(label).fire('click')
      dialogModule.ask.mockResolvedValueOnce(true); await view.root.button(label).fire('click')
    }
    expect(actions.resetContext).toHaveBeenCalledExactlyOnceWith('c1')
    expect(actions.deleteConversation).toHaveBeenCalledExactlyOnceWith('c1')
    expect(close).toHaveBeenCalledTimes(12)
  })

  it('lists archived/unread/busy threads, toggles search/menu, and restores focus after row removal', async () => {
    vi.setSystemTime(new Date('2026-10-07T12:00:00Z'))
    state.conversations = [
      { ...conversation, updated_at: '2026-10-07T10:00:00Z' },
      { ...conversation, id: 'c2', title: 'Thread', unread: 150, inherited_from: { title: 'Original' } },
      { ...conversation, id: 'c3', title: 'Busy', updated_at: 'invalid' },
      { ...conversation, id: 'c4', title: 'Archived', unread: 3, archived: true, updated_at: '2025-01-01T00:00:00Z' }
    ]
    actions.isBusy.mockImplementation((id: string) => id === 'c3')
    const view = await screen('ConversationList')
    expect(view.root.textContent()).not.toContain('Archived'); expect(view.root.textContent()).toContain('99+')
    expect(view.root.named('Busy, Odin is working').props['aria-current']).toBeUndefined()
    view.root.named('Thread, thread from Original, 150 unread').fire('click'); expect(actions.select).toHaveBeenCalledWith('c2')
    view.root.named('New conversation').fire('click'); expect(actions.newConversation).toHaveBeenCalledOnce()
    cls(view.root, 'conv-search').fire('click'); await flush(); expect(state.search.open).toBe(true)
    view.root.button('Show archived (1)').fire('click'); await flush()
    expect(view.root.named('Archived, archived, 3 unread')).toBeDefined()
    expect(view.root.button('Hide archived')).toBeDefined()
    const opener = view.root.named('Actions for Original'); focus(opener)
    opener.fire('click', { currentTarget: opener, stopPropagation() {} }); await flush()
    expect(opener.props['aria-expanded']).toBe(true)
    const menu = view.root.findAll((n) => n.props.role === 'menu')[0]!; key(menu, 'Escape'); await flush()
    expect(doc.activeElement).toBe(opener); expect(opener.props['aria-expanded']).toBe(false)
    opener.fire('keydown', { key: 'ArrowDown', currentTarget: opener, preventDefault() {} }); await flush()
    opener.fire('click', { currentTarget: opener, stopPropagation() {} }); await flush(); expect(opener.props['aria-expanded']).toBe(false)
    const deleted = view.root.named('Thread, thread from Original, 150 unread'); focus(deleted)
    state.conversations.splice(1, 1); await flush()
    expect(doc.activeElement).toBe(view.root.named('Original'))
    state.conversationsUnavailable = true; await flush(); expect(view.root.textContent()).toContain('Conversations')
  })
})

describe('B3 messages and resume', () => {
  it('renders markdown, formats attachments, copies both variants, restores copy focus and starts threads', async () => {
    const message = { id: 'm1', role: 'assistant', text: '**Hello**', created_at: '2026-10-07T10:00:00Z', attachments: [{ ref: 'a', name: 'tiny', size: 2 }, { ref: 'b', name: 'kilo', size: 2048 }, { ref: 'c', name: 'mega', size: 1048576 }] }
    const view = await screen('Message', { message, conversationId: 'c1', actions: true, highlight: true })
    expect(view.root.find('article')!.props['aria-label']).toContain('Odin message at')
    expect(cls(view.root, 'body').props.innerHTML).toContain('<strong>Hello</strong>')
    const codeButton = { textContent: 'Copy', parentElement: { querySelector: () => ({ textContent: 'pwd' }) } }
    cls(view.root, 'body').fire('click', { target: { closest: () => codeButton } }); await flush()
    expect(api.copyText).toHaveBeenCalledWith('pwd'); expect(codeButton.textContent).toBe('Copied')
    expect(view.root.textContent()).toContain('tiny · 2 Bkilo · 2 KBmega · 1.0 MB')
    const copy = view.root.button('Copy'); copy.fire('click'); await flush()
    expect(doc.activeElement).toBe(view.root.button('Copy as Markdown'))
    await view.root.button('Copy as Markdown').fire('click'); await flush()
    expect(api.copyText).toHaveBeenCalledWith('**Hello**'); expect(doc.activeElement).toBe(copy); expect(view.root.textContent()).toContain('Copied')
    vi.advanceTimersByTime(1500); await flush(); expect(cls(view.root, 'copied').textContent()).toBe('')
    api.copyText.mockResolvedValueOnce({ ok: false })
    copy.fire('click'); await flush(); await view.root.button('Copy as plain text').fire('click'); await flush()
    expect(api.copyText).toHaveBeenLastCalledWith('Hello'); expect(view.root.textContent()).toContain("Couldn't copy")
    copy.fire('click'); await flush(); key(cls(view.root, 'copy-choices'), 'Escape'); await flush(); expect(view.root.findAll((n) => String(n.props.class) === 'copy-choices')).toHaveLength(0)
    view.root.button('Thread from here').fire('click'); expect(actions.startThread).toHaveBeenCalledWith('c1', 'm1')
  })

  it('loads images once, falls back after decode failure, renders file/report leaves, and releases handles', async () => {
    let resolve!: (url: string | null) => void
    const release = vi.fn()
    acquire.mockReturnValueOnce({ url: new Promise((r) => { resolve = r }), release })
    const message = reactive({ id: 'images', role: 'user', text: '', created_at: '2026-10-07T10:00:00Z', artifacts: [{ ref: 'image', name: 'Photo', kind: 'image' }, { ref: 'file', name: 'File', kind: 'file' }, { ref: 'report', name: 'Report', kind: 'report' }] })
    const view = await screen('Message', { message, conversationId: 'c1' })
    expect(view.root.textContent()).toContain('Loading Photo')
    expect(view.root.find('article')!.props['aria-label']).toContain('You message at')
    resolve('blob:image'); await flush()
    const image = view.root.find('img')!; expect(image.props.src).toBe('blob:image'); image.fire('error'); await flush()
    expect(view.root.find('img')).toBeUndefined(); expect(view.root.findAll((n) => n.props['data-ref'] === 'image')).toHaveLength(1)
    expect(view.root.findAll((n) => n.props['data-leaf'] === 'ReportViewer')).toHaveLength(1)
    message.artifacts = [...message.artifacts, { ref: 'second', name: 'Second', kind: 'image' }]; await flush()
    expect(acquire).toHaveBeenCalledTimes(2)
    view.unmount(); mounted.splice(mounted.indexOf(view), 1)
    expect(release).toHaveBeenCalledOnce(); expect(acquired[0].release).toHaveBeenCalledOnce()
  })

  it('guards duplicate resume and moves focus to history once admitted, including blocked/rejected states', async () => {
    const outcome = { request_id: 'r1', generation: 1, outcome: 'suspended' }
    state.views.c1 = { target: { outcome, blocked: '' } }
    const history = new Host('div'); history.parent = shell; doc.getElementById.mockReturnValue(history)
    const view = await screen('ResumeBanner', { conversationId: 'c1' })
    const button = view.root.button('Resume'); expect(view.root.textContent()).toContain('was suspended')
    state.resumes['r1:1'] = { status: 'unknown' }; await flush(); await button.fire('click', { currentTarget: button }); expect(actions.resume).not.toHaveBeenCalled()
    expect(view.root.textContent()).toContain('never sent twice')
    state.resumes['r1:1'] = { status: 'sending' }; await flush(); expect(view.root.button('Resuming…').props['aria-disabled']).toBe(true)
    state.resumes['r1:1'] = { status: 'rejected', reason: 'Rejected' }; await flush(); expect(view.root.textContent()).toContain('Rejected')
    actions.resume.mockImplementation(async () => { state.resumes['r1:1'] = { status: 'admitted' } })
    focus(button); await button.fire('click', { currentTarget: button }); await flush()
    expect(actions.resume).toHaveBeenCalledExactlyOnceWith('c1', outcome); expect(doc.activeElement).toBe(history); expect(view.root.find('button')).toBeUndefined()
    delete state.resumes['r1:1']; state.views.c1.target = { outcome: { ...outcome, outcome: 'interrupted' }, blocked: 'Checkpoint unavailable' }; await flush()
    expect(view.root.textContent()).toContain('was interrupted. Checkpoint unavailable'); expect(view.root.find('button')).toBeUndefined()
    state.views.c1.target.blocked = ''; await flush(); focus(view.root.button('Resume'))
    state.views.c1.target = null; await flush(); expect(doc.activeElement).toBe(history)
  })
})

describe('B3 release and trajectory controls', () => {
  it.each([
    ['cannot-check-private', 'private'], ['offline', 'Offline'], ['rate-limited', 'rate-limited'],
    ['malformed', 'invalid release information'], ['unavailable', 'unavailable or incomplete'],
    ['invalid-current-version', 'stable version number'], ['no-release', 'not an up-to-date check'],
    ['equal', 'Up to date'], ['older', 'newer than'], ['newer', 'new version is available']
  ])('explains the actual release state %s', async (releaseState, expected) => {
    api.checkReleases.mockResolvedValue({ ok: true, result: { state: releaseState, currentVersion: '1.0.0', latestVersion: '2.0.0', releaseUrl: 'https://example.test/release' } })
    const view = await screen('ReleaseNotice')
    expect(view.root.textContent()).toContain('Not checked')
    await view.root.button('Check for updates').fire('click'); await flush()
    expect(view.root.textContent()).toContain(expected); expect(view.root.textContent()).toContain('Version 1.0.0')
    await view.root.find('a')!.fire('click', { preventDefault() {} }); expect(api.openRelease).toHaveBeenCalledWith()
  })

  it('blocks overlapping release checks and shows returned/thrown errors for checks and opening', async () => {
    let resolve!: (r: any) => void
    api.checkReleases.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const view = await screen('ReleaseNotice'); const button = view.root.button('Check for updates')
    const first = button.fire('click'); await flush(); expect(view.root.textContent()).toContain('Checking for updates')
    await button.fire('click'); expect(api.checkReleases).toHaveBeenCalledOnce()
    resolve({ ok: false, error: { message: 'Denied' } }); await first; await flush(); expect(view.root.textContent()).toContain('Denied')
    api.checkReleases.mockRejectedValueOnce(new Error('fail')); await button.fire('click'); await flush(); expect(view.root.textContent()).toContain('app operation failed')
    api.checkReleases.mockResolvedValue({ ok: true, result: { state: 'newer', latestVersion: '2.0.0', releaseUrl: 'https://example.test' } }); await button.fire('click'); await flush()
    api.openRelease.mockResolvedValueOnce({ ok: false, error: { message: 'No browser' } }); await view.root.find('a')!.fire('click', { preventDefault() {} }); await flush(); expect(view.root.textContent()).toContain('No browser')
    api.openRelease.mockRejectedValueOnce(new Error('fail')); await view.root.find('a')!.fire('click', { preventDefault() {} }); await flush(); expect(view.root.textContent()).toContain('Could not open the release page')
  })

  it('passes selected trajectory filters to read/search/list/message APIs and hides unsupported controls', async () => {
    const view = await screen('TrajectoryDetails')
    expect(view.root.button('Read trajectory').props.disabled).toBe(true)
    const inputs = view.root.findAll((n) => n.tag === 'input')
    inputs[0]!.type('trace.jsonl'); inputs[1]!.type('channel'); inputs[2]!.type('user'); inputs[3]!.type('run_command'); inputs[4]!.type('25')
    inputs[5]!.checked = true; inputs[5]!.fire('change'); inputs[6]!.type('message-1'); await flush()
    await view.root.button('List trajectory files').fire('click'); expect(api.trajectoriesList).toHaveBeenCalledWith({})
    await view.root.button('Read trajectory').fire('click'); expect(api.trajectoriesRead).toHaveBeenCalledWith({ filename: 'trace.jsonl', channel_id: 'channel', user_id: 'user', tool_name: 'run_command', limit: 25, errors_only: true })
    await view.root.button('Search trajectories').fire('click'); expect(api.trajectoriesSearch).toHaveBeenCalledWith({ channel_id: 'channel', user_id: 'user', tool_name: 'run_command', limit: 25, errors_only: true })
    await view.root.button('Read message trajectory').fire('click'); expect(api.trajectoriesMessage).toHaveBeenCalledWith({ message_id: 'message-1' })
    expect(completionModule.readCompletion).toHaveBeenLastCalledWith('trace-message', expect.any(Function), 'message-1')
    completionModule.completion['trace-files'] = { unavailable: true }; await flush(); expect(view.root.find('input')).toBeUndefined()
  })
})

describe('B3 tool details and chat status', () => {
  it('renders all outcomes and paginates retained output, with expired/retry handling and no replay', async () => {
    const entries = ['success', 'failure', 'unknown', undefined].map((outcome, i) => ({ invocation_id: `i${i}`, tool: `tool${i}`, summary: 'summary', outcome, target: 'localhost', exit_code: 0, duration_ms: 1234 }))
    api.toolDetail.mockResolvedValue({ ok: true, result: { arguments: { command: 'pwd' }, previews: [{ label: 'Preview', text: 'short', truncated: true }], output: { cursor: 'page1', expires_at: '2026-10-08T10:00:00Z' } } })
    const view = await screen('ToolActivity', { entries, requestId: 'r1', live: true })
    expect(view.root.textContent()).toContain('✓'); expect(view.root.textContent()).toContain('✕'); expect(view.root.textContent()).toContain('?'); expect(view.root.textContent()).toContain('…')
    const row = cls(view.root, 'tool-row'); await row.fire('click'); await flush()
    expect(api.toolDetail).toHaveBeenCalledWith({ request_id: 'r1', invocation_id: 'i0' }); expect(view.root.textContent()).toContain('Kept until'); expect(view.root.textContent()).toContain('"command": "pwd"')
    api.toolOutput.mockResolvedValueOnce({ ok: false, error: { code: 'expired', message: 'Expired' } })
    await view.root.named('Show full output for tool0').fire('click'); await flush(); expect(view.root.textContent()).toContain('Odin no longer keeps this output')
    api.toolOutput.mockResolvedValueOnce({ ok: true, result: { text: 'first ', attachments: [{ ref: 'binary', mime: 'application/octet-stream', size: 12 }], next_cursor: 'page2', eof: false } })
    await view.root.named('Show full output for tool0').fire('click'); await flush()
    expect(api.toolOutput).toHaveBeenLastCalledWith({ cursor: 'page1', limit: 32768 }); expect(view.root.textContent()).toContain('first ')
    api.toolOutput.mockResolvedValueOnce({ ok: true, result: { text: 'second', attachments: [], eof: true } })
    await view.root.named('Load more for tool0').fire('click'); await flush()
    expect(api.toolOutput).toHaveBeenLastCalledWith({ cursor: 'page2', limit: 32768 }); expect(view.root.textContent()).toContain('first second'); expect(view.root.named('All output loaded for tool0').props['aria-disabled']).toBe(true)
    await view.root.named('All output loaded for tool0').fire('click'); expect(api.toolOutput).toHaveBeenCalledTimes(3)
    await row.fire('click'); await flush(); expect(cls(view.root, 'tool-row').props['aria-expanded']).toBe(false)
    cls(view.root, 'tools-toggle').fire('click'); await flush(); expect(view.root.find('ul')).toBeUndefined()
  })

  it('ignores late retained output after collapse and duplicate reads while loading, then displays detail refusal', async () => {
    let resolve!: (result: any) => void
    api.toolDetail.mockResolvedValue({ ok: true, result: { arguments: undefined, previews: [], output: { cursor: 'p' } } })
    const view = await screen('ToolActivity', { entries: [{ invocation_id: 'i', tool: 'read' }], requestId: 'r', live: true })
    const row = cls(view.root, 'tool-row'); await row.fire('click'); await flush(); expect(view.root.textContent()).toContain('undefined')
    api.toolOutput.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const more = view.root.named('Show full output for read'); const pending = more.fire('click'); await flush()
    expect(view.root.named('Loading… for read').props['aria-disabled']).toBe(true)
    await view.root.named('Loading… for read').fire('click'); expect(api.toolOutput).toHaveBeenCalledOnce()
    await row.fire('click'); resolve({ ok: true, result: { text: 'stale', eof: true } }); await pending; await flush(); expect(view.root.textContent()).not.toContain('stale')
    api.toolDetail.mockResolvedValueOnce({ ok: false, error: { message: 'Detail unavailable' } }); await row.fire('click'); await flush(); expect(view.root.textContent()).toContain('Detail unavailable')
  })

  it('opens connected status/usage reports, includes quota reset facts and hides stale data', async () => {
    const measured = (value: number) => ({ value, kind: 'measured' })
    status.core = { model: { main: 'Local', effort: 'high', provider: 'local' } }
    status.usage = { period: '24h', context: { used: measured(20), budget: measured(100) }, quota: [{ account: 'Primary', window: 'week', used_percent: measured(30), resets_at: '2026-10-08T10:00:00Z' }], tokens: measured(2000) }
    const view = await screen('ChatStatus'); const buttons = view.root.findAll((n) => n.tag === 'button')
    expect(buttons[1]!.props.title).toContain('resets'); expect(view.root.textContent()).toContain('Context 20% · Quota 30% · 2K tokens')
    buttons[0]!.fire('click'); buttons[1]!.fire('click'); expect(commands[0].run).toHaveBeenCalledWith(''); expect(commands[1].run).toHaveBeenCalledWith('')
    status.usage.quota = []; await flush(); expect(view.root.textContent()).not.toContain('Quota'); expect(view.root.textContent()).toContain('Context 20% · 2K tokens in 24h')
    state.app.link = 'reconnecting'; await flush(); expect(view.root.find('button')).toBeUndefined()
  })
})
