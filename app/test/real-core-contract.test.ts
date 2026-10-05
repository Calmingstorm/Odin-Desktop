import { randomUUID } from 'node:crypto'
import { statSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import type { CoreEvent } from '../src/shared/api'
import { PROTOCOL, type Settled, type Welcome } from '../src/main/broker'
import { assertIsolated, onceEvent, RealCoreHarness, waitFor } from './real-core-harness'

// Intentional module-level hard failure if someone invokes this file with the normal/unisolated Vitest gate.
assertIsolated()

const capabilities = ['status.get', 'events.subscribe', 'runtime.shutdown', 'submission.send', 'notifications.ack', ...[
  'conversations.list', 'conversations.create', 'conversations.update', 'conversations.delete',
  'conversations.reset_context', 'conversations.mark_read', 'messages.list',
  'conversation.snapshot', 'search.query', 'messages.around', 'attachments.begin',
  'attachments.chunk', 'attachments.commit', 'attachments.cancel', 'artifacts.read', 'tool.detail', 'tool.output'
].sort()]
function successful<T>(answer: Settled): T {
  expect(answer.ok).toBe(true)
  if (!answer.ok) throw new Error(`Expected a real-core receipt, got ${answer.error.code}`)
  return answer.result as T
}
function refused(answer: Settled, code: string, disposition = 'rejected'): void {
  expect(answer).toMatchObject({ ok: false, error: { code, disposition } })
}
type Status = { phase: string; core_instance_id: string; version: string; capabilities: string[] }
type Subscription = { event_high: string; reset_required: boolean }

describe('actual app Broker ↔ repository real core', () => {
  let core: RealCoreHarness
  beforeEach(async () => {
    core = new RealCoreHarness()
    await core.start()
  })
  afterEach(async () => { await core?.dispose() })

  test('authenticates the handshake, reads real status and replays events after a cursor', async () => {
    const { broker, welcome } = await core.connect()
    expect(welcome).toMatchObject({
      protocol: { major: PROTOCOL.major }, profile_id: 'default', capabilities, features: [],
      core: { version: '0.1.0.dev1' }
    })
    expect(welcome.core.instance_id).toMatch(/^[a-f0-9-]{36}$/)
    expect(welcome.max_frame).toBe(4 * 1024 * 1024)
    expect(statSync(core.paths.socketPath).mode & 0o777).toBe(0o600)
    expect(statSync(core.paths.tokenPath).mode & 0o777).toBe(0o600)
    const status = successful<Status>(await broker.request('status.get'))
    expect(status).toEqual({ phase: 'ready', core_instance_id: welcome.core.instance_id,
      version: welcome.core.version, capabilities })

    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    const subscribed = successful<Subscription>(await broker.request('events.subscribe', { after: '0' }))
    expect(subscribed).toEqual({ event_high: welcome.event_high, reset_required: false })
    await waitFor(() => events.length === 1, 'startup event replay')
    expect(events[0]).toMatchObject({ t: 'evt', seq: 1, cursor: '1', type: 'runtime.status',
      entity: { kind: 'runtime', id: welcome.core.instance_id }, payload: status })
    expect(events[0]!.at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/)
    expect(Date.parse(events[0]!.at)).not.toBeNaN()
    expect(broker.cursor).toBe('1')
    // A newly connected Broker can replay the same persisted interval, not a fixture projection.
    const second = await core.connect()
    const replay = onceEvent<CoreEvent>(second.broker, 'event')
    successful(await second.broker.request('events.subscribe', { after: '0' }))
    expect(await replay).toEqual(events[0])
  })

  test('runtime.shutdown returns acceptance and shuts down gracefully; original receipt survives restart without another shutdown', async () => {
    const { broker } = await core.connect()
    const id = randomUUID()
    const params = { reason: 'real-core contract shutdown' }
    const accepted = await broker.request('runtime.shutdown', params, id)
    expect(accepted).toEqual({ ok: true, result: { disposition: 'accepted' } })
    expect(await core.waitExit()).toEqual({ code: 0, signal: null })
    broker.close()
    await core.start()
    const restarted = await core.connect()
    expect(await restarted.broker.request('runtime.shutdown', params, id)).toEqual(accepted)
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
    expect(core.running).toBe(true)
    refused(await restarted.broker.request('runtime.shutdown', { reason: 'different reason' }, id), 'id_conflict')
    refused(await restarted.broker.request('status.get', {}, id), 'id_conflict')
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
  })

  test('validation refusals are durable original receipts; canonical params agree and changed params conflict', async () => {
    const { broker } = await core.connect()
    const id = randomUUID()
    const original = await broker.request('runtime.shutdown', { reason: 42, extra: true }, id)
    refused(original, 'bad_request')
    expect(await broker.request('runtime.shutdown', { extra: true, reason: 42 }, id)).toEqual(original)
    refused(await broker.request('runtime.shutdown', { reason: 'now valid', extra: true }, id), 'id_conflict')
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    await core.start()
    const restarted = await core.connect()
    expect(await restarted.broker.request('runtime.shutdown', { extra: true, reason: 42 }, id)).toEqual(original)
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
  })

  test('the real startup pruner expires a receipt body but never re-admits its retained identity', async () => {
    const { broker } = await core.connect()
    const id = randomUUID()
    const params = { reason: 'expire real receipt' }
    expect(await broker.request('runtime.shutdown', params, id)).toEqual({ ok: true, result: { disposition: 'accepted' } })
    expect(await core.waitExit()).toEqual({ code: 0, signal: null })
    broker.close()
    // Only age finished_at offline. No handmade response/tombstone and no patched engine retention.
    core.ageReceipt(id)
    await core.start()
    const restarted = await core.connect()
    refused(await restarted.broker.request('runtime.shutdown', params, id), 'receipt_expired', 'outcome_unknown')
    refused(await restarted.broker.request('runtime.shutdown', { reason: 'changed expired binding' }, id), 'id_conflict')
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
    expect(core.running).toBe(true)
  })

  test('fresh reads and unserved capabilities do not reserve command IDs', async () => {
    const { broker, welcome } = await core.connect()
    const id = randomUUID()
    expect(successful<Status>(await broker.request('status.get', {}, id)).core_instance_id).toBe(welcome.core.instance_id)
    expect(successful<Subscription>(await broker.request('events.subscribe', { after: '0' }, id)).reset_required).toBe(false)
    expect(successful<Subscription>(await broker.request('events.subscribe', { after: '999999' }, id)).reset_required).toBe(true)
    expect(successful<{ items: unknown[] }>(await broker.request('conversations.list', {}, id)).items).toEqual([])
    refused(await broker.request('work.list', {}, id), 'capability_unavailable')
    refused(await broker.request('settings.schema', {}, id), 'capability_unavailable')
    expect(await broker.request('runtime.shutdown', { reason: 'read ID is still available' }, id)).toEqual({
      ok: true, result: { disposition: 'accepted' }
    })
    expect(await core.waitExit()).toEqual({ code: 0, signal: null })
  })

  test('reads identical public transcript payloads through paging, snapshot and search navigation', async () => {
    const { broker } = await core.connect()
    type Conversation = { id: string; rev: number }
    const created = successful<{ conversation: Conversation }>(await broker.request(
      'conversations.create', { title: 'real conversation navigation' }, randomUUID()))
    const reset = successful<{ conversation: Conversation }>(await broker.request(
      'conversations.reset_context', { id: created.conversation.id, expected_rev: created.conversation.rev }, randomUUID()))
    const cid = reset.conversation.id
    const page = successful<{ items: { id: string; text: string }[] }>(await broker.request(
      'messages.list', { conversation_id: cid, limit: 100 }))
    const snapshot = successful<{ messages: { items: unknown[] } }>(await broker.request(
      'conversation.snapshot', { conversation_id: cid }))
    expect(page.items).toHaveLength(1)
    expect(page.items[0]!.text).toBe('Model context reset.')
    const around = successful<{ items: unknown[] }>(await broker.request('messages.around', {
      conversation_id: cid, message_id: page.items[0]!.id, before: 0, after: 0
    }))
    expect(around.items).toEqual(page.items)
    expect(around.items).toEqual(snapshot.messages.items)
    refused(await broker.request('messages.list', { conversation_id: cid, before: 'm_missing', limit: 100 }), 'not_found')
    const found = successful<{ hits: { message_id: string }[] }>(await broker.request(
      'search.query', { query: 'context RESET', conversation_id: cid }))
    expect(found.hits.map((hit) => hit.message_id)).toEqual([page.items[0]!.id])
  })

  test('closing the parent stdin pipe exits orderly and releases the profile for a successor', async () => {
    const { broker, welcome } = await core.connect()
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    broker.close()
    expect(core.running).toBe(false)
    await core.start()
    const restarted = await core.connect()
    expect(restarted.welcome.core.instance_id).not.toBe(welcome.core.instance_id)
    expect(successful<Status>(await restarted.broker.request('status.get')).phase).toBe('ready')
  })

  test('a wrong token is unauthorized, never reaches ready, and cannot stop the real core', async () => {
    const broker = core.broker(true)
    const welcomes: Welcome[] = []
    broker.on('welcome', (welcome: Welcome) => welcomes.push(welcome))
    const rejected = onceEvent<string>(broker, 'bye')
    broker.connect()
    expect(await rejected).toBe('unauthorized')
    broker.close()
    expect(welcomes).toEqual([])
    expect(broker.linkState).not.toBe('ready')
    refused(await broker.request('runtime.shutdown', { reason: 'must not execute' }), 'not_connected', 'not_dispatched')
    const valid = await core.connect()
    expect(successful<Status>(await valid.broker.request('status.get')).phase).toBe('ready')
  })

  test('restart preserves the event sequence and the same Broker catches up with no reset or duplicate', async () => {
    const { broker, welcome } = await core.connect()
    const events: CoreEvent[] = []
    const resets: unknown[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    broker.on('reset', (reset: unknown) => resets.push(reset))
    // A normal app subscription starts live at null; only future status events flow.
    successful(await broker.subscribe())
    expect(events).toEqual([])
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    await waitFor(() => events.length === 1, 'old incarnation quiescing event')
    expect(broker.cursor).toBe('2')
    const changed = onceEvent<string>(broker, 'core-changed')
    await core.start()
    const newInstance = await changed
    expect(newInstance).not.toBe(welcome.core.instance_id)
    await waitFor(() => events.some((event) => event.payload.core_instance_id === newInstance), 'new incarnation event after reconnect')
    expect(events.map((event) => event.seq)).toEqual([2, 3])
    expect(events.map((event) => event.cursor)).toEqual(['2', '3'])
    expect(events.map((event) => event.payload.phase)).toEqual(['quiescing', 'ready'])
    expect(events[1]!.entity.id).toBe(newInstance)
    expect(broker.cursor).toBe('3')
    expect(resets).toEqual([])
    expect(successful<Status>(await broker.request('status.get')).core_instance_id).toBe(newInstance)
    const replayBroker = (await core.connect()).broker
    const replayed: CoreEvent[] = []
    replayBroker.on('event', (event: CoreEvent) => replayed.push(event))
    expect(successful<Subscription>(await replayBroker.request('events.subscribe', { after: '0' }))).toEqual({
      reset_required: false, event_high: '3'
    })
    await waitFor(() => replayed.length === 3, 'entire persisted interval after restart')
    expect(replayed.map((event) => event.seq)).toEqual([1, 2, 3])
    expect(replayed[0]!.entity.id).toBe(welcome.core.instance_id)
    expect(replayed.slice(1)).toEqual(events)
    replayBroker.close()
    // The exact same read ID returns the successor's fresh status, never the old runtime's status.
    const id = randomUUID()
    successful(await broker.request('status.get', {}, id))
    expect(await core.parentEOF()).toEqual({ code: 0, signal: null })
    const next = onceEvent<string>(broker, 'core-changed')
    await core.start()
    const nextInstance = await next
    expect(successful<Status>(await broker.request('status.get', {}, id)).core_instance_id).toBe(nextInstance)
  })
})
