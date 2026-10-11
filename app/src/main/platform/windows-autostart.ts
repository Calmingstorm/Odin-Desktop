// Start at login for the installed Windows app (phase 4, P10): Electron's login items, which write an HKCU Run value
// named for this app (its AppUserModelID). The entry runs the installed executable itself with --hidden, never a source
// command or interpreter; a source run keeps start at login unavailable (Settings shows why). It reads as on only when
// that owned entry is registered in the user's scope with exactly this executable and arguments and Windows will run
// it: an entry with other arguments (stale), one disabled from Task Manager's Startup page, or someone else's entry for
// the same executable reads as off, and enabling rewrites and re-approves the owned one.
import { app } from 'electron'
import { APP_ID } from '../identity'

export const AUTOSTART_UNAVAILABLE = 'Start at login comes with the installed Windows app.'
const ARGS = ['--hidden']

type LaunchItem = { name: string; path: string; args: string[]; scope: string; enabled: boolean }
type LoginItems = Pick<typeof app, 'isPackaged' | 'setLoginItemSettings'> & {
  getLoginItemSettings(options: { path: string; args: string[] }): { launchItems?: LaunchItem[] }
  readonly execPath?: string
}

function executable(electron: LoginItems): string {
  return electron.execPath ?? process.execPath
}

/** Whether Windows will start the installed app at login through the entry this app owns. */
export function windowsAutostartEnabled(_path?: string, _command?: readonly string[],
  electron: LoginItems = app): boolean {
  if (!electron.isPackaged) return false
  const exe = executable(electron)
  const owned = electron.getLoginItemSettings({ path: exe, args: ARGS }).launchItems
    ?.find((item) => item.name === APP_ID && item.scope === 'user')
  return !!owned && owned.enabled === true && owned.path.toLowerCase() === exe.toLowerCase()
    && owned.args.length === ARGS.length && owned.args.every((arg, index) => arg === ARGS[index])
}

/** Register (and approve) or remove the owned login entry; return the state Windows now reports. */
export function setWindowsAutostart(enabled: boolean, _command?: readonly string[], _path?: string,
  electron: LoginItems = app): boolean {
  if (!electron.isPackaged) throw new Error(AUTOSTART_UNAVAILABLE)
  electron.setLoginItemSettings({ openAtLogin: enabled, enabled, name: APP_ID, path: executable(electron), args: ARGS })
  return windowsAutostartEnabled(undefined, undefined, electron)
}
