// App lifecycle rules (decision D3), kept free of Electron so they can be tested directly.
//
// - Closing the window hides it; Odin keeps working.
// - Exit (tray menu, window menu, or the launcher's `--exit` action) is the only way to stop Odin.
// - A second launch focuses the running app instead of starting another Odin.

export interface LifecycleState {
  quitting: boolean
  trayAvailable: boolean
  noTrayNoticeShown: boolean
}

export interface CloseDecision {
  /** 'hide' keeps the app (and Odin) running; 'allow' lets the window close because we are exiting. */
  action: 'hide' | 'allow'
  /** Show the one-time "Odin is still running" notice: only when there is no tray to reopen from. */
  showNoTrayNotice: boolean
}

export function decideWindowClose(state: LifecycleState): CloseDecision {
  if (state.quitting) return { action: 'allow', showNoTrayNotice: false }
  return { action: 'hide', showNoTrayNotice: !state.trayAvailable && !state.noTrayNoticeShown }
}

export interface LaunchFlags {
  exit: boolean
  hidden: boolean
  smokeTest: boolean
}

export function parseLaunchFlags(argv: readonly string[]): LaunchFlags {
  return {
    exit: argv.includes('--exit'),
    hidden: argv.includes('--hidden'),
    smokeTest: argv.includes('--smoke-test')
  }
}

/** What a second launch asks the running instance to do. */
export function decideSecondInstance(argv: readonly string[]): 'exit' | 'focus' {
  return parseLaunchFlags(argv).exit ? 'exit' : 'focus'
}

/** The part of a BrowserWindow the first-show rule uses. */
export interface FirstShowWindow {
  once(event: 'ready-to-show', listener: () => void): unknown
  isDestroyed(): boolean
  isVisible(): boolean
  show(): void
  webContents: { once(event: 'did-finish-load', listener: () => void): unknown }
}

/** Show a window created hidden once it is ready: on ready-to-show, or once its page has
 * loaded. A hidden window may never paint under Wayland, so waiting for ready-to-show alone
 * left a fresh launch with no window at all on GNOME and KDE. */
export function showWhenReady(win: FirstShowWindow, wanted: () => boolean): void {
  const show = (): void => {
    if (wanted() && !win.isDestroyed() && !win.isVisible()) win.show()
  }
  win.once('ready-to-show', show)
  win.webContents.once('did-finish-load', show)
}
