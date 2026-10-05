// These object-renderer tests check component wiring and keyboard decisions, not native focus/AT-SPI.
// The integrated isolated-Electron gate owns DOM focus, visual focus and accessibility-tree proof.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { menuKey } from '../../src/renderer/src/conversation-menu-keys'
import { flush, Host, mount, type Mounted } from './component-host'

describe('conversation menu key decisions', () => {
  it('wraps arrows, handles endpoints, and closes on Escape and Tab without swallowing activation keys', () => {
    expect(menuKey('ArrowDown', 5, 6)).toBe(0)
    expect(menuKey('ArrowUp', 0, 6)).toBe(5)
    expect(menuKey('ArrowUp', -1, 6)).toBe(5)
    expect(menuKey('Home', 4, 6)).toBe(0)
    expect(menuKey('End', 1, 6)).toBe(5)
    expect(menuKey('Escape', 1, 6)).toBe('close')
    expect(menuKey('Tab', 1, 6)).toBe('close')
    expect(menuKey('Enter', 1, 6)).toBeNull()
    expect(menuKey(' ', 1, 6)).toBeNull()
    expect(menuKey('Home', 0, 0)).toBeNull()
  })
})

let mounted: Mounted | undefined
let state: any
let runSearch: ReturnType<typeof vi.fn>
let moreResults: ReturnType<typeof vi.fn>
let jumpTo: ReturnType<typeof vi.fn>
let doc: { activeElement: Host | null; body: Host; getElementById: ReturnType<typeof vi.fn> }
const hit = (id: string) => ({ message_id: id, conversation_id: 'c1', snippet: `Match ${id}`, created_at: '2026-10-05T00:00:00Z' })

beforeEach(() => {
  vi.resetModules()
  doc = { activeElement: null, body: new Host('body'), getElementById: vi.fn() }
  vi.stubGlobal('document', doc)
  Object.defineProperties(Host.prototype, {
    // DOM nodes are not reactive proxies. Keep host-node identity equally stable in component refs.
    __v_skip: { configurable: true, value: true },
    isConnected: { configurable: true, get(this: Host) { return this.tag === 'root' || this.tag === 'body' || Boolean((this.parent as (Host & { isConnected: boolean }) | null)?.isConnected) } }
  })
  Object.assign(Host.prototype, {
    focus(this: Host) { doc.activeElement = this },
    contains(this: Host, target: Host) { return this === target || this.findAll((node) => node === target).length > 0 }
  })
  state = reactive({
    activeId: 'c1', highlightId: null,
    conversations: [{ id: 'c1', title: 'First chat', unread: 2, archived: false, inherited_from: { title: 'Parent chat' } }],
    showArchived: false, conversationsUnavailable: false,
    search: { open: true, query: 'Match', hits: [hit('one')], nextCursor: 'page2', loading: false, error: '', unavailable: false }
  })
  runSearch = vi.fn()
  moreResults = vi.fn()
  jumpTo = vi.fn()
  vi.doMock('../../src/renderer/src/store', () => ({ state, runSearch, moreResults, jumpTo, isBusy: () => false, select: vi.fn(), newConversation: vi.fn() }))
})

afterEach(() => { mounted?.unmount(); mounted = undefined; vi.unstubAllGlobals() })
async function screen(name: string, props?: Record<string, unknown>) {
  mounted = mount((await import(`../../src/renderer/src/components/${name}.vue`)).default, props)
  await flush()
  return mounted
}

