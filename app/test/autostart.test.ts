import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { autostartEntry, autostartPath, isAutostartEnabled, quoteExecArg, setAutostart } from '../src/main/autostart'

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
})
