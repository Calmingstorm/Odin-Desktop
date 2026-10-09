import type { WorkItem } from '../../shared/api'

/** Real managers use Unix seconds, while fixture/scheduler dates are ISO strings. */
export function workStartedMillis(value: WorkItem['started_at']): number {
  const time = typeof value === 'number' ? value * 1000 : value ? Date.parse(value) : NaN
  return Number.isFinite(time) ? time : 0
}
