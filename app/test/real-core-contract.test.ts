import { createHash, randomUUID } from 'node:crypto'
import { statSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import type { CoreEvent } from '../src/shared/api'
import { PROTOCOL, type Settled, type Welcome } from '../src/main/broker'
import { assertIsolated, onceEvent, RealCoreHarness, waitFor } from './real-core-harness'
import { FILE_CONTENT, IMAGE_BYTES, PAGED_TEXT, REPLY, TOOL_REPLY } from './real-core-provider-fixture.mjs'

// Intentional module-level hard failure if someone invokes this file with the normal/unisolated Vitest gate.
assertIsolated()

const capabilities = ['status.get', 'events.subscribe', 'runtime.shutdown', 'submission.send', 'notifications.ack', ...[
  'conversations.list', 'conversations.create', 'conversations.update', 'conversations.delete',
  'conversations.reset_context', 'conversations.mark_read', 'messages.list',
  'conversation.snapshot', 'search.query', 'messages.around', 'attachments.begin',
  'attachments.chunk', 'attachments.commit', 'attachments.cancel', 'artifacts.read', 'tool.detail', 'tool.output',
  'control.stop', 'control.steer', 'control.resume'
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
      version: welcome.core.version, capabilities,
      limits: { attachment_bytes: 50 * 1024 * 1024, attachments_per_turn: 10, chunk_bytes: 512 * 1024 } })

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

type Conversation = { id: string; rev: number; title: string; archived: boolean; parent_id: string | null }
type Message = { id: string; role: string; text: string; request_id?: string;
  artifacts?: { ref: string; name: string; mime: string }[]; attachments?: { ref: string }[] }
type Snapshot = { conversation: Conversation; watermark: string; messages: { items: Message[] };
  running: { request_id: string; generation: number } | null; queued: { request_id: string }[];
    recent: { request_id: string; outcome: string; unknown_effects: number }[];
    tools: Record<string, { invocation_id: string; tool: string }[]>; controls: unknown[] }
type Submission = { disposition: string; request_id: string; message_id: string }

describe('provider-backed steps 2-4 through the real Broker and real OpenAICompatibleClient', () => {
  let core: RealCoreHarness
  beforeEach(async () => {
    core = new RealCoreHarness()
    await core.configureProvider()
    await core.start()
  })
  afterEach(async () => { await core?.dispose() })

  async function setup() {
    const { broker } = await core.connect()
    const events: CoreEvent[] = []
    broker.on('event', (event: CoreEvent) => events.push(event))
    successful(await broker.subscribe())
    const conversation = successful<{ conversation: Conversation }>(await broker.request(
      'conversations.create', { title: 'Provider contract' }, randomUUID())).conversation
    const snapshot = async () => successful<Snapshot>(await broker.request('conversation.snapshot', { conversation_id: conversation.id }))
    const send = async (text: string, extra = {}) => successful<Submission>(await broker.request('submission.send', {
      conversation_id: conversation.id, client_submission_id: randomUUID(), text, ...extra
    }, randomUUID()))
    const settled = async (request: Submission, outcome = 'completed') => {
      await waitFor(() => events.some((event) => event.type === `request.${outcome}` && event.payload.request_id === request.request_id),
        `${request.request_id} ${outcome}`, 12_000)
      return snapshot()
    }
    const replied = async (text = REPLY) => waitFor(() => events.some((event) =>
      event.type === 'message.committed' && (event.payload.message as Message | undefined)?.text === text), 'committed guarded reply')
    return { broker, events, conversation, snapshot, send, settled, replied }
  }

  test('reply and immutable send receipt; CRUD/child/reset/search/jump and watermark catch-up', async () => {
    const { broker, events, conversation, snapshot, settled, replied } = await setup()
    const params = { conversation_id: conversation.id, client_submission_id: randomUUID(), text: '[reply] navigation contract' }
    const sent = successful<Submission>(await broker.request('submission.send', params, randomUUID()))
    await settled(sent)
    await replied()
    expect(successful(await broker.request('submission.send', params, randomUUID()))).toEqual(sent)
    refused(await broker.request('submission.send', { ...params, text: '[reply] changed' }, randomUUID()), 'id_conflict')
    let snap = await snapshot()
    const reply = snap.messages.items.find((message) => message.role === 'assistant')!
    expect(reply.text).toBe(REPLY)
    expect(reply.request_id).toBe(sent.request_id)
    expect(events.filter((event) => event.type === 'message.committed' && (event.payload.message as Message | undefined)?.role === 'assistant')).toHaveLength(1)
    expect(core.provider!.requests).toHaveLength(1)
    expect(core.provider!.requests[0]!.body).toMatchObject({ stream: true, model: 'canned-contract' })
    const child = successful<{ conversation: Conversation }>(await broker.request('conversations.create', {
      title: 'Child snapshot', parent_id: conversation.id, from_message_id: reply.id
    }, randomUUID())).conversation
    expect(child.parent_id).toBe(conversation.id)
    const childSent = successful<Submission>(await broker.request('submission.send', {
      conversation_id: child.id, client_submission_id: randomUUID(), text: '[reply] child context'
    }, randomUUID()))
    await waitFor(() => events.some((event) => event.type === 'request.completed' && event.payload.request_id === childSent.request_id), 'child real generation')
    expect(JSON.stringify(core.provider!.requests.find((entry) => JSON.stringify(entry.body.messages).includes('child context'))?.body.messages)).toContain('navigation contract')
    let current = successful<{ conversation: Conversation }>(await broker.request('conversations.update', {
      id: conversation.id, expected_rev: snap.conversation.rev, title: 'Renamed provider contract', archived: true
    }, randomUUID())).conversation
    expect(current).toMatchObject({ title: 'Renamed provider contract', archived: true })
    refused(await broker.request('conversations.update', { id: current.id, expected_rev: 1, title: 'stale' }, randomUUID()), 'stale_binding', 'stale_binding')
    const found = successful<{ hits: { message_id: string }[] }>(await broker.request('search.query', { query: 'real core contract', conversation_id: current.id }))
    expect(found.hits.some((hit) => hit.message_id === reply.id)).toBe(true)
    expect(successful<{ items: Message[] }>(await broker.request('messages.around', {
      conversation_id: current.id, message_id: reply.id, before: 0, after: 0
    })).items).toEqual([reply])
    const watermark = (await snapshot()).watermark
    current = successful<{ conversation: Conversation }>(await broker.request('conversations.reset_context', {
      id: current.id, expected_rev: current.rev
    }, randomUUID())).conversation
    snap = await snapshot()
    expect(snap.messages.items.at(-1)?.text).toBe('Model context reset.')
    expect(snap.messages.items).toContainEqual(reply)
    const reconnected = (await core.connect()).broker
    const replay: CoreEvent[] = []
    reconnected.on('event', (event: CoreEvent) => replay.push(event))
    successful(await reconnected.request('events.subscribe', { after: watermark }))
    await waitFor(() => replay.some((event) => event.cursor === snap.watermark), 'snapshot watermark catch-up')
    expect(replay.every((event) => BigInt(event.cursor) > BigInt(watermark))).toBe(true)
    expect(new Set(replay.map((event) => event.cursor)).size).toBe(replay.length)
    const afterReset = successful<Submission>(await broker.request('submission.send', {
      conversation_id: current.id, client_submission_id: randomUUID(), text: '[reply] after reset'
    }, randomUUID()))
    await settled(afterReset)
    const resetInput = core.provider!.requests.find((entry) => JSON.stringify(entry.body.messages).includes('after reset'))!
    expect(JSON.stringify(resetInput.body.messages)).not.toContain('navigation contract')
    expect(JSON.stringify(resetInput.body.messages)).not.toContain('child context')
    current = (await snapshot()).conversation
    const childCurrent = successful<Snapshot>(await broker.request('conversation.snapshot', { conversation_id: child.id })).conversation
    successful(await broker.request('conversations.delete', { id: child.id, expected_rev: childCurrent.rev }, randomUUID()))
    successful(await broker.request('conversations.delete', { id: current.id, expected_rev: current.rev }, randomUUID()))
    expect(successful<{ items: Conversation[] }>(await broker.request('conversations.list')).items).toEqual([])
    refused(await broker.request('conversation.snapshot', { conversation_id: current.id }), 'not_found')
  })

  test('harmless real tool produces activity and scoped detail rather than fixture cards', async () => {
    const { broker, snapshot, send, settled, replied } = await setup()
    const sent = await send('[tool] parse a harmless time')
    await settled(sent)
    await replied(TOOL_REPLY)
    const snap = await snapshot()
    const tool = snap.tools[sent.request_id]![0]!
    expect(tool).toBeDefined()
    const detail = successful<Record<string, unknown>>(await broker.request('tool.detail', { request_id: sent.request_id, invocation_id: tool.invocation_id }))
    expect(JSON.stringify(detail)).toContain('parse_time')
    expect(JSON.stringify(detail)).toContain('in 2 hours')
    // The real completion classifier may request another generation. Require
    // actual tool feedback, not a brittle exact count of model invocations.
    expect(core.provider!.requests.length).toBeGreaterThanOrEqual(2)
    expect(core.provider!.requests.some((entry) => entry.body.messages.some((message) => message.role === 'tool'))).toBe(true)
    refused(await broker.request('tool.detail', { request_id: 'r_missing', invocation_id: tool.invocation_id }), 'not_found')
  })

  test('real retained tool output pages through the original source without duplicate tails', async () => {
    const { broker, snapshot, send, settled, replied } = await setup()
    const sent = await send('[paged-tool] read canned retained evidence')
    await settled(sent)
    await replied(TOOL_REPLY)
    const tool = (await snapshot()).tools[sent.request_id]![0]!
    const detail = successful<{ output: { cursor: string } }>(await broker.request('tool.detail', { request_id: sent.request_id, invocation_id: tool.invocation_id }))
    expect(detail.output.cursor, JSON.stringify(detail)).toBeTruthy()
    let cursor: string | undefined = detail.output.cursor
    let text = ''
    let pages = 0
    while (cursor) {
      const page: { text: string; next_cursor?: string; eof: boolean } = successful(await broker.request('tool.output', { cursor, limit: 8000 }))
      text += page.text
      pages++
      expect(pages).toBeLessThan(40)
      cursor = page.next_cursor
      if (!cursor) expect(page.eof).toBe(true)
    }
    expect(pages).toBeGreaterThan(1)
    expect(text).toContain('Evidence line 0000')
    expect(text).toContain('Evidence line 0899')
    expect(text.match(/Evidence line 0000/g)).toHaveLength(1)
    expect(text.match(/Evidence line 0899/g)).toHaveLength(1)
    expect(PAGED_TEXT.length).toBeGreaterThan(32_000)
  })

  test('posted file and decoded image carry real artifact bytes and scoped reads', async () => {
    const { broker, events, snapshot, send, settled } = await setup()
    const sent = await send('[artifact] post a canned text file and image')
    await settled(sent)
    await waitFor(() => events.filter((event) => event.type === 'artifact.published').length === 2, 'posted file/image events')
    const artifacts = (await snapshot()).messages.items.flatMap((message) => message.artifacts ?? [])
    expect(artifacts).toHaveLength(2)
    const text = artifacts.find((artifact) => artifact.name === 'contract.txt')!
    const image = artifacts.find((artifact) => artifact.mime === 'image/png')!
    expect(image).toBeDefined()
    for (const [artifact, expected] of [[text, Buffer.from(FILE_CONTENT)], [image, IMAGE_BYTES]] as const) {
      const result = successful<{ data_b64: string }>(await broker.request('artifacts.read', { ref: artifact.ref, offset: 0, length: 4096 }))
      expect(Buffer.from(result.data_b64, 'base64')).toEqual(expected)
    }
    refused(await broker.request('artifacts.read', { ref: 'a_missing', offset: 0, length: 4096 }), 'not_found')
  })

  test('chunked attachment commit/adoption/cancel runs processing into provider input', async () => {
    const { broker, conversation, send, settled, snapshot, replied } = await setup()
    const bytes = Buffer.from('CANNED_ATTACHMENT_TEXT_CONTENT\n')
    const begin = async () => successful<{ upload_id: string }>(await broker.request('attachments.begin', {
      client_attachment_id: randomUUID(), conversation_id: conversation.id, name: 'input.txt', mime: 'text/plain', size: bytes.length
    })).upload_id
    const upload = await begin()
    for (const [offset, chunk] of [[0, bytes.subarray(0, 7)], [7, bytes.subarray(7)]] as const) {
      successful(await broker.request('attachments.chunk', { upload_id: upload, offset, data_b64: chunk.toString('base64') }))
    }
    const committed = successful<{ attachment: { ref: string } }>(await broker.request('attachments.commit', {
      upload_id: upload, sha256: createHash('sha256').update(bytes).digest('hex')
    }))
    const sent = await send('[reply] read my attachment', { attachments: [committed.attachment] })
    await settled(sent)
    await replied()
    expect(JSON.stringify(core.provider!.requests[0]!.body.messages)).toContain('CANNED_ATTACHMENT_TEXT_CONTENT')
    expect((await snapshot()).messages.items.find((message) => message.id === sent.message_id)?.attachments).toHaveLength(1)
    const abandoned = await begin()
    successful(await broker.request('attachments.cancel', { upload_id: abandoned }))
    refused(await broker.request('attachments.chunk', { upload_id: abandoned, offset: 0, data_b64: bytes.toString('base64') }), 'expired')
  })

  test('provider failure is terminal failed, never successful, and the next send runs', async () => {
    const { events, send, settled, replied } = await setup()
    const failed = await send('[fail] fail on demand')
    const snap = await settled(failed, 'failed')
    expect(snap.recent).toContainEqual(expect.objectContaining({ request_id: failed.request_id, outcome: 'failed', unknown_effects: 0 }))
    expect(events.some((event) => event.type === 'request.completed' && event.payload.request_id === failed.request_id)).toBe(false)
    expect(snap.messages.items.filter((message) => message.role === 'assistant').every((message) => message.text !== REPLY)).toBe(true)
    await settled(await send('[reply] recovery after failure'))
    await replied()
  })

  test('held generation queues follow-up and consumes an accepted steer once at safe boundary', async () => {
    const { broker, events, conversation, snapshot, send, settled } = await setup()
    const active = await send('[hold-steer] hold for steering')
    await waitFor(() => core.provider!.requests.length === 1, 'held provider generation')
    // D9: provider generation is not transcript publication. Only the final
    // guarded delivery can create a public assistant message.
    expect((await snapshot()).messages.items.filter((message) => message.role === 'assistant')).toEqual([])
    const queued = await send('[reply] queued follow-up')
    expect((await snapshot()).queued.map((item) => item.request_id)).toContain(queued.request_id)
    const params = { control_command_id: randomUUID(), conversation_id: conversation.id, request_id: active.request_id, generation: 1, text: 'STEERING_DIRECTIVE_CONTRACT' }
    const receipt = await broker.request('control.steer', params, randomUUID())
    expect(successful(receipt)).toMatchObject({ disposition: 'queued', sequence: 1 })
    expect(await broker.request('control.steer', params, randomUUID())).toEqual(receipt)
    core.provider!.release('[hold-steer]')
    await settled(active)
    await settled(queued)
    await waitFor(() => events.some((event) => event.type === 'control.receipt' && event.payload.disposition === 'consumed'), 'steer consumed receipt')
    expect(JSON.stringify(core.provider!.requests.map((entry) => entry.body.messages))).toContain('STEERING_DIRECTIVE_CONTRACT')
    expect((await snapshot()).queued).toEqual([])
  })

  test('request-bound stop and stale controls never retarget a successor; resume answers honestly', async () => {
    const { broker, events, conversation, send, settled } = await setup()
    const active = await send('[hold-stop] wait for stop')
    await waitFor(() => core.provider!.requests.length === 1, 'held stop generation')
    const params = { control_command_id: randomUUID(), conversation_id: conversation.id, request_id: active.request_id, generation: 1 }
    const stopped = await broker.request('control.stop', params, randomUUID())
    expect(successful(stopped)).toMatchObject({ disposition: 'requested' })
    expect(await broker.request('control.stop', params, randomUUID())).toEqual(stopped)
    await waitFor(() => events.some((event) => ['request.cancelled', 'request.suspended'].includes(event.type) && event.payload.request_id === active.request_id), 'stopped generation settled')
    expect(events.some((event) => event.type === 'control.receipt' && event.payload.control_command_id === params.control_command_id)).toBe(true)
    expect(successful(await broker.request('control.stop', { ...params, control_command_id: randomUUID(), generation: 99 }, randomUUID()))).toMatchObject({ disposition: 'stale_binding' })
    const resumed = await broker.request('control.resume', { ...params, control_command_id: randomUUID() }, randomUUID())
    expect(successful(resumed)).toMatchObject({ disposition: 'rejected', reason: 'not_resumable' })
    await settled(await send('[reply] successor after stop'))
  })

  test('restart interrupted checkpoint resumes the same request on a new generation, not a new submission', async () => {
    const { broker, conversation, send, snapshot } = await setup()
    const active = await send('[hold-stop] preserve resumable checkpoint')
    await waitFor(() => core.provider!.requests.length === 1, 'checkpoint generation HTTP request')
    expect((await snapshot()).messages.items.filter((message) => message.role === 'assistant')).toEqual([])
    // The isolated core loses its process-local worker while retaining the real
    // durable generation checkpoint. No test-made ledger rows or fake decoder.
    core.child.kill('SIGKILL')
    await core.waitExit()
    broker.close()
    core.provider!.release('[hold-stop]')
    await core.start()
    const restarted = (await core.connect()).broker
    const events: CoreEvent[] = []
    restarted.on('event', (event: CoreEvent) => events.push(event))
    successful(await restarted.subscribe())
    const params = { control_command_id: randomUUID(), conversation_id: conversation.id,
      request_id: active.request_id, generation: 1 }
    const admitted = await restarted.request('control.resume', params, randomUUID())
    expect(successful(admitted)).toMatchObject({ disposition: 'admitted' })
    expect(await restarted.request('control.resume', params, randomUUID())).toEqual(admitted)
    await waitFor(() => events.some((event) => event.type === 'request.completed' && event.payload.request_id === active.request_id), 'resumed completion')
    const snap = successful<Snapshot>(await restarted.request('conversation.snapshot', { conversation_id: conversation.id }))
    expect(snap.recent).toContainEqual(expect.objectContaining({ request_id: active.request_id, generation: 2, outcome: 'completed' }))
    expect(snap.messages.items.filter((message) => message.role === 'user').map((message) => message.id)).toEqual([active.message_id])
    await waitFor(() => events.some((event) => event.type === 'message.committed' && (event.payload.message as Message | undefined)?.text === REPLY), 'resumed guarded reply')
  })
})
