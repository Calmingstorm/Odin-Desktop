// Process exit is not a tool/native-input release receipt. Unknown evidence is never silently cleared.
import { closeSync, fsyncSync, openSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'
import type { StopOutcome } from './core-supervisor'

export interface CleanupRecord {
  version: 1
  state: 'running' | 'process-exited' | 'unknown'
  at: string
  reason: string
  processOutcome?: StopOutcome
  shutdownAccepted?: boolean
  unsaved?: boolean
  unreceipted?: number
}

export class CleanupJournal {
  private unknown: CleanupRecord | null
  constructor(private readonly path: string) {
    try {
      const saved = JSON.parse(readFileSync(path, 'utf8')) as CleanupRecord
      this.unknown = saved.version === 1 && saved.state === 'process-exited' ? null : {
        ...saved,
        version: 1, state: 'unknown', at: saved.at ?? new Date().toISOString(),
        reason: saved.state === 'running' ? 'Previous app stopped without a shutdown receipt. Cleanup unknown; effects are not undone.' : saved.reason ?? 'Previous cleanup receipt is unknown'
      }
    } catch (error) {
      this.unknown = (error as NodeJS.ErrnoException).code === 'ENOENT' ? null : {
        version: 1, state: 'unknown', at: new Date().toISOString(), reason: 'Previous cleanup evidence could not be read'
      }
    }
  }
  get warning(): CleanupRecord | null { return this.unknown }
  begin(): void { this.write(this.unknown ?? this.record('running', 'App running; shutdown not yet observed')) }
  markUnknown(reason: string): void {
    this.unknown ??= this.record('unknown', reason)
    this.write(this.unknown)
  }
  finish(record: CleanupRecord): void {
    if (record.state === 'unknown') this.unknown ??= record
    this.write(this.unknown ?? record)
  }
  private record(state: CleanupRecord['state'], reason: string): CleanupRecord {
    return { version: 1, state, reason, at: new Date().toISOString() }
  }
  private write(record: CleanupRecord): void {
    const pending = `${this.path}.pending`
    const fd = openSync(pending, 'w', 0o600)
    try { writeFileSync(fd, JSON.stringify(record)); fsyncSync(fd) } finally { closeSync(fd) }
    renameSync(pending, this.path)
    const directory = openSync(dirname(this.path), 'r')
    try { fsyncSync(directory) } finally { closeSync(directory) }
  }
}

export interface ShutdownDeps {
  stopAdmission(): void
  persist(): void
  requestShutdown(): Promise<boolean>
  stopCore(): Promise<StopOutcome>
  unreceipted(): number
  finish(record: CleanupRecord): void
  release(): void
  exit(code: number): void
  requestTimeoutMs?: number
}

export function boundedShutdown(deps: ShutdownDeps): (code?: number) => Promise<CleanupRecord> {
  let exiting: Promise<CleanupRecord> | null = null
  return (code = 0) => {
    if (exiting) return exiting
    deps.stopAdmission()
    exiting = (async () => {
      let unsaved = false
      try { deps.persist() } catch { unsaved = true }
      let timer: NodeJS.Timeout | undefined
      let shutdownAccepted = false
      try {
        shutdownAccepted = await Promise.race([
          Promise.resolve().then(() => deps.requestShutdown()).catch(() => false),
          new Promise<boolean>((resolve) => { timer = setTimeout(() => resolve(false), deps.requestTimeoutMs ?? 5_000) })
        ])
      } finally { if (timer) clearTimeout(timer) }
      let processOutcome: StopOutcome
      try { processOutcome = await deps.stopCore() } catch { processOutcome = 'unknown' }
      const unreceipted = deps.unreceipted()
      const unknown = unsaved || unreceipted > 0 || !shutdownAccepted || !['exited', 'not-running'].includes(processOutcome)
      const record: CleanupRecord = {
        version: 1, at: new Date().toISOString(), state: unknown ? 'unknown' : 'process-exited',
        reason: unknown ? 'Cleanup unknown. Effects are not labelled undone; no work will be replayed.' : 'Core process exited after accepted shutdown; no tool/input-release claim.',
        processOutcome, shutdownAccepted, unsaved, unreceipted
      }
      try { deps.finish(record) } catch { code = 1 }
      try { deps.release() } finally { deps.exit(code) }
      return record
    })()
    return exiting
  }
}
