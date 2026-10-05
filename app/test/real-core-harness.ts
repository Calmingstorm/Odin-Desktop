// The app's actual Broker against `python -m src`, never the fixture or an in-process service substitute.
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, readlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { Broker, type Welcome } from '../src/main/broker'
import { ensureProfileDirs, ensureToken, profilePaths, type ProfilePaths } from '../src/main/paths'

const repository = resolve(__dirname, '../..')

export function assertIsolated(): void {
  if (process.platform !== 'linux' || !process.getuid || process.getuid() === 0) {
    throw new Error('Real-core tests require Linux and an unprivileged user; never run them as root.')
  }
  const outer = process.env.ODIN_REAL_CORE_OUTER_PID_NS
  if (!outer || readlinkSync('/proc/self/ns/pid') === outer) {
    throw new Error('Real-core tests refused outside an isolated PID namespace. Run npm run test:real-core, not vitest directly.')
  }
  const init = readFileSync('/proc/1/cmdline', 'utf8').split('\0')
  if (!init.includes(join(repository, 'app/scripts/real-core-isolation.mjs')) || !init.includes('--inside-run')) {
    throw new Error('Real-core tests refused: namespace PID 1 is not the isolation runner.')
  }
  const root = process.env.ODIN_REAL_CORE_ROOT
  if (!root || !root.startsWith(join(tmpdir(), 'odrc-')) || process.env.HOME !== root) {
    throw new Error('Real-core tests refused without the isolation runner throwaway HOME.')
  }
  for (const [key, leaf] of Object.entries({
    XDG_CONFIG_HOME: 'config', XDG_DATA_HOME: 'data', XDG_CACHE_HOME: 'cache', XDG_RUNTIME_DIR: 'run'
  })) {
    if (process.env[key] !== join(root, leaf)) throw new Error(`Real-core tests refused: unsafe ${key}.`)
  }
}

function enginePython(): string {
  assertIsolated()
  const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repository, '.venv/bin/python')
  if (!existsSync(python)) {
    throw new Error('Real engine Python is absent. Set ODIN_DESKTOP_ENGINE_PYTHON or provision repository .venv with engine dependencies. Tests never skip.')
  }
  if (!existsSync(join(repository, 'src/desktop/core.py'))) throw new Error('Real repository core is absent; no fixture fallback.')
  return python
}

export async function waitFor(check: () => boolean, description: string, timeoutMs = 8_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (!check()) {
    if (Date.now() >= deadline) throw new Error(`Timed out: ${description}`)
    await new Promise((accept) => setTimeout(accept, 20))
  }
}

export function onceEvent<T>(broker: Broker, event: string, timeoutMs = 8_000): Promise<T> {
  return new Promise((accept, reject) => {
    const listener = (value: T): void => { clearTimeout(timer); accept(value) }
    const timer = setTimeout(() => {
      broker.off(event, listener)
      reject(new Error(`Timed out waiting for Broker ${event}`))
    }, timeoutMs)
    broker.once(event, listener)
  })
}

export class RealCoreHarness {
  readonly root: string
  readonly paths: ProfilePaths
  readonly python: string
  readonly env: NodeJS.ProcessEnv
  private process: ChildProcessWithoutNullStreams | null = null
  private output = ''
  private exited: Promise<{ code: number | null; signal: NodeJS.Signals | null }> | null = null
  private readonly brokers = new Set<Broker>()

  constructor() {
    this.python = enginePython()
    this.root = mkdtempSync(join(process.env.ODIN_REAL_CORE_ROOT!, 'profile-'))
    this.env = {
      PATH: '/usr/local/bin:/usr/bin:/bin', LANG: 'C.UTF-8', HOME: this.root,
      XDG_CONFIG_HOME: join(this.root, 'config'), XDG_DATA_HOME: join(this.root, 'data'),
      XDG_CACHE_HOME: join(this.root, 'cache'), XDG_RUNTIME_DIR: join(this.root, 'run'),
      PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1'
    }
    this.paths = profilePaths('default', this.env)
    ensureProfileDirs(this.paths)
    ensureToken(this.paths)
  }

