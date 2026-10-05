// Shared real-core gate. All imports/launches of the engine happen after entering the PID namespace.
import { spawn, spawnSync } from 'node:child_process'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const script = fileURLToPath(import.meta.url)
export const repositoryRoot = resolve(dirname(script), '../..')

export function assertRealCoreIsolation() {
  if (process.platform !== 'linux' || !process.getuid || process.getuid() === 0) {
    throw new Error('Real-core gates require Linux and an unprivileged test user, never root.')
  }
  const outer = process.env.ODIN_REAL_CORE_OUTER_PID_NS
  if (!outer || readlinkSync('/proc/self/ns/pid') === outer) {
    throw new Error('Real-core gate refused: not in a separate PID namespace. Use scripts/real-core-test.mjs or launchIsolated().')
  }
  const init = readFileSync('/proc/1/cmdline', 'utf8').split('\0')
  if (!init.includes(script) || !init.includes('--inside-run')) {
    throw new Error('Real-core gate refused: namespace PID 1 is not the isolation runner.')
  }
  const root = process.env.ODIN_REAL_CORE_ROOT
  if (!root || process.env.HOME !== root || !root.startsWith(join(tmpdir(), 'odrc-'))) {
    throw new Error('Real-core gate refused: throwaway HOME is missing.')
  }
  for (const [key, leaf] of Object.entries({
    XDG_CONFIG_HOME: 'config', XDG_DATA_HOME: 'data', XDG_CACHE_HOME: 'cache', XDG_RUNTIME_DIR: 'run'
  })) {
    if (process.env[key] !== join(root, leaf)) throw new Error(`Real-core gate refused: unsafe ${key}.`)
  }
}

/**
 * Resolves only on exit 0; streams the child output; rejects clearly otherwise.
 * The command and its entire process tree run under unshare, with the caller's uid/gid and a private HOME/XDG.
 * `env` is a sanitized overlay (not inherited wholesale). HOME/XDG/display/session overrides are forbidden.
 * Engine Python is explicit ODIN_DESKTOP_ENGINE_PYTHON or repository .venv/bin/python, never a host fallback.
 */
