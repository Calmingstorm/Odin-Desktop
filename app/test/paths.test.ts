import { mkdtempSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { ensureProfileDirs, ensureToken, profilePaths } from '../src/main/paths'

const dirs: string[] = []
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true })
})

function tempEnv() {
  const root = mkdtempSync(join(tmpdir(), 'odin-paths-'))
  dirs.push(root)
  return {
    HOME: root,
    XDG_CONFIG_HOME: join(root, 'config'),
    XDG_DATA_HOME: join(root, 'data'),
    XDG_CACHE_HOME: join(root, 'cache'),
    XDG_RUNTIME_DIR: join(root, 'run')
  }
}

describe('profile paths', () => {
  it('keeps everything under the user’s own XDG roots', () => {
    const env = tempEnv()
    const p = profilePaths('default', env)
    expect(p.socketPath).toBe(join(env.XDG_RUNTIME_DIR, 'odin-desktop', 'default', 'core.sock'))
    expect(p.tokenPath.startsWith(env.XDG_CONFIG_HOME)).toBe(true)
    expect(JSON.stringify(p)).not.toContain('/opt/odin')
  })

  it('refuses unsafe profile names', () => {
    expect(() => profilePaths('../x', tempEnv())).toThrow()
    expect(() => profilePaths('A', tempEnv())).toThrow()
  })

  it('creates owner-only directories and a stable owner-only token', () => {
    const p = profilePaths('default', tempEnv())
    ensureProfileDirs(p)
    expect(statSync(p.configDir).mode & 0o777).toBe(0o700)
    const token = ensureToken(p)
    expect(token).toMatch(/^[0-9a-f]{64}$/)
    expect(statSync(p.tokenPath).mode & 0o777).toBe(0o600)
    expect(ensureToken(p)).toBe(token)
  })

  it('replaces a malformed token file', () => {
    const p = profilePaths('default', tempEnv())
    ensureProfileDirs(p)
    writeFileSync(p.tokenPath, 'garbage', { mode: 0o644 })
    expect(ensureToken(p)).toMatch(/^[0-9a-f]{64}$/)
    expect(statSync(p.tokenPath).mode & 0o777).toBe(0o600)
  })
})