  get child(): ChildProcessWithoutNullStreams {
    if (!this.process) throw new Error('No real core process has been started.')
    return this.process
  }

  get running(): boolean {
    return this.process !== null && this.process.exitCode === null && this.process.signalCode === null
  }

  async start(): Promise<void> {
    assertIsolated()
    if (this.running) throw new Error('Real core is already running.')
    this.output = ''
    const child = spawn(this.python, ['-m', 'src', '--socket', this.paths.socketPath,
      '--token-file', this.paths.tokenPath, '--profile', this.paths.profileId, '--data-dir', this.paths.dataDir],
    { cwd: repository, env: this.env, stdio: ['pipe', 'pipe', 'pipe'] })
    this.process = child
    child.stdout.on('data', (chunk: Buffer) => { this.output = (this.output + chunk.toString()).slice(-8_000) })
    child.stderr.on('data', (chunk: Buffer) => { this.output = (this.output + chunk.toString()).slice(-8_000) })
    let launchError: Error | null = null
    this.exited = new Promise((accept) => {
      child.once('error', (error) => { launchError = error; accept({ code: null, signal: null }) })
      child.once('exit', (code, signal) => accept({ code, signal }))
    })
    await waitFor(() => {
      if (launchError || !this.running) {
        throw new Error(`Real core startup failed. Check engine Python/dependencies. ${launchError?.message ?? ''}\n${this.output}`)
      }
      return existsSync(this.paths.socketPath)
    }, 'real core socket creation')
  }

  broker(wrongToken = false): Broker {
    const broker = new Broker({
      socketPath: this.paths.socketPath,
      readToken: () => wrongToken ? '0'.repeat(64) : readFileSync(this.paths.tokenPath, 'utf8').trim(),
      profileId: this.paths.profileId, clientVersion: 'real-core-contract',
      requestTimeoutMs: 3_000, helloTimeoutMs: 3_000, reconnectDelaysMs: [40, 80, 150]
    })
    this.brokers.add(broker)
    return broker
  }

  async connect(): Promise<{ broker: Broker; welcome: Welcome }> {
    const broker = this.broker()
    const ready = onceEvent<Welcome>(broker, 'welcome')
    broker.connect()
    const welcome = await ready
    return { broker, welcome }
  }

  async waitExit(timeoutMs = 8_000): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
    if (!this.exited) throw new Error('No real core process to wait for.')
    let timer: NodeJS.Timeout | undefined
    try {
      return await Promise.race([this.exited, new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Real core did not exit in ${timeoutMs}ms.\n${this.output}`)), timeoutMs)
      })])
    } finally {
      if (timer) clearTimeout(timer)
    }
  }

  async parentEOF(): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
    this.child.stdin.end()
    return this.waitExit()
  }

  /** Offline time travel, not a fabricated tombstone: startup runs the real receipt pruner. */
  ageReceipt(commandId: string): void {
    assertIsolated()
    if (this.running) throw new Error('Receipt aging requires the real core to have exited.')
    const result = spawnSync(this.python, ['-c',
      'import sqlite3, sys; db=sqlite3.connect(sys.argv[1]); row=db.execute("UPDATE command_receipts SET finished_at=0 WHERE command_id=? AND state=\'final\' AND unknown_outcome=0", (sys.argv[2],)); assert row.rowcount == 1, "Expected one real final receipt"; db.commit(); db.close()',
      join(this.paths.dataDir, 'transport.sqlite3'), commandId], { cwd: repository, env: this.env, encoding: 'utf8', timeout: 5_000 })
    if (result.error || result.status !== 0) throw new Error(`Offline receipt aging failed: ${result.error?.message ?? result.stderr}`)
  }

  async dispose(): Promise<void> {
    for (const broker of this.brokers) broker.close()
    try {
      if (this.running) {
        this.child.stdin.end()
        try { await this.waitExit(5_000) } catch {
          this.child.kill('SIGKILL')
          await this.waitExit(3_000)
        }
      }
    } finally {
      if (!this.running) rmSync(this.root, { recursive: true, force: true })
    }
  }
}
