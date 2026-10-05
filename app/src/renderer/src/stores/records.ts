// The Records section: what Odin did and how he is, in the shapes of Odin's /api/audit, /api/usage,
// /api/health/components, /api/logs, /api/turn-state and /api/computer routes. Read-only, except computer-use cleanup.
import { reactive } from 'vue'
import type { AuditEntry, AuditVerify, ComputerStatus, HealthReport, LogEntry, Result, TurnStateReport, UsageResult } from '../../../shared/api'
import { isUnavailable, resultMessage } from '../capability'
import { act, management } from './management'

export type RecordSection = 'audit' | 'verify' | 'usage' | 'health' | 'logs' | 'turns' | 'computer'

export const records = reactive({
  audit: [] as AuditEntry[],
  verify: null as AuditVerify | null,
  usage: null as UsageResult | null,
  health: null as HealthReport | null,
  logs: [] as LogEntry[],
  turns: null as TurnStateReport | null,
  computer: null as ComputerStatus | null,
  /** Sections whose last read answered. Until one has, nothing it shows is a fact: not even "nothing". */
  loaded: {} as Partial<Record<RecordSection, boolean>>,
  /** Why a section's last read failed. What it showed before stays, marked as from an earlier read. */
  errors: {} as Partial<Record<RecordSection, string>>,
  unavailable: {} as Partial<Record<RecordSection, boolean>>
})

const features: Record<RecordSection, string> = { audit: 'Audit', verify: 'Audit verification', usage: 'Usage', health: 'Health', logs: 'Log search', turns: 'Preserved work', computer: 'Computer use' }

/** Notes a read's answer for its section, and says whether it can be shown. */
function answered<T>(section: RecordSection, result: Result<T>): result is { ok: true; result: T } {
  if (!result.ok) {
    if (isUnavailable(result.error)) {
      records.unavailable[section] = true
      delete records.errors[section]
      delete records.loaded[section]
      // No last-read rows or safety verdicts belong to a core that refused this capability. Shared action locks
      // (including a reconciliation awaiting its late receipt) remain owned by management.
      if (section === 'audit') records.audit = []
      else if (section === 'logs') records.logs = []
      else records[section] = null
      if (section === 'computer') {
        for (const key of Object.keys(management.notes)) {
          if (key.startsWith('computer:') && !management.busy[key]) delete management.notes[key]
        }
      }
    } else records.errors[section] = result.error.message
    return false
  }
  records.unavailable[section] = false
  records.errors[section] = undefined
  records.loaded[section] = true
  return true
}

export interface AuditFilter {
  q?: string
  tool?: string
  error_only?: boolean
}

let latestAudit = 0

export async function loadAudit(filter: AuditFilter = {}): Promise<void> {
  const mine = ++latestAudit
  const params = { limit: 100, ...Object.fromEntries(Object.entries(filter).filter(([, v]) => v !== '' && v !== undefined && v !== false)) }
  const result = await window.odin.auditQuery(params)
  if (mine !== latestAudit) return
  if (answered('audit', result)) records.audit = result.result
}

/** A failed check is no verdict: the record is neither intact nor broken until a check answers. */
export async function verifyAudit(): Promise<void> {
  const mine = ++latestVerify
  const result = await window.odin.auditVerify({})
  if (mine !== latestVerify) return
  if (answered('verify', result)) records.verify = result.result
  else records.verify = null
}

let latestUsage = 0
let latestVerify = 0
let latestHealth = 0
let latestTurns = 0
let latestComputer = 0

export async function loadUsage(period: '24h' | '7d' | '30d' | 'all'): Promise<void> {
  const mine = ++latestUsage
  const result = await window.odin.usage(period)
  if (mine !== latestUsage) return
  if (answered('usage', result)) records.usage = result.result
}

export async function loadHealth(): Promise<void> {
  const mine = ++latestHealth
  const result = await window.odin.healthGet({})
  if (mine !== latestHealth) return
  if (answered('health', result)) records.health = result.result
}

let latestLogs = 0

export async function searchLogs(filter: { q?: string; level?: 'error' | 'info' | 'all' } = {}): Promise<void> {
  const mine = ++latestLogs
  const result = await window.odin.logsSearch({ limit: 200, level: filter.level ?? 'all', ...(filter.q ? { q: filter.q } : {}) })
  if (mine !== latestLogs) return
  if (answered('logs', result)) records.logs = result.result.entries
}

export async function loadTurns(): Promise<void> {
  const mine = ++latestTurns
  const result = await window.odin.turnStateList({ limit: 50 })
  if (mine !== latestTurns) return
  if (answered('turns', result)) records.turns = result.result
}

export async function loadComputer(): Promise<void> {
  const mine = ++latestComputer
  const result = await window.odin.computerStatus({})
  if (mine !== latestComputer) return
  if (answered('computer', result)) records.computer = result.result
}

const RECOVERY_REASONS: Record<string, string> = {
  owned_process_remaining: 'a process the session started is still running',
  owned_process_group_remaining: 'processes the session started are still running',
  process_inspection_unavailable: "Odin couldn't inspect the session's processes",
  inspection_unavailable: "Odin couldn't inspect what the session left",
  inspection_timeout: 'inspecting what the session left took too long',
  runtime_identity_required: "Odin has no record of the session's runtime to inspect",
  owned_input_release_unproven: "the session's input release is unproven",
  controller_lost: 'Odin lost the session while it was running'
}

export const reasonText = (reason: string): string => RECOVERY_REASONS[reason] ?? reason.replace(/_/g, ' ')

/**
 * What reconciling did, from Odin's own record. Odin answers success for an acknowledgment, a cleanup still unknown
 * and a verified one alike, so only the recovery it records says which.
 */
export function reconcileOutcome(status: ComputerStatus): string {
  const recovery = status.recovery
  if (recovery?.status === 'absence_verified') return 'Released: Odin verified nothing of the session remains.'
  if (recovery?.status === 'operator_acknowledged_unverified') return 'Acknowledged: Odin closed the session on your word. Its cleanup stays unverified.'
  const why = recovery ? reasonText(recovery.reason) : 'Odin recorded no recovery'
  return `Not released: ${why}. The session ${status.state === 'quarantined' ? 'stays quarantined' : `is ${status.state}`}.`
}

/** Odin's headless release-all, bound to the session's own generation: you say you've checked the computer. */
export async function reconcileComputer(status: ComputerStatus): Promise<boolean> {
  if (records.unavailable.computer) return false
  const generation = status.session_generation ?? status.generation ?? 0
  return act(
    `computer:${status.session_id}`,
    async () => {
      const result = await window.odin.computerReconcile({
        session_id: status.session_id,
        generation,
        acknowledgment: `ACKNOWLEDGE UNVERIFIED CLEANUP ${status.session_id}`
      })
      if (!result.ok && isUnavailable(result.error)) {
        answered('computer', result)
        return { ...result, error: { ...result.error, message: resultMessage(result, features.computer) } }
      }
      return result
    },
    (answer) => {
      records.computer = answer
      return reconcileOutcome(answer)
    },
    loadComputer
  )
}

export async function loadRecords(): Promise<void> {
  await Promise.all([loadAudit(), loadUsage('7d'), loadHealth(), searchLogs(), loadTurns(), loadComputer()])
}

