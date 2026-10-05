// Local wall clock to instant, with the two daylight-saving cases made explicit: a port of Odin's ui/js/schedule-time.js.
//
// `new Date('2026-03-08T02:30')` does not fail on a time that never happens: it quietly returns 03:30. And
// `new Date('2026-11-01T01:30')` quietly picks the first of two real instants an hour apart. Either way someone would
// schedule a moment they did not choose, which is the defect this module exists to prevent.
//
// The zone is a parameter so tests can fix one; the app uses the computer's own.

/** Minutes behind UTC at an instant, as Date.getTimezoneOffset() counts them. */
export interface Zone {
  offsetMinutes(ms: number): number
}

export const SYSTEM_ZONE: Zone = { offsetMinutes: (ms) => new Date(ms).getTimezoneOffset() }

// Anchored at both ends, so "2026-04-01T09:00garbage" is not valid.
const PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/

const pad = (n: number): string => String(n).padStart(2, '0')

/** An instant as the wall-clock text a datetime-local input shows. */
export function localWallClock(ms: number, withSeconds = false, zone: Zone = SYSTEM_ZONE): string {
  const shifted = new Date(ms - zone.offsetMinutes(ms) * 60_000)
  const base =
    `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}` +
    `T${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}`
  return withSeconds ? `${base}:${pad(shifted.getUTCSeconds())}` : base
}

/** The offset at an instant, such as "UTC-4" or "UTC+10:30". */
export function offsetLabel(ms: number, zone: Zone = SYSTEM_ZONE): string {
  const minutes = -zone.offsetMinutes(ms)
  const sign = minutes >= 0 ? '+' : '-'
  const abs = Math.abs(minutes)
  const rest = abs % 60
  return `UTC${sign}${Math.floor(abs / 60)}${rest ? `:${pad(rest)}` : ''}`
}

export interface Occurrence {
  ms: number
  offset: string
  iso: string
}

export type LocalTime =
  | { state: 'empty' }
  | { state: 'invalid'; typed: string }
  | { state: 'nonexistent'; typed: string }
  | { state: 'ambiguous'; typed: string; options: Occurrence[] }
  | { state: 'ok'; typed: string; ms: number; iso: string }

/** Classifies a datetime-local value: empty, invalid, skipped by the clocks, happening twice, or one instant. */
export function analyzeLocalDateTime(raw: string, zone: Zone = SYSTEM_ZONE): LocalTime {
  const typed = String(raw || '').trim()
  if (!typed) return { state: 'empty' }
  const match = PATTERN.exec(typed)
  if (!match) return { state: 'invalid', typed }
  const part = (i: number): number => Number(match[i])
  // Seconds are optional, but honoured when given: accepting 09:00:30 and scheduling 09:00:00 would be the same
  // quiet reinterpretation.
  const ss = match[6] === undefined ? 0 : Number(match[6])
  if (ss > 59) return { state: 'invalid', typed }
  const withSeconds = match[6] !== undefined
  const normalized = withSeconds ? typed.slice(0, 19) : typed.slice(0, 16)

  // Read the typed parts as if they were UTC, then apply the zone's offset. The offset differs on either side of a
  // change, so probe both sides rather than assume how far the clocks move: some zones move 30 minutes, some two hours.
  const asIfUtc = Date.UTC(part(1), part(2) - 1, part(3), part(4), part(5), ss)
  const candidates: number[] = []
  for (const offset of new Set([zone.offsetMinutes(asIfUtc - 86_400_000), zone.offsetMinutes(asIfUtc + 86_400_000)])) {
    const ms = asIfUtc + offset * 60_000
    // Keep only instants that really show the typed wall clock.
    if (localWallClock(ms, withSeconds, zone) !== normalized || candidates.includes(ms)) continue
    candidates.push(ms)
  }
  candidates.sort((a, b) => a - b)
  const [only] = candidates
  if (only === undefined) return { state: 'nonexistent', typed }
  if (candidates.length > 1) {
    return {
      state: 'ambiguous',
      typed,
      options: candidates.map((ms) => ({ ms, offset: offsetLabel(ms, zone), iso: new Date(ms).toISOString() }))
    }
  }
  return { state: 'ok', typed, ms: only, iso: new Date(only).toISOString() }
}
