import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { autostartEntry, autostartPath, autostartStatus, isAutostartEnabled, quoteExecArg, setAutostart } from '../src/main/autostart'

const dirs: string[] = []
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true })
})

describe('start at login (R2)', () => {
  it('starts Odin minimized to the tray', () => {
    const entry = autostartEntry(['/opt/Odin/odin-desktop'])
    expect(entry).toContain('Exec=/opt/Odin/odin-desktop --hidden')
    expect(entry).toContain('X-GNOME-Autostart-enabled=true')
  })

  it('quotes arguments per the Desktop Entry spec', () => {
    expect(quoteExecArg('/plain/path')).toBe('/plain/path')
    expect(quoteExecArg('/with space/odin')).toBe('"/with space/odin"')
    expect(quoteExecArg('a"b$c')).toBe('"a\\"b\\$c"')
    expect(quoteExecArg('100%')).toBe('100%%')
  })

  it('writes and removes the XDG autostart entry', () => {
    const home = mkdtempSync(join(tmpdir(), 'odin-autostart-'))
    dirs.push(home)
    const path = autostartPath({ XDG_CONFIG_HOME: home })
    expect(isAutostartEnabled(path)).toBe(false)
    expect(setAutostart(true, ['/opt/Odin/odin-desktop'], path)).toBe(true)
    expect(readFileSync(path, 'utf8')).toContain('--hidden')
    expect(setAutostart(false, ['/opt/Odin/odin-desktop'], path)).toBe(false)
  })

  it('detects AppImage relocation without mutating the launcher, then repairs on explicit enable', () => {
    const home = mkdtempSync(join(tmpdir(), 'odin-autostart-'))
    dirs.push(home)
    const path = autostartPath({ XDG_CONFIG_HOME: home })
    const old = ['/home/owner/Applications with spaces/Odin 0.1.AppImage']
    const relocated = ['/home/owner/New Applications/Odin 0.2.AppImage']
    expect(autostartStatus(old, path)).toBe('disabled')
    setAutostart(true, old, path)
    const saved = readFileSync(path, 'utf8')
    expect(autostartStatus(old, path)).toBe('enabled')
    expect(autostartStatus(relocated, path)).toBe('stale')
    expect(isAutostartEnabled(path, relocated)).toBe(false)
    expect(readFileSync(path, 'utf8')).toBe(saved)
    expect(setAutostart(true, relocated, path)).toBe(true)
    expect(readFileSync(path, 'utf8')).toBe(autostartEntry(relocated))
  })

  it('same-path image replacement keeps the autostart command consistent', () => {
    const home = mkdtempSync(join(tmpdir(), 'odin-autostart-'))
    dirs.push(home)
    const path = autostartPath({ XDG_CONFIG_HOME: home })
    const command = ['/home/owner/Applications/Odin current.AppImage']
    setAutostart(true, command, path)
    expect(autostartStatus(command, path)).toBe('enabled')
    expect(readFileSync(path, 'utf8')).not.toContain('/tmp/.mount_')
  })

  it('rejects field injection in an autostart executable name', () => {
    for (const argument of ['image\nExec=other', 'image\rName=other', 'image\0other']) {
      expect(() => autostartEntry([argument])).toThrow('invalid autostart argument')
    }
  })
})
