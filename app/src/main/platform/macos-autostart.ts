// Start at login on macOS (phase 4): the installed app itself as a login item, SMAppService's main app service through
// Electron's login items. Electron 44.5.1 reports openAtLogin from the service status, so only `enabled` reads as on
// (shell/browser/browser_mac.mm). A login start is recognised by wasOpenedAtLogin, set from the launch Apple event's
// keyAELaunchedAsLogInItem (shell/browser/mac/electron_application_delegate.mm), and is hidden as --hidden is on Linux.
// When turning it on leaves it needing the user's approval, System Settings opens at Login Items: nothing works around
// that approval. A source run has no bundle to register, so start at login stays unavailable there.
import { app, shell } from 'electron'

export const AUTOSTART_UNAVAILABLE = 'Start at login comes with the installed Mac app.'
export const LOGIN_ITEMS_SETTINGS = 'x-apple.systempreferences:com.apple.LoginItems-Settings.extension'

export interface LoginItems {
  readonly isPackaged: boolean
  getLoginItemSettings(): { openAtLogin: boolean; wasOpenedAtLogin?: boolean; status?: string }
  setLoginItemSettings(settings: { openAtLogin: boolean }): void
}

/** Whether macOS will open the installed app at login: its login item is registered and enabled. */
export function macosAutostartEnabled(electron: LoginItems = app): boolean {
  return electron.isPackaged && electron.getLoginItemSettings().openAtLogin === true
}

/** Register or remove the app's login item; return the state macOS now reports. */
export function setMacosAutostart(enabled: boolean, electron: LoginItems = app,
  openSettings: (url: string) => Promise<void> = (url) => shell.openExternal(url)): boolean {
  if (!electron.isPackaged) throw new Error(AUTOSTART_UNAVAILABLE)
  electron.setLoginItemSettings({ openAtLogin: enabled })
  if (enabled && electron.getLoginItemSettings().status === 'requires-approval') {
    void openSettings(LOGIN_ITEMS_SETTINGS).catch(() => undefined)
  }
  return macosAutostartEnabled(electron)
}

/** Whether this start is the login item's: the window then stays hidden. */
export function macosOpenedAtLogin(electron: LoginItems = app): boolean {
  return electron.isPackaged && electron.getLoginItemSettings().wasOpenedAtLogin === true
}
