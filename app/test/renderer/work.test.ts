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
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      workList: async () => {
        lists += 1
        return { ok: true, result: { items: listed.map((i) => ({ ...i, actions: [...i.actions] })) } }
      },
      workControl: async (params: Record<string, unknown>) => {
        controls.push(params)
        return controlAnswer
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
    expect(work.work.notes.a1).toBe('Stop: requested')
    controlAnswer = { ok: true, result: { disposition: 'not_available' } }
    await work.controlWork(work.work.items[0]!, 'stop')
    expect(work.work.notes.a1).toBe('Stop: no longer offered')
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
