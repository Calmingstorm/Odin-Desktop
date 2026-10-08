// Object-renderer keyboard/dispatch proofs. Native focus is checked separately.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host, type Mounted } from './component-host'
let views: Mounted[] = []
beforeEach(() => {
  vi.resetModules()
  vi.stubGlobal('document', { activeElement: null })
  vi.stubGlobal('window', { innerWidth: 1180, innerHeight: 780 })
})
afterEach(() => { views.forEach(v => v.unmount()); views = []; vi.unstubAllGlobals() })
async function fixture(props: Record<string, unknown> = {}) {
  const action = vi.fn()
  const v = mount((await import('../../src/renderer/src/components/settings/AccountMoreMenu.vue')).default,
    { accountId: 1, name: 'Secondary', busy: false, refreshDisabled: false, canRename: true, onAction: action, ...props })
  views.push(v)
  const trigger = v.root.button('More') as any
  const menu = v.root.findAll(n => n.props.role === 'menu')[0] as any
  const controls = menu.children.filter((n: Host) => n.props.role === 'menuitem')
  trigger.focus = vi.fn(); menu.showPopover = vi.fn(); menu.hidePopover = vi.fn()
  menu.querySelectorAll = () => controls.filter((n: Host) => !n.props.disabled)
  controls.forEach((n: any) => { n.focus = vi.fn(() => { (globalThis as any).document.activeElement = n }) })
  return { trigger, menu, controls, action }
}
const event = (key: string) => ({ key, preventDefault: vi.fn(), stopPropagation: vi.fn() })
describe('account More menu', () => {
  it('uses a stable per-account id, roving arrows/Home/End, Escape/Tab and opener restoration before dispatch', async () => {
    const { trigger, menu, controls, action } = await fixture()
    expect(trigger.props['aria-controls']).toBe('account-more-1')
    trigger.fire('keydown', event('ArrowDown')); await flush(); expect(controls[0].focus).toHaveBeenCalled()
    menu.fire('keydown', event('End')); expect(controls[2].focus).toHaveBeenCalled()
    menu.fire('keydown', event('ArrowDown')); expect(controls[0].focus).toHaveBeenCalledTimes(2)
    menu.fire('keydown', event('Home')); expect(controls[0].focus).toHaveBeenCalledTimes(3)
    menu.fire('keydown', event('ArrowUp')); expect(controls[2].focus).toHaveBeenCalledTimes(2)
    menu.fire('keydown', event('Escape')); await flush(); expect(trigger.props['aria-expanded']).toBe(false)
    trigger.fire('keydown', event('ArrowUp')); await flush(); expect(controls[2].focus).toHaveBeenCalledTimes(3)
    for (const [index, name] of ['refresh', 'rename', 'remove'].entries()) {
      await controls[index].fire('click'); expect(action).toHaveBeenLastCalledWith(name)
      expect(trigger.focus.mock.invocationCallOrder.at(-1)).toBeLessThan(action.mock.invocationCallOrder.at(-1)!)
    }
    trigger.fire('click'); await flush()
    const tab = event('Tab'); menu.fire('keydown', tab); await flush(); expect(tab.preventDefault).not.toHaveBeenCalled()
    menu.fire('keydown', event('q'))
  })
  it('preserves busy/stale and refresh gates, optional rename, popover dismissal and bounded positioning', async () => {
    const busy = await fixture({ busy: true })
    busy.trigger.fire('click'); await flush(); expect(busy.trigger.props['aria-expanded']).toBe(false)
    for (const control of busy.controls) { await control.fire('click'); expect(control.props.disabled).toBe(true) }
    expect(busy.action).not.toHaveBeenCalled()
    const restricted = await fixture({ refreshDisabled: true, canRename: false })
    expect(restricted.controls).toHaveLength(2)
    restricted.trigger.fire('click'); await flush(); expect(restricted.controls[1].focus).toHaveBeenCalled()
    await restricted.controls[0].fire('click'); expect(restricted.action).not.toHaveBeenCalled()
    restricted.menu.fire('toggle', { newState: 'closed' }); await flush(); expect(restricted.trigger.props['aria-expanded']).toBe(false)
    restricted.trigger.getBoundingClientRect = () => ({ bottom: 780, right: 1180 })
    restricted.trigger.fire('click'); await flush(); expect(restricted.menu.props.style).toEqual({ top: '630px', left: '972px' })
    restricted.trigger.fire('click'); await flush(); expect(restricted.trigger.props['aria-expanded']).toBe(false)
  })
})
