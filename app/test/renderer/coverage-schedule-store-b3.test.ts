// Exercise the real schedules/management stores. Only the preload IPC boundary is fake:
// cron coverage must not depend on Work.vue's 400 ms debounce beating suite teardown.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, ScheduleRow, ScheduleRun, ScheduleRunResult } from '../../src/shared/api'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const failed = (message: string): Result<never> => ({ ok: false, error: { code: 'internal', message } })
const refused = (): Result<never> => ({ ok: false, error: { code: 'capability_unavailable', message: 'Scheduling unavailable', disposition: 'not_dispatched' } })
const ROW: ScheduleRow = {
  id: 'b3-schedule', description: 'Disk report', action: 'check', channel_id: 'c1',
  created_at: '2026-10-07T00:00:00Z', paused: false
}
const RUN: ScheduleRun = {
  schedule_id: ROW.id, description: ROW.description, action: ROW.action,
  timestamp: '2026-10-07T22:00:00Z', status: 'success', duration_ms: 12
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((land) => { resolve = land })
  return { promise, resolve }
}

const bridge = {
  schedulesList: vi.fn(async (): Promise<Result<ScheduleRow[]>> => ok([ROW])),
  schedulesHistory: vi.fn(async (): Promise<Result<ScheduleRun[]>> => ok([RUN])),
  schedulesValidateCron: vi.fn(async (): Promise<Result<{ next_runs: string[] }>> => ok({ next_runs: ['2026-10-08T09:00:00Z'] })),
  schedulesSave: vi.fn(async (): Promise<Result<ScheduleRow>> => ok(ROW)),
  schedulesRun: vi.fn(async (): Promise<Result<ScheduleRunResult>> => ok({ schedule_id: ROW.id, status: 'success' })),
  schedulesResetFailures: vi.fn(async (): Promise<Result<Record<string, never>>> => ok({})),
  schedulesDelete: vi.fn(async (): Promise<Result<Record<string, never>>> => ok({}))
}
let store: typeof import('../../src/renderer/src/stores/schedules')
let management: typeof import('../../src/renderer/src/stores/management')
let core: typeof import('../../src/renderer/src/store')

