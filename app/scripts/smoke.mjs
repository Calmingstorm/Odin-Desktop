// Launches the built app on an isolated virtual display (xvfb) with a throwaway profile, waits for the core
// handshake, saves a screenshot, and exits through the normal Exit path. It never touches the real desktop session,
// the user's real Odin Desktop profile, or their autostart entries.
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, chmodSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const appDir = resolve(import.meta.dirname, '..')
const root = mkdtempSync(join(tmpdir(), 'odin-smoke-'))
const runtime = join(root, 'run')
mkdirSync(runtime, { mode: 0o700 })
chmodSync(runtime, 0o700)
const out = process.env.ODIN_SMOKE_OUT || join(root, 'smoke.png')

const env = { ...process.env }
for (const key of ['DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY']) delete env[key]
Object.assign(env, {
  HOME: root,
  XDG_CONFIG_HOME: join(root, 'config'),
  XDG_DATA_HOME: join(root, 'data'),
  XDG_CACHE_HOME: join(root, 'cache'),
  XDG_RUNTIME_DIR: runtime,
  ODIN_SMOKE_OUT: out
})
// This gate explicitly chooses the fixture, even if a developer shell is using
// a real-core override for a different task. No fallback is tested here.
delete env.ODIN_SMOKE_REAL_CORE
delete env.ODIN_DESKTOP_CORE_CMD

const electron = join(appDir, 'node_modules', '.bin', 'electron')
const result = spawnSync('xvfb-run', ['-a', '-s', '-screen 0 1280x800x24', electron, appDir, '--smoke-test'], {
  env,
  encoding: 'utf8',
  timeout: 90_000
})
process.stdout.write(result.stdout ?? '')
process.stderr.write((result.stderr ?? '').split('\n').filter((l) => !/dbus|Fontconfig|gpu_|viz_main|ui_base/i.test(l)).join('\n'))
const ok = result.status === 0 && /smoke: ok link=ready/.test(result.stdout ?? '') && existsSync(out)
console.log(`\nsmoke ${ok ? 'PASSED' : 'FAILED'} (exit ${result.status})${ok ? ` screenshot: ${out}` : ''}`)
if (!process.env.ODIN_SMOKE_KEEP) rmSync(root, { recursive: true, force: true })
process.exit(ok ? 0 : 1)
