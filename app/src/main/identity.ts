// Packaging identity is not the name users see, nor the Chromium profile root.
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

interface ElectronIdentity {
  setName(name: string): void
  getPath(name: 'appData'): string
  setPath(name: 'userData', path: string): void
}

/** Must run before ready, single-instance admission and any BrowserWindow. */
export function configureIdentity(app: ElectronIdentity): void {
  app.setName('Odin')
  const userData = join(app.getPath('appData'), 'odin-desktop', 'electron')
  mkdirSync(userData, { recursive: true, mode: 0o700 })
  app.setPath('userData', userData)
}
