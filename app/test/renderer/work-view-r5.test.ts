// R5 acceptance through Work.vue's actual editable controls and Save/Create listeners.
// The host intentionally does not implement browser disabled-event suppression: never fire a disabled control.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result, ScheduleRow } from '../../src/shared/api'
import { flush, mount, type Host, type Mounted } from './component-host'

const ok = <T>(result: T): Result<T> => ({ ok: true, result })
const ROW: ScheduleRow = {
  id: 'r5-created', action: 'reminder', description: 'Reminder', channel_id: 'c1',
  created_at: '2026-10-05T12:00:00Z',
  cron: '0 9 * * *', timezone: 'UTC', message: 'sent message', paused: false,
  max_retries: 0, retry_backoff_seconds: 60
}
let view: Mounted
let saves: Array<{ body: Record<string, unknown>; land: (answer: Result<unknown>) => void }>

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  saves = []
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
  ;(globalThis as unknown as { window: unknown }).window = { odin: {
    schedulesList: async () => ok([]),
    schedulesValidateCron: async () => ok({ next_runs: [] }),
    schedulesSave: (body: Record<string, unknown>) => new Promise((resolve) => saves.push({ body, land: resolve }))
  } }
  const store = await import('../../src/renderer/src/store')
  store.state.activeId = 'c1'
  store.state.conversations = [{ id: 'c1', title: 'First' }, { id: 'c2', title: 'Second' }] as typeof store.state.conversations
  const Work = (await import('../../src/renderer/src/views/settings/Work.vue')).default
  view = mount(Work)
  await flush()
  view.root.button('New schedule').fire('click')
  await flush()
})

afterEach(() => { view?.unmount(); vi.useRealTimers() })

function control(tag: string, matches: (host: Host) => boolean): Host {
  const found = view.root.findAll((host) => host.tag === tag && matches(host))
  expect(found).toHaveLength(1)
  return found[0]!
}
const description = () => control('input', (h) => h.props.maxlength === '500')
const cron = () => control('input', (h) => h.props.placeholder === '0 9 * * 1-5')
const message = () => control('textarea', (h) => h.props.placeholder === 'The description, if left empty')
const retries = () => control('input', (h) => h.props.type === 'number' && h.props.placeholder === '0')
const backoff = () => control('input', (h) => h.props.type === 'number' && h.props.placeholder === '60')
const action = () => control('select', (h) => h.options.some((o) => o.value === 'check'))
// A native input event with no listener is a no-op, not a browser exception.
// Keep mutation checks grounded in the resulting request/error, not Host.fire's listener guard.
function typeNumeric(host: Host, text: string): void {
  host.value = text
  try { host.fire('input') } catch (error) {
    if (!(error instanceof Error) || error.message !== 'no input listener on <input>') throw error
  }
}
async function click(label: string): Promise<void> {
  const button = view.root.button(label)
  expect(button.props.disabled).toBeFalsy()
  button.fire('click')
  await flush()
}
async function begin(): Promise<void> {
  expect(retries().value).toBe('')
  expect(backoff().value).toBe('')
  description().type('Reminder')
  cron().type(ROW.cron!)
  message().type('sent message')
  await flush()
  await click('Create')
  expect(saves).toHaveLength(1)
  expect(saves[0]!.body).toEqual({ action: 'reminder', description: 'Reminder', channel_id: 'c1', cron: ROW.cron, message: 'sent message' })
}
async function landCreate(late: boolean, row: ScheduleRow = ROW): Promise<void> {
  if (late) {
    saves[0]!.land({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'r5-create-receipt' } })
    await flush()
    const store = await import('../../src/renderer/src/store')
    store.applyReceipt({ id: 'r5-create-receipt', settled: ok(row) })
  } else saves[0]!.land(ok(row))
  await flush()
}

