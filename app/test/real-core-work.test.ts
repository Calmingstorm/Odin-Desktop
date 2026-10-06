import { randomUUID } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import type { Settled } from '../src/main/broker'
import { assertIsolated, RealCoreHarness, waitFor } from './real-core-harness'

assertIsolated()
function result<T>(answer: Settled): T {
  if (!answer.ok) throw new Error(`Real core refused: ${JSON.stringify(answer.error)}`)
  return answer.result as T
}
type Work = { kind: string; id: string; manager_id: string; manager_generation: string; run_id: string;
  generation: number; conversation_id: string; state: string; actions: string[]; title: string;
  settlement: { state: string; resource_release?: string }; detail: { revision?: number; inbox_sequence?: number } }
function control(item: Work, action: string, control_command_id = randomUUID()) {
  const { kind, id, manager_generation, run_id, generation, conversation_id } = item
  return { kind, id, manager_generation, run_id, generation, conversation_id, action, control_command_id,
    ...(kind === 'schedule' ? { revision: item.detail.revision } : {}) }
}

describe('actual Broker ↔ real work/control/scheduler/report owners', () => {
  let core: RealCoreHarness
  beforeEach(async () => { core = new RealCoreHarness({ workProof: true }); await core.start() })
  afterEach(async () => { await core?.dispose() })
  const seed = (core: RealCoreHarness) => JSON.parse(readFileSync(join(core.root, 'work-proof.json'), 'utf8')) as {
    conversation_id: string; report_id: string; reminder_id: string; recovery_id: string; producer_id: string }
  const counts = (core: RealCoreHarness) => ({
    background: readFileSync(join(core.root, 'background-effects'), 'utf8').trim().split('\n').length,
    report: readFileSync(join(core.root, 'report-effects'), 'utf8').trim().split('\n').length
  })

  test('all six kinds are destination-bound; actual task finishes and unknown release remains unknown', async () => {
    const { broker } = await core.connect()
    const items = result<{ items: Work[] }>(await broker.request('work.list')).items
    expect(new Set(items.map(i => i.kind))).toEqual(new Set(['agent', 'task', 'workflow', 'loop', 'process', 'schedule']))
    for (const item of items) {
      expect(item.conversation_id).toBe(seed(core).conversation_id)
      expect(item.id).not.toBe(item.manager_id)
      expect(item.run_id).toBeTruthy()
      expect(item.manager_generation).toBeTruthy()
      expect(item.generation).toBe(1)
    }
    expect(items.find(i => i.title === 'Harmless completed task')).toMatchObject({ state: 'completed', actions: [],
      settlement: { state: 'settled', resource_release: 'manager_task_finished' } })
    expect(items.find(i => i.kind === 'process')).toMatchObject({ state: 'unknown', actions: [],
      settlement: { state: 'unknown', resource_release: 'unproven' } })
    expect(result<{ items: Work[] }>(await broker.request('work.list', { conversation_id: 'foreign' })).items).toEqual([])
    expect(result<{ items: Work[] }>(await broker.request('work.list', { kind: 'task' })).items.every(i => i.kind === 'task')).toBe(true)
    expect(await broker.request('work.list', { kind: 'invented' })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
  })

  test('real task cancel receipt replays through new envelopes and restart, conflicts do not repeat; agent steer is queued only', async () => {
    const { broker } = await core.connect()
    const items = result<{ items: Work[] }>(await broker.request('work.list')).items
    const task = items.find(i => i.title === 'Harmless cancellable task')!
    const params = control(task, 'cancel')
    const envelope = randomUUID()
    const receipt = await broker.request('work.control', params, envelope)
    expect(result(receipt)).toMatchObject({ disposition: 'done', run_id: task.run_id,
      settlement: { state: 'settled', resource_release: 'manager_task_finished' } })
    expect(await broker.request('work.control', params, envelope)).toEqual(receipt)
    expect(await broker.request('work.control', params, randomUUID())).toEqual(receipt)
    expect(await broker.request('work.control', { ...params, action: 'stop' }, randomUUID())).toMatchObject({ ok: false, error: { code: 'id_conflict' } })
    const agent = items.find(i => i.kind === 'agent')!
    const steer = { ...control(agent, 'steer'), text: 'Harmless correction' }
    const queued = await broker.request('work.control', steer, randomUUID())
    expect(result(queued)).toMatchObject({ disposition: 'queued', consumed: false, sequence: 1 })
    expect(await broker.request('work.control', steer, randomUUID())).toEqual(queued)
    const after = result<{ items: Work[] }>(await broker.request('work.list', { kind: 'agent' })).items[0]!
    expect(after.detail.inbox_sequence).toBe(1)
    const loop = items.find(i => i.kind === 'loop')!
    expect(result(await broker.request('work.control', control(loop, 'stop'), randomUUID())))
      .toMatchObject({ disposition: 'done', settlement: { state: 'settled' } })
    expect(result(await broker.request('work.control', { ...control(loop, 'stop'), id: 'unknown-work' }, randomUUID())))
      .toMatchObject({ disposition: 'not_available' })
    expect(await broker.request('work.control', { ...control(agent, 'cancel'), manager_generation: 'stale' }, randomUUID()))
      .toMatchObject({ ok: true, result: { disposition: 'not_available' } })
    const before = counts(core)
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    await core.start()
    const reopened = await core.connect()
    expect(await reopened.broker.request('work.control', params, randomUUID())).toEqual(receipt)
    expect(counts(core)).toEqual(before)
    expect(result<{ items: Work[] }>(await reopened.broker.request('work.list', { kind: 'agent' })).items[0])
      .toMatchObject({ state: 'interrupted', actions: [], settlement: { state: 'unknown', resource_release: 'unproven' } })
  })

  test('real schedule CRUD, paused manual run, failure reset and history use journaled commands', async () => {
    const { broker } = await core.connect()
    const cid = seed(core).conversation_id
    const params = { description: 'Harmless CRUD reminder', action: 'reminder', channel_id: cid,
      cron: '0 0 1 1 *', message: 'Explicit manual reminder only' }
    const command = randomUUID()
    const created = await broker.request('schedules.save', params, command)
    const item = result<{ id: string }>(created)
    expect(await broker.request('schedules.save', params, command)).toEqual(created)
    const update = result<Record<string, unknown>>(await broker.request('schedules.save', { id: item.id,
      description: 'Updated harmless reminder', paused: true }, randomUUID()))
    expect(update).toMatchObject({ id: item.id, paused: true, description: 'Updated harmless reminder' })
    const listing = result<Array<{ id: string; paused: boolean }>>(await broker.request('schedules.list'))
    expect(listing.find(s => s.id === item.id)?.paused).toBe(true)
    expect(result(await broker.request('schedules.run', { id: item.id }, randomUUID())))
      .toMatchObject({ status: 'success' })
    expect(result<unknown[]>(await broker.request('schedules.history', { id: item.id }))).toHaveLength(1)
    result(await broker.request('schedules.reset_failures', { id: item.id }, randomUUID()))
    const resumed = result<{ paused: boolean }>(await broker.request('schedules.save', { id: item.id, paused: false }, randomUUID()))
    expect(resumed.paused).toBe(false)
    expect(result(await broker.request('schedules.delete', { id: item.id }, randomUUID())))
      .toMatchObject({ status: 'deleted' })
    expect(result<Array<{ id: string }>>(await broker.request('schedules.list')).some(s => s.id === item.id)).toBe(false)
    expect(result<unknown[]>(await broker.request('schedules.history', { id: item.id }))).toHaveLength(1)
    expect(await broker.request('schedules.delete', { id: 'missing' }, randomUUID()))
      .toMatchObject({ ok: false, error: { code: 'not_found' } })
  })

  test('core death after real control reservation never replays lost cleanup or claims settlement', async () => {
    const { broker } = await core.connect()
    const task = result<{ items: Work[] }>(await broker.request('work.list')).items.find(i => i.title === 'Harmless lost-receipt task')!
    const params = control(task, 'cancel')
    const pending = broker.request('work.control', params, randomUUID())
    await waitFor(() => existsSync(join(core.root, 'work-cancel-entered')), 'external cleanup entered after journal reservation')
    core.child.kill('SIGKILL')
    await core.waitExit()
    await pending
    broker.close()
    const before = counts(core)
    await core.start()
    const reopened = await core.connect()
    expect(await reopened.broker.request('work.control', params, randomUUID())).toMatchObject({ ok: false,
      error: { code: 'internal', disposition: 'outcome_unknown' } })
    expect(await reopened.broker.request('work.control', params, randomUUID())).toMatchObject({ ok: false,
      error: { disposition: 'outcome_unknown' } })
    expect(counts(core)).toEqual(before)
    expect(result<{ items: Work[] }>(await reopened.broker.request('work.list')).items.find(i => i.id === task.id))
      .toMatchObject({ state: 'interrupted', actions: [], settlement: { state: 'unknown', resource_release: 'unproven' } })
  })

  test('seeded workProof forwards ordinary tools and commands to the actual executor', async () => {
    const { broker } = await core.connect()
    const cid = seed(core).conversation_id
    const before = counts(core)
    for (const [description, tool_name, tool_input, output] of [
      ['Actual process registry list', 'manage_process', { action: 'list' }, 'PID'],
      ['Ordinary local command', 'run_command', { command: "printf 'ordinary-command-pass-through'" }, 'ordinary-command-pass-through']
    ] as const) {
      const schedule = result<{ id: string }>(await broker.request('schedules.save', {
        description, action: 'workflow', channel_id: cid, cron: '0 0 1 1 *',
        steps: [{ tool_name, tool_input }], max_retries: 0
      }, randomUUID()))
      expect(result(await broker.request('schedules.run', { id: schedule.id }, randomUUID())))
        .toMatchObject({ status: 'success' })
      expect(result<unknown[]>(await broker.request('schedules.history', { id: schedule.id })))
        .toEqual([expect.objectContaining({ status: 'success', run_binding: expect.objectContaining({ conversation_id: cid }) })])
      const messages = result<{ items: Array<{ text: string }> }>(await broker.request('messages.list', { conversation_id: cid, limit: 100 }))
      expect(messages.items.map(message => message.text).join('\n')).toContain(output)
    }
    // A real list is not process admission. The original row remains metadata-only.
    expect(result<{ items: Work[] }>(await broker.request('work.list', { kind: 'process' })).items)
      .toMatchObject([{ state: 'unknown', actions: [], settlement: { state: 'unknown', resource_release: 'unproven' } }])
    expect(counts(core)).toEqual(before)
  })

  test('D12 coalesces overdue reminder once, requires recovery for missed checks; report pages are stored and never rerun', async () => {
    const { broker } = await core.connect()
    const proof = seed(core)
    const schedules = result<Array<Record<string, unknown>>>(await broker.request('schedules.list'))
    expect(schedules.find(s => s.id === proof.reminder_id)).toMatchObject({ settlement: 'success',
      missed_run: { policy: 'coalesced', count_truncated: true } })
    expect(schedules.find(s => s.id === proof.recovery_id)).toMatchObject({ recovery_required: expect.stringContaining('No effects were replayed'),
      missed_run: { policy: 'manual', workflow_catchup_limit: 0 } })
    const messages = result<{ items: Array<{ text: string }> }>(await broker.request('messages.list', { conversation_id: proof.conversation_id, limit: 100 }))
    const notices = messages.items.filter(m => m.text.includes('Harmless catch-up notice'))
    expect(notices).toHaveLength(1)
    expect(notices[0]!.text).toMatch(/Due:.*late by.*Omitted slots:/s)
    const before = counts(core)
    for (let i = 0; i < 3; i++) {
      expect(result(await broker.request('reports.page', { report_id: proof.report_id, page: 1 })))
        .toMatchObject({ page: 1, pages: 2, text: expect.stringContaining('produced once') })
      expect(result(await broker.request('reports.page', { report_id: proof.report_id, page: 2 })))
        .toMatchObject({ page: 2, pages: 2, text: expect.stringContaining('no rerun') })
    }
    expect(await broker.request('reports.page', { report_id: proof.report_id, page: 3 })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
    expect(await broker.request('reports.page', { report_id: proof.report_id, page: 1, conversation_id: 'foreign' }))
      .toMatchObject({ ok: false, error: { code: 'bad_request' } })
    expect(await broker.request('reports.page', { report_id: 'missing-report', page: 1 }))
      .toMatchObject({ ok: false, error: { code: 'not_found' } })
    expect(counts(core)).toEqual(before)
    expect(before.report).toBe(1)
    expect(before.background).toBe(1)
    const history = result<unknown[]>(await broker.request('schedules.history', { id: proof.producer_id }))
    expect(history).toHaveLength(1)
    const schedule = result<{ items: Work[] }>(await broker.request('work.list', { kind: 'schedule' })).items.find(i => i.manager_id === proof.producer_id)!
    expect(result(await broker.request('work.control', control(schedule, 'pause'), randomUUID()))).toMatchObject({ disposition: 'done' })
    expect(result(await broker.request('work.control', control(schedule, 'resume'), randomUUID()))).toMatchObject({ disposition: 'not_available' })
    const current = result<{ items: Work[] }>(await broker.request('work.list', { kind: 'schedule' })).items.find(i => i.id === schedule.id)!
    expect(result(await broker.request('work.control', control(current, 'resume'), randomUUID()))).toMatchObject({ disposition: 'done' })
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    await core.start()
    const reopened = await core.connect()
    expect(result(await reopened.broker.request('reports.page', { report_id: proof.report_id, page: 2 })))
      .toMatchObject({ page: 2, pages: 2, text: expect.stringContaining('no rerun') })
    expect(counts(core)).toEqual(before)
  })
})
