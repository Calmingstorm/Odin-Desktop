import { EventEmitter } from 'node:events'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WindowStateController, loadWindowState, objectRecord, reachableTitlebar, restoreWindowState, validBounds,
  windowBackend, type Bounds, type WindowState } from '../src/main/window-state'
const primary = { id: 1, workArea: { x: 0, y: 30, width: 1280, height: 770 }, scaleFactor: 1 }
const negative = { id: 2, workArea: { x: -1920, y: -1080, width: 1920, height: 1080 }, scaleFactor: 2 }
const initial: WindowState = { version: 1, normalBounds: { x: 50, y: 60, width: 900, height: 600 }, maximized: false }
const stateAt = (bounds: Bounds, maximized = false): WindowState => ({ version: 1, normalBounds: bounds, maximized })
class FakeWindow extends EventEmitter {
  bounds = { ...initial.normalBounds }
  maximized = false
  minimized = false
  fullscreen = false
  destroyed = false
  minimum = [720, 480]
  isDestroyed() { return this.destroyed }
  isMaximized() { return this.maximized }
  isMinimized() { return this.minimized }
  isFullScreen() { return this.fullscreen }
  getNormalBounds() { return this.bounds }
  setBounds(bounds: Partial<Bounds>) { this.bounds = { ...this.bounds, ...bounds }; this.emit('resize') }
  setMinimumSize(width: number, height: number) { this.minimum = [width, height] }
}
afterEach(() => vi.useRealTimers())
describe('DIP restore validation', () => {
  it.each([null, [], 'x', 1, true])('rejects top-level nonobjects %j', (value) => {
    expect(objectRecord(value)).toEqual({}); expect(loadWindowState(value)).toBeNull()
  })
  it.each([null, {}, [], { ...initial, version: 2 }, { ...initial, maximized: 'yes' },
    stateAt({ x: NaN, y: 0, width: 900, height: 600 }), stateAt({ x: Infinity, y: 0, width: 900, height: 600 }),
    stateAt({ x: 1e12, y: 0, width: 900, height: 600 }), stateAt({ x: 0, y: 0, width: 0, height: 600 }),
    { ...initial, normalBounds: { x: '1', y: 0, width: 900, height: 600 } }])('repairs malformed/absurd %j', (value) => {
    expect(loadWindowState(value)).toBeNull()
    expect(restoreWindowState(value, [primary], 1, 'x11').options)
      .toEqual({ x: 50, y: 30, width: 1180, height: 770, minWidth: 720, minHeight: 480 })
  })
  it('rounds DIP without scale multiplication, retaining negative monitor coordinates', () => {
    expect(restoreWindowState(stateAt({ x: -1700.3, y: -900.4, width: 900.2, height: 600.1 }), [primary, negative], 1, 'x11').state.normalBounds)
      .toEqual({ x: -1700, y: -900, width: 900, height: 600 })
    expect(validBounds({ x: 0, y: 0, width: .2, height: 600 })).toBeNull()
  })
  it('requires titlebar not only body, and repairs lost monitors on primary', () => {
    expect(restoreWindowState(stateAt({ x: -1700, y: -900, width: 900, height: 600 }), [primary], 1, 'x11').state.normalBounds)
      .toEqual({ x: 190, y: 115, width: 900, height: 600 })
    const bodyOnly = { x: 50, y: -200, width: 900, height: 600 }
    expect(reachableTitlebar(bodyOnly, primary.workArea)).toBe(false)
    expect(restoreWindowState(stateAt(bodyOnly), [primary], 1, 'x11').state.normalBounds.y).toBe(115)
    expect(reachableTitlebar({ ...bodyOnly, y: 20 }, primary.workArea)).toBe(false)
    expect(reachableTitlebar({ ...bodyOnly, y: 30 }, primary.workArea)).toBe(true)
  })
  it('clamps dimensions and positions after workarea/DPI changes', () => {
    expect(restoreWindowState(initial, [{ ...primary, scaleFactor: 2, workArea: { x: 0, y: 40, width: 800, height: 550 } }], 1, 'x11').state.normalBounds)
      .toEqual({ x: 0, y: 40, width: 800, height: 550 })
  })
  it('fits minimums to tiny workarea', () => {
    const tiny = { id: 1, workArea: { x: -10, y: 15, width: 80, height: 20 } }
    const restored = restoreWindowState(initial, [tiny], 1, 'x11')
    expect(restored.options).toEqual({ x: -10, y: 15, width: 80, height: 20, minWidth: 80, minHeight: 20 })
    expect(reachableTitlebar(restored.state.normalBounds, tiny.workArea)).toBe(true)
  })
  it('native Wayland and unknown omit coordinates, preserving size/maximize only', () => {
    for (const backend of ['wayland', 'unknown'] as const) {
      const restored = restoreWindowState({ ...initial, maximized: true }, [primary], 1, backend)
      expect(restored.options).toEqual({ width: 900, height: 600, minWidth: 720, minHeight: 480 })
      expect(restored.state.maximized).toBe(true)
    }
    expect(windowBackend('linux', 'x11')).toBe('x11'); expect(windowBackend('linux', 'wayland')).toBe('wayland')
    expect(windowBackend('linux', '')).toBe('unknown'); expect(windowBackend('linux', 'auto')).toBe('unknown')
    expect(windowBackend('darwin', 'x11')).toBe('unknown')
  })
  it('defends against missing/invalid display data', () => {
    expect(restoreWindowState(null, [{ id: 1, workArea: { x: 0, y: 0, width: -1, height: 0 } }], 1, 'x11').options.width).toBe(1180)
  })
})
describe('event capture and best effort lifecycle', () => {
  it('debounces writes, keeps current snapshot for other writes, flush cancels timer', () => {
    vi.useFakeTimers()
    const win = new FakeWindow(), save = vi.fn(), controller = new WindowStateController(win, initial, save, 'x11')
    win.setBounds({ x: 80 }); vi.advanceTimersByTime(200); win.setBounds({ width: 950 })
    expect(controller.snapshot().normalBounds).toEqual({ x: 80, y: 60, width: 950, height: 600 })
    expect(save).not.toHaveBeenCalled(); vi.advanceTimersByTime(250); expect(save).toHaveBeenCalledTimes(1)
    win.setBounds({ y: 90 }); controller.flush(); expect(save).toHaveBeenCalledTimes(2)
    vi.advanceTimersByTime(500); expect(save).toHaveBeenCalledTimes(2)
    controller.dispose(); expect(win.listenerCount('resize')).toBe(0)
  })
  it('retains normal geometry and max flag across min/fullscreen transient bounds', () => {
    vi.useFakeTimers()
    const win = new FakeWindow(), controller = new WindowStateController(win, initial, vi.fn(), 'x11')
    win.maximized = true; win.emit('maximize'); expect(controller.snapshot().maximized).toBe(true)
    win.minimized = true; win.bounds = { x: 0, y: 0, width: 1, height: 1 }; win.emit('resize'); controller.flush()
    expect(controller.snapshot()).toEqual({ ...initial, maximized: true })
    win.minimized = false; win.fullscreen = true; win.emit('resize'); controller.flush()
    expect(controller.snapshot()).toEqual({ ...initial, maximized: true })
    win.fullscreen = false; win.bounds = { ...initial.normalBounds }; win.maximized = false; win.emit('unmaximize')
    expect(controller.snapshot()).toEqual(initial); controller.dispose()
  })
  it('repairs unplugged monitor after unmaximize rather than capturing stale normal bounds', () => {
    vi.useFakeTimers()
    const win = new FakeWindow(); win.bounds = { x: -1700, y: -900, width: 900, height: 600 }; win.maximized = true
    const controller = new WindowStateController(win, stateAt(win.bounds, true), vi.fn(), 'x11')
    controller.repair([primary], 1); expect(controller.snapshot().normalBounds.x).toBe(190); expect(win.bounds.x).toBe(-1700)
    controller.flush(); expect(controller.snapshot().normalBounds.x).toBe(190)
    win.maximized = false; win.emit('unmaximize')
    expect(win.bounds).toEqual({ x: 190, y: 115, width: 900, height: 600 }); expect(controller.snapshot().maximized).toBe(false)
    controller.dispose()
  })
  it.each(['minimized', 'fullscreen'] as const)('defers tiny display repair while %s then restores', (mode) => {
    vi.useFakeTimers()
    const win = new FakeWindow(), controller = new WindowStateController(win, initial, vi.fn(), 'x11')
    win[mode] = true; controller.repair([{ id: 1, workArea: { x: 0, y: 0, width: 200, height: 100 } }], 1)
    expect(win.minimum).toEqual([200, 100]); win[mode] = false; win.emit(mode === 'minimized' ? 'restore' : 'leave-full-screen')
    expect(win.bounds).toEqual({ x: 0, y: 0, width: 200, height: 100 }); controller.dispose()
  })
  it('Wayland repair sends no position', () => {
    vi.useFakeTimers()
    const win = new FakeWindow(), spy = vi.spyOn(win, 'setBounds'), controller = new WindowStateController(win, initial, vi.fn(), 'wayland')
    controller.repair([primary], 1); expect(spy).toHaveBeenCalledWith({ width: 900, height: 600 }); controller.dispose()
  })
  it('destroyed windows and failed disk writes do not throw or leave timers live', () => {
    vi.useFakeTimers()
    const win = new FakeWindow(), save = vi.fn(() => { throw new Error('disk unavailable') }), controller = new WindowStateController(win, initial, save, 'x11')
    win.emit('move'); expect(() => vi.advanceTimersByTime(250)).not.toThrow(); win.destroyed = true
    expect(() => controller.repair([primary], 1)).not.toThrow(); expect(() => controller.flush()).not.toThrow()
    expect(controller.snapshot()).toEqual(initial); controller.dispose(); controller.flush(); win.emit('move'); expect(vi.getTimerCount()).toBe(0)
  })
  it('native destruction race and repair failures cannot break best effort flush', () => {
    vi.useFakeTimers()
    const win = new FakeWindow(), save = vi.fn(), controller = new WindowStateController(win, initial, save, 'x11')
    vi.spyOn(win, 'getNormalBounds').mockImplementation(() => { throw new Error('native ending') })
    expect(() => win.emit('resize')).not.toThrow(); expect(() => controller.flush()).not.toThrow()
    vi.spyOn(win, 'setMinimumSize').mockImplementation(() => { throw new Error('native ending') })
    expect(() => controller.repair([primary], 1)).not.toThrow(); expect(() => controller.dispose()).not.toThrow()
    expect(save).toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0)
  })
  it('hidden startup maximize retains known normal rectangle across misleading native bounds', () => {
    vi.useFakeTimers()
    const win = new FakeWindow(), controller = new WindowStateController(win, { ...initial, maximized: true }, vi.fn(), 'x11')
    win.bounds = { x: 0, y: 30, width: 1280, height: 770 }; win.emit('resize')
    win.maximized = true; win.emit('maximize'); controller.flush()
    expect(controller.snapshot()).toEqual({ ...initial, maximized: true })
    win.maximized = false; win.emit('unmaximize')
    expect(win.bounds).toEqual(initial.normalBounds); expect(controller.snapshot()).toEqual(initial)
    controller.dispose()
  })
})
