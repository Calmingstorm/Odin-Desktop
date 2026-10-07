import { randomUUID } from 'node:crypto'
import { request } from 'node:http'
import { createServer, type Server } from 'node:net'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import type { Broker, Settled } from '../src/main/broker'
import { assertIsolated, RealCoreHarness } from './real-core-harness'

assertIsolated()

type Ingress = { reason: string; address: [string, number] | null;
  eligible_schedules: number; unknown_deliveries: number }
type Schema = { revision: string; fields: Array<{ path: string; desired: unknown;
  effective: unknown; configured: boolean | null; sensitivity: string; secret_route: string | null }> }
type Message = { id: string; role: string; text: string }
type History = { schedule_id: string; status: string; run_binding: { run_id: string; conversation_id: string } }

function result<T = unknown>(answer: Settled): T {
  expect(answer.ok, JSON.stringify(answer)).toBe(true)
  if (!answer.ok) throw new Error(`Real core refused: ${answer.error.code}`)
  return answer.result as T
}

// No fixture ingress, injected scheduler callback, or direct store edits: every
// setting, schedule and observation passes through the actual Broker/core graph.
describe('real core delivery-only webhook ingress contract', () => {
  let core: RealCoreHarness
  let broker: Broker
  let occupied: Server | undefined
  beforeEach(async () => {
    core = new RealCoreHarness({ memoryKeyring: true })
    await core.start()
    broker = (await core.connect()).broker
  })
  afterEach(async () => {
    try { await core?.dispose() } finally {
      if (occupied) await new Promise<void>((resolve, reject) =>
        occupied!.close(error => error ? reject(error) : resolve()))
      occupied = undefined
    }
  })

  async function schema(): Promise<Schema> {
    return result<Schema>(await broker.request('settings.schema'))
  }
  async function settings(changes: Array<{ path: string; value: unknown }>): Promise<Settled> {
    const before = await schema()
    return broker.request('settings.set', { expected_revision: before.revision, changes })
  }
  async function ingress(): Promise<Ingress> {
    const status = result<{ webhook_ingress: Ingress }>(await broker.request('status.get'))
    expect(Object.keys(status.webhook_ingress).sort())
      .toEqual(['address', 'eligible_schedules', 'reason', 'unknown_deliveries'])
    expect(status.webhook_ingress).toMatchObject({ reason: expect.any(String),
      eligible_schedules: expect.any(Number), unknown_deliveries: expect.any(Number) })
    return status.webhook_ingress
  }
  async function state(reason: string, eligible: number): Promise<Ingress> {
    const deadline = Date.now() + 8_000
    for (;;) {
      const view = await ingress()
      if (view.reason === reason && view.eligible_schedules === eligible) {
        expect(view.unknown_deliveries).toBe(0)
        if (reason === 'accepting') {
          expect(view.address).toEqual(['127.0.0.1', expect.any(Number)])
          expect(view.address![1]).toBeGreaterThan(0)
        } else expect(view.address).toBeNull()
        return view
      }
      if (Date.now() >= deadline) throw new Error(`Ingress did not settle: ${JSON.stringify(view)}`)
      await new Promise(resolve => setTimeout(resolve, 20))
    }
  }
  async function enable(port = 0): Promise<void> {
    result(await settings([{ path: 'webhook.enabled', value: true },
      { path: 'webhook.bind_address', value: '127.0.0.1' }, { path: 'webhook.port', value: port }]))
  }
  async function schedule(source = 'generic') {
    const conversation = result<{ conversation: { id: string } }>(await broker.request('conversations.create',
      { title: 'Disposable webhook destination' }))
    const cid = conversation.conversation.id
    const message = `Harmless webhook reminder ${randomUUID()}`
    const saved = result<{ id: string }>(await broker.request('schedules.save', {
      description: 'Delivery-only reminder', action: 'reminder', channel_id: cid, message,
      trigger: { source, event: 'contract' }
    }))
    return { id: saved.id, cid, message }
  }
  async function configure(id: string, source = 'generic') {
    const secret = `disposable-webhook-${randomUUID()}`
    const path = `webhook.triggers.${id}.secret`
    result(await settings([{ path: `webhook.triggers.${id}.source`, value: source }]))
    expect(result(await broker.request('secrets.set', { path, value: secret }))).toEqual({ set: true })
    return { path, secret }
  }
  async function post(address: [string, number], body: string, secret?: string, route = '/webhook/generic') {
    return new Promise<{ status: number; body: unknown }>((resolve, reject) => {
      const req = request({ hostname: address[0], port: address[1], path: route, method: 'POST', agent: false,
        headers: { 'Content-Type': 'application/json', ...(secret === undefined ? {} : { 'X-Webhook-Secret': secret }) } }, res => {
        let text = ''
        res.setEncoding('utf8')
        res.on('data', chunk => { text += chunk })
        res.on('error', reject)
        res.on('end', () => {
          try { resolve({ status: res.statusCode!, body: JSON.parse(text) }) } catch (error) { reject(error) }
        })
      })
      req.on('error', reject)
      req.setTimeout(3_000, () => req.destroy(new Error('Disposable webhook HTTP timed out')))
      req.end(body)
    })
  }
  async function history(id: string): Promise<History[]> {
    return result<History[]>(await broker.request('schedules.history', { id, limit: 100 }))
  }
  async function messages(cid: string): Promise<Message[]> {
    return result<{ items: Message[] }>(await broker.request('messages.list', { conversation_id: cid, limit: 100 })).items
  }

  test('opt-in binds only an eligible keyed trigger; authentic identical HTTP deliveries run twice with native replies', async () => {
    await state('disabled', 0)
    result(await settings([{ path: 'webhook.enabled', value: true }]))
    await state('unconfigured_bind', 0)
    await enable()
    await state('no_eligible_schedule', 0)
    const item = await schedule()
    await state('no_eligible_schedule', 0)
    result(await settings([{ path: `webhook.triggers.${item.id}.source`, value: 'generic' }]))
    await state('no_eligible_schedule', 0)
    const { secret } = await configure(item.id)
    const address = (await state('accepting', 1)).address!
    const body = JSON.stringify({ event: 'contract', title: 'Incoming contract', message: 'Identical external event' })
    expect(await post(address, body)).toEqual({ status: 403, body: { error: 'invalid secret' } })
    expect(await post(address, body, 'wrong-disposable-key')).toEqual({ status: 403, body: { error: 'invalid secret' } })
    expect(await history(item.id)).toEqual([])
    expect(await messages(item.cid)).toEqual([])
    expect(await post(address, '{', secret)).toEqual({ status: 400, body: { error: 'invalid JSON' } })
    // D17: plain HTTP, no timestamp/freshness/owner-confirmation envelope.
    // Identical bodies are independent external deliveries, not command replays.
    expect(await post(address, body, secret)).toEqual({ status: 200, body: { status: 'delivered' } })
    expect(await post(address, body, secret)).toEqual({ status: 200, body: { status: 'delivered' } })
    const runs = await history(item.id)
    expect(runs).toHaveLength(2)
    expect(runs).toEqual([expect.objectContaining({ status: 'success', schedule_id: item.id }),
      expect.objectContaining({ status: 'success', schedule_id: item.id })])
    expect(new Set(runs.map(run => run.run_binding.run_id)).size).toBe(2)
    expect(runs.every(run => run.run_binding.conversation_id === item.cid)).toBe(true)
    const transcript = await messages(item.cid)
    const notices = transcript.filter(row => row.text === '**Incoming contract**\nIdentical external event')
    expect(notices).toHaveLength(2)
    expect(notices.every(row => row.role === 'notice')).toBe(true)
    expect(new Set(notices.map(row => row.id)).size).toBe(2)
    expect(transcript.filter(row => row.text.includes(item.message))).toHaveLength(2)
    await state('accepting', 1)
  })

  test('pause and secret clear revoke the actual listener; resuming restores only the eligible schedule', async () => {
    const item = await schedule()
    const { path, secret } = await configure(item.id)
    await enable()
    const first = (await state('accepting', 1)).address!
    result(await broker.request('schedules.save', { id: item.id, paused: true }))
    await state('no_eligible_schedule', 0)
    await expect(post(first, '{}', secret)).rejects.toMatchObject({ code: 'ECONNREFUSED' })
    result(await broker.request('schedules.save', { id: item.id, paused: false }))
    const second = (await state('accepting', 1)).address!
    expect(result(await broker.request('secrets.clear', { path }))).toEqual({ set: false })
    await state('no_eligible_schedule', 0)
    await expect(post(second, '{}', secret)).rejects.toMatchObject({ code: 'ECONNREFUSED' })
    expect(await history(item.id)).toEqual([])
    expect(await messages(item.cid)).toEqual([])
  })

  test('per-schedule credential never reads back through schema/status or persisted profile; event text is redacted', async () => {
    const item = await schedule()
    const { path, secret } = await configure(item.id)
    await enable()
    const address = (await state('accepting', 1)).address!
    const view = await schema()
    expect(view.fields.find(field => field.path === path)).toMatchObject({ configured: true,
      sensitivity: 'sensitive', secret_route: 'secrets.set' })
    expect(JSON.stringify({ view, status: result(await broker.request('status.get')) })).not.toContain(secret)
    expect(core.persistedFilesContain(secret)).toBe(false)
    expect(core.diagnostics).not.toContain(secret)
    expect(await post(address, JSON.stringify({ event: 'contract', title: 'Redacted credential', message: secret }), secret))
      .toEqual({ status: 200, body: { status: 'delivered' } })
    const transcript = await messages(item.cid)
    expect(transcript.some(row => row.text === '**Redacted credential**\n[REDACTED]')).toBe(true)
    expect(JSON.stringify({ transcript, view: await schema(), status: result(await broker.request('status.get')) })).not.toContain(secret)
    expect(core.persistedFilesContain(secret)).toBe(false)
    expect(core.diagnostics).not.toContain(secret)
  })

  test.each(['0.0.0.0', '::'])('wildcard bind %s is rejected without changing desired configuration or binding', async address => {
    const before = await schema()
    expect(await settings([{ path: 'webhook.bind_address', value: address }]))
      .toMatchObject({ ok: false, error: { code: 'bad_request', disposition: 'rejected' } })
    const after = await schema()
    expect(after.revision).toBe(before.revision)
    expect(after.fields.find(field => field.path === 'webhook.bind_address')?.desired).toBe('')
    await state('disabled', 0)
  })

  test('an occupied explicit loopback port remains not_bound and never accepts on a fallback port', async () => {
    occupied = createServer(socket => socket.destroy())
    await new Promise<void>((resolve, reject) => {
      occupied!.once('error', reject)
      occupied!.listen(0, '127.0.0.1', resolve)
    })
    const reservation = occupied.address()
    if (!reservation || typeof reservation === 'string') throw new Error('Disposable port reservation failed')
    const item = await schedule()
    await configure(item.id)
    await enable(reservation.port)
    await state('not_bound', 1)
    // Keep the reservation alive across the ingress retry interval.
    await new Promise(resolve => setTimeout(resolve, 1_100))
    await state('not_bound', 1)
    expect((await schema()).fields.find(field => field.path === 'webhook.port')?.desired).toBe(reservation.port)
    expect(await history(item.id)).toEqual([])
    result(await settings([{ path: 'webhook.enabled', value: false }]))
    await state('disabled', 0)
  })

  test('GitLab remains a valid native schedule source but cannot configure or activate unsupported ingress', async () => {
    await enable()
    const item = await schedule('gitlab')
    expect(result<Array<{ id: string; trigger: { source: string } }>>(await broker.request('schedules.list')))
      .toContainEqual(expect.objectContaining({ id: item.id, trigger: expect.objectContaining({ source: 'gitlab' }) }))
    expect(await settings([{ path: `webhook.triggers.${item.id}.source`, value: 'gitlab' }]))
      .toMatchObject({ ok: false, error: { code: 'bad_request' } })
    await state('no_eligible_schedule', 0)
    // A supported row with a real key still cannot widen a GitLab definition.
    await configure(item.id, 'generic')
    await state('no_eligible_schedule', 0)
    expect(await history(item.id)).toEqual([])
  })
})
