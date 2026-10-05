// The work panel's state, driven through a fake bridge: the list is the authority, events patch it at once.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CoreEvent, Result, WorkItem } from '../../src/shared/api'

type WorkStore = typeof import('../../src/renderer/src/stores/work')

function item(fields: Partial<WorkItem> & Pick<WorkItem, 'id' | 'kind'>): WorkItem {
  return { title: fields.id, state: 'running', detail: '', actions: ['stop'], ...fields }
}

let work: WorkStore
let listed: WorkItem[]
let controls: Array<Record<string, unknown>>
let controlAnswer: Result<{ disposition: string }>
let lists: number
/** When set, control answers wait here until the test releases them. */
let holdControls = false
let heldControls: Array<(answer: Result<{ disposition: string }>) => void> = []

function event(seq: number, payload: Record<string, unknown>): CoreEvent {
  return { seq, cursor: String(seq), type: 'work.updated', entity: { kind: 'work', id: String(payload.id) }, at: '2026-10-05T00:00:00Z', payload }
}

beforeEach(async () => {
  vi.resetModules()
  vi.useRealTimers()
  listed = []
  controls = []
  lists = 0
  controlAnswer = { ok: true, result: { disposition: 'requested' } }
  holdControls = false
  heldControls = []
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      workList: async () => {
        lists += 1
        return { ok: true, result: { items: listed.map((i) => ({ ...i, actions: [...i.actions] })) } }
      },
      workControl: (params: Record<string, unknown>) => {
        controls.push(params)
        if (!holdControls) return Promise.resolve(controlAnswer)
        return new Promise<Result<{ disposition: string }>>((resolve) => heldControls.push(resolve))
      }
    }
  }
  delete (globalThis as unknown as { document?: unknown }).document
  work = await import('../../src/renderer/src/stores/work')
})

describe('the work panel', () => {
  it('groups by kind in a fixed order, running items first, newest first, and counts what runs', async () => {
    listed = [
      item({ id: 's1', kind: 'schedule', state: 'active', actions: ['pause', 'run_now'] }),
      item({ id: 'a-old', kind: 'agent', state: 'completed', actions: [], started_at: '2026-10-05T09:00:00Z' }),
      item({ id: 'a-new', kind: 'agent', started_at: '2026-10-05T10:00:00Z' }),
      item({ id: 'a-mid', kind: 'agent', started_at: '2026-10-05T09:30:00Z' }),
      item({ id: 'p1', kind: 'process' })
    ]
    await work.loadWork()
    expect(work.grouped().map((g) => [g.kind, g.items.map((i) => i.id)])).toEqual([
      ['agent', ['a-new', 'a-mid', 'a-old']],
      ['process', ['p1']],
      ['schedule', ['s1']]
    ])
    expect(work.activeCount()).toBe(3)
  })

  it('patches the state from an event at once, then fetches the list again for its new controls', async () => {
    listed = [item({ id: 'a1', kind: 'agent' })]
    await work.loadWork()
    listed = [item({ id: 'a1', kind: 'agent', state: 'stopped', actions: [] })]
    work.applyWorkEvent(event(1, { kind: 'agent', id: 'a1', state: 'stopping' }))
    expect(work.work.items[0]!.state).toBe('stopping')
    expect(work.work.items[0]!.actions).toEqual(['stop'])
    await vi.waitFor(() => expect(work.work.items[0]!.state).toBe('stopped'))
    expect(work.work.items[0]!.actions).toEqual([])
  })

  it('collapses a burst of events into one fetch', async () => {
    await work.loadWork()
    const before = lists
    for (let seq = 1; seq <= 5; seq++) work.applyWorkEvent(event(seq, { kind: 'agent', id: 'a1', state: 'running' }))
    await vi.waitFor(() => expect(lists).toBe(before + 1))
    await new Promise((r) => setTimeout(r, 300))
    expect(lists).toBe(before + 1)
  })

  it('sends one control with a fresh command id, notes what the core said, and refreshes', async () => {
    const agent = item({ id: 'a1', kind: 'agent' })
    listed = [agent]
    await work.loadWork()
    await work.controlWork(work.work.items[0]!, 'stop')
    expect(controls).toEqual([{ control_command_id: expect.stringMatching(/^[0-9a-f-]{36}$/), kind: 'agent', id: 'a1', action: 'stop' }])
    expect(work.work.notes['agent:a1']).toBe('Stop: requested')
    controlAnswer = { ok: true, result: { disposition: 'not_available' } }
    await work.controlWork(work.work.items[0]!, 'stop')
    expect(work.work.notes['agent:a1']).toBe('Stop: no longer offered')
    expect(controls[0]!.control_command_id).not.toBe(controls[1]!.control_command_id)
  })

  it('keeps the last list and says why when a fetch fails', async () => {
    listed = [item({ id: 'a1', kind: 'agent' })]
    await work.loadWork()
    ;(window as unknown as { odin: { workList: () => Promise<unknown> } }).odin.workList = async () => ({
      ok: false,
      error: { code: 'unavailable', message: 'Odin is restarting.', disposition: 'not_dispatched' }
    })
    await work.loadWork()
    expect(work.work.error).toBe('Odin is restarting.')
    expect(work.work.items.map((i) => i.id)).toEqual(['a1'])
  })
})