describe('15.R5.1: a returned row adopts untouched fields, not newer text', () => {
  it.each([false, true])('blank defaults allow a message-only second Save (late receipt=%s)', async (late) => {
    await begin()
    message().type('newer message')
    await flush()
    await landCreate(late)
    expect(message().value).toBe('newer message')
    await click('Save')
    expect(saves).toHaveLength(2)
    expect(saves[1]!.body).toEqual({ id: ROW.id, message: 'newer message' })
    expect(String(retries().value)).toBe('0')
    expect(String(backoff().value)).toBe('60')
    saves[1]!.land(ok({ ...ROW, message: 'newer message' }))
    await flush()
    expect(view.root.findAll((h) => h.props['aria-label'] === 'Schedule form')).toHaveLength(0)
  })

  it('adopts server-normalized untouched fields while preserving newer text and channel fields', async () => {
    await begin()
    description().type('newer description')
    message().type('newer message')
    const channel = control('select', (h) => h.options.some((o) => o.value === 'c2'))
    channel.choose(channel.options.findIndex((o) => o.value === 'c2'))
    await flush()
    await landCreate(false, { ...ROW, description: 'core description', cron: '0 10 * * *', message: 'core message' })
    expect(description().value).toBe('newer description')
    expect(message().value).toBe('newer message')
    expect(String(retries().value)).toBe('0')
    expect(backoff().value).toBe('60')
    expect(cron().value).toBe('0 10 * * *')
    expect(channel.options[channel.selectedIndex]?.value).toBe('c2')
    await click('Save')
    expect(saves[1]!.body).toEqual({ id: ROW.id, description: 'newer description', channel_id: 'c2', message: 'newer message' })
  })
})

describe('15.R5.2: a sent create binds the immutable action', () => {
  it.each([false, true])('disables action while sent, including outcome-unknown waiting (late receipt=%s)', async (late) => {
    expect(action().props.disabled).toBeFalsy()
    await begin()
    expect(action().props.disabled).toBeTruthy()
    // Ordinary text remains editable, so a newer draft keeps the form open after success.
    message().type('newer message')
    await flush()
    if (late) {
      saves[0]!.land({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown', command_id: 'r5-action-receipt' } })
      await flush()
      expect(action().props.disabled).toBeTruthy()
      const store = await import('../../src/renderer/src/store')
      store.applyReceipt({ id: 'r5-action-receipt', settled: ok(ROW) })
      await flush()
    } else await landCreate(false)
    expect(view.root.findAll((h) => h.tag === 'select' && h.options.some((o) => o.value === 'check'))).toHaveLength(0)
    expect(view.root.findAll((h) => h.props.placeholder === 'run_command')).toHaveLength(0)
    expect(message().value).toBe('newer message')
    await click('Save')
    expect(saves[1]!.body).toEqual({ id: ROW.id, message: 'newer message' })
  })
})

it('15.R5.3: the actual backoff control has minimum 1, retries retain minimum 0', () => {
  expect(String(backoff().props.min)).toBe('1')
  expect(String(retries().props.min)).toBe('0')
})

describe('15.R5.4: actual numeric controls preserve valid zero and reject zero backoff', () => {
  async function fillSchedule(): Promise<void> {
    description().type('Reminder')
    cron().type(ROW.cron!)
    message().type('sent message')
    await flush()
  }

  it('creates with zero retries and one-second backoff from the controls', async () => {
    await fillSchedule()
    typeNumeric(retries(), '0')
    typeNumeric(backoff(), '1')
    await flush()

    await click('Create')
    expect(saves).toHaveLength(1)
    expect(saves[0]!.body).toEqual({
      action: 'reminder', description: 'Reminder', channel_id: 'c1', cron: ROW.cron,
      message: 'sent message', max_retries: 0, retry_backoff_seconds: 1
    })
  })

  it('rejects zero backoff through the actual control without issuing a request', async () => {
    await fillSchedule()
    typeNumeric(retries(), '0')
    typeNumeric(backoff(), '0')
    await flush()

    await click('Create')
    expect(saves).toHaveLength(0)
    expect(view.root.textContent()).toContain('The wait between retries is a whole number of seconds, at least 1.')
  })
})
