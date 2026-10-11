// Windows: the profile under local AppData (windows-paths.ts), session end, and the installed app's members (phase 4):
// the shared package lease through the bundled guardian, start at login through Electron's login items, and the
// refusal of an elevated start. A source run has no installed-app members: start at login stays unavailable.
import { app, BrowserWindow } from 'electron'
import type { CoreLaunch } from '../core-command'
import { acquirePackagedApp, admitPackagedApp } from '../package-ownership'
import { inspectPackagedState } from '../package-state'
import type { AppPlatform } from './contracts'
import { AUTOSTART_UNAVAILABLE, setWindowsAutostart, windowsAutostartEnabled } from './windows-autostart'
import { elevatedStartRefusal } from './windows-elevation'
import { ensureWindowsProfileDirs, ensureWindowsToken, windowsProfilePaths } from './windows-paths'

export { AUTOSTART_UNAVAILABLE }

/** Session end: `session-end` reaches every window; each is subscribed once and forgotten when it closes. */
export function windowsSessionMonitor(_launch: CoreLaunch, onEnd: () => void,
  electron: { app: typeof app; BrowserWindow: typeof BrowserWindow } = { app, BrowserWindow }): { close(): void } {
  const watched = new Map<BrowserWindow, () => void>()
  let ended = false
  const end = (): void => {
    if (ended) return
    ended = true
    onEnd()
  }
  const watch = (win: BrowserWindow): void => {
    if (watched.has(win) || win.isDestroyed()) return
    const forget = (): void => {
      win.removeListener('session-end', end)
      watched.delete(win)
    }
    win.on('session-end', end)
    win.once('closed', forget)
    watched.set(win, forget)
  }
  const created = (_event: unknown, win: BrowserWindow): void => watch(win)
  for (const win of electron.BrowserWindow.getAllWindows()) watch(win)
  electron.app.on('browser-window-created', created)
  return {
    close: () => {
      electron.app.removeListener('browser-window-created', created)
      for (const forget of [...watched.values()]) forget()
    }
  }
}

export const windowsPlatform: AppPlatform = {
  name: 'windows',
  profilePaths: windowsProfilePaths,
  ensureProfileDirs: ensureWindowsProfileDirs,
  ensureToken: ensureWindowsToken,
  isAutostartEnabled: (path, command) => windowsAutostartEnabled(path, command),
  setAutostart: (enabled, command, path) => setWindowsAutostart(enabled, command, path),
  // Only a source run lacks start at login: its command would need its core selection.
  get autostartUnavailable() {
    return app.isPackaged ? undefined : AUTOSTART_UNAVAILABLE
  },
  // The Linux modules choose Windows' interpreter and the nsis lease by the system they run on.
  inspectPackagedState,
  acquirePackagedApp,
  admitPackagedApp,
  startRefusal: () => elevatedStartRefusal(),
  startSessionMonitor: (launch, onEnd) => windowsSessionMonitor(launch, onEnd),
  installLogoutHook: () => null
}
