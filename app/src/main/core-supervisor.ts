// Starts and watches Odin's core as a child of the app (D3).
//
// - The core's stdin is a pipe the app holds. If the app dies, the pipe closes and the core shuts itself down, so it
//   never carries on as an unsupervised daemon.
// - A crash is restarted within a bounded budget. Nothing is replayed: the core reports interrupted work itself.
// - A core that fails to start (a missing or unrunnable executable) goes through the same budget. Each child's end is
//   handled exactly once, whichever of 'error' and 'exit' reports it.
// - Stop asks for an orderly shutdown, then escalates only if the core doesn't exit in time.
import { spawn, type ChildProcess } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { createWriteStream, existsSync, renameSync, statSync, type WriteStream } from 'node:fs'

export interface SupervisorOptions {
  command: string
  args: string[]
  env?: NodeJS.ProcessEnv
  logFile: string
  maxRestarts?: number
  restartWindowMs?: number
  backoffMs?: number[]
  maxLogBytes?: number
  killWaitMs?: number
  restartAllowed?: (code: number | null, signal: NodeJS.Signals | null) => boolean
}

export type StopOutcome = 'exited' | 'terminated' | 'killed' | 'not-running' | 'unknown'

export type SupervisorState = 'idle' | 'starting' | 'running' | 'restarting' | 'stopping' | 'stopped' | 'failed'

export class CoreSupervisor extends EventEmitter {
  private child: ChildProcess | null = null
  private state: SupervisorState = 'idle'
  private crashTimes: number[] = []
  private restartTimer: NodeJS.Timeout | null = null
  private log: WriteStream | null = null
  private stopping: Promise<StopOutcome> | null = null
  private stopRequested = false
  private readonly maxRestarts: number
  private readonly restartWindowMs: number
  private readonly backoffMs: number[]
  private readonly maxLogBytes: number

  constructor(private readonly options: SupervisorOptions) {
    super()
    this.maxRestarts = options.maxRestarts ?? 3
    this.restartWindowMs = options.restartWindowMs ?? 5 * 60_000
    this.backoffMs = options.backoffMs ?? [1_000, 3_000, 10_000]
    this.maxLogBytes = options.maxLogBytes ?? 5 * 1024 * 1024
  }

  get current(): SupervisorState {
    return this.state
  }

  get pid(): number | undefined {
    return this.child?.pid
  }

  start(): void {
    if (this.stopRequested || this.state === 'failed' || this.restartTimer || this.state === 'starting' || this.state === 'running') return
    this.openLog()
    this.setState('starting')
    let child: ChildProcess
    try {
      child = spawn(this.options.command, this.options.args, {
        env: this.options.env ?? process.env,
        stdio: ['pipe', 'pipe', 'pipe'],
        detached: false,
        windowsHide: true // Windows: no console window for the engine
      })
    } catch (error) {
      // Invalid arguments throw synchronously; treat it like any other failed start.
      this.writeLog(Buffer.from(`[supervisor] spawn error: ${(error as Error).message}\n`))
      this.child = null
      setImmediate(() => this.onEnded(null, null, null))
      return
    }
    this.child = child
    let ended = false
    const end = (code: number | null, signal: NodeJS.Signals | null): void => {
      if (ended) return
      ended = true
      this.onEnded(child, code, signal)
    }
    child.stdout?.on('data', (chunk: Buffer) => this.writeLog(chunk))
    child.stderr?.on('data', (chunk: Buffer) => this.writeLog(chunk))
    child.once('spawn', () => {
      if (this.child !== child || this.state !== 'starting') return
      this.setState('running')
      this.emit('started', child.pid)
    })
    child.on('error', (error) => {
      // A child that never got a PID never started, and Node may not emit 'exit' for it.
      const started = child.pid !== undefined
      this.writeLog(Buffer.from(`[supervisor] ${started ? 'process' : 'spawn'} error: ${error.message}\n`))
      if (!started) end(null, null)
    })
    child.once('exit', (code, signal) => end(code, signal))
  }

  /** Bounded and shared. Sending a signal is not proof of exit. */
  stop(graceMs = 15_000, termMs = 5_000): Promise<StopOutcome> {
    if (this.stopping) return this.stopping
    this.stopRequested = true
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    const child = this.child
    if (!child || child.pid === undefined || child.exitCode !== null || child.signalCode !== null) {
      this.setState('stopped')
      this.closeLog()
      this.child = null
      this.stopping = Promise.resolve('not-running')
      return this.stopping
    }
    this.setState('stopping')
    this.stopping = new Promise((resolve) => {
      let outcome: 'exited' | 'terminated' | 'killed' = 'exited'
      let settled = false
      const finish = (result: StopOutcome): void => {
        if (settled) return
        settled = true
        clearTimeout(termTimer)
        clearTimeout(killTimer)
        clearTimeout(deadline)
        child.off('exit', onExit)
        if (result === 'unknown') this.closeLog()
        resolve(result)
      }
      const onExit = (): void => finish(outcome)
      const signal = (value: NodeJS.Signals): void => {
        try { child.kill(value) } catch (error) {
          this.writeLog(Buffer.from(`[supervisor] ${value} failed: ${String(error)}\n`))
        }
      }
      const termTimer = setTimeout(() => {
        outcome = 'terminated'
        signal('SIGTERM')
      }, graceMs)
      const killTimer = setTimeout(() => {
        outcome = 'killed'
        signal('SIGKILL')
      }, graceMs + termMs)
      const deadline = setTimeout(() => finish('unknown'), graceMs + termMs + (this.options.killWaitMs ?? 2_000))
      child.once('exit', onExit)
      child.stdin?.on('error', () => undefined)
      try { child.stdin?.end() } catch { /* escalation retains its bounded deadline */ }
    })
    return this.stopping
  }

  private onEnded(child: ChildProcess | null, code: number | null, signal: NodeJS.Signals | null): void {
    if (child !== this.child) return
    this.child = null
    this.writeLog(Buffer.from(`[supervisor] core ended code=${code} signal=${signal}\n`))
    this.emit('exited', { code, signal })
    if (this.stopRequested) {
      this.setState('stopped')
      this.closeLog()
      return
    }
    if (this.options.restartAllowed && !this.options.restartAllowed(code, signal)) {
      this.setState('failed')
      this.emit('failed', { code, signal, cleanup: 'unknown' })
      this.closeLog()
      return
    }
    const now = Date.now()
    this.crashTimes = this.crashTimes.filter((t) => now - t < this.restartWindowMs)
    this.crashTimes.push(now)
    if (this.crashTimes.length > this.maxRestarts) {
      this.setState('failed')
      this.emit('failed', { code, signal })
      this.closeLog()
      return
    }
    const attempt = this.crashTimes.length
    const delay = this.backoffMs[Math.min(attempt - 1, this.backoffMs.length - 1)] ?? 1_000
    this.setState('restarting')
    this.emit('restarting', { attempt, delay })
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null
      this.start()
    }, delay)
  }

  private setState(state: SupervisorState): void {
    this.state = state
    this.emit('state', state)
  }

  private openLog(): void {
    if (this.log) return
    if (existsSync(this.options.logFile) && statSync(this.options.logFile).size > this.maxLogBytes) {
      renameSync(this.options.logFile, `${this.options.logFile}.1`)
    }
    this.log = createWriteStream(this.options.logFile, { flags: 'a', mode: 0o600 })
  }

  private writeLog(chunk: Buffer): void {
    this.log?.write(chunk)
  }

  private closeLog(): void {
    this.log?.end()
    this.log = null
  }
}
