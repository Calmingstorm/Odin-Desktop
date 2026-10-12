// Start at login for the installed Windows app (phase 4, P10): Electron's login items, which write an HKCU Run value
// named for this app (its AppUserModelID). The entry runs the installed executable itself with --hidden, never a source
// command or interpreter; a source run keeps start at login unavailable (Settings shows why).
//
// It reads as on only when both hold, as pinned Electron 44.5.1 reports them (shell/browser/browser_win.cc):
// - openAtLogin: the Run value named for this app's AppUserModelID is exactly this executable with --hidden (the
//   quoted executable, then each argument quoted as needed), so a missing or extra switch reads as off;
// - the owned launch item (that name, in the user's Run key) is enabled in StartupApproved, so an entry turned off
//   from Task Manager reads as off whatever other entries for the same executable say.
// Both reads get the executable quoted: openAtLogin strips one pair of surrounding quotes before quoting it again, and
// the launch items parse the path as a command line, where an unquoted path stops at its first space. A launch item's
// args never show --hidden: Chromium's CommandLine counts it as a switch, and args are the positional arguments.
import { app } from 'electron'
import { APP_ID } from '../identity'

export const AUTOSTART_UNAVAILABLE = 'Start at login comes with the installed Windows app.'
const ARGS = ['--hidden']

type LaunchItem = { name: string; path: string; args: string[]; scope: string; enabled: boolean }
type LoginItems = Pick<typeof app, 'isPackaged' | 'setLoginItemSettings'> & {
  getLoginItemSettings(options: { path: string; args: string[] }): { openAtLogin: boolean; launchItems?: LaunchItem[] }
  readonly execPath?: string
}

function executable(electron: LoginItems): string {
  return electron.execPath ?? process.execPath
}

/** Whether Windows will start the installed app at login through the entry this app owns, exactly as registered. */
export function windowsAutostartEnabled(_path?: string, _command?: readonly string[],
  electron: LoginItems = app): boolean {
  if (!electron.isPackaged) return false
  const settings = electron.getLoginItemSettings({ path: `"${executable(electron)}"`, args: ARGS })
  const owned = settings.launchItems?.find((item) => item.name === APP_ID && item.scope === 'user')
  return settings.openAtLogin === true && owned?.enabled === true
}

/** Register (and approve) or remove the owned login entry; return the state Windows now reports. */
export function setWindowsAutostart(enabled: boolean, _command?: readonly string[], _path?: string,
  electron: LoginItems = app): boolean {
  if (!electron.isPackaged) throw new Error(AUTOSTART_UNAVAILABLE)
  electron.setLoginItemSettings({ openAtLogin: enabled, enabled, name: APP_ID, path: executable(electron), args: ARGS })
  return windowsAutostartEnabled(undefined, undefined, electron)
}