beforeEach(async () => {
  vi.resetModules()
  vi.resetAllMocks()
  bridge.schedulesList.mockResolvedValue(ok([ROW]))
  bridge.schedulesHistory.mockResolvedValue(ok([RUN]))
  bridge.schedulesValidateCron.mockResolvedValue(ok({ next_runs: ['2026-10-08T09:00:00Z'] }))
  bridge.schedulesSave.mockResolvedValue(ok(ROW))
  bridge.schedulesRun.mockResolvedValue(ok({ schedule_id: ROW.id, status: 'success' }))
  bridge.schedulesResetFailures.mockResolvedValue(ok({}))
  bridge.schedulesDelete.mockResolvedValue(ok({}))
  vi.stubGlobal('window', { odin: bridge })
  store = await import('../../src/renderer/src/stores/schedules')
  management = await import('../../src/renderer/src/stores/management')
  core = await import('../../src/renderer/src/store')
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('B3 real schedule store: cron validation is explicit, ordered and fenced', () => {
  it('trims the IPC expression, retains the displayed draft, and clears a blank draft without IPC', async () => {
    await store.checkCron(' 0 9 * * * ')
    expect(bridge.schedulesValidateCron).toHaveBeenCalledWith({ expression: '0 9 * * *' })
    expect(store.schedules.cron).toEqual({ expression: ' 0 9 * * * ', next_runs: ['2026-10-08T09:00:00Z'], error: '' })
    await store.checkCron(' \t ')
    expect(store.schedules.cron).toBeNull()
    expect(bridge.schedulesValidateCron).toHaveBeenCalledTimes(1)
  })

  it('shows validation errors as errors, never as a successful empty next-run list', async () => {
    bridge.schedulesValidateCron.mockResolvedValueOnce(failed('Expected five cron fields'))
    await store.checkCron('not cron')
    expect(store.schedules.cron).toEqual({ expression: 'not cron', next_runs: [], error: 'Expected five cron fields' })
  })

  it('keeps the newer answer when an older request finishes last', async () => {
    const old = deferred<Result<{ next_runs: string[] }>>()
    bridge.schedulesValidateCron.mockReturnValueOnce(old.promise)
    const pending = store.checkCron('0 8 * * *')
    await store.checkCron('0 9 * * *')
    old.resolve(failed('Stale validation error'))
    await pending
    expect(store.schedules.cron).toEqual({ expression: '0 9 * * *', next_runs: ['2026-10-08T09:00:00Z'], error: '' })
  })

  it.each(['blank draft', 'capability refusal'])('does not resurrect a pending answer after %s', async (fence) => {
    const old = deferred<Result<{ next_runs: string[] }>>()
    bridge.schedulesValidateCron.mockReturnValueOnce(old.promise)
    const pending = store.checkCron('0 9 * * *')
    if (fence === 'blank draft') await store.checkCron('')
    else {
      bridge.schedulesList.mockResolvedValueOnce(refused())
      await store.loadSchedules()
      expect(store.schedules).toMatchObject({ loaded: true, unavailable: true, list: [], history: {} })
    }
    old.resolve(ok({ next_runs: ['stale'] }))
    await pending
    expect(store.schedules.cron).toBeNull()
  })
})

describe('B3 real schedule controls use actual management actions and refreshes', () => {
  it.each([true, false])('sends only id and paused=%s, reports the receipt and rereads actual state', async (paused) => {
    bridge.schedulesList.mockResolvedValueOnce(ok([{ ...ROW, paused }]))
    await store.setPaused(ROW, paused)
    expect(bridge.schedulesSave).toHaveBeenCalledWith({ id: ROW.id, paused })
    expect(management.management.notes[`schedule:${ROW.id}`]).toBe(paused ? 'Paused.' : 'Running on its schedule again.')
    expect(management.management.busy[`schedule:${ROW.id}`]).toBe(false)
    expect(bridge.schedulesList).toHaveBeenCalledWith({})
    expect(store.schedules.list[0]?.paused).toBe(paused)
  })

  it('clears failures and retries through the bridge, then adopts the returned list', async () => {
    bridge.schedulesList.mockResolvedValueOnce(ok([{ ...ROW, consecutive_failures: 0, retry_at: null }]))
    await store.resetFailures(ROW)
    expect(bridge.schedulesResetFailures).toHaveBeenCalledWith({ id: ROW.id })
    expect(management.management.notes[`schedule:${ROW.id}`]).toBe('Failures cleared, and pending retries cancelled.')
    expect(store.schedules.list[0]).toMatchObject({ consecutive_failures: 0, retry_at: null })
  })

  it('deletes by immutable id and removes the row only from the authoritative refresh', async () => {
    store.schedules.list = [ROW]
    bridge.schedulesList.mockResolvedValueOnce(ok([]))
    await store.deleteSchedule(ROW)
    expect(bridge.schedulesDelete).toHaveBeenCalledWith({ id: ROW.id })
    expect(management.management.notes[`schedule:${ROW.id}`]).toBe('Deleted.')
    expect(store.schedules.list).toEqual([])
  })

  it('retains a shared lock for an uncertain pause and settles it only from the late receipt', async () => {
    bridge.schedulesSave.mockResolvedValueOnce({ ok: false, error: { code: 'no_receipt', message: 'Pending', disposition: 'outcome_unknown', command_id: 'b3-pause' } })
    await store.setPaused(ROW, true)
    expect(management.management.busy[`schedule:${ROW.id}`]).toBe(true)
    await store.deleteSchedule(ROW)
    expect(bridge.schedulesDelete).not.toHaveBeenCalled()
    expect(bridge.schedulesList).not.toHaveBeenCalled()
    bridge.schedulesList.mockResolvedValueOnce(ok([{ ...ROW, paused: true }]))
    core.applyReceipt({ id: 'b3-pause', settled: ok({ ...ROW, paused: true }) })
    await vi.waitFor(() => expect(store.schedules.list[0]?.paused).toBe(true))
    expect(management.management.busy[`schedule:${ROW.id}`]).toBe(false)
    expect(management.management.notes[`schedule:${ROW.id}`]).toBe('Paused.')
  })

  it('does not claim deletion when the core rejects it', async () => {
    bridge.schedulesDelete.mockResolvedValueOnce(failed('Schedule is executing'))
    await store.deleteSchedule(ROW)
    expect(management.management.notes[`schedule:${ROW.id}`]).toBe('Schedule is executing')
    expect(store.schedules.list).toEqual([ROW])
  })
})

describe('B3 schedule read/save/run integration', () => {
  it('reports an ordinary list failure without inventing capability refusal or clearing the cached list', async () => {
    store.schedules.list = [ROW]
    bridge.schedulesList.mockResolvedValueOnce(failed('Database failed'))
    await store.loadSchedules()
    expect(store.schedules.list).toEqual([ROW])
    expect(store.schedules.unavailable).toBe(false)
    expect(management.management.error).toBe('Database failed')
  })

  it('loads history with a bounded request and reports a genuine history error', async () => {
    await store.loadHistory(ROW.id)
    expect(bridge.schedulesHistory).toHaveBeenCalledWith({ id: ROW.id, limit: 20 })
    expect(store.schedules.history[ROW.id]).toEqual([RUN])
    bridge.schedulesHistory.mockResolvedValueOnce(failed('History failed'))
    await store.loadHistory(ROW.id)
    expect(management.management.notes[`schedule:${ROW.id}`]).toBe('History failed')
    expect(store.schedules.history[ROW.id]).toEqual([RUN])
  })

  it('drops history obtained before a new list generation', async () => {
    const old = deferred<Result<ScheduleRun[]>>()
    bridge.schedulesHistory.mockReturnValueOnce(old.promise)
    const pending = store.loadHistory(ROW.id)
    await store.loadSchedules()
    old.resolve(ok([RUN]))
    await pending
    expect(store.schedules.history[ROW.id]).toBeUndefined()
  })

  it.each([null, '2026-10-08T09:00:00Z'])('adopts a saved row and formats its next run=%s', async (next_run) => {
    const row = { ...ROW, next_run }
    bridge.schedulesSave.mockResolvedValueOnce(ok(row))
    const saved = vi.fn()
    expect(await store.saveSchedule({ id: ROW.id, description: 'Changed' }, saved)).toBe(true)
    expect(saved).toHaveBeenCalledWith(row)
    expect(bridge.schedulesSave).toHaveBeenCalledWith({ id: ROW.id, description: 'Changed' })
    expect(management.management.notes[`schedule:${ROW.id}`]).toBe(next_run ? `Saved. It runs next ${new Date(next_run).toLocaleString()}.` : 'Saved.')
  })

  it.each([
    [{ status: 'success' }, 'Ran: it succeeded.'],
    [{ status: 'failure', error: 'Disk full', warning: 'Retry pending' }, 'Ran: it failed. Disk full Note: Retry pending.'],
    [{ status: 'skipped' }, 'Not run: skipped.']
  ] as const)('reports the actual run outcome %# and refreshes an open history', async (outcome, note) => {
    store.schedules.history[ROW.id] = []
    bridge.schedulesRun.mockResolvedValueOnce(ok({ schedule_id: ROW.id, ...outcome }))
    await store.runNow(ROW)
    expect(bridge.schedulesRun).toHaveBeenCalledWith({ id: ROW.id })
    expect(management.management.notes[`schedule:${ROW.id}`]).toBe(note)
    expect(bridge.schedulesList).toHaveBeenCalledWith({})
    expect(store.schedules.history[ROW.id]).toEqual([RUN])
  })

  it('coalesces schedule work events into one authoritative reread', async () => {
    vi.useFakeTimers()
    await store.loadSchedules()
    bridge.schedulesList.mockResolvedValueOnce(ok([{ ...ROW, paused: true }]))
    for (const seq of [1, 2]) core.applyEvent({ type: 'work.updated', seq, cursor: String(seq), at: '',
      entity: { kind: 'schedule', id: ROW.id }, payload: { kind: 'schedule', id: ROW.id, state: 'scheduled' } })
    expect(bridge.schedulesList).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(200)
    expect(bridge.schedulesList).toHaveBeenCalledTimes(2)
    expect(store.schedules.list[0]?.paused).toBe(true)
  })
})
