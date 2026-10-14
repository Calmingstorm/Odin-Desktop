// Linux: today's modules, unchanged.
import { isAutostartEnabled, setAutostart } from '../autostart'
import { acquirePackagedApp, admitPackagedApp } from '../package-ownership'
import { inspectPackagedState } from '../package-state'
import { ensureProfileDirs, ensureToken, profilePaths } from '../paths'
import { installKdeLogoutHook, startSessionMonitor } from '../session-logout'
import type { AppPlatform } from './contracts'

export const linuxPlatform: AppPlatform = {
  name: 'linux',
  profilePaths,
  ensureProfileDirs,
  ensureToken,
  isAutostartEnabled,
  setAutostart,
  inspectPackagedState,
  acquirePackagedApp,
  admitPackagedApp,
  startSessionMonitor,
  installLogoutHook: installKdeLogoutHook,
  // maximize() shows a hidden window here too (Electron 44, X11 and Wayland share the views window), so a start at
  // login keeps a saved maximized window for its first show.
  maximizeOnFirstShow: true
}
