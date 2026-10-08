// Keyboard adapter proofs, not Electron native focus qualification.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host, type Mounted } from './component-host'
let views: Mounted[] = []
beforeEach(() => {
  vi.resetModules()
  ;(globalThis as any).document = { activeElement: null }
  ;(globalThis as any).window = { innerWidth: 1180, innerHeight: 780 }
})
afterEach(() => { views.forEach(v => v.unmount()); views = [] })
async function fixture(props: Record<string, unknown> = {}) {
  const action = vi.fn()
  const v = mount((await import('../../src/renderer/src/components/settings/McpMoreMenu.vue')).default, { name: 'docs', enabled: true, busy: false, shownTools: false, onAction: action, ...props }); views.push(v)
  const trigger = v.root.button('More') as any
  const menu = v.root.findAll(n => n.props.role === 'menu')[0] as any
  const controls = menu.children.filter((n: Host) => n.props.role === 'menuitem')
  trigger.focus = vi.fn(); menu.showPopover = vi.fn(); menu.hidePopover = vi.fn()
  menu.querySelectorAll = () => controls.filter((n: Host) => !n.props.disabled)
  controls.forEach((n: any) => { n.focus = vi.fn(() => { (globalThis as any).document.activeElement = n }) })
  return { v, trigger, menu, controls, action }
}
const event = (key: string) => ({ key, preventDefault: vi.fn(), stopPropagation: vi.fn() })
describe('review C MCP More keyboard adapter', () => {
  it('opens with arrows, wraps enabled items, handles Home/End/Escape/Tab, restores opener before dispatch', async () => {
    const { trigger, menu, controls, action } = await fixture()
    trigger.fire('keydown', event('ArrowDown')); await flush(); expect(controls[0].focus).toHaveBeenCalled()
    menu.fire('keydown', event('End')); expect(controls[3].focus).toHaveBeenCalled()
    menu.fire('keydown', event('ArrowDown')); expect(controls[0].focus).toHaveBeenCalledTimes(2)
    menu.fire('keydown', event('Home')); expect(controls[0].focus).toHaveBeenCalledTimes(3)
    menu.fire('keydown', event('ArrowUp')); expect(controls[3].focus).toHaveBeenCalledTimes(2)
    menu.fire('keydown', event('Escape')); await flush(); expect(trigger.focus).toHaveBeenCalled()
    trigger.fire('keydown', event('ArrowUp')); await flush(); expect(controls[3].focus).toHaveBeenCalledTimes(3)
    await controls[3].fire('click'); expect(action).toHaveBeenCalledWith('remove')
    expect(trigger.focus.mock.invocationCallOrder.at(-1)).toBeLessThan(action.mock.invocationCallOrder[0]!)
    trigger.fire('click'); await flush(); const tab = event('Tab'); menu.fire('keydown', tab); await flush(); expect(tab.preventDefault).not.toHaveBeenCalled()
    const ordinary = event('q'); menu.fire('keydown', ordinary); expect(ordinary.preventDefault).not.toHaveBeenCalled()
  })
  it('handles native outside-dismissal state, disabled actions, all emitted actions and opener toggle', async () => {
    const { trigger, menu, controls, action } = await fixture({ enabled: false })
    trigger.fire('click'); await flush(); expect(controls[2].focus).toHaveBeenCalled()
    menu.fire('toggle', { newState: 'closed' }); await flush(); expect(trigger.props['aria-expanded']).toBe(false)
    await controls[0].fire('click'); await controls[1].fire('click'); expect(action).not.toHaveBeenCalled()
    const busy = await fixture({ busy: true }); await busy.controls[3].fire('click'); busy.trigger.fire('click'); await flush(); expect(busy.action).not.toHaveBeenCalled(); expect(busy.trigger.props['aria-expanded']).toBe(false)
    const enabled = await fixture({ shownTools: true })
    for (const [i, name] of ['reconnect', 'refresh', 'tools', 'remove'].entries()) { await enabled.controls[i].fire('click'); expect(enabled.action).toHaveBeenLastCalledWith(name) }
    enabled.trigger.getBoundingClientRect = () => ({ bottom: 80, right: 170 })
    enabled.trigger.fire('click'); await flush(); expect(enabled.menu.props.style).toEqual({ top: '84px', left: '8px' })
    enabled.trigger.fire('click'); await flush(); expect(enabled.trigger.props['aria-expanded']).toBe(false)
    enabled.menu.fire('toggle', { newState: 'open' }); await flush(); expect(enabled.trigger.props['aria-expanded']).toBe(true)
  })
})
