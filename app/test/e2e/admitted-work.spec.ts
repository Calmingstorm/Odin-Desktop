import { readFileSync, readlinkSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { expect, test, type ElectronApplication, type TestInfo } from '@playwright/test'
import { exitApp, launchApp, launchSecond, request, snapshot, waitForCore } from './harness'
import { OwnedHttpReceiver } from './owned-http-receiver'

async function attach(info: TestInfo, name: string, value: unknown) {
  await info.attach(name, { body: Buffer.from(JSON.stringify(value, null, 2)), contentType: 'application/json' })
}
async function close(application: ElectronApplication | null) {
  if (!application) return
  try { await application.close() } catch (error) { if (!/closed|_object/.test(String(error))) throw error }
}
function identity(pid: number) {
  const stat = readFileSync(`/proc/${pid}/stat`, 'utf8')
  return {pid, startTicks: stat.slice(stat.lastIndexOf(')') + 2).split(' ')[19],
    pidNamespace: readlinkSync(`/proc/${pid}/ns/pid`),
    uid: Number(/^Uid:\s+(\d+)/m.exec(readFileSync(`/proc/${pid}/status`, 'utf8'))?.[1])}
}
async function target(application: ElectronApplication, receiver: OwnedHttpReceiver, caseName: string) {
  const result = await request(application, 'webhooks.outbound.save', {
    name: `Owned harmless ${caseName}`, url: `http://127.0.0.1:${receiver.port}/${caseName}`, events: ['custom']
  }, randomUUID())
  expect(result.ok).toBe(true)
  const saved = result.result as { id: string; has_secret: boolean }
  expect(saved.has_secret).toBe(false)
  return saved.id
}
async function pending(application: ElectronApplication, receiver: OwnedHttpReceiver, targetId: string, commandId: string) {
  const state = await snapshot(application)
  // Main-only Broker hook; no renderer generic RPC and no fake management method.
  const promise = request(application, 'webhooks.outbound.test', { id: targetId }, commandId)
  await expect.poll(async () => (await receiver.snapshot()).effect_count).toBe(1)
  expect(await receiver.journal(state.paths.dataDir, commandId)).toMatchObject({ command_id: commandId, state: 'pending', response: null })
  expect((await receiver.snapshot()).requests[0]).toMatchObject({response_sent: false,
    body: {event_type: 'test', data: {webhook_id: targetId}}})
  return { state, promise }
}

test('admitted actual management HTTP effect completes while hidden and exact durable receipt never replays after relaunch', async ({}, info) => {
  const receiver = new OwnedHttpReceiver()
  let application: ElectronApplication | null = null
  await receiver.start()
  try {
    const profile = 'admitted-hidden'
    const env = { ODIN_DESKTOP_CORE_CMD: receiver.coreCommand }
    application = await launchApp({ profile, env })
    const original = await waitForCore(application)
    const originalIdentity = identity(original.pid)
    const targetId = await target(application, receiver, 'hidden')
    const commandId = randomUUID()
    const admitted = await pending(application, receiver, targetId, commandId)
    await application.evaluate(() => (globalThis as unknown as {__odinE2E: {close(): void}}).__odinE2E.close())
    expect((await snapshot(application)).visible).toBe(false)
    expect(await waitForCore(application)).toEqual(original)
    await receiver.control('release')
    const response = await admitted.promise
    expect(response).toMatchObject({ ok: true, result: {success: true, status_code: 204, attempt: 1, webhook_id: targetId} })
    const hidden = await snapshot(application)
    expect(hidden.visible).toBe(false)
    expect((await receiver.snapshot()).effect_count).toBe(1)
    const durable = await receiver.journal(hidden.paths.dataDir, commandId)
    expect(durable).toMatchObject({command_id: commandId, state: 'final', response, unknown_outcome: 0})
    await launchSecond(application)
    expect((await snapshot(application)).visible).toBe(true)
    expect(await waitForCore(application)).toEqual(original)
    await exitApp(application); application = null
    application = await launchApp({ profile, env })
    const fresh = await waitForCore(application)
    expect(fresh.instanceId).not.toBe(original.instanceId)
    expect(await request(application, 'webhooks.outbound.test', {id: targetId}, commandId)).toEqual(response)
    expect(await request(application, 'webhooks.outbound.test', {id: `${targetId}-changed`}, commandId)).toMatchObject({ok: false, error: {code: 'id_conflict'}})
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect((await receiver.snapshot()).effect_count).toBe(1)
    await attach(info, 'real-management-hidden-durable-no-replay', { commandId, targetId, original,
      originalIdentity, fresh, freshIdentity: identity(fresh.pid), hidden, durable,
      receiver: await receiver.snapshot(), scope: 'Actual named management admission only; no turns/background execution claim',
      seam: 'Real src.__main__.main and CoreService; supported secret backend returns None, forbids writes; no credentials' })
    await exitApp(application); application = null
  } finally { await close(application); await attach(info, 'owned-http-cleanup', await receiver.stop()) }
})

test('Exit while an admitted HTTP management call is pending lets short work settle durably before shutdown', async ({}, info) => {
  const receiver = new OwnedHttpReceiver()
  let application: ElectronApplication | null = null
  await receiver.start()
  try {
    application = await launchApp({ profile: 'admitted-exit-settle', env: {ODIN_DESKTOP_CORE_CMD: receiver.coreCommand} })
    await waitForCore(application)
    const targetId = await target(application, receiver, 'exit-settle')
    const commandId = randomUUID()
    const admitted = await pending(application, receiver, targetId, commandId)
    const exiting = exitApp(application)
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect((await receiver.snapshot()).requests[0]?.response_sent).toBe(false)
    await receiver.control('release')
    const response = await admitted.promise
    expect(response).toMatchObject({ok: true, result: {success: true, status_code: 204}})
    await exiting; application = null
    const durable = await receiver.journal(admitted.state.paths.dataDir, commandId)
    expect(durable).toMatchObject({command_id: commandId, state: 'final', response, unknown_outcome: 0})
    const cleanup = JSON.parse(readFileSync(admitted.state.cleanupPath, 'utf8'))
    expect(cleanup).toMatchObject({state: 'process-exited', shutdownAccepted: true, unreceipted: 0})
    expect((await receiver.snapshot()).effect_count).toBe(1)
    await attach(info, 'real-management-exit-settled', {commandId, targetId, durable, cleanup, receiver: await receiver.snapshot()})
  } finally { await close(application); await attach(info, 'owned-http-cleanup', await receiver.stop()) }
})

test('Exit cancels long pending admitted management durably as unknown and fresh app core never replays the effect', async ({}, info) => {
  test.setTimeout(60_000)
  const receiver = new OwnedHttpReceiver()
  let application: ElectronApplication | null = null
  await receiver.start()
  try {
    const profile = 'admitted-exit-cancel'
    const env = {ODIN_DESKTOP_CORE_CMD: receiver.coreCommand}
    application = await launchApp({profile, env})
    const original = await waitForCore(application)
    const originalIdentity = identity(original.pid)
    const targetId = await target(application, receiver, 'exit-cancel')
    const commandId = randomUUID()
    const admitted = await pending(application, receiver, targetId, commandId)
    // Exit can close the CDP connection before evaluate returns. Capture rather than invent a receipt.
    const appResponse = admitted.promise.then((value) => value, (error) => ({transportClosed: String(error)}))
    await exitApp(application); application = null
    await expect.poll(async () => (await receiver.snapshot()).requests[0]?.disconnected).toBe(true)
    const afterExit = await receiver.journal(admitted.state.paths.dataDir, commandId)
    expect(afterExit).toMatchObject({command_id: commandId, state: 'pending', response: null})
    const cleanup = JSON.parse(readFileSync(admitted.state.cleanupPath, 'utf8'))
    expect(cleanup).toMatchObject({state: 'unknown', shutdownAccepted: false})
    expect(cleanup.unreceipted).toBeGreaterThanOrEqual(1)
    const effectsAtExit = await receiver.snapshot()
    expect(effectsAtExit.effect_count).toBe(1)
    application = await launchApp({profile, env})
    const fresh = await waitForCore(application)
    expect(fresh.instanceId).not.toBe(original.instanceId)
    const replay = await request(application, 'webhooks.outbound.test', {id: targetId}, commandId)
    expect(replay).toMatchObject({ok: false, error: {disposition: 'outcome_unknown'}})
    expect((await snapshot(application)).cleanupUnknown?.state).toBe('unknown')
    await new Promise((resolve) => setTimeout(resolve, 500))
    // The independent receiver recorded one effect before cancellation; lookup must add none.
    expect((await receiver.snapshot()).effect_count).toBe(effectsAtExit.effect_count)
    await attach(info, 'real-management-exit-cancel-no-replay', {commandId, targetId, original, originalIdentity,
      fresh, freshIdentity: identity(fresh.pid), afterExit, cleanup,
      appResponse: await appResponse, replay, effectsAtExit, afterFreshLookup: await receiver.snapshot(),
      scope: 'Cancellation leaves durable pending reservation/outcome_unknown, not an undone HTTP effect or completed turn' })
    await exitApp(application); application = null
  } finally { await close(application); await attach(info, 'owned-http-cleanup', await receiver.stop()) }
})
