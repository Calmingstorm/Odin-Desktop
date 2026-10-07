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

// Electron emits ready-to-show on the window and did-finish-load on its webContents.
function hiddenWindow() {
  return Object.assign(new EventEmitter(), {
    visible: false, destroyed: false, shows: 0,
    isDestroyed() { return this.destroyed },
    isVisible() { return this.visible },
    show() { this.shows += 1; this.visible = true },
    webContents: new EventEmitter()
  })
}

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
