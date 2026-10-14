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

/** The part of Electron's app the early listeners use. */
export interface EarlyRequestSource {
  on(event: 'second-instance', listener: (event: unknown, argv: string[]) => void): unknown
  on(event: 'activate', listener: () => void): unknown
  removeListener(event: 'second-instance', listener: (event: unknown, argv: string[]) => void): unknown
  removeListener(event: 'activate', listener: () => void): unknown
}

/** Opens and Exits asked for before the app's own handlers exist. A packaged start checks ownership
 * first, asynchronously; another launch (its argv) or a Dock click arriving meanwhile had no listener
 * and was lost. These record it until the handlers are attached, which then replay it. */
export class EarlyRequests {
  private exit = false
  private open = false
  private readonly onSecondInstance = (_event: unknown, argv: string[]): void => {
    if (decideSecondInstance(argv) === 'exit') this.exit = true
    else this.open = true
  }

  private readonly onActivate = (): void => { this.open = true }

  constructor(private readonly source: EarlyRequestSource) {
    source.on('second-instance', this.onSecondInstance)
    source.on('activate', this.onActivate)
  }

  /** Stop recording and say what was asked: an Exit wins over an open. */
  release(): 'exit' | 'open' | null {
    this.source.removeListener('second-instance', this.onSecondInstance)
    this.source.removeListener('activate', this.onActivate)
    return this.exit ? 'exit' : this.open ? 'open' : null
  }
}

/** Whether the first window shows. --hidden and a login item's start stay hidden; an open asked for at any time
 * (a second instance, the Dock, the tray) shows it, whichever comes first. The login flag is read once the app is
 * ready, never before: macOS reports it as launching finishes (Electron 44 fills wasOpenedAtLogin in
 * applicationDidFinishLaunching, just before ready), so an earlier read says false and a login start would show. */
export class StartVisibility {
  private login = false
  private requested = false
  constructor(private readonly hidden: boolean) {}
  /** At readiness, before the window is created. */
  ready(openedAtLogin?: () => boolean): void { this.login = openedAtLogin?.() === true }
  request(): void { this.requested = true }
  get wanted(): boolean { return this.requested || (!this.hidden && !this.login) }
}

/** The part of a BrowserWindow the first-show rule uses. */
export interface FirstShowWindow {
  once(event: 'ready-to-show', listener: () => void): unknown
  once(event: 'show', listener: () => void): unknown
  isDestroyed(): boolean
  isVisible(): boolean
  show(): void
  webContents: { once(event: 'did-finish-load', listener: () => void): unknown }
}

/** Show a window created hidden once it is ready: on ready-to-show, or once its page has
 * loaded. A hidden window may never paint under Wayland, so waiting for ready-to-show alone
 * left a fresh launch with no window at all on GNOME and KDE.
 *
 * This is one decision, made by whichever event comes first. Once the window has been shown
 * by anyone, including an explicit Open, the later event never shows it again: a Close in
 * between must stick. */
export function showWhenReady(win: FirstShowWindow, wanted: () => boolean): void {
  let decided = false
  win.once('show', () => { decided = true })
  const decide = (): void => {
    if (decided) return
    decided = true
    if (wanted() && !win.isDestroyed() && !win.isVisible()) win.show()
  }
  win.once('ready-to-show', decide)
  win.webContents.once('did-finish-load', decide)
}
