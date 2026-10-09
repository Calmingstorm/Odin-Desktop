// Schedules, in the shapes of Odin's /api/schedules routes: what each one does and when, its runs and failures, and
// the controls Odin's page offers. Running one now is a separate, explicit action; it never happens by itself.
import { reactive } from 'vue'
import type { ScheduleRow, ScheduleRun, ScheduleSave } from '../../../shared/api'
import { act, failure, management } from './management'
import { isUnavailable } from '../capability'
import { onCoreEvent, onReady } from '../store'

export const schedules = reactive({
  list: [] as ScheduleRow[],
  loaded: false,
  unavailable: false,
  history: {} as Record<string, ScheduleRun[] | undefined>,
  /** The last cron check: the expression, and its next runs or why it's not valid. */
  cron: null as { expression: string; timezone: string; next_runs: string[]; error: string } | null
})

/** Each read of the list, in order: an older answer never replaces a newer one. */
let listRead = 0

export async function loadSchedules(): Promise<void> {
  const mine = ++listRead
  const result = await window.odin.schedulesList({})
  if (mine !== listRead) return
  management.error = failure(result)
  schedules.unavailable = !result.ok && isUnavailable(result.error)
  if (schedules.unavailable) {
    latestCron += 1
    schedules.list = []
    schedules.history = {}
    schedules.cron = null
    schedules.loaded = true
    management.error = ''
    return
  }
  if (result.ok) {
    schedules.list = result.result
    schedules.loaded = true
  }
}

export async function loadHistory(id: string): Promise<void> {
  const generation = listRead
  const result = await window.odin.schedulesHistory({ id, limit: 20 })
  if (generation !== listRead || schedules.unavailable) return
  if (result.ok) schedules.history[id] = result.result
  else management.notes[`schedule:${id}`] = result.error.message
}

/**
 * Saves a new schedule or a change; the note says what the core did, and the list shows the result. `saved` gets the
 * saved schedule whenever the save lands, at once or by a late receipt.
 */
export async function saveSchedule(change: ScheduleSave, saved?: (row: ScheduleRow) => void): Promise<boolean> {
  const key = 'id' in change ? `schedule:${change.id}` : 'schedule:new'
  return act(key, () => window.odin.schedulesSave(change), (row) => {
    saved?.(row)
    return `Saved. ${row.next_run ? 'It runs next ' + new Date(row.next_run).toLocaleString() + '.' : ''}`.trim()
  }, loadSchedules)
}

export async function setPaused(row: ScheduleRow, paused: boolean): Promise<void> {
  await act(`schedule:${row.id}`, () => window.odin.schedulesSave({ id: row.id, paused }), () => (paused ? 'Paused.' : 'Running on its schedule again.'), loadSchedules)
}

export async function runNow(row: ScheduleRow): Promise<void> {
  await act(
    `schedule:${row.id}`,
    () => window.odin.schedulesRun({ id: row.id }),
    (r) => {
      const outcome = r.status === 'success' ? 'Ran: it succeeded.' : r.status === 'failure' ? `Ran: it failed. ${r.error ?? ''}` : `Not run: ${r.error ?? 'skipped'}.`
      return r.warning ? `${outcome} Note: ${r.warning}.` : outcome
    },
    async () => {
      await loadSchedules()
      if (schedules.history[row.id]) await loadHistory(row.id)
    }
  )
}

export async function resetFailures(row: ScheduleRow): Promise<void> {
  await act(`schedule:${row.id}`, () => window.odin.schedulesResetFailures({ id: row.id }), () => 'Failures cleared, and pending retries cancelled.', loadSchedules)
}

export async function deleteSchedule(row: ScheduleRow): Promise<void> {
  await act(`schedule:${row.id}`, () => window.odin.schedulesDelete({ id: row.id }), () => 'Deleted.', loadSchedules)
}

let latestCron = 0

/** Checks a cron expression with the core, which answers its next runs. A newer check answers instead of an older one. */
/** Previews the next runs as the scheduler computes them: in `timezone`, or UTC without one. */
export async function checkCron(expression: string, timezone = ''): Promise<void> {
  const mine = ++latestCron
  if (!expression.trim()) {
    schedules.cron = null
    return
  }
  const zone = timezone.trim()
  const result = await window.odin.schedulesValidateCron({ expression: expression.trim(), ...(zone ? { timezone: zone } : {}) })
  if (mine !== latestCron) return
  schedules.cron = result.ok
    ? { expression, timezone: zone, next_runs: result.result.next_runs, error: '' }
    : { expression, timezone: zone, next_runs: [], error: result.error.message }
}

// Work controls and automatic scheduler completions can change a definition while Settings is open.
// Re-read the actual schedule service rather than deriving pause/recovery state from a work event.
let refreshTimer: ReturnType<typeof setTimeout> | undefined
onCoreEvent((event) => {
  if (event.type !== 'work.updated' || event.payload.kind !== 'schedule' || !schedules.loaded || refreshTimer) return
  refreshTimer = setTimeout(() => {
    refreshTimer = undefined
    void loadSchedules()
  }, 200)
})

// A new incarnation or cursor reset invalidates the open Settings projection too.
onReady(() => { if (schedules.loaded) void loadSchedules() })
