import { mkdtempSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { configureIdentity } from '../src/main/identity'
import { profilePaths } from '../src/main/paths'

const roots: string[] = []
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }) })

describe('Electron identity before ready', () => {
  it('uses Odin for native UI and a private Chromium subtree separate from engine profiles', () => {
    const home = mkdtempSync(join(tmpdir(), 'odin-identity-'))
    roots.push(home)
    const appData = join(home, '.config')
    const app = { setName: vi.fn(), getPath: vi.fn(() => appData), setPath: vi.fn() }
    configureIdentity(app)
    const chromium = join(appData, 'odin-desktop', 'electron')
    expect(app.setName).toHaveBeenCalledExactlyOnceWith('Odin')
    expect(app.getPath).toHaveBeenCalledExactlyOnceWith('appData')
    expect(app.setPath).toHaveBeenCalledExactlyOnceWith('userData', chromium)
    expect(statSync(chromium).mode & 0o777).toBe(0o700)
    expect(chromium).not.toBe(profilePaths('default', { HOME: home }).configDir)
    expect(app.setName.mock.invocationCallOrder[0]!).toBeLessThan(app.setPath.mock.invocationCallOrder[0]!)
  })

  it('respects Electron’s XDG appData root and can reuse the Chromium directory', () => {
    const root = mkdtempSync(join(tmpdir(), 'odin-identity-xdg-'))
    roots.push(root)
    const app = { setName: vi.fn(), getPath: vi.fn(() => root), setPath: vi.fn() }
    configureIdentity(app)
    configureIdentity(app)
    expect(app.setPath).toHaveBeenLastCalledWith('userData', join(root, 'odin-desktop', 'electron'))
  })
})
