import { describe, expect, it } from 'vitest'
import { EventEmitter } from 'node:events'
import { decideSecondInstance, decideWindowClose, parseLaunchFlags, showWhenReady } from '../src/main/lifecycle'

describe('lifecycle (D3)', () => {
  it('closing the window hides it and keeps Odin running', () => {
    expect(decideWindowClose({ quitting: false, trayAvailable: true, noTrayNoticeShown: false })).toEqual({
      action: 'hide',
      showNoTrayNotice: false
    })
  })

  it('without a tray, the first close shows the still-running notice once', () => {
    expect(decideWindowClose({ quitting: false, trayAvailable: false, noTrayNoticeShown: false }).showNoTrayNotice).toBe(true)
    expect(decideWindowClose({ quitting: false, trayAvailable: false, noTrayNoticeShown: true }).showNoTrayNotice).toBe(false)
  })

  it('only Exit lets the window actually close', () => {
    expect(decideWindowClose({ quitting: true, trayAvailable: false, noTrayNoticeShown: false })).toEqual({
      action: 'allow',
      showNoTrayNotice: false
    })
  })

  it('a second launch focuses the app; --exit stops it', () => {
    expect(decideSecondInstance(['/opt/odin-desktop/odin'])).toBe('focus')
    expect(decideSecondInstance(['/opt/odin-desktop/odin', '--exit'])).toBe('exit')
  })

  it('parses launch flags', () => {
    expect(parseLaunchFlags(['x', '--hidden'])).toEqual({ exit: false, hidden: true, smokeTest: false })
  })
})

// Electron emits ready-to-show and show on the window, and did-finish-load on its webContents.
class HiddenWindow extends EventEmitter {
  visible = false
  destroyed = false
  shows = 0
  webContents = new EventEmitter()
  isDestroyed(): boolean { return this.destroyed }
  isVisible(): boolean { return this.visible }
  show(): void { this.shows += 1; this.visible = true; this.emit('show') }
}
const hiddenWindow = (): HiddenWindow => new HiddenWindow()

describe('first window show', () => {
  it('shows a window whose page loaded but never painted (Wayland)', () => {
    const win = hiddenWindow()
    showWhenReady(win, () => true)
    win.webContents.emit('did-finish-load')
    expect(win.shows).toBe(1)
  })

  it('shows on ready-to-show once, however the two events are ordered', () => {
    for (const order of [['ready-to-show', 'did-finish-load'], ['did-finish-load', 'ready-to-show']]) {
      const win = hiddenWindow()
      showWhenReady(win, () => true)
      for (const event of order) (event === 'ready-to-show' ? win : win.webContents).emit(event)
      expect(win.shows).toBe(1)
    }
  })

  it('a Close between the two events sticks, in either order', () => {
    const orders: Array<[string, string]> = [['ready-to-show', 'did-finish-load'], ['did-finish-load', 'ready-to-show']]
    for (const [first, second] of orders) {
      const win = hiddenWindow()
      showWhenReady(win, () => true)
      ;(first === 'ready-to-show' ? win : win.webContents).emit(first)
      win.visible = false // Close hides the window and keeps Odin running
      ;(second === 'ready-to-show' ? win : win.webContents).emit(second)
      expect(win.shows).toBe(1)
    }
  })

  it('an explicit Open and Close before the page is ready is not undone', () => {
    const win = hiddenWindow()
    showWhenReady(win, () => true)
    win.show() // tray Open during startup
    win.visible = false // then Close
    win.webContents.emit('did-finish-load')
    win.emit('ready-to-show')
    expect(win.shows).toBe(1)
  })

  it('a renderer lost before its first load still gets one first show on reload', () => {
    const win = hiddenWindow()
    showWhenReady(win, () => true)
    win.webContents.emit('did-finish-load') // the reloaded page
    win.visible = false
    win.emit('ready-to-show')
    expect(win.shows).toBe(1)
  })

  it('keeps a --hidden launch hidden', () => {
    const win = hiddenWindow()
    showWhenReady(win, () => false)
    win.emit('ready-to-show')
    win.webContents.emit('did-finish-load')
    expect(win.shows).toBe(0)
  })

  it('shows nothing once Exit has started or the window is gone', () => {
    let quitting = false
    const exiting = hiddenWindow()
    showWhenReady(exiting, () => !quitting)
    quitting = true
    exiting.webContents.emit('did-finish-load')
    const destroyed = hiddenWindow()
    showWhenReady(destroyed, () => true)
    destroyed.destroyed = true
    destroyed.webContents.emit('did-finish-load')
    expect([exiting.shows, destroyed.shows]).toEqual([0, 0])
  })
})
