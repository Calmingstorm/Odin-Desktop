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
  installLogoutHook: installKdeLogoutHook
}
