// macOS: the profile under ~/Library (macos-paths.ts), start at login as the app's own login item
// (macos-autostart.ts), a template image in the menu bar, and the installed app's members shared with Linux (the
// package lease is the per-user `macos` kind). Logout, restart and shut down reach Exit through index.ts's powerMonitor `shutdown` handler, which stops
// Electron's quit until Exit has finished; macOS needs no other session monitor or logout hook.
import { app } from 'electron'
import { acquirePackagedApp, admitPackagedApp } from '../package-ownership'
import { inspectPackagedState } from '../package-state'
import { ensureProfileDirs, ensureToken } from '../paths'
import type { AppPlatform } from './contracts'
import { AUTOSTART_UNAVAILABLE, macosAutostartEnabled, macosOpenedAtLogin, setMacosAutostart } from './macos-autostart'
import { macosProfilePaths } from './macos-paths'

export { AUTOSTART_UNAVAILABLE }

export const macosPlatform: AppPlatform = {
  name: 'macos',
  profilePaths: macosProfilePaths,
  ensureProfileDirs,
  ensureToken,
  isAutostartEnabled: () => macosAutostartEnabled(),
  setAutostart: (enabled) => setMacosAutostart(enabled),
  // Only a source run lacks start at login: it has no bundle to register.
  get autostartUnavailable() {
    return app.isPackaged ? undefined : AUTOSTART_UNAVAILABLE
  },
  openedAtLogin: () => macosOpenedAtLogin(),
  trayIcon: 'trayTemplate.png',
  // The shared modules choose the macOS interpreter layout, guardian and lease kind by the system they run on.
  inspectPackagedState,
  acquirePackagedApp,
  admitPackagedApp,
  startSessionMonitor: () => null,
  installLogoutHook: () => null
}