describe('search wiring', () => {
  it('names close and results controls, associates errors, and keeps a focused hit mounted while loading', async () => {
    const view = await screen('SearchPanel')
    const input = view.root.find('input')!
    const button = view.root.findAll((node) => node.props.id === 'search-hit-one')[0]!
    expect(view.root.findAll((node) => node.props['aria-label'] === 'Close search')).toHaveLength(1)
    expect(view.root.find('ul')!.props['aria-label']).toBe('Search results')
    ;(button as any).focus()
    state.search.loading = true
    await flush()
    expect(view.root.findAll((node) => node.props.id === 'search-hit-one')[0]).toBe(button)
    expect(doc.activeElement).toBe(button)
    expect(view.root.button('More results').props.disabled).toBeUndefined()
    expect(view.root.button('More results').props['aria-disabled']).toBe(true)
    state.search.loading = false
    state.search.error = 'Could not search'
    await flush()
    expect(input.props['aria-invalid']).toBe(true)
    expect(input.props['aria-describedby']).toBe('conversation-search-error')
    expect(view.root.findAll((node) => node.props.id === 'conversation-search-error')[0]!.props.role).toBe('alert')
    state.search.unavailable = true
    await flush()
    expect(input.props['aria-invalid']).toBeUndefined()
  })

  it('submits trimmed queries and ignores pagination reactivation while loading', async () => {
    const view = await screen('SearchPanel')
    view.setup.query = '  find me  '
    view.root.find('form')!.fire('submit', { preventDefault() {} })
    expect(runSearch).toHaveBeenCalledWith('find me')
    state.search.loading = true
    await flush()
    await view.root.button('More results').fire('click', { currentTarget: view.root.button('More results') })
    expect(moreResults).not.toHaveBeenCalled()
  })

  it('retains pagination focus during loading and moves to the first new hit after the final page', async () => {
    const view = await screen('SearchPanel')
    const trigger = view.root.button('More results')
    let current: Host | null = trigger
    Object.defineProperty(doc, 'activeElement', {
      configurable: true,
      get: () => current && !(current as Host & { isConnected: boolean }).isConnected ? doc.body : current,
      set: (value: Host | null) => { current = value }
    })
    let complete!: () => void
    moreResults.mockImplementation(() => {
      state.search.loading = true
      return new Promise<void>((resolve) => { complete = () => {
        state.search.hits.push(hit('two'))
        state.search.nextCursor = null
        state.search.loading = false
        resolve()
      } })
    })
    doc.getElementById.mockImplementation((id) => view.root.findAll((node) => node.props.id === id)[0])
    const paging = trigger.fire('click', { currentTarget: trigger })
    await flush()
    expect(doc.activeElement).toBe(trigger)
    expect(view.root.button('More results')).toBe(trigger)
    complete()
    await paging
    expect(doc.activeElement?.props.id).toBe('search-hit-two')
  })

  it('keeps search focus when a new result set removes its focused hit', async () => {
    const view = await screen('SearchPanel')
    let current: Host | null = view.root.findAll((node) => node.props.id === 'search-hit-one')[0]!
    Object.defineProperty(doc, 'activeElement', {
      configurable: true,
      get: () => current && !(current as Host & { isConnected: boolean }).isConnected ? doc.body : current,
      set: (value: Host | null) => { current = value }
    })
    state.search.hits = []
    await flush()
    expect(doc.activeElement).toBe(view.root.find('input'))
  })

  it('focuses a completed message jump only if the initiating hit still owns focus', async () => {
    const view = await screen('SearchPanel')
    const button = view.root.findAll((node) => node.props.id === 'search-hit-one')[0]!
    const message = new Host('article')
    doc.getElementById.mockReturnValue(message)
    jumpTo.mockImplementation(async () => { state.highlightId = 'one' })
    ;(button as any).focus()
    await button.fire('click', { currentTarget: button })
    expect(doc.getElementById).toHaveBeenCalledWith('m-one')
    expect(doc.activeElement).toBe(message)
    jumpTo.mockImplementation(async () => { state.highlightId = 'one'; doc.activeElement = view.root.find('input')! })
    ;(button as any).focus()
    await button.fire('click', { currentTarget: button })
    expect(doc.activeElement).toBe(view.root.find('input'))
  })

  it('restores a connected search opener on close, but does not steal focus from another region', async () => {
    const opener = new Host('button')
    opener.parent = doc.body
    doc.activeElement = opener
    await screen('SearchPanel')
    mounted!.unmount(); mounted = undefined
    expect(doc.activeElement).toBe(opener)
    await screen('SearchPanel')
    const elsewhere = new Host('textarea')
    doc.activeElement = elsewhere
    mounted!.unmount(); mounted = undefined
    expect(doc.activeElement).toBe(elsewhere)
  })
})

describe('conversation and palette naming/semantics', () => {
  it('names child relationships and exposes the current conversation and menu trigger', async () => {
    const view = await screen('ConversationList')
    const current = view.root.findAll((node) => node.props['aria-current'] === 'page')[0]!
    expect(current.props['aria-label']).toBe('First chat, thread from Parent chat')
    const trigger = view.root.findAll((node) => node.props['aria-label'] === 'Actions for First chat')[0]!
    expect(trigger.props['aria-haspopup']).toBe('menu')
    expect(trigger.props['aria-expanded']).toBe(false)
    expect(view.root.button('+ New').props['aria-label']).toBe('New conversation')
  })

  it('uses noninteractive listbox options with stable ids for the composer active descendant', async () => {
    const view = await screen('CommandPalette', { commands: [{ name: 'new', usage: '/new', affects: 'New conversation' }], selected: 0, onPick: vi.fn() })
    expect(view.root.find('ul')!.props.id).toBe('command-palette')
    const option = view.root.find('li')!
    expect(option.props.role).toBe('option')
    expect(option.props.id).toBe('command-option-new')
    expect(option.props['aria-selected']).toBe(true)
    expect(view.root.find('button')).toBeUndefined()
    option.fire('click')
  })
})
