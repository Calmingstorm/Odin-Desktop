// Process exit is not a tool/native-input release receipt. Unknown evidence is never silently cleared.
import * as nodeFs from 'node:fs'
import { readFileSync } from 'node:fs'
import { dirname } from 'node:path'
import { createHash, randomUUID } from 'node:crypto'
import type { CleanupWarning } from '../shared/api'
import type { Broker } from './broker'
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
  /** App-local evidence identity, never authority to replay or release a resource. */
  eventId?: string
  source?: string
}

export interface CleanupAcknowledgment extends CleanupWarning {
  acknowledgedAt: string
  records: CleanupRecord[]
}
interface JournalWarning extends CleanupWarning { records: CleanupRecord[] }
interface JournalEvidence extends CleanupRecord {
  journalVersion: 2
  current: CleanupRecord
  warning: JournalWarning | null
  archived: CleanupAcknowledgment[]
}

/** JSON persistence may reorder object keys without creating new uncertainty. */
export function resourceCleanupSource(evidence: unknown): string {
  const canonical = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(canonical)
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, canonical(child)]))
    }
    return value
  }
  return `core-resource:${createHash('sha256').update(JSON.stringify(canonical(evidence))).digest('hex')}`
}

function validRecord(value: unknown): value is CleanupRecord {
  if (!value || typeof value !== 'object') return false
  const row = value as CleanupRecord
  return row.version === 1 && ['running', 'process-exited', 'unknown'].includes(row.state)
    && typeof row.at === 'string' && typeof row.reason === 'string'
}
function validWarning(value: unknown): value is JournalWarning {
  if (!value || typeof value !== 'object') return false
  const row = value as JournalWarning
  return typeof row.id === 'string' && row.id.length > 0 && typeof row.at === 'string'
    && Array.isArray(row.records) && row.records.length > 0
    && row.records.every((record) => validRecord(record) && record.state === 'unknown')
}

/** The file operations the journal writes with (injectable, so each step's failure can be tested). */
export type JournalFs = Pick<typeof nodeFs, 'openSync' | 'writeFileSync' | 'fsyncSync' | 'closeSync' | 'renameSync'>

export class CleanupJournal {
  private unknown: JournalWarning | null = null
  private current: CleanupRecord = this.record('running', 'App running; shutdown not yet observed')
  private archive: CleanupAcknowledgment[] = []
  private readonly system: NodeJS.Platform
  private readonly fs: JournalFs
  constructor(private readonly path: string, options: { system?: NodeJS.Platform; fs?: JournalFs } = {}) {
    this.system = options.system ?? process.platform
    this.fs = options.fs ?? nodeFs
    try {
      const saved: unknown = JSON.parse(readFileSync(path, 'utf8'))
      if (!validRecord(saved)) throw new Error('Invalid cleanup evidence')
      if ('journalVersion' in saved) {
        const evidence = saved as JournalEvidence
        if (evidence.journalVersion !== 2 || !validRecord(evidence.current)
          || (evidence.warning !== null && !validWarning(evidence.warning))
          || !Array.isArray(evidence.archived)
          || !evidence.archived.every((row) => validWarning(row) && typeof row.acknowledgedAt === 'string')) {
          throw new Error('Invalid cleanup journal')
        }
        this.current = evidence.current
        this.unknown = evidence.warning
        this.archive = evidence.archived
      } else {
        // Migrate the previous single-record format without discarding uncertainty.
        this.current = saved
        if (saved.state === 'unknown') this.unknown = this.addUnknown(saved)
      }
      if (this.current.state === 'running') {
        this.unknown = this.addUnknown({ ...this.current, state: 'unknown',
          source: `app-lifetime:${this.current.eventId ?? this.current.at}`,
          reason: 'Previous app stopped without a shutdown receipt. Cleanup unknown; effects are not undone.' })
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
        this.unknown = this.addUnknown(this.record('unknown', 'Previous cleanup evidence could not be read'))
      }
    }
  }
  get warning(): CleanupRecord | null { return this.unknown ? structuredClone(this.unknown.records[0]!) : null }
  get notice(): CleanupWarning | null { return structuredClone(this.unknown) }
  get archived(): CleanupAcknowledgment[] { return structuredClone(this.archive) }
  begin(): void {
    const current = this.record('running', 'App running; shutdown not yet observed')
    this.write(current, this.unknown, this.archive)
    this.current = current
  }
  markUnknown(reason: string, source?: string): void {
    const warning = this.addUnknown({ ...this.record('unknown', reason), ...(source ? { source } : {}) })
    this.write(this.current, warning, this.archive)
    this.unknown = warning
  }
  finish(record: CleanupRecord): void {
    const warning = record.state === 'unknown' ? this.addUnknown(record) : this.unknown
    this.write(record, warning, this.archive)
    this.current = record
    this.unknown = warning
  }
  /** Archive the observed notice only. Never change core quarantine, release truth or replay policy. */
  acknowledge(id: string): boolean {
    if (!this.unknown || this.unknown.id !== id) return false
    const archived = [...this.archive, { ...this.unknown, acknowledgedAt: new Date().toISOString() }]
    // Do not hide the notice until the same journal has durably retained its evidence.
    this.write(this.current, null, archived)
    this.archive = archived
    this.unknown = null
    return true
  }
  private addUnknown(record: CleanupRecord): JournalWarning | null {
    // A repeated core report of the SAME uncertainty is not a new event. A new
    // receipt/count has a different source, so it raises a fresh warning.
    const retained = [...(this.unknown?.records ?? []), ...this.archive.flatMap((row) => row.records)]
    if (record.source && retained.some((row) => row.source === record.source)) return this.unknown
    return { id: randomUUID(), at: record.at, records: [...(this.unknown?.records ?? []), record] }
  }
  private record(state: CleanupRecord['state'], reason: string): CleanupRecord {
    return { version: 1, state, reason, at: new Date().toISOString(), eventId: randomUUID() }
  }
  private write(current: CleanupRecord, warning: JournalWarning | null, archived: CleanupAcknowledgment[]): void {
    // Keep the legacy top-level summary readable, and separately retain the
    // current lifetime marker even while older uncertainty remains visible.
    const evidence: JournalEvidence = { ...(warning?.records[0] ?? current),
      journalVersion: 2, current, warning, archived }
    const pending = `${this.path}.pending`
    const fd = this.fs.openSync(pending, 'w', 0o600)
    try { this.fs.writeFileSync(fd, JSON.stringify(evidence)); this.fs.fsyncSync(fd) } finally { this.fs.closeSync(fd) }
    this.fs.renameSync(pending, this.path)
    // Windows: Node can't open a folder, so there is no directory flush. The contents are flushed before the
    // rename replaces the journal (atomically, on NTFS); that the replacement survives a power loss isn't proven.
    if (this.system === 'win32') return
    const directory = this.fs.openSync(dirname(this.path), 'r')
    try { this.fs.fsyncSync(directory) } finally { this.fs.closeSync(directory) }
  }
}

