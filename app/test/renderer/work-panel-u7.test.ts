// U7: the chat Work column renders a deliberately small projection. Control bindings stay intact but invisible.
// Vue's object renderer proves rendered content and control wiring, not pixels or native keyboard behaviour.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, WorkControlReceipt, WorkItem } from '../../src/shared/api'
import { flush, mount, type Host, type Mounted } from './component-host'

let view: Mounted | undefined
let workStore: typeof import('../../src/renderer/src/stores/work')
let store: typeof import('../../src/renderer/src/store')
let listed: WorkItem[]
let controls: Record<string, unknown>[]
let land: ((answer: Result<WorkControlReceipt>) => void) | undefined
let snapshotLand: ((answer: unknown) => void) | undefined
const now = new Date(2026, 9, 8, 18, 30)
const started = new Date(2026, 9, 8, 17, 25)
const next = new Date(2026, 9, 8, 19, 45)
const localTime = (date: Date): string => date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
const agent = (changes: Partial<WorkItem> = {}): WorkItem => ({
  kind: 'agent', id: 'public-binding', manager_id: 'manager-binding', manager_generation: 'immutable-generation',
  run_id: 'run-binding', generation: 73, conversation_id: 'chat-binding', title: 'Inspect disks', state: 'running',
  started_at: started.getTime() / 1000, actions: ['cancel', 'steer'],
  detail: { result: 'All disks have room.', revision: 71, parent_id: 'parent-binding', iteration_count: 4 },
  settlement: { state: 'pending', resource_release: 'unproven', remote_effects: 'not_undone' }, ...changes
})

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  vi.setSystemTime(now)
  listed = [agent()]
  controls = []
  land = undefined
  snapshotLand = undefined
  vi.stubGlobal('window', { odin: {
    workList: vi.fn(async () => ({ ok: true, result: { items: listed } })),
    workControl: (params: Record<string, unknown>) => {
      controls.push(params)
      return new Promise<Result<WorkControlReceipt>>((resolve) => { land = resolve })
    },
    snapshotConversation: () => new Promise((resolve) => { snapshotLand = resolve })
  } })
  vi.stubGlobal('document', { activeElement: null, body: {}, getElementById: vi.fn(), querySelector: vi.fn() })
  workStore = await import('../../src/renderer/src/stores/work')
  store = await import('../../src/renderer/src/store')
  store.state.conversations = [{ id: 'chat-binding', title: 'Disk chat', rev: 1, parent_id: null, unread: 0, archived: false, updated_at: started.toISOString() }]
  await workStore.loadWork()
})

afterEach(() => { view?.unmount(); view = undefined; vi.useRealTimers(); vi.unstubAllGlobals() })
async function render(): Promise<void> {
  view = mount((await import('../../src/renderer/src/components/WorkPanel.vue')).default)
  await flush()
}
const row = (): Host => view!.root.find('article')!

