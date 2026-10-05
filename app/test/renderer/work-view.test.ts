// The schedule form in the settings menu, mounted with its real code and the real stores over a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, ScheduleRow } from '../../src/shared/api'
import type { ScheduleForm } from '../../src/renderer/src/schedule-form'
import { flush, mount, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const ROW = { id: 'sched01', description: 'Disk report', action: 'reminder', channel_id: 'c1', cron: '0 9 * * *', timezone: 'UTC', message: 'Check disks', paused: false } as ScheduleRow

let view: Mounted
let saves: Array<{ params: Record<string, unknown>; land: (answer?: Result<unknown>) => void }>

type Editing = { form: ScheduleForm; original: ScheduleRow | null } | null

beforeEach(async () => {
  vi.resetModules()
  saves = []
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      schedulesList: async () => ok([ROW]),
      schedulesValidateCron: async () => ok({ next_runs: [] }),
      schedulesSave: (params: Record<string, unknown>) =>
        new Promise((resolve) =>
          saves.push({ params, land: (answer) => resolve(answer ?? ok({ ...ROW, id: String(params.id ?? 'sched02'), description: params.description ?? ROW.description })) })
        )
    }
  }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
  const Work = (await import('../../src/renderer/src/views/settings/Work.vue')).default
  view = mount(Work)
  await flush()
})

const editing = (): Editing => view.setup.editing as Editing
const call = (name: string, ...args: unknown[]): unknown => (view.setup[name] as (...a: unknown[]) => unknown)(...args)

describe('review round 4: a schedule save that lands finds the form it belongs to (15.R4.4)', () => {
  it('leaves another form opened since alone', async () => {
    call('startEdit', ROW)
    editing()!.form.description = 'first'
    void call('save')
    await flush()
    call('startNew')
    Object.assign(editing()!.form, { description: 'second unsaved form', channel_id: 'c1', cron: '0 8 * * *' })
    saves.shift()!.land()
    await flush()
    expect(editing()?.form.description).toBe('second unsaved form')
    expect(editing()?.original).toBeNull()
  })

  it('keeps a form changed since it was sent open, now editing what was saved', async () => {
    call('startNew')
    Object.assign(editing()!.form, { description: 'Nightly', channel_id: 'c1', cron: '0 2 * * *' })
    void call('save')
    await flush()
    editing()!.form.message = 'retain me'
    saves.shift()!.land(ok({ ...ROW, id: 'sched02', description: 'Nightly' }))
    await flush()
    expect(editing()?.form.message).toBe('retain me')
    expect(editing()?.original?.id).toBe('sched02') // a second save changes it, never creates another
  })

  it('closes the form when an unchanged save lands by a late receipt', async () => {
    call('startNew')
    Object.assign(editing()!.form, { description: 'Nightly', channel_id: 'c1', cron: '0 2 * * *' })
    void call('save')
    await flush()
    saves.shift()!.land({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'cmd-save' } } as Result<unknown>)
    await flush()
    expect(editing()).not.toBeNull()
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'cmd-save', settled: ok({ ...ROW, id: 'sched02', description: 'Nightly' }) })
    await flush()
    expect(editing()).toBeNull()
  })
})
