import { describe, expect, it } from 'vitest'
import { EventEmitter } from 'node:events'
import { decideSecondInstance, decideWindowClose, EarlyRequests, parseLaunchFlags, showWhenReady, StartVisibility } from '../src/main/lifecycle'

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

describe('early open and Exit requests', () => {
  it('records what arrives before the handlers exist, and an Exit wins over an open', () => {
    const app = new EventEmitter()
    const nothing = new EarlyRequests(app)
    expect(nothing.release()).toBeNull()
    const open = new EarlyRequests(app)
    app.emit('activate')
    expect(open.release()).toBe('open')
    const launch = new EarlyRequests(app)
    app.emit('second-instance', {}, ['/opt/odin-desktop/odin'])
    expect(launch.release()).toBe('open')
    const exit = new EarlyRequests(app)
    app.emit('second-instance', {}, ['/opt/odin-desktop/odin'])
    app.emit('second-instance', {}, ['/opt/odin-desktop/odin', '--exit'])
    app.emit('activate')
    expect(exit.release()).toBe('exit')
  })

  it('stops listening once released', () => {
    const app = new EventEmitter()
    const early = new EarlyRequests(app)
    expect(app.listenerCount('second-instance')).toBe(1)
    expect(app.listenerCount('activate')).toBe(1)
    expect(early.release()).toBeNull()
    expect(app.listenerCount('second-instance')).toBe(0)
    expect(app.listenerCount('activate')).toBe(0)
    app.emit('second-instance', {}, ['x', '--exit'])
    expect(early.release()).toBeNull()
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

describe('first-show visibility', () => {
  it('reads the login flag at readiness, not before: one reported as launching finishes still hides', () => {
    let reported = false // macOS reports a login item's start only as launching finishes
    const reads: boolean[] = []
    const visibility = new StartVisibility(false)
    reported = true
    expect(reads).toEqual([]) // nothing is read while the app starts
    visibility.ready(() => { reads.push(reported); return reported })
    expect(reads).toEqual([true])
    expect(visibility.wanted).toBe(false)
  })

  it('keeps --hidden hidden, shows an ordinary start, and lets an explicit open win in any order', () => {
    const ordinary = new StartVisibility(false)
    ordinary.ready(() => false)
    expect(ordinary.wanted).toBe(true)
    const hidden = new StartVisibility(true)
    hidden.ready(() => false)
    expect(hidden.wanted).toBe(false)
    hidden.request() // the tray or a second instance
    expect(hidden.wanted).toBe(true)
    const early = new StartVisibility(false)
    early.request() // an open before readiness still wins over a login start
    early.ready(() => true)
    expect(early.wanted).toBe(true)
    const linux = new StartVisibility(false)
    linux.ready(undefined) // no login flag on Linux or Windows: --hidden is their login start
    expect(linux.wanted).toBe(true)
  })
})

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
