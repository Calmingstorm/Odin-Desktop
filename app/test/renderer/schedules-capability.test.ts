import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, ScheduleRow } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

const refused = (): Result<never> => ({ ok: false, error: { code: 'capability_unavailable', message: 'Service is not available yet', disposition: 'not_dispatched' } })
const row = { id: 'old', description: 'Cached fixture schedule', action: 'reminder', channel_id: 'old', paused: false } as ScheduleRow
let store: typeof import('../../src/renderer/src/stores/schedules')
let work: typeof import('../../src/renderer/src/stores/work')
let management: typeof import('../../src/renderer/src/stores/management')
let view: Mounted | undefined
const list = vi.fn(async (): Promise<Result<ScheduleRow[]>> => refused())

beforeEach(async () => {
  vi.resetModules()
  list.mockReset().mockResolvedValue(refused())
  vi.stubGlobal('window', { odin: { schedulesList: list } })
  vi.stubGlobal('document', { activeElement: null })
  store = await import('../../src/renderer/src/stores/schedules')
  work = await import('../../src/renderer/src/stores/work')
  management = await import('../../src/renderer/src/stores/management')
  view = undefined
})

afterEach(() => {
  view?.unmount()
  vi.unstubAllGlobals()
})

describe('schedule capability refusal after the settings merge', () => {
  it('clears cached list and history, retains the shared unknown-outcome lock, and recovers on a served read', async () => {
    store.schedules.list = [row]
    store.schedules.history.old = [{ status: 'success' } as never]
    store.schedules.cron = { expression: '0 9 * * *', next_runs: ['old'], error: '' }
    management.management.busy['schedule:old'] = true
    await store.loadSchedules()
    expect(store.schedules).toMatchObject({ unavailable: true, loaded: true, list: [], history: {}, cron: null })
    expect(management.management.error).toBe('')
    expect(work.work.busy['schedule:old']).toBe(true)
    list.mockResolvedValueOnce({ ok: true, result: [row] })
    await store.loadSchedules()
    expect(store.schedules.unavailable).toBe(false)
    expect(store.schedules.list).toEqual([row])
  })

  it('renders scheduling and work refusal separately without successful-empty claims or creation controls', async () => {
    work.work.unavailable = true
    work.work.error = 'Work (agents, tasks, loops, processes, workflows and schedules) is unavailable in this core.'
    const Work = (await import('../../src/renderer/src/views/settings/Work.vue')).default
    view = mount(Work)
    await flush()
    expect(list).toHaveBeenCalledWith({})
    expect(view.root.textContent()).toContain('Scheduling is unavailable.')
    expect(view.root.textContent()).toContain('Work (agents, tasks, loops, processes, workflows and schedules) is unavailable.')
    expect(view.root.textContent()).not.toMatch(/New schedule|No schedules yet|Nothing is running|Service is not available yet/)
    expect(view.root.findAll(node => node.props.role === 'alert')).toEqual([])
    expect(view.root.find('input')).toBeUndefined()
  })

  it('does not relabel genuine failures as an unavailable capability', async () => {
    list.mockResolvedValueOnce({ ok: false, error: { code: 'internal', message: 'Database failed' } })
    await store.loadSchedules()
    expect(store.schedules.unavailable).toBe(false)
    expect(management.management.error).toBe('Database failed')
  })
})
