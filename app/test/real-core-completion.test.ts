// Completion contract against the actual Broker and the isolated repository core.
import { randomUUID } from 'node:crypto'
import { afterEach, describe, expect, test } from 'vitest'
import type { Broker, Settled } from '../src/main/broker'
import { assertIsolated, RealCoreHarness, SERVED_CAPABILITIES } from './real-core-harness'

assertIsolated()

function result<T = unknown>(answer: Settled): T {
  expect(answer.ok, JSON.stringify(answer)).toBe(true)
  if (!answer.ok) throw new Error(`Expected success, received ${answer.error.code}`)
  return answer.result as T
}
function refused(answer: Settled, code: string, disposition = 'rejected'): void {
  expect(answer).toMatchObject({ ok: false, error: { code, disposition } })
}

describe('step 5 completion methods through the real Broker', () => {
  let core: RealCoreHarness | undefined
  afterEach(async () => { await core?.dispose(); core = undefined })
  async function connect(memoryKeyring = false): Promise<Broker> {
    core = new RealCoreHarness({ memoryKeyring })
    await core.start()
    return (await core.connect()).broker
  }

  test('composed capabilities are exact and completion reads return real profile data', async () => {
    const broker = await connect(true)
    const status = result<{ capabilities: string[] }>(await broker.request('status.get'))
    expect(status.capabilities).toEqual(SERVED_CAPABILITIES)
    for (const name of [
      'knowledge.chunks', 'knowledge.duplicates', 'knowledge.merge', 'knowledge.version', 'knowledge.diff',
      'learned.list', 'learned.update', 'learned.delete', 'audit.diffs', 'audit.failures', 'audit.tail',
      'logs.stats', 'logs.tail', 'observability.stats', 'observability.risk', 'observability.risk_recent',
      'observability.governor', 'observability.audit_risk', 'observability.freshness',
      'observability.freshness_recent', 'observability.bulkheads', 'observability.compression',
      'observability.validation', 'observability.affordances', 'observability.context',
      'observability.usage', 'observability.usage_totals', 'observability.subsystems',
      'recovery.stats', 'recovery.recent', 'capacity.snapshot', 'turn_state.snapshot',
      'pools.ssh', 'pools.http', 'pools.close', 'trajectories.list', 'trajectories.read',
      'trajectories.search', 'trajectories.message', 'codex.accounts.refresh', 'openrouter.catalogue',
      'openrouter.endpoints', 'openrouter.select', 'providers.compat.diagnostic', 'models.status',
      'models.provider.get', 'models.provider.set'
    ]) expect(status.capabilities).toContain(name)

    expect(result(await broker.request('learned.list'))).toMatchObject({ entries: expect.any(Array) })
    refused(await broker.request('learned.delete', { key: 'missing-profile-entry' }), 'not_found')
    expect(result(await broker.request('audit.diffs'))).toMatchObject({ entries: expect.any(Array), count: 0 })
    expect(result(await broker.request('audit.failures'))).toEqual(expect.any(Object))
    expect(result(await broker.request('logs.stats'))).toEqual(expect.any(Object))
    expect(result(await broker.request('audit.tail'))).toMatchObject({ lines: expect.any(Array), availability: expect.any(String) })
    expect(result(await broker.request('logs.tail'))).toMatchObject({ lines: expect.any(Array), availability: expect.any(String) })
    expect(result(await broker.request('observability.stats'))).toEqual(expect.any(Object))
    expect(result(await broker.request('recovery.stats'))).toEqual(expect.any(Object))
    expect(result(await broker.request('capacity.snapshot'))).toMatchObject({ availability: expect.any(String) })
    expect(result(await broker.request('turn_state.snapshot'))).toMatchObject({ availability: expect.any(String) })
    expect(result(await broker.request('trajectories.list'))).toMatchObject({ files: expect.any(Array), count: 0 })
    refused(await broker.request('openrouter.endpoints', { model: 'not-a-real-openrouter-model' }), 'not_found')
    refused(await broker.request('codex.accounts.refresh', { index: 0 }), 'capability_unavailable')
  })

  test('knowledge ingest, chunks, versions, diff, duplicate detection and reads use durable store', async () => {
    const broker = await connect()
    const source = 'real-core-completion-test.md'
    const firstText = 'The northern observatory records the blue comet every winter.'
    const secondText = 'The northern observatory records the blue comet every winter. A second measured passage follows.'
    const first = result<{ source: string; chunks: number }>(await broker.request('knowledge.ingest', {
      source, content: firstText
    }, randomUUID()))
    expect(first).toMatchObject({ source, chunks: expect.any(Number) })
    expect(first.chunks).toBeGreaterThan(0)
    const chunks = result<unknown[]>(await broker.request('knowledge.chunks', { source }))
    expect(chunks.length).toBeGreaterThan(0)
    expect(JSON.stringify(chunks)).toContain('northern observatory')
    expect(result(await broker.request('knowledge.version', { source, version: 1 }))).toBeTruthy()

    const second = result<{ source: string; chunks: number }>(await broker.request('knowledge.ingest', {
      source, content: secondText
    }, randomUUID()))
    expect(second.source).toBe(source)
    expect(result(await broker.request('knowledge.versions', { source }))).toBeTruthy()
    const diff = result(await broker.request('knowledge.diff', { source, v1: 1, v2: 2 }))
    expect(JSON.stringify(diff)).toContain('second measured passage')
    expect(result(await broker.request('knowledge.duplicates'))).toEqual(expect.objectContaining({ exact: expect.any(Array), near: expect.any(Array) }))
    expect(result<unknown[]>(await broker.request('knowledge.list'))).toEqual(expect.arrayContaining([expect.objectContaining({ source })]))
    expect(result(await broker.request('knowledge.search', { q: 'northern observatory blue comet' }))).toBeTruthy()
  })

  test('pool close is a real command with replay and conflicting-ID protection', async () => {
    const broker = await connect()
    const id = randomUUID()
    const params = { host: 'profile-local-nonexistent.invalid' }
    const saved = await broker.request('pools.close', params, id)
    expect(result(saved)).toEqual({ closed: false, host: params.host })
    // A constructed but idle real profile pool is not an unavailable capability.
    expect(await broker.request('pools.close', params, id)).toEqual(saved)
    refused(await broker.request('pools.close', { host: 'different.invalid' }, id), 'id_conflict')
  })
})
