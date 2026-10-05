// Schedules' state, and the one lock a schedule has wherever it is run from: the settings menu or the work list.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, ScheduleRow, WorkItem } from '../../src/shared/api'

type Schedules = typeof import('../../src/renderer/src/stores/schedules')
type Work = typeof import('../../src/renderer/src/stores/work')

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const unknown = (id: string) => ({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: id } }) as const
const ROW = { id: 'sched01', description: 'Disk report', action: 'check', paused: false } as ScheduleRow
const ITEM = { kind: 'schedule', id: 'sched01', state: 'scheduled' } as WorkItem

let schedules: Schedules
let work: Work
let runs: Array<Record<string, unknown>>
let lists: Array<(answer: Result<ScheduleRow[]>) => void>
let holdLists: boolean

beforeEach(async () => {
  vi.resetModules()
  runs = []
  lists = []
  holdLists = false
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      schedulesRun: async (params: Record<string, unknown>) => (runs.push({ surface: 'schedules', ...params }), unknown('cmd-run')),
      workControl: async (params: Record<string, unknown>) => (runs.push({ surface: 'work', ...params }), unknown(String(params.control_command_id))),
      schedulesList: () => (holdLists ? new Promise((resolve) => lists.push(resolve)) : Promise.resolve(ok([ROW]))),
      workList: async () => ok({ items: [ITEM] })
    }
  }
  schedules = await import('../../src/renderer/src/stores/schedules')
  work = await import('../../src/renderer/src/stores/work')
})

describe('review round 4: a schedule run with no answer holds the schedule everywhere (15.R4.1)', () => {
  it("doesn't run it again from the work list", async () => {
    await schedules.runNow(ROW)
    await work.controlWork(ITEM, 'run_now')
    expect(runs.map((r) => r.surface)).toEqual(['schedules'])
  })

  it("doesn't run it again from the settings menu", async () => {
    await work.controlWork(ITEM, 'run_now')
    await schedules.runNow(ROW)
    expect(runs.map((r) => r.surface)).toEqual(['work'])
  })

  it('frees it on both once the late receipt settles the run', async () => {
    await schedules.runNow(ROW)
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'cmd-run', settled: ok({ status: 'success' }) })
    await work.controlWork(ITEM, 'run_now')
    expect(runs.map((r) => r.surface)).toEqual(['schedules', 'work'])
  })
})

describe('review round 4: the schedule list', () => {
  it('never lets an older answer replace a newer one (15.R4.3)', async () => {
    holdLists = true
    const older = schedules.loadSchedules()
    const newer = schedules.loadSchedules()
    lists[1]!(ok([{ ...ROW, paused: true }]))
    await newer
    lists[0]!(ok([{ ...ROW, paused: false }]))
    await older
    expect(schedules.schedules.list[0]?.paused).toBe(true)
  })
})
