import { readFileSync } from 'node:fs'
import type { Socket } from 'node:net'
import { afterEach, describe, expect, it } from 'vitest'
import { Broker } from '../src/main/broker'
import { startFixture, waitFor, type FixtureCore } from './fixture-harness'

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => { for (const cleanup of cleanups.splice(0).reverse()) await cleanup() })

async function connected() {
  const core: FixtureCore = await startFixture()
  cleanups.push(() => core.stop())
  const broker = new Broker({
    socketPath: core.paths.socketPath,
    readToken: () => readFileSync(core.paths.tokenPath, 'utf8').trim(),
    profileId: 'default', clientVersion: 'exit-admission-test', reconnectDelaysMs: [10]
  })
  cleanups.push(() => broker.close())
  broker.connect()
  await waitFor(() => broker.linkState === 'ready')
  return { core, broker }
}

describe('broker Exit quiescing', () => {
  it('retains and honestly settles in-flight command identities on explicit close', async () => {
    const { broker } = await connected()
    // The request is queued locally; close runs synchronously before any socket
    // receipt callback. Whether the fixture received it is deliberately unknown.
    const pending = broker.request('conversations.create', { title: 'in flight' })
    broker.quiesce()
    broker.close()
    expect(await pending).toMatchObject({ ok: false, error: {
      code: 'no_receipt', disposition: 'outcome_unknown'
    } })
    expect(broker.unreceiptedCount).toBe(1)
  })

  it('keeps current shutdown transport but rejects every ordinary dispatch', async () => {
    const { broker } = await connected()
    broker.quiesce()
    expect(await broker.request('conversations.create', { title: 'late' })).toMatchObject({
      ok: false, error: { code: 'busy', disposition: 'not_dispatched' }
    })
    expect(await broker.request('runtime.shutdown', { reason: 'exit' })).toMatchObject({ ok: true })
  })

  it('does not reconnect or reconcile unknown command identities after Exit starts', async () => {
    const { broker } = await connected()
    let welcomes = 0
    broker.on('welcome', () => welcomes++)
    const internals = broker as unknown as {
      socket: Socket; unreceipted: Map<string, Record<string, unknown>>
    }
    // Owned transport fixture: emulate a command for which a previous connection
    // did not return a receipt. Do not manufacture a successful engine outcome.
    const id = crypto.randomUUID()
    internals.unreceipted.set(id, { t: 'req', id, method: 'conversations.create', params: {} })
    broker.quiesce()
    internals.socket.destroy()
    broker.connect()
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(welcomes).toBe(0)
    expect(broker.unreceiptedCount).toBe(1)
    expect(await broker.request('runtime.shutdown', { reason: 'exit' })).toMatchObject({ ok: false })
  })
})