describe('U7: clean Work cards', () => {
  it('shows kind, title, plain state, local short time and result, not manager internals', async () => {
    listed = [agent({ detail: {
      result: 'All disks have room.', last_error: null, next_run: null, revision: 71,
      run_binding: { conversation_id: 'hidden-conversation', generation: 91, owner_id: 'hidden-owner', run_id: 'hidden-run', schedule_id: 'hidden-schedule' },
      settlement: { state: 'settled', resource_release: 'manager_task_finished' }, empty: null
    } })]
    await workStore.loadWork()
    await render()
    const text = row().textContent()
    for (const expected of ['Agent', 'Inspect disks', 'Running', `Started Today ${localTime(started)}`, 'Result: All disks have room.', 'Cancel', 'Steer', 'Open conversation Disk chat']) expect(text).toContain(expected)
    for (const forbidden of ['Revision', '71', '91', '73', 'run_binding', 'Run binding', 'Settlement', 'Resource release', 'Not reported', 'None reported', 'manager_task_finished', 'unproven', 'public-binding', 'manager-binding', 'run-binding', 'immutable-generation', 'hidden-', started.toISOString()]) expect(text).not.toContain(forbidden)
    expect(view!.root.textContent()).toContain('started from your chats.')
    expect(view!.root.textContent()).not.toContain('reported by the core')
    expect(view!.root.findAll((node) => node.tag === 'dl')).toHaveLength(0)
  })

  it('shows schedule next and last runs locally and keeps the last error', async () => {
    const yesterday = new Date(2026, 9, 7, 20, 10)
    listed = [agent({ kind: 'schedule', title: 'Evening report', state: 'scheduled', actions: ['pause', 'run_now'], started_at: yesterday.toISOString(),
      detail: { next_run: next.toISOString(), last_run: started.toISOString(), last_error: 'The endpoint timed out.', last_result: 'Previous report saved.', revision: 8, inert_reason: null },
      settlement: { state: 'definition', last_run: { state: 'settled', resource_release: 'confirmed' } }
    })]
    await workStore.loadWork()
    await render()
    const text = row().textContent()
    for (const expected of ['Schedule', 'Scheduled', `Created Yesterday ${localTime(yesterday)}`, `Next run Today ${localTime(next)}`, `Last run Today ${localTime(started)}`, 'Last error: The endpoint timed out.', 'Result: Previous report saved.']) expect(text).toContain(expected)
    expect(text).not.toContain(next.toISOString())
    expect(text).not.toContain('outcome is not confirmed')
  })

  it.each([
    ['completed', 'Done'], ['failed', 'Failed'], ['timeout', 'Timed out'], ['killed', 'Stopped'],
    ['cancelled', 'Stopped'], ['paused', 'Paused'], ['interrupted', 'Interrupted'], ['unknown', 'Unknown'], ['waiting_for_input', 'Waiting for input']
  ])('uses plain %s state without printing empty or invalid fields', async (state, label) => {
    listed = [agent({ state, started_at: 'not a date', actions: [], detail: { result: '', last_error: 'Not reported', next_run: null }, settlement: { state: 'settled', resource_release: 'confirmed' } })]
    await workStore.loadWork()
    await render()
    const stateNode = view!.root.findAll((node) => String(node.props.class).includes('work-state'))[0]!
    expect(stateNode.textContent()).toBe(label)
    for (const forbidden of ['Invalid Date', 'not a date', 'Started', 'Last error', 'Result:', 'Not reported', 'waiting_for_input']) expect(row().textContent()).not.toContain(forbidden)
  })

  it('uses a local calendar date for older work, including the year when needed', async () => {
    const older = new Date(2025, 11, 24, 8, 5)
    listed = [agent({ started_at: older.toISOString() })]
    await workStore.loadWork()
    await render()
    expect(row().textContent()).toContain(`Started ${older.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })} ${localTime(older)}`)
  })

  it('retains legacy text results without printing blank placeholder output', async () => {
    listed = [agent({ detail: 'Legacy report saved.' })]
    await workStore.loadWork()
    await render()
    expect(row().textContent()).toContain('Result: Legacy report saved.')
  })

  it.each([[0, 'Done'], [2, 'Failed']])('uses the reported process exit code %s rather than inferring success', async (exit_code, label) => {
    listed = [agent({ kind: 'process', state: 'exited', detail: { exit_code }, settlement: { state: 'settled', resource_release: 'confirmed' } })]
    await workStore.loadWork()
    await render()
    expect(view!.root.findAll((node) => String(node.props.class).includes('work-state'))[0]!.textContent()).toBe(label)
  })

  it('omits absent, invalid and structured schedule dates and output instead of exposing records', async () => {
    listed = [agent({ kind: 'schedule', started_at: null, detail: { next_run: 'bad date', last_run: { run_id: 'never-show' }, result: { binding: 'never-show' }, last_error: 'None reported' }, settlement: { state: 'definition' } })]
    await workStore.loadWork()
    await render()
    const text = row().textContent()
    for (const forbidden of ['Created', 'Next run', 'Last run', 'Result:', 'Last error', 'never-show', '[object Object]', 'Not reported', 'None reported']) expect(text).not.toContain(forbidden)
  })

  it.each([
    agent({ kind: 'process', state: 'stopped', settlement: { state: 'unknown', resource_release: 'unproven' } }),
    agent({ state: 'completed', settlement: { state: 'pending', resource_release: 'unproven' } }),
    agent({ kind: 'schedule', state: 'scheduled', settlement: { state: 'definition', last_run: { state: 'unknown', resource_release: 'unproven' } } })
  ])('keeps unknown outcomes honest without settlement tables for $kind', async (item) => {
    listed = [item]
    await workStore.loadWork()
    await render()
    expect(row().textContent()).toContain('The outcome is not confirmed.')
    expect(row().textContent()).not.toMatch(/Settlement|Resource release|unproven/)
  })

  it('announces lifecycle changes with the same plain state as the card', async () => {
    await render()
    workStore.work.items[0]!.state = 'completed'
    await flush()
    await vi.advanceTimersByTimeAsync(150)
    expect(view!.root.findAll((node) => node.props.role === 'status')[0]!.textContent()).toBe('agent: Inspect disks. Done.')
  })
})

