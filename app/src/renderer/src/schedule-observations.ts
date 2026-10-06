import type { ScheduleRow, ScheduleRun } from '../../shared/api'

/** Display the scheduler's observations without turning unknown effects into a successful run. */
export function scheduleRecovery(row: ScheduleRow): string[] {
  const lines: string[] = []
  if (row.recovery_required) lines.push(row.recovery_required)
  const missed = row.missed_run
  if (missed) {
    const count = `${missed.count_truncated ? 'at least ' : ''}${missed.missed_count}`
    lines.push(`Missed ${count} scheduled run${missed.missed_count === 1 ? '' : 's'}; due ${missed.due_at}.`)
    if (missed.policy === 'coalesced') lines.push('Missed reminders are coalesced into one catch-up notice, not one delivery per missed run.')
    else lines.push('Missed actions are not replayed automatically. Run now is a separate explicit action.')
  }
  if (row.settlement) lines.push(`Last run settlement: ${row.settlement}.`)
  return lines
}

export function scheduleRunLabel(run: Pick<ScheduleRun, 'status'>): string {
  return run.status === 'success' ? 'Succeeded' : run.status === 'failure' ? 'Failed' : run.status === 'skipped' ? 'Not run' : 'Unknown'
}
