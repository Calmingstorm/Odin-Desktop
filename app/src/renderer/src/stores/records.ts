// The Records section: what Odin did and how he is, in the shapes of Odin's /api/audit, /api/usage,
// /api/health/components, /api/logs, /api/turn-state and /api/computer routes. Read-only, except computer-use cleanup.
import { reactive } from 'vue'
import type { AuditEntry, AuditVerify, ComputerStatus, HealthReport, LogEntry, TurnStateReport, UsageResult } from '../../../shared/api'
import { act, failure, management } from './management'

export const records = reactive({
  audit: [] as AuditEntry[],
  verify: null as AuditVerify | null,
  usage: null as UsageResult | null,
  health: null as HealthReport | null,
  logs: [] as LogEntry[],
  turns: null as TurnStateReport | null,
  computer: null as ComputerStatus | null
})

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
  management.error = failure(result)
  if (result.ok) records.audit = result.result
}

export async function verifyAudit(): Promise<void> {
  const result = await window.odin.auditVerify({})
  records.verify = result.ok ? result.result : { valid: false, reason: result.error.message }
}

export async function loadUsage(period: '24h' | '7d' | '30d' | 'all'): Promise<void> {
  const result = await window.odin.usage(period)
  if (result.ok) records.usage = result.result
}

export async function loadHealth(): Promise<void> {
  const result = await window.odin.healthGet({})
  if (result.ok) records.health = result.result
}

let latestLogs = 0

export async function searchLogs(filter: { q?: string; level?: 'error' | 'info' | 'all' } = {}): Promise<void> {
  const mine = ++latestLogs
  const result = await window.odin.logsSearch({ limit: 200, level: filter.level ?? 'all', ...(filter.q ? { q: filter.q } : {}) })
  if (mine !== latestLogs) return
  if (result.ok) records.logs = result.result.entries
}

export async function loadTurns(): Promise<void> {
  const result = await window.odin.turnStateList({ limit: 50 })
  if (result.ok) records.turns = result.result
}

export async function loadComputer(): Promise<void> {
  const result = await window.odin.computerStatus({})
  if (result.ok) records.computer = result.result
}

/** Odin's headless release-all: the session's input release couldn't be verified, and you say you've checked. */
export async function reconcileComputer(session: { session_id: string; generation: number }): Promise<boolean> {
  return act(
    `computer:${session.session_id}`,
    () =>
      window.odin.computerReconcile({
        session_id: session.session_id,
        generation: session.generation,
        acknowledgment: `ACKNOWLEDGE UNVERIFIED CLEANUP ${session.session_id}`
      }),
    () => 'Reconciled: the session is released.',
    loadComputer
  )
}

export async function loadRecords(): Promise<void> {
  await Promise.all([loadAudit(), loadUsage('7d'), loadHealth(), searchLogs(), loadTurns(), loadComputer()])
}