describe('U7: existing actions remain bound and safe', () => {
  it('dispatches a schedule control with its invisible immutable identity and revision, not a rendered ID', async () => {
    listed = [agent({ kind: 'schedule', state: 'scheduled', actions: ['pause', 'run_now'], detail: { revision: 9 } })]
    await workStore.loadWork()
    await render()
    const button = view!.root.named('Pause schedule: Inspect disks')
    const pausing = button.fire('click', { currentTarget: button })
    await flush()
    expect(controls).toEqual([{ control_command_id: expect.any(String), kind: 'schedule', id: 'public-binding', action: 'pause', manager_generation: 'immutable-generation', run_id: 'run-binding', generation: 73, conversation_id: 'chat-binding', revision: 9 }])
    land!({ ok: true, result: { disposition: 'done' } })
    await pausing
    expect(workStore.work.notes['schedule:manager-binding']).toBe('Pause: done')
  })

  it('retains unknown-control locks and notes without replaying the control', async () => {
    await render()
    const button = view!.root.named('Cancel agent: Inspect disks')
    const cancelling = button.fire('click', { currentTarget: button })
    await flush()
    expect(button.props['aria-disabled']).toBe(true)
    expect(button.props.disabled).toBeUndefined()
    land!({ ok: false, error: { code: 'no_receipt', message: 'No receipt', disposition: 'outcome_unknown' } })
    await cancelling
    await flush()
    await button.fire('click', { currentTarget: button })
    expect(controls).toHaveLength(1)
    expect(row().textContent()).toContain('Cancel: waiting for Odin to confirm. It is never sent twice.')
    store.applyReceipt({ id: String(controls[0]!.control_command_id), settled: { ok: true, result: { disposition: 'done' } } })
    await flush()
    expect(button.props['aria-disabled']).toBe(false)
  })

  it('opens and sends the inline steer form once, preserving exact text and queued-not-consumed receipt', async () => {
    await render()
    await view!.root.named('Steer agent: Inspect disks').fire('click')
    await flush()
    expect(controls).toEqual([])
    const textarea = view!.root.find('textarea')!
    textarea.type('Keep this exact correction.\nNo replacement run.')
    const form = view!.root.find('form')!
    const sending = form.fire('submit', { preventDefault: vi.fn() })
    await flush()
    await form.fire('submit', { preventDefault: vi.fn() })
    expect(controls).toHaveLength(1)
    expect(controls[0]).toMatchObject({ action: 'steer', id: 'public-binding', text: 'Keep this exact correction.\nNo replacement run.' })
    land!({ ok: true, result: { disposition: 'queued', consumed: false, sequence: 5 } })
    await sending
    await flush()
    expect(textarea.value).toBe('')
    expect(row().textContent()).toContain('Queued is not consumed.')
  })

  it('opens the associated conversation and only moves focus if the initiating action still owns it', async () => {
    await render()
    const button = view!.root.named('Open conversation Disk chat for agent: Inspect disks')
    const focus = vi.fn()
    Object.assign(document, { activeElement: button, getElementById: vi.fn(() => ({ focus })) })
    workStore.work.open = true
    const opening = button.fire('click', { currentTarget: button })
    snapshotLand!({ ok: true, result: { conversation: store.state.conversations[0], watermark: '0', messages: { items: [], has_more: false }, running: null, queued: [], recent: [], unresolved: [], tools: {}, controls: [] } })
    await opening
    expect(store.state.activeId).toBe('chat-binding')
    expect(workStore.work.open).toBe(false)
    expect(document.getElementById).toHaveBeenCalledWith('conversation-history')
    expect(focus).toHaveBeenCalledOnce()
  })

  it('keeps generation-specific card and action associations distinct', async () => {
    listed = [agent({ kind: 'schedule', id: 'first-generation', actions: ['pause'] }), agent({ kind: 'schedule', id: 'second-generation', actions: ['pause'] })]
    await workStore.loadWork()
    await render()
    const ids = view!.root.findAll((node) => Boolean(node.props.id)).map((node) => node.props.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(view!.root.findAll((node) => node.tag === 'article')).toHaveLength(2)
    for (const button of view!.root.findAll((node) => node.tag === 'button' && String(node.props['aria-label']).startsWith('Pause'))) expect(ids).toContain(button.props['aria-describedby'])
  })

  it('repairs focus to its own row when a focused control disappears after a completion event', async () => {
    await render()
    const button = view!.root.named('Cancel agent: Inspect disks')
    const currentRow = row()
    const active = { isConnected: true, closest: () => ({ id: currentRow.props.id }) }
    const focus = vi.fn()
    Object.assign(document, { activeElement: active, getElementById: vi.fn(() => ({ focus })) })
    Object.defineProperty(button, 'parent', { configurable: true, get: () => currentRow, set: () => {
      active.isConnected = false
      Object.assign(document, { activeElement: document.body })
    } })
    workStore.work.items[0]!.actions = []
    await flush()
    expect(document.getElementById).toHaveBeenCalledWith(currentRow.props.id)
    expect(focus).toHaveBeenCalledOnce()
  })

  it('repairs focus when a control receipt removes the initiating action', async () => {
    await render()
    const button = view!.root.named('Cancel agent: Inspect disks')
    const currentRow = row()
    const focus = vi.fn()
    Object.assign(document, { activeElement: button, getElementById: vi.fn(() => ({ focus })) })
    const cancelling = button.fire('click', { currentTarget: button })
    await flush()
    Object.assign(button, { isConnected: false })
    Object.assign(document, { activeElement: document.body })
    listed = [agent({ state: 'completed', actions: [], settlement: { state: 'settled', resource_release: 'confirmed' } })]
    land!({ ok: true, result: { disposition: 'done' } })
    await cancelling
    await flush()
    expect(document.getElementById).toHaveBeenCalledWith(currentRow.props.id)
    expect(focus).toHaveBeenCalledOnce()
  })

  it('does not steal focus when someone leaves while the conversation loads', async () => {
    await render()
    const button = view!.root.named('Open conversation Disk chat for agent: Inspect disks')
    Object.assign(document, { activeElement: button })
    workStore.work.open = true
    const opening = button.fire('click', { currentTarget: button })
    Object.assign(document, { activeElement: { elsewhere: true } })
    snapshotLand!({ ok: true, result: { conversation: store.state.conversations[0], watermark: '0', messages: { items: [], has_more: false }, running: null, queued: [], recent: [], unresolved: [], tools: {}, controls: [] } })
    await opening
    expect(workStore.work.open).toBe(true)
    expect(document.getElementById).not.toHaveBeenCalledWith('conversation-history')
  })

  it('restores the work toggle when its opener no longer exists', async () => {
    const focus = vi.fn()
    Object.assign(document, { activeElement: { isConnected: false }, querySelector: vi.fn(() => ({ focus })) })
    await render()
    view!.root.named('Close work').fire('click')
    expect(document.querySelector).toHaveBeenCalledWith('.work-toggle')
    expect(focus).toHaveBeenCalledOnce()
  })
})
