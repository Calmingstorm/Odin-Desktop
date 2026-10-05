// Fixture fidelity through the real Broker and a disposable fixture profile, never live schedules.
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import type { Result, ScheduleRow } from '../src/shared/api'
import { Broker } from '../src/main/broker'
import { startFixture, waitFor } from './fixture-harness'

const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => { for (const cleanup of cleanups.splice(0).reverse()) await cleanup() })

async function connect() {
  const core = await startFixture()
  cleanups.push(() => core.stop())
  const broker = new Broker({ socketPath: core.paths.socketPath, readToken: () => readFileSync(core.paths.tokenPath, 'utf8').trim(), profileId: 'default', clientVersion: 'r5-test', reconnectDelaysMs: [50] })
  cleanups.push(() => broker.close())
  broker.connect()
  await waitFor(() => broker.linkState === 'ready')
  const conversation = await broker.request('conversations.create', {}) as Result<{ conversation: { id: string } }>
  expect(conversation.ok).toBe(true)
  if (!conversation.ok) throw new Error('disposable conversation not created')
  const base = { action: 'check', description: 'R5 fidelity', channel_id: conversation.result.conversation.id, cron: '0 9 * * *', tool_name: 'run_command', tool_input: { command: 'uptime' } }
  const save = (params: Record<string, unknown>) => broker.request('schedules.save', params, crypto.randomUUID()) as Promise<Result<ScheduleRow>>
  const rows = async () => {
    const answer = await broker.request('schedules.list', {}) as Result<ScheduleRow[]>
    if (!answer.ok) throw new Error('fixture list failed')
    return answer.result
  }
  return { save, base, rows }
}

describe('R5 fixture fidelity', () => {
  it('schedules.save report_format empty string removes the property, in its answer and subsequent reads', async () => {
    const { save, base, rows } = await connect()
    const created = await save({ ...base, report_format: 'paginated_embed_v1' })
    expect(created.ok).toBe(true)
    if (!created.ok) return
    expect(created.result.report_format).toBe('paginated_embed_v1')
    const cleared = await save({ id: created.result.id, report_format: '' })
    expect(cleared.ok).toBe(true)
    if (!cleared.ok) return
    expect(cleared.result).not.toHaveProperty('report_format')
    expect((await rows()).find((r) => r.id === created.result.id)).not.toHaveProperty('report_format')
    expect(cleared.result).toMatchObject({ action: 'check', tool_name: 'run_command', tool_input: { command: 'uptime' } })
  })

  it('rejects retry_backoff_seconds 0 at create without adding a schedule', async () => {
    const { save, base, rows } = await connect()
    const before = await rows()
    expect(await save({ ...base, retry_backoff_seconds: 0 })).toMatchObject({ ok: false, error: { message: expect.stringMatching(/retry_backoff_seconds.*(?:>=\s*1|at least 1)/) } })
    expect(await rows()).toEqual(before)
  })

  it('rejects retry_backoff_seconds 0 at update without changing saved 60', async () => {
    const { save, base, rows } = await connect()
    const created = await save(base)
    expect(created.ok).toBe(true)
    if (!created.ok) return
    expect(created.result).toMatchObject({ max_retries: 0, retry_backoff_seconds: 60 })
    expect(await save({ id: created.result.id, retry_backoff_seconds: 0 })).toMatchObject({ ok: false, error: { message: expect.stringMatching(/retry_backoff_seconds.*(?:>=\s*1|at least 1)/) } })
    expect((await rows()).find((r) => r.id === created.result.id)).toEqual(created.result)
  })

  it('accepts minimum backoff 1 and max_retries 0 at create and update', async () => {
    const { save, base, rows } = await connect()
    const created = await save({ ...base, max_retries: 0, retry_backoff_seconds: 1 })
    expect(created.ok).toBe(true)
    if (!created.ok) return
    expect(created.result).toMatchObject({ max_retries: 0, retry_backoff_seconds: 1 })
    const changed = await save({ id: created.result.id, description: 'Accepted minimum', max_retries: 0, retry_backoff_seconds: 1 })
    expect(changed).toMatchObject({ ok: true, result: { description: 'Accepted minimum', max_retries: 0, retry_backoff_seconds: 1 } })
    expect((await rows()).find((r) => r.id === created.result.id)).toMatchObject({ description: 'Accepted minimum', max_retries: 0, retry_backoff_seconds: 1 })
  })
})