export interface ShutdownDeps {
  stopAdmission(): void
  persist(): void
  /** Whether to send the shutdown request, settled within its own bounds before the request's bound starts. */
  readyForShutdown(): Promise<boolean>
  requestShutdown(signal: AbortSignal): Promise<boolean>
  /** Settles the shutdown request either way before it returns: by its receipt, or as unreceipted once the core has
   * exited. A receipt that comes after the request's bound, while the core is stopped, still counts. */
  stopCore(): Promise<StopOutcome>
  unreceipted(): number
  finish(record: CleanupRecord): void
  release(): void
  exit(code: number): void
  requestTimeoutMs?: number
}

/** How long Exit waits for the core to show it is answering: its connection becoming ready, or the next receipt it is
 * owed. */
export const SHUTDOWN_READY_MS = 5_000

/** How long the shutdown request waits for its receipt once sent. Accepting it commits the core's quiescing event and
 * receipt, which a loaded machine can stall for seconds (5.4 s, timed on a hosted Windows runner right after an
 * installer run). A receipt that comes later, while the core is being stopped, still counts (stopKeepingReceipts).
 */
export const SHUTDOWN_REQUEST_MS = 10_000

/** Exit's turn on the core's connection: a starting connection gets `boundMs` to become ready, then the requests sent
 * before Exit are answered first, since the core answers a connection's requests in order. While their answers keep
 * coming the core is answering and the wait goes on; `boundMs` without one, or one that settles without its answer,
 * means it isn't, and no shutdown request is sent. Then the request has its own bound: a core still answering what it
 * was asked is not a core that doesn't answer.
 */
export async function shutdownTurn(link: Pick<Broker, 'waitForShutdownReady' | 'requestsAnswered'>,
  boundMs = SHUTDOWN_READY_MS): Promise<boolean> {
  return await link.waitForShutdownReady(boundMs) && link.requestsAnswered(boundMs)
}

/** Exit's stop: the core is stopped with its connection still open, so a shutdown receipt that comes after the
 * request's bound still lands; once the core has exited, what it never answered settles as unreceipted.
 */
export async function stopKeepingReceipts(stop: () => Promise<StopOutcome>,
  link: Pick<Broker, 'drained' | 'close'>): Promise<StopOutcome> {
  try {
    return await stop()
  } finally {
    await link.drained(1_000)
    link.close()
  }
}

export function boundedShutdown(deps: ShutdownDeps): (code?: number) => Promise<CleanupRecord> {
  let exiting: Promise<CleanupRecord> | null = null
  return (code = 0) => {
    if (exiting) return exiting
    deps.stopAdmission()
    exiting = (async () => {
      let unsaved = false
      try { deps.persist() } catch { unsaved = true }
      let ready = false
      try { ready = await deps.readyForShutdown() } catch { ready = false }
      let timer: NodeJS.Timeout | undefined
      const requestBound = new AbortController()
      let shutdownAccepted = false
      let request: Promise<boolean> | null = null
      if (ready) {
        request = Promise.resolve().then(() => deps.requestShutdown(requestBound.signal)).catch(() => false)
        try {
          shutdownAccepted = await Promise.race([request,
            new Promise<boolean>((resolve) => { timer = setTimeout(() => resolve(false), deps.requestTimeoutMs ?? SHUTDOWN_REQUEST_MS) })
          ])
        } finally { requestBound.abort(); if (timer) clearTimeout(timer) }
      }
      let processOutcome: StopOutcome
      try { processOutcome = await deps.stopCore() } catch { processOutcome = 'unknown' }
      // A late receipt, answered while the core was being stopped, is still its acceptance. stopCore has settled the
      // request by now (a timer turn lets its result through); one that somehow hasn't counts as not accepted.
      if (!shutdownAccepted && request) {
        let late: NodeJS.Timeout | undefined
        shutdownAccepted = await Promise.race([request,
          new Promise<boolean>((resolve) => { late = setTimeout(() => resolve(false), 0) })])
        clearTimeout(late)
      }
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
