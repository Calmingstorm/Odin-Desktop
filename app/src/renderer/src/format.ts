// How the window writes numbers the core reports. A measured value is shown as it is, an estimate is marked with "~",
// and an unknown value is a dash: the window never invents a number.
import type { Measured } from '../../shared/api'

const WEAKER: Record<Measured['kind'], number> = { measured: 0, estimated: 1, unknown: 2 }

export function compact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, '')}K`
  return String(Math.round(value))
}

function shown(value: Measured, text: (n: number) => string): string {
  if (value.kind === 'unknown' || value.value === null) return '—'
  return value.kind === 'estimated' ? `~${text(value.value)}` : text(value.value)
}

export function count(value: Measured): string {
  return shown(value, compact)
}

export function percent(value: Measured): string {
  return shown(value, (n) => `${Math.round(n)}%`)
}

/** Used against budget as a share; as uncertain as the less certain of the two. */
export function share(used: Measured, budget: Measured): Measured {
  const kind = WEAKER[used.kind] >= WEAKER[budget.kind] ? used.kind : budget.kind
  if (kind === 'unknown' || used.value === null || budget.value === null || budget.value <= 0) {
    return { value: null, kind: 'unknown' }
  }
  return { value: (used.value / budget.value) * 100, kind }
}

/** What a value's tag means, for tooltips. */
export function basis(value: Measured): string {
  if (value.kind === 'measured') return 'measured'
  if (value.kind === 'estimated') return 'estimated'
  return "not measured: Odin doesn't know this value"
}

/** Whether two instants fall on the same day on this computer's clock. */
export function sameDay(a: string, b: string): boolean {
  return new Date(a).toDateString() === new Date(b).toDateString()
}

/** A day heading for the transcript: Today, Yesterday, else the weekday and date (with the year when it isn't this one). */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const date = new Date(iso)
  if (!Number.isFinite(date.getTime())) return ''
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (date.toDateString() === now.toDateString()) return 'Today'
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return date.toLocaleDateString([], {
    weekday: 'long', month: 'long', day: 'numeric', ...(date.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' as const })
  })
}