export async function launchIsolated(command, args = [], { env = {}, cwd = repositoryRoot, timeoutMs = 120_000 } = {}) {
  if (process.platform !== 'linux' || !process.getuid || process.getuid() === 0) {
    throw new Error('Real-core isolation requires Linux and a non-root caller. No privileged tests are permitted.')
  }
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1) throw new Error('Expected a positive timeoutMs.')
  const python = resolve(cwd, env.ODIN_DESKTOP_ENGINE_PYTHON || process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python'))
  if (!existsSync(python)) {
    throw new Error('Engine Python is absent. Set ODIN_DESKTOP_ENGINE_PYTHON to an installed Python 3.12 engine environment, or provision repository .venv with the engine dependencies. This gate never skips.')
  }
  if (!existsSync(join(repositoryRoot, 'src/desktop/core.py'))) throw new Error('Repository real core is absent; no fixture fallback is allowed.')
  const allowed = /^(ODIN_DESKTOP_[A-Z0-9_]+|ODIN_APP_[A-Z0-9_]+|ODIN_SMOKE_[A-Z0-9_]+|CI|DEBUG|NODE_OPTIONS|ELECTRON_[A-Z0-9_]+)$/
  for (const key of Object.keys(env)) {
    if (!allowed.test(key)) throw new Error(`Isolation env override is not allowed: ${key}`)
  }
  const root = mkdtempSync(join(tmpdir(), 'odrc-'))
  chmodSync(root, 0o700)
  const safeEnv = {
    PATH: '/usr/local/bin:/usr/bin:/bin', LANG: 'C.UTF-8', HOME: root,
    XDG_CONFIG_HOME: join(root, 'config'), XDG_DATA_HOME: join(root, 'data'),
    XDG_CACHE_HOME: join(root, 'cache'), XDG_RUNTIME_DIR: join(root, 'run'),
    PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1',
    ...env, ODIN_DESKTOP_ENGINE_PYTHON: python, ODIN_REAL_CORE_ROOT: root,
    ODIN_REAL_CORE_OUTER_PID_NS: readlinkSync('/proc/self/ns/pid'),
    ODIN_REAL_CORE_TIMEOUT_MS: String(timeoutMs)
  }
  for (const dir of ['config', 'data', 'cache', 'run']) mkdirSync(join(root, dir), { mode: 0o700 })
  try {
    await new Promise((accept, reject) => {
      // env -i explicitly drops DISPLAY, WAYLAND_DISPLAY, DBUS, desktop tokens and all ambient application state.
      const child = spawn('sudo', ['-n', 'unshare', '--pid', '--fork', '--mount-proc', '--kill-child=KILL',
        'setpriv', `--reuid=${process.getuid()}`, `--regid=${process.getgid()}`, '--clear-groups', '--no-new-privs',
        'env', '-i', ...Object.entries(safeEnv).map(([key, value]) => `${key}=${value}`),
        process.execPath, script, '--inside-run', resolve(cwd), command, ...args], { stdio: 'inherit' })
      const timer = setTimeout(() => child.kill('SIGTERM'), timeoutMs + 10_000)
      const escalation = setTimeout(() => child.kill('SIGKILL'), timeoutMs + 15_000)
      child.once('error', (error) => { clearTimeout(timer); clearTimeout(escalation); reject(error) })
      child.once('exit', (code, signal) => {
        clearTimeout(timer); clearTimeout(escalation)
        if (code === 0) accept()
        else reject(new Error(`Isolated real-core gate failed (exit ${code}, signal ${signal ?? 'none'}). Verify sudo -n unshare --pid --fork --mount-proc and setpriv are available; no unisolated fallback or silent skip is allowed.`))
      })
    })
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
}

async function inside() {
  assertRealCoreIsolation()
  const [, , , cwd, command, ...args] = process.argv
  process.chdir(repositoryRoot)
  const preflight = spawnSync(process.env.ODIN_DESKTOP_ENGINE_PYTHON, ['-P', '-c',
    'import sys, pathlib; assert sys.version_info[:2] == (3, 12), "Engine requires Python 3.12"; import src.__main__, src.desktop.core; assert pathlib.Path(src.desktop.core.__file__).resolve() == pathlib.Path("src/desktop/core.py").resolve(), "Imported a different core"'],
  { encoding: 'utf8', timeout: 20_000 })
  if (preflight.error || preflight.status !== 0) {
    // The sanitized environment carries no credentials. Import diagnostics explain absent dependencies.
    throw new Error(`Real engine import preflight failed. Install the repository engine dependencies in ODIN_DESKTOP_ENGINE_PYTHON (or .venv). No fixture fallback.\n${preflight.error?.message ?? ''}\n${preflight.stderr ?? ''}`)
  }
  process.chdir(cwd)
  const child = spawn(command, args, { cwd, stdio: 'inherit' })
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    console.error('Isolated real-core gate timed out; terminating its namespace.')
    child.kill('SIGTERM')
    setTimeout(() => process.exit(124), 3_000)
  }, Number(process.env.ODIN_REAL_CORE_TIMEOUT_MS))
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { child.kill(signal); setTimeout(() => process.exit(128), 3_000) })
  child.once('error', (error) => { clearTimeout(timer); console.error(error.message); process.exitCode = 1 })
  child.once('exit', (code, signal) => { clearTimeout(timer); process.exit(timedOut ? 124 : code ?? (signal ? 1 : 0)) })
}

if (process.argv[1] && resolve(process.argv[1]) === script && process.argv[2] === '--inside-run') {
  inside().catch((error) => { console.error(error.message); process.exitCode = 1 })
}
