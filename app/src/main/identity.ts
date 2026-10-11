// Packaging identity is not the name users see, nor the Chromium profile root.
import { mkdirSync } from 'node:fs'
import { join, win32 } from 'node:path'
import { localAppData } from './platform/windows-paths'

interface ElectronIdentity {
  setName(name: string): void
  getPath(name: 'appData'): string
  setPath(name: 'userData', path: string): void
  setAppUserModelId?(id: string): void
  readonly isPackaged?: boolean
}

/** electron-builder.yml's appId: the installed app's Start Menu shortcut carries it as its AppUserModelID. */
export const APP_ID = 'net.calmingstorm.odin.desktop'

/** Must run before ready, single-instance admission and any BrowserWindow. */
export function configureIdentity(app: ElectronIdentity, system: NodeJS.Platform = process.platform,
  env: Record<string, string | undefined> = process.env,
  makeDir: (path: string, options: { recursive: true; mode?: number }) => unknown = mkdirSync): void {
  app.setName('Odin')
  if (system === 'win32') {
    // Local, not roaming, AppData (the design's storage rule); a smoke's redirected root carries it too.
    const userData = win32.join(localAppData(env), 'odin-desktop', 'electron')
    makeDir(userData, { recursive: true })
    app.setPath('userData', userData)
    // The installed app's ID matches its shortcut's, so its toasts are its own; a source run has no
    // shortcut, and Electron's guidance for one is its own executable.
    app.setAppUserModelId?.(app.isPackaged ? APP_ID : process.execPath)
    return
  }
  const userData = join(app.getPath('appData'), 'odin-desktop', 'electron')
  makeDir(userData, { recursive: true, mode: 0o700 })
  app.setPath('userData', userData)
}
