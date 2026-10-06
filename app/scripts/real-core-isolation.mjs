// Shared real-core gate. All imports/launches of the engine happen after entering the PID namespace.
import { spawn, spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const script = fileURLToPath(import.meta.url)
export const repositoryRoot = resolve(dirname(script), '../..')

const helper = '/usr/local/sbin/odin-desktop-isolate'
const xdg = { XDG_CONFIG_HOME: 'config', XDG_DATA_HOME: 'data', XDG_CACHE_HOME: 'cache', XDG_RUNTIME_DIR: 'run' }
const outerEnv = { PATH: '/usr/local/bin:/usr/bin:/bin', LANG: 'C.UTF-8' }

// The injected primitives are only for focused fake tests. The public launcher below always uses native primitives.
export function createIsolationLauncher({ process: host = process, files = fs, spawnChild = spawn,
  temporaryDirectory = tmpdir, schedule = setTimeout, unschedule = clearTimeout } = {}) {
  function caller() {
    if (host.platform !== 'linux' || !host.getuid || !host.geteuid || !host.getgid || !host.getegid ||
        host.getuid() === 0 || host.getgid() === 0 || host.getuid() !== host.geteuid() || host.getgid() !== host.getegid()) {
      throw new Error('Real-core isolation requires Linux and an unchanged non-root numeric UID/GID. No privileged tests are permitted.')
    }
    return { uid: host.getuid(), gid: host.getgid() }
  }

  function assertRealCoreIsolation(mode = '--inside-run') {
    const { uid, gid } = caller()
    const numeric = /^(0|[1-9][0-9]*)$/
    const expectedUid = host.env.ODIN_REAL_CORE_UID
    const expectedGid = host.env.ODIN_REAL_CORE_GID
    if (!numeric.test(expectedUid ?? '') || !numeric.test(expectedGid ?? '') ||
        Number(expectedUid) !== uid || Number(expectedGid) !== gid) {
      throw new Error('Real-core gate refused: invoking numeric UID/GID was not preserved.')
    }
    const namespace = files.readlinkSync('/proc/self/ns/pid')
    if (!host.env.ODIN_REAL_CORE_OUTER_PID_NS || namespace === host.env.ODIN_REAL_CORE_OUTER_PID_NS ||
        host.pid !== 1 || files.readlinkSync('/proc/1/ns/pid') !== namespace) {
      throw new Error('Real-core gate refused: PID 1 and a separate PID namespace with private /proc are required.')
    }
    const init = files.readFileSync('/proc/1/cmdline', 'utf8').split('\0')
    if (!['--inside-run', '--inside-probe'].includes(mode) || init[0] !== host.execPath ||
        init[1] !== script || init[2] !== mode || host.argv[1] !== script || host.argv[2] !== mode) {
      throw new Error('Real-core gate refused: namespace PID 1 is not the exact isolation runner.')
    }
    const status = files.readFileSync('/proc/self/status', 'utf8')
    if (!/^CapEff:\s+0+$/m.test(status) || !/^CapBnd:\s+0+$/m.test(status) ||
        !/^NoNewPrivs:\s+1$/m.test(status) || !/^Groups:\s*$/m.test(status)) {
      throw new Error('Real-core gate refused: capabilities, supplementary groups or privilege escalation remain enabled.')
    }
    const root = host.env.ODIN_REAL_CORE_ROOT
    if (!root || host.env.HOME !== root || dirname(root) !== temporaryDirectory() ||
        !root.startsWith(join(temporaryDirectory(), 'odrc-'))) {
      throw new Error('Real-core gate refused: throwaway HOME is missing.')
    }
    for (const [key, leaf] of Object.entries(xdg)) {
      if (host.env[key] !== join(root, leaf)) throw new Error(`Real-core gate refused: unsafe ${key}.`)
    }
    for (const directory of [root, ...Object.values(xdg).map((leaf) => join(root, leaf))]) {
      const stat = files.lstatSync(directory)
      if (!stat.isDirectory() || stat.uid !== uid || stat.gid !== gid || (stat.mode & 0o777) !== 0o700) {
        throw new Error('Real-core gate refused: HOME/XDG ownership or permissions are unsafe.')
      }
    }
  }

  // Always use a new process group, including probes. TERM to sudo/unshare does not terminate the namespace.
  // Wait for exit before restoring handlers or deleting HOME. Never use privileged kill, or retry a started suite.
  function supervise(command, args, { cwd, timeoutMs, signal, capture = false }) {
    return new Promise((accept, reject) => {
      if (signal?.aborted) { reject(new Error('Isolated real-core gate cancelled before launch.')); return }
      let child, timer, failure, finished = false
      let output = ''
      const cleanup = () => {
        if (timer !== undefined) unschedule(timer)
        host.off('SIGINT', interrupt)
        host.off('SIGTERM', terminate)
        signal?.removeEventListener('abort', abort)
      }
      const finish = (code, exitSignal) => {
        if (finished) return
        finished = true
        cleanup()
        if (failure) reject(failure)
        else accept({ code, signal: exitSignal, output })
      }
      const cancel = (message) => {
        if (finished || failure) return
        failure = new Error(message)
        if (child?.pid) {
          try { host.kill(-child.pid, 'SIGKILL') } catch (error) {
            // ESRCH can race the exit event. Other errors are reported, never escalated through sudo.
            if (error.code !== 'ESRCH') failure = new Error(`${message} Process-group cleanup failed: ${error.message}`, { cause: error })
          }
        }
      }
      const interrupt = () => cancel('Isolated real-core gate cancelled by SIGINT.')
      const terminate = () => cancel('Isolated real-core gate cancelled by SIGTERM.')
      const abort = () => cancel('Isolated real-core gate cancelled.')
      host.on('SIGINT', interrupt)
      host.on('SIGTERM', terminate)
      signal?.addEventListener('abort', abort, { once: true })
      try {
        child = spawnChild(command, args, { cwd, env: outerEnv, detached: true,
          stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit' })
        child.once('error', (error) => {
          if (!child.pid) { failure = error; finish(null, null) }
          else cancel(`Isolated real-core launch error: ${error.message}`)
        })
        child.once('exit', finish)
        if (capture) {
          const record = (chunk) => { output = (output + chunk.toString()).slice(-4_000) }
          child.stdout.on('data', record)
          child.stderr.on('data', record)
        }
        timer = schedule(() => cancel('Isolated real-core gate timed out; killing its process group.'), timeoutMs)
        // Covers abort during spawn without replaying the command.
        if (signal?.aborted) abort()
      } catch (error) {
        if (!child?.pid) { failure = error; finish(null, null) }
        else cancel(`Isolated real-core launch error: ${error.message}`)
      }
    })
  }

  /**
   * Resolves only on exit 0; streams the child output; rejects clearly otherwise.
   * The command and its entire process tree run under unshare, with the caller's uid/gid and a private HOME/XDG.
   * `env` is a sanitized overlay (not inherited wholesale). HOME/XDG/display/session overrides are forbidden.
   * Engine Python is explicit ODIN_DESKTOP_ENGINE_PYTHON or repository .venv/bin/python, never a host fallback.
   */
  // The default bounds a whole gate under CI load, not its individual tests or 10-second capability probes.
  async function launchIsolated(command, args = [], { env = {}, cwd = repositoryRoot, timeoutMs = 600_000, signal } = {}) {
    const { uid, gid } = caller()
    if (!Number.isFinite(timeoutMs) || timeoutMs < 1) throw new Error('Expected a positive timeoutMs.')
    const python = resolve(cwd, env.ODIN_DESKTOP_ENGINE_PYTHON || host.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python'))
    if (!files.existsSync(python)) {
      throw new Error('Engine Python is absent. Set ODIN_DESKTOP_ENGINE_PYTHON to an installed Python 3.12 engine environment, or provision repository .venv with the engine dependencies. This gate never skips.')
    }
    if (!files.existsSync(join(repositoryRoot, 'src/desktop/core.py'))) throw new Error('Repository real core is absent; no fixture fallback is allowed.')
    const allowed = /^(ODIN_DESKTOP_[A-Z0-9_]+|ODIN_APP_[A-Z0-9_]+|ODIN_SMOKE_[A-Z0-9_]+|CI|DEBUG|NODE_OPTIONS|ELECTRON_[A-Z0-9_]+)$/
    for (const key of Object.keys(env)) {
      if (!allowed.test(key)) throw new Error(`Isolation env override is not allowed: ${key}`)
    }
    if (signal?.aborted) throw new Error('Isolated real-core gate cancelled before launch.')
    const root = files.mkdtempSync(join(temporaryDirectory(), 'odrc-'))
    // Setup belongs inside finally too: a failed mkdir must not leak HOME.
    try {
      files.chmodSync(root, 0o700)
      const safeEnv = {
        PATH: `${dirname(host.execPath)}:/usr/local/bin:/usr/bin:/bin`, LANG: 'C.UTF-8', HOME: root,
        XDG_CONFIG_HOME: join(root, 'config'), XDG_DATA_HOME: join(root, 'data'),
        XDG_CACHE_HOME: join(root, 'cache'), XDG_RUNTIME_DIR: join(root, 'run'),
        PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1',
        ...env, ODIN_DESKTOP_ENGINE_PYTHON: python, ODIN_REAL_CORE_ROOT: root,
        ODIN_REAL_CORE_UID: String(uid), ODIN_REAL_CORE_GID: String(gid),
        ODIN_REAL_CORE_OUTER_PID_NS: files.readlinkSync('/proc/self/ns/pid'),
        ODIN_REAL_CORE_TIMEOUT_MS: String(timeoutMs)
      }
      if (host.env.RUNNER_TRACKING_ID) safeEnv.RUNNER_TRACKING_ID = host.env.RUNNER_TRACKING_ID
      for (const dir of Object.values(xdg)) files.mkdirSync(join(root, dir), { mode: 0o700 })
      const payload = ['env', '-i', ...Object.entries(safeEnv).map(([key, value]) => `${key}=${value}`), host.execPath, script]
      const failures = []
      const check = async (prefix, label) => {
        try {
          const result = await supervise('sudo', prefix, { cwd, timeoutMs: 10_000, signal, capture: true })
          if (result.code === 0) return true
          failures.push(`${label}: exit ${result.code}, signal ${result.signal ?? 'none'}${result.output.trim() ? ` (${result.output.trim()})` : ''}`)
        } catch (error) {
          if (signal?.aborted || /cancelled/.test(error.message)) throw error
          failures.push(`${label}: ${error.message}`)
        }
        return false
      }
      const candidates = []
      if (await check(['-n', '-l', helper], 'helper permission check')) {
        candidates.push(['approved isolation helper', ['-n', helper]])
      }
      // Current-user-only user namespaces are intentionally absent: they turn host root ownership into UID 65534.
      // Full-sudo machines may use this last resort, with an explicit numeric identity drop, never nested sudo.
      candidates.push(['generic sudo unshare fallback', ['-n', 'unshare', '--mount', '--pid', '--fork', '--mount-proc',
        '--kill-child=KILL', 'setpriv', `--reuid=${uid}`, `--regid=${gid}`, '--clear-groups', '--no-new-privs',
        '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all']])
      let selected
      for (const [label, prefix] of candidates) {
        if (await check([...prefix, ...payload, '--inside-probe'], label)) { selected = prefix; break }
      }
      if (!selected) throw new Error(`Cannot establish a verified non-root PID namespace; no tests were started. ${failures.join('; ')}. Provision the approved isolation helper or non-interactive sudo unshare. Current-user-only user namespaces cannot preserve root-owned filesystem guards; no unisolated fallback or silent skip is allowed.`)
      const result = await supervise('sudo', [...selected, ...payload, '--inside-run', resolve(cwd), command, ...args],
        { cwd, timeoutMs: timeoutMs + 10_000, signal })
      if (result.code !== 0) throw new Error(`Isolated real-core gate failed (exit ${result.code}, signal ${result.signal ?? 'none'}). No retry after tests start.`)
    } finally {
      files.rmSync(root, { recursive: true, force: true })
    }
  }
  return { assertRealCoreIsolation, launchIsolated }
}

export const { assertRealCoreIsolation, launchIsolated } = createIsolationLauncher()

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

if (process.argv[1] && resolve(process.argv[1]) === script) {
  if (process.argv[2] === '--inside-probe') {
    try { assertRealCoreIsolation('--inside-probe') } catch (error) { console.error(error.message); process.exitCode = 1 }
  } else if (process.argv[2] === '--inside-run') {
    inside().catch((error) => { console.error(error.message); process.exitCode = 1 })
  }
}
