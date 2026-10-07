import { mkdtempSync, readFileSync, writeFileSync, existsSync, statSync, rmSync, symlinkSync, mkdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, test } from 'vitest'
import { installKdeLogoutHook, kdeLogoutHook, sessionMonitorCommand } from '../src/main/session-logout'

const roots: string[] = []
function environment(): NodeJS.ProcessEnv {
  const root = mkdtempSync(join(tmpdir(), 'odin-logout-')); roots.push(root)
  return { XDG_CONFIG_HOME: root, XDG_CURRENT_DESKTOP: 'KDE' }
}
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }) })

test('only Plasma installs the hook, and only exact owned bytes are removed', () => {
  const env = environment()
  expect(installKdeLogoutHook(['/bin/true'], { ...env, XDG_CURRENT_DESKTOP: 'GNOME' })).toBeNull()
  const hook = installKdeLogoutHook(['/bin/true'], env, 123)!
  expect(statSync(hook.path).mode & 0o777).toBe(0o700)
  expect(readFileSync(hook.path, 'utf8')).toBe(kdeLogoutHook(['/bin/true'], 123))
  writeFileSync(hook.path, 'user-owned')
  hook.remove()
  expect(readFileSync(hook.path, 'utf8')).toBe('user-owned')
  expect(installKdeLogoutHook(['/bin/true'], env)).toBeNull()
})
test('clean Exit removes its hook; absent manager and unwritable config fail open', () => {
  const env = environment()
  const hook = installKdeLogoutHook(['/bin/true'], env, 123)!
  hook.remove()
  expect(existsSync(hook.path)).toBe(false)
  rmSync(join(env.XDG_CONFIG_HOME!, 'plasma-workspace', 'shutdown'), { recursive: true })
  writeFileSync(join(env.XDG_CONFIG_HOME!, 'plasma-workspace', 'shutdown'), 'not a directory')
  expect(installKdeLogoutHook(['/bin/true'], env)).toBeNull()
})
test('shell quoting preserves launcher arguments and bounds the complete handoff', () => {
  const text = kdeLogoutHook(["/path/with 'quote'/odin", 'a;$(false)'], 123)
  expect(text).toContain('timeout -k 1s 8s')
  expect(text).toContain('kill -0 123')
  expect(text).toContain('--exit')
  expect(() => kdeLogoutHook(['bad\narg'], 123)).toThrow()
})
test('monitor uses the exact selected runtime, retains isolated flags, never a fixture fallback', () => {
  const launch = { command: '/bundle/python', args: ['-I', '-B', '-m', 'src', '--profile', 'default'], env: {} }
  expect(sessionMonitorCommand(launch)).toEqual({ ...launch, args: ['-I', '-B', '-m', 'src.desktop.session_end'] })
  expect(sessionMonitorCommand({ ...launch, args: ['/fixture.py'] })).toBeNull()
})
test('stale owner identity never invokes even a harmless replacement launcher', () => {
  const env = environment()
  const output = join(env.XDG_CONFIG_HOME!, 'invoked')
  const script = kdeLogoutHook(['/usr/bin/touch', output], process.pid, '0')
  expect(spawnSync('/bin/sh', ['-c', script]).status).toBe(0)
  expect(existsSync(output)).toBe(false)
})
test('foreign symlink is never followed or replaced', () => {
  const env = environment()
  const target = join(env.XDG_CONFIG_HOME!, 'foreign')
  writeFileSync(target, 'do not touch')
  const directory = join(env.XDG_CONFIG_HOME!, 'plasma-workspace', 'shutdown')
  mkdirSync(directory, { recursive: true })
  symlinkSync(target, join(directory, 'odin-desktop.sh'))
  expect(installKdeLogoutHook(['/bin/true'], env)).toBeNull()
  expect(readFileSync(target, 'utf8')).toBe('do not touch')
})
