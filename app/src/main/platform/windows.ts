// Windows, from a source checkout (phase 3d): the profile under local AppData (windows-paths.ts), session end, and no
// installed-app members yet: start at login and package ownership come with the installed app (phase 4).
import { app, BrowserWindow } from 'electron'
import type { CoreLaunch } from '../core-command'
import type { AppPlatform } from './contracts'
import { elevatedStartRefusal } from './windows-elevation'
import { ensureWindowsProfileDirs, ensureWindowsToken, windowsProfilePaths } from './windows-paths'

export const AUTOSTART_UNAVAILABLE = 'Start at login comes with the installed Windows app.'
const PACKAGED_UNAVAILABLE = 'The installed Windows app comes with phase 4.'

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

function packagedUnavailable(): never {
  throw new Error(PACKAGED_UNAVAILABLE)
}

export const windowsPlatform: AppPlatform = {
  name: 'windows',
  profilePaths: windowsProfilePaths,
  ensureProfileDirs: ensureWindowsProfileDirs,
  ensureToken: ensureWindowsToken,
  // Start at login needs the installed app's launcher: a source run's command needs its core selection.
  isAutostartEnabled: () => false,
  setAutostart: () => {
    throw new Error(AUTOSTART_UNAVAILABLE)
  },
  autostartUnavailable: AUTOSTART_UNAVAILABLE,
  inspectPackagedState: () => packagedUnavailable(),
  acquirePackagedApp: async () => packagedUnavailable(),
  admitPackagedApp: async () => packagedUnavailable(),
  startRefusal: () => elevatedStartRefusal(),
  startSessionMonitor: (launch, onEnd) => windowsSessionMonitor(launch, onEnd),
  installLogoutHook: () => null
}