describe('review round 2: controls are confirmed once, per item', () => {
  const UNKNOWN = { ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown' } } as const

  it("holds an unconfirmed Run now under its first command until that command's receipt settles it", async () => {
    const schedule = item({ id: 's1', kind: 'schedule', state: 'active', actions: ['pause', 'run_now'] })
    listed = [schedule]
    await work.loadWork()
    controlAnswer = UNKNOWN
    await work.controlWork(schedule, 'run_now')
    await work.controlWork(schedule, 'run_now')
    expect(controls).toHaveLength(1)
    expect(work.work.busy['schedule:s1']).toBe(true)
    expect(work.work.notes['schedule:s1']).toMatch(/waiting for Odin to confirm/)
    const store = await import('../../src/renderer/src/store')
    const first = String(controls[0]!.control_command_id)
    store.applyReceipt({ id: first, settled: UNKNOWN })
    expect(work.work.busy['schedule:s1']).toBe(true)
    store.applyReceipt({ id: first, settled: { ok: true, result: { disposition: 'done' } } })
    expect(work.work.busy['schedule:s1']).toBe(false)
    expect(work.work.notes['schedule:s1']).toBe('Run now: done')
    controlAnswer = { ok: true, result: { disposition: 'done' } }
    await work.controlWork(schedule, 'run_now') // settled, so a new command may go
    expect(controls.map((c) => c.control_command_id)).toEqual([first, expect.not.stringMatching(first)])
  })

  it('keeps items of different kinds that share an id apart', async () => {
    const agent = item({ id: 'x1', kind: 'agent' })
    const process = item({ id: 'x1', kind: 'process' })
    listed = [agent, process]
    await work.loadWork()
    holdControls = true
    const stopping = work.controlWork(agent, 'stop')
    expect(work.work.busy['agent:x1']).toBe(true)
    expect(work.work.busy['process:x1']).toBeFalsy()
    const stoppingProcess = work.controlWork(process, 'stop')
    expect(controls.map((c) => c.kind)).toEqual(['agent', 'process'])
    heldControls[0]!({ ok: true, result: { disposition: 'requested' } })
    heldControls[1]!({ ok: false, error: { code: 'not_found', message: 'that work is no longer listed', disposition: 'not_dispatched' } })
    await Promise.all([stopping, stoppingProcess])
    expect(work.work.notes['agent:x1']).toBe('Stop: requested')
    expect(work.work.notes['process:x1']).toBe('that work is no longer listed')
  })
})

