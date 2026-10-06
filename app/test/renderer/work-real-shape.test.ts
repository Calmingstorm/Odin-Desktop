import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, WorkControlReceipt, WorkItem } from '../../src/shared/api'
import { flush, mount, type Mounted } from './component-host'

let view: Mounted | undefined
let work: typeof import('../../src/renderer/src/stores/work')
let listed: WorkItem[]
let controls: Record<string, unknown>[]
let land: ((answer: Result<WorkControlReceipt>) => void) | undefined
const agent = (): WorkItem => ({
  kind: 'agent', id: 'public01', manager_id: 'manager01', manager_generation: '2026-10-06T00:00:00Z', run_id: 'run01', generation: 3,
  conversation_id: 'conversation01', title: 'Inspect local fixture', state: 'running', actions: ['cancel', 'steer'],
  detail: { iteration_count: 0, max_iterations: 10, inbox_sequence: 2, last_consumed_sequence: 1, unsettled_descendants: ['child01'] },
  settlement: { state: 'pending', resource_release: 'unproven' }
})

beforeEach(async () => {
  vi.resetModules()
  listed = [agent()]
  controls = []
  land = undefined
  ;(globalThis as unknown as { window: unknown }).window = { odin: {
    workList: async () => ({ ok: true, result: { items: listed } }),
    workControl: (params: Record<string, unknown>) => {
      controls.push(params)
      return new Promise<Result<WorkControlReceipt>>((resolve) => { land = resolve })
    }
  } }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null, body: {}, getElementById: vi.fn(), querySelector: vi.fn() }
  work = await import('../../src/renderer/src/stores/work')
  await work.loadWork()
})
afterEach(() => { view?.unmount(); view = undefined })

