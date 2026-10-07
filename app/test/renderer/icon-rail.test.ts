// The rail on Vue's plain-object renderer: real component and store code, a stubbed preload bridge.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host } from './component-host'
import IconRail from '../../src/renderer/src/components/IconRail.vue'
import { state } from '../../src/renderer/src/store'
import { work } from '../../src/renderer/src/stores/work'

function named(root: Host, label: string): Host {
  const found = root.findAll((host) => host.tag === 'button' && host.props['aria-label'] === label)
  if (found.length !== 1) throw new Error(`expected one "${label}" button, found ${found.length}`)
  return found[0]!
}

describe('the rail', () => {
  const setAppearance = vi.fn(async (appearance: string) => ({ ok: true, result: { appearance } }))
  beforeEach(() => {
    vi.stubGlobal('window', { odin: { setAppearance } })
    state.view = 'chat'
    state.dark = true
    state.appearance = 'system'
    work.open = false
    work.items = []
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    setAppearance.mockClear()
  })

  it('names every control and marks the current view', async () => {
    const { root, unmount } = mount(IconRail)
    await flush()
    const nav = root.find('nav')!
    expect(nav.props['aria-label']).toBe('Odin')
    expect(named(root, 'Chats').props['aria-current']).toBe('page')
    expect(named(root, 'Settings').props['aria-current']).toBeUndefined()
    expect(named(root, 'Settings').props.title).toBe('Settings (Ctrl+,)')
    expect(named(root, 'Work').props['aria-expanded']).toBe(false)
    // Icons are decorative; each button's name is its label.
    expect(root.findAll((host) => host.tag === 'svg').every((svg) => svg.props['aria-hidden'] === 'true')).toBe(true)
    state.view = 'settings'
    await flush()
    expect(named(root, 'Chats').props['aria-current']).toBeUndefined()
    expect(named(root, 'Settings').props['aria-current']).toBe('page')
    unmount()
  })

  it('switches to the other theme and saves the choice through the bridge', async () => {
    const { root, unmount } = mount(IconRail)
    await flush()
    named(root, 'Switch to light theme').fire('click')
    await flush()
    expect(setAppearance).toHaveBeenCalledExactlyOnceWith('light')
    expect(state.appearance).toBe('light')
    // The theme in effect comes from the page's colour scheme, which the saved choice drives.
    state.dark = false
    await flush()
    named(root, 'Switch to dark theme').fire('click')
    await flush()
    expect(setAppearance).toHaveBeenLastCalledWith('dark')
    expect(state.appearance).toBe('dark')
    unmount()
  })

  it('counts active work in the Work name and opens Work beside the chat, also from settings', async () => {
    work.items = [
      { id: 'a', kind: 'agent', state: 'running' }, { id: 'p', kind: 'process', state: 'stopping' },
      { id: 'd', kind: 'task', state: 'completed' }
    ] as never
    const { root, unmount } = mount(IconRail)
    await flush()
    const button = named(root, 'Work, 2 active')
    expect(button.textContent()).toBe('2')
    button.fire('click')
    await flush()
    expect(work.open).toBe(true)
    expect(named(root, 'Work, 2 active').props['aria-expanded']).toBe(true)
    named(root, 'Work, 2 active').fire('click')
    await flush()
    expect(work.open).toBe(false)
    state.view = 'settings'
    await flush()
    named(root, 'Work, 2 active').fire('click')
    await flush()
    expect(state.view).toBe('chat')
    expect(work.open).toBe(true)
    unmount()
  })
})
