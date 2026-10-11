// Start at login for the installed Windows app (phase 4, P10): Electron's login items, which write the HKCU Run
// entry. The entry runs the installed executable itself with --hidden, never a source command or interpreter; a
// source run keeps start at login unavailable (Settings shows why). It reads as on only when this exact entry is
// registered and Windows will run it: an entry with other arguments (stale) or one disabled from Task Manager's
// Startup page reads as off, and enabling it again rewrites and re-approves it.
import { app } from 'electron'

export const AUTOSTART_UNAVAILABLE = 'Start at login comes with the installed Windows app.'

type LoginItems = Pick<typeof app, 'isPackaged' | 'getLoginItemSettings' | 'setLoginItemSettings'> &
  { readonly execPath?: string }

function entry(electron: LoginItems): { path: string; args: string[] } {
  return { path: electron.execPath ?? process.execPath, args: ['--hidden'] }
}

/** Whether Windows will start the installed app at login: registered and not disabled. */
export function windowsAutostartEnabled(_path?: string, _command?: readonly string[],
  electron: LoginItems = app): boolean {
  if (!electron.isPackaged) return false
  const settings = electron.getLoginItemSettings(entry(electron))
  return settings.openAtLogin === true && settings.executableWillLaunchAtLogin === true
}

/** Register (and approve) or remove the installed app's login entry; return the state Windows now reports. */
export function setWindowsAutostart(enabled: boolean, _command?: readonly string[], _path?: string,
  electron: LoginItems = app): boolean {
  if (!electron.isPackaged) throw new Error(AUTOSTART_UNAVAILABLE)
  electron.setLoginItemSettings({ openAtLogin: enabled, enabled, ...entry(electron) })
  return windowsAutostartEnabled(undefined, undefined, electron)
}
