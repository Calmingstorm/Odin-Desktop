// The app's operating-system pieces. A platform is chosen once at startup; Linux hands back today's modules, so
// Linux behaviour can't change through this seam. Signatures are the Linux functions' own.
import type { isAutostartEnabled, setAutostart } from '../autostart'
import type { acquirePackagedApp, admitPackagedApp } from '../package-ownership'
import type { inspectPackagedState } from '../package-state'
import type { ensureProfileDirs, ensureToken, profilePaths } from '../paths'
import type { installKdeLogoutHook, startSessionMonitor } from '../session-logout'

export interface AppPlatform {
  readonly name: string
  /** Where the profile's config, data, cache, runtime folder and engine endpoint live. */
  profilePaths: typeof profilePaths
  ensureProfileDirs: typeof ensureProfileDirs
  ensureToken: typeof ensureToken
  /** Start at login. */
  isAutostartEnabled: typeof isAutostartEnabled
  setAutostart: typeof setAutostart
  /** Why start at login isn't offered, where it isn't (Settings shows it and disables the switch). */
  autostartUnavailable?: string
  /** The installed package's ownership and state, checked before the first window. */
  inspectPackagedState: typeof inspectPackagedState
  acquirePackagedApp: typeof acquirePackagedApp
  admitPackagedApp: typeof admitPackagedApp
  /** Ending the user's session: a monitor, plus the desktop's own logout hook where one is needed. */
  startSessionMonitor: typeof startSessionMonitor
  installLogoutHook: typeof installKdeLogoutHook
}