describe('Work real-core projections and steering', () => {
  it('renders structured details and unknown resource release, not object stringification or inferred success', async () => {
    listed = [
      agent(),
      { kind: 'task', id: 'task01', title: 'Task', state: 'completed', actions: [], detail: { current_step: 1, steps: 2, results: 1, progress: 'Finished' }, settlement: { state: 'settled', resource_release: 'manager_task_finished', remote_effects: 'not_undone' } },
      { kind: 'workflow', id: 'workflow01', title: 'Workflow', state: 'running', actions: ['cancel'], detail: { current_step: 0, steps: 3 } },
      { kind: 'loop', id: 'loop01', title: 'Loop', state: 'running', actions: ['stop'], detail: { mode: 'silent', interval_seconds: 60 } },
      { kind: 'process', id: 'process01', title: 'Process', state: 'stopped', actions: ['stop'], detail: { session_confirmed_empty: false, containment: 'local_session' }, settlement: { state: 'unknown', resource_release: 'unknown' } },
      { kind: 'schedule', id: 'schedule01', title: 'Schedule', state: 'scheduled', actions: ['pause'], detail: { revision: 4, inert_reason: null }, settlement: { state: 'definition', last_run: { state: 'unknown', resource_release: 'unproven' } } }
    ]
    await work.loadWork()
    view = mount((await import('../../src/renderer/src/components/WorkList.vue')).default)
    const text = view.root.textContent()
    for (const value of ['Iteration count', 'Last consumed sequence', 'Unsettled descendants', 'Current step', 'Interval seconds', 'Session confirmed empty', 'Resource release', 'unknown', 'not_undone', 'Last run / Resource release']) expect(text).toContain(value)
    expect(text).not.toContain('[object Object]')
    expect(text).toContain('Resource release is not confirmed')
    expect(view.root.findAll((node) => node.tag === 'button').map((node) => node.textContent().trim())).not.toContain('Restart')
  })

  it('opens an inline steer form without dispatch and submits exact text and binding once', async () => {
    view = mount((await import('../../src/renderer/src/components/WorkList.vue')).default)
    await view.root.button('Steer').fire('click')
    await flush()
    expect(controls).toEqual([])
    const textarea = view.root.find('textarea')!
    textarea.type('Keep this correction exactly.\nNo replacement run.')
    const form = view.root.find('form')!
    const pending = form.fire('submit', { preventDefault: vi.fn() })
    await flush()
    await form.fire('submit', { preventDefault: vi.fn() })
    expect(controls).toEqual([{
      control_command_id: expect.any(String), kind: 'agent', id: 'public01', action: 'steer',
      manager_generation: '2026-10-06T00:00:00Z', run_id: 'run01', generation: 3, conversation_id: 'conversation01',
      text: 'Keep this correction exactly.\nNo replacement run.'
    }])
    land!({ ok: true, result: { disposition: 'queued', consumed: false, sequence: 3, settlement: { state: 'pending' } } })
    await pending
    await flush()
    expect(work.work.notes['agent:public01']).toBe('Steer: queued (sequence 3). Queued is not consumed.')
    expect(textarea.value).toBe('')
    expect((await import('../../src/renderer/src/dialog')).dialog.current).toBeNull()
  })

  it('blocks unsafe retries after an unknown steer and settles only the original late receipt', async () => {
    const pending = work.controlWork(listed[0]!, 'steer', 'One correction')
    const unknown = { ok: false, error: { code: 'internal', message: 'No receipt', disposition: 'outcome_unknown' } } as const
    land!(unknown)
    await pending
    await work.controlWork(listed[0]!, 'steer', 'One correction')
    expect(controls).toHaveLength(1)
    expect(work.work.busy['agent:public01']).toBe(true)
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: String(controls[0]!.control_command_id), settled: unknown })
    expect(work.work.busy['agent:public01']).toBe(true)
    store.applyReceipt({ id: String(controls[0]!.control_command_id), settled: { ok: true, result: { disposition: 'queued', consumed: false, sequence: 3 } } })
    expect(work.work.busy['agent:public01']).toBe(false)
    expect(work.work.notes['agent:public01']).toContain('Queued is not consumed')
  })

  it('shares schedule manager locks with Settings, submits immutable ID and exact listed revision', async () => {
    const schedule: WorkItem = { ...agent(), kind: 'schedule', id: 'immutable-schedule01', manager_id: 'short01', detail: { revision: 9 }, actions: ['pause', 'run_now'] }
    expect(work.workKey(schedule)).toBe('schedule:short01')
    work.work.busy['schedule:short01'] = true
    await work.controlWork(schedule, 'run_now')
    expect(controls).toEqual([])
    work.work.busy['schedule:short01'] = false
    const pausing = work.controlWork(schedule, 'pause')
    expect(controls[0]).toMatchObject({ id: 'immutable-schedule01', revision: 9 })
    expect(controls[0]).not.toHaveProperty('manager_id')
    land!({ ok: true, result: { disposition: 'done' } })
    await pausing
  })

  it('rejects non-offered controls and invalid steer, and applies full event projections immediately', async () => {
    for (const [action, text] of [['restart', undefined], ['steer', undefined], ['steer', '']] as const) await work.controlWork(listed[0]!, action, text)
    expect(controls).toEqual([])
    work.applyWorkEvent({ seq: 1, cursor: '1', type: 'work.updated', entity: { kind: 'work', id: 'public01' }, at: '', payload: {
      kind: 'agent', id: 'public01', state: 'interrupted', actions: [], detail: { last_consumed_sequence: 1 }, settlement: { state: 'unknown', resource_release: 'unproven' }
    } })
    expect(work.work.items[0]).toMatchObject({ state: 'interrupted', actions: [], settlement: { state: 'unknown', resource_release: 'unproven' }, detail: { last_consumed_sequence: 1 } })
  })

  it('sorts real manager epoch seconds alongside fixture ISO text without crashing', async () => {
    listed = [
      { ...agent(), id: 'older', started_at: 1791264600 },
      { ...agent(), id: 'newer', started_at: '2026-10-06T05:31:00Z' }
    ]
    await work.loadWork()
    expect(work.grouped()[0]!.items.map((item) => item.id)).toEqual(['newer', 'older'])
    view = mount((await import('../../src/renderer/src/components/WorkList.vue')).default)
    expect(view.root.textContent()).not.toContain('Invalid Date')
  })

  it('keeps schedule generation row IDs distinct even though they share the manager lock', async () => {
    const schedule: WorkItem = { kind: 'schedule', id: 'generation01', manager_id: 'short01', title: 'Schedule', state: 'scheduled', actions: [], detail: {} }
    listed = [schedule, { ...schedule, id: 'generation02' }]
    await work.loadWork()
    view = mount((await import('../../src/renderer/src/components/WorkList.vue')).default)
    const ids = view.root.findAll((node) => Boolean(node.props.id)).map((node) => node.props.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(view.root.findAll((node) => node.tag === 'article')).toHaveLength(2)
  })
})
