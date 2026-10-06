// Running work, tool details and guarded resume against the fixture core, over the real broker.
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import type { CoreEvent, ToolDetail, WorkItem } from '../src/shared/api'
import { Broker } from '../src/main/broker'
import { startFixture, waitFor } from './fixture-harness'

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

type Ok<T> = { ok: true; result: T }

async function connect() {
  const core = await startFixture()
  cleanups.push(() => core.stop())
  const broker = new Broker({
    socketPath: core.paths.socketPath,
    readToken: () => readFileSync(core.paths.tokenPath, 'utf8').trim(),
    profileId: 'default',
    clientVersion: 'test',
    reconnectDelaysMs: [50]
  })
  const events: CoreEvent[] = []
  broker.on('event', (e: CoreEvent) => events.push(e))
  broker.connect()
  cleanups.push(() => broker.close())
  await waitFor(() => broker.linkState === 'ready')
  await broker.subscribe()
  const created = (await broker.request('conversations.create', {})) as Ok<{ conversation: { id: string } }>
  const conversationId = created.result.conversation.id
  /** Sends a message and waits until its request settles; returns the request's id. */
  const send = async (text: string): Promise<string> => {
    const sub = crypto.randomUUID()
    const sent = (await broker.request('submission.send', { client_submission_id: sub, conversation_id: conversationId, text }, sub)) as Ok<{
      request_id: string
    }>
    const id = sent.result.request_id
    await waitFor(() => events.some((e) => e.type.startsWith('request.') && e.type !== 'request.started' && e.type !== 'request.queued' && e.payload.request_id === id))
    return id
  }
  const list = async (): Promise<WorkItem[]> => ((await broker.request('work.list', {})) as Ok<{ items: WorkItem[] }>).result.items
  const control = (kind: string, id: string, action: string, commandId = crypto.randomUUID()) =>
    broker.request('work.control', { control_command_id: commandId, kind, id, action }, commandId)
  return { broker, events, conversationId, send, list, control }
}

describe('running work', () => {
  it('keeps structured steering queued, preserves exact binding, and exposes unknown release honestly', async () => {
    const { broker, events, send, list, control } = await connect()
    await send('start a structured agent')
    const agent = (await list()).find((i) => i.kind === 'agent')!
    expect(agent).toMatchObject({ actions: ['cancel', 'steer'], detail: { inbox_sequence: 0, last_consumed_sequence: 0 }, settlement: { state: 'pending', resource_release: 'unproven' } })
    const commandId = crypto.randomUUID()
    const params = { control_command_id: commandId, kind: agent.kind, id: agent.id, action: 'steer', text: 'Keep original scope',
      manager_generation: agent.manager_generation, run_id: agent.run_id, generation: agent.generation, conversation_id: agent.conversation_id }
    expect(await broker.request('work.control', params, commandId)).toMatchObject({ ok: true, result: { disposition: 'queued', consumed: false, sequence: 1 } })
    expect(await broker.request('work.control', params, commandId)).toMatchObject({ ok: true, result: { disposition: 'queued', consumed: false, sequence: 1 } })
    expect((await list()).find((i) => i.id === agent.id)).toMatchObject({ detail: { inbox_sequence: 1, last_consumed_sequence: 0 } })
    expect(await control('agent', agent.id, 'cancel')).toMatchObject({ ok: true, result: { disposition: 'requested' } })
    await waitFor(() => events.some((e) => e.type === 'work.updated' && e.payload.id === agent.id && e.payload.state === 'stopped'))
    expect((await list()).find((i) => i.id === agent.id)).toMatchObject({ settlement: { state: 'unknown', resource_release: 'unknown' } })
  })

  it('lists work with the controls Odin offers now, stops an agent, and stops offering what no longer applies', async () => {
    const { events, send, list, control } = await connect()
    await send('start an agent')
    const agent = (await list()).find((i) => i.kind === 'agent')!
    expect(agent).toMatchObject({ title: 'Research agent', state: 'running', actions: ['stop'], conversation_id: expect.any(String) })
    expect(await control('agent', agent.id, 'stop')).toEqual({ ok: true, result: { disposition: 'requested' } })
    await waitFor(() => events.some((e) => e.type === 'work.updated' && e.payload.id === agent.id && e.payload.state === 'stopped'))
    expect((await list()).find((i) => i.id === agent.id)).toMatchObject({ state: 'stopped', actions: [] })
    expect(await control('agent', agent.id, 'stop')).toEqual({ ok: true, result: { disposition: 'not_available' } })
  })

  it('pauses and resumes a schedule, and answers a repeated command id with its original answer', async () => {
    const { list, control } = await connect()
    const schedule = (await list()).find((i) => i.kind === 'schedule')!
    expect(schedule.actions).toEqual(['pause', 'run_now'])
    const id = crypto.randomUUID()
    expect(await control('schedule', schedule.id, 'pause', id)).toEqual({ ok: true, result: { disposition: 'done' } })
    expect((await list()).find((i) => i.id === schedule.id)).toMatchObject({ state: 'paused', actions: ['resume', 'run_now'] })
    expect(await control('schedule', schedule.id, 'pause', id)).toEqual({ ok: true, result: { disposition: 'done' } })
    expect(await control('schedule', schedule.id, 'resume', id)).toMatchObject({ ok: false, error: { code: 'id_conflict' } })
    expect(await control('schedule', schedule.id, 'resume')).toEqual({ ok: true, result: { disposition: 'done' } })
    expect((await list()).find((i) => i.id === schedule.id)!.state).toBe('active')
  })
})

describe('tool details', () => {
  async function toolCall(text: string) {
    const session = await connect()
    const requestId = await session.send(text)
    const started = session.events.find((e) => e.type === 'tool.started' && e.payload.request_id === requestId)!
    const invocationId = String(started.payload.invocation_id)
    const detail = (await session.broker.request('tool.detail', { request_id: requestId, invocation_id: invocationId })) as Ok<ToolDetail>
    return { ...session, requestId, invocationId, detail: detail.result }
  }

  it('shows scrubbed arguments and labeled previews, and pages retained output without re-running the tool', async () => {
    const { broker, events, detail, requestId } = await toolCall('show the output, password=hunter2')
    expect(detail.arguments).toEqual({ text: 'show the output, password=•••' })
    expect(detail.previews[0]).toMatchObject({ label: 'Output, first 5 lines', truncated: true })
    let cursor = detail.output.cursor
    let text = ''
    let pages = 0
    while (cursor) {
      const page = (await broker.request('tool.output', { cursor, limit: 10_000 })) as Ok<{ text: string; next_cursor?: string; eof: boolean }>
      text += page.result.text
      pages += 1
      cursor = page.result.eof ? undefined : page.result.next_cursor
    }
    expect(pages).toBeGreaterThan(1)
    expect(text.split('\n')).toHaveLength(2000)
    expect(text.split('\n')[1999]).toBe('build step 2000: ok')
    const ran = events.filter((e) => e.type === 'tool.started' && e.payload.request_id === requestId)
    expect(ran).toHaveLength(1)
  })

  it('says when retained output is no longer kept, and refuses a tool call from another request', async () => {
    const { broker, detail, invocationId } = await toolCall('output that will expire')
    expect(await broker.request('tool.output', { cursor: detail.output.cursor, limit: 100 })).toMatchObject({
      ok: false,
      error: { code: 'expired' }
    })
    expect(await broker.request('tool.detail', { request_id: 'r_other', invocation_id: invocationId })).toMatchObject({
      ok: false,
      error: { code: 'not_found' }
    })
  })
})

describe('guarded resume', () => {
  const resume = (broker: Broker, conversationId: string, requestId: string, generation: number) => {
    const id = crypto.randomUUID()
    return broker.request('control.resume', { control_command_id: id, conversation_id: conversationId, request_id: requestId, generation }, id)
  }

  it('carries an interrupted request on as the same request with a new generation, exactly once', async () => {
    const { broker, events, conversationId, send } = await connect()
    const requestId = await send('please interrupt this one')
    expect(events.find((e) => e.type === 'request.interrupted' && e.payload.request_id === requestId)!.payload.unknown_effects).toBe(0)
    expect(await resume(broker, conversationId, requestId, 1)).toEqual({ ok: true, result: { disposition: 'admitted' } })
    await waitFor(() => events.some((e) => e.type === 'request.completed' && e.payload.request_id === requestId))
    expect(events.find((e) => e.type === 'request.started' && e.payload.request_id === requestId && e.payload.generation === 2)).toBeTruthy()
    expect(await resume(broker, conversationId, requestId, 1)).toMatchObject({ ok: false, error: { code: 'stale_binding' } })
    expect(await resume(broker, conversationId, requestId, 2)).toMatchObject({ ok: true, result: { disposition: 'rejected' } })
  })

  it('refuses while effects are unknown, and while other work runs in the conversation', async () => {
    const { broker, events, conversationId, send } = await connect()
    const unknown = await send('an unknown outcome')
    const ended = events.find((e) => e.type === 'request.interrupted' && e.payload.request_id === unknown)!
    expect(ended.payload.unknown_effects).toBe(1)
    const refused = (await resume(broker, conversationId, unknown, 1)) as Ok<{ disposition: string; reason: string }>
    expect(refused.result).toEqual({ disposition: 'rejected', reason: expect.stringMatching(/couldn't confirm/) })
    const snapshot = (await broker.request('conversation.snapshot', { conversation_id: conversationId })) as Ok<{
      unresolved: Array<{ request_id: string }>
    }>
    expect(snapshot.result.unresolved.map((o) => o.request_id)).toEqual([unknown])

    const interrupted = await send('interrupt')
    const sub = crypto.randomUUID()
    await broker.request('submission.send', { client_submission_id: sub, conversation_id: conversationId, text: 'slow work' }, sub)
    await waitFor(() => events.some((e) => e.type === 'request.started' && e.payload.request_id !== unknown && e.payload.request_id !== interrupted))
    const busy = (await resume(broker, conversationId, interrupted, 1)) as Ok<{ disposition: string; reason: string }>
    expect(busy.result).toEqual({ disposition: 'rejected', reason: expect.stringMatching(/working in this conversation/) })
  })
})

describe('usage', () => {
  it('tags every number, and never invents one it does not know', async () => {
    const { broker, send } = await connect()
    await send('hello there')
    const usage = (await broker.request('usage.get', { period: '24h' })) as Ok<{
      tokens: { value: number | null; kind: string }
      context: { used: { kind: string }; budget: { value: number; kind: string } }
      quota: Array<{ used_percent: { value: number | null; kind: string } }>
    }>
    expect(usage.result.tokens.kind).toBe('estimated')
    expect(usage.result.context.budget).toEqual({ value: 272000, kind: 'measured' })
    expect(usage.result.quota[0]!.used_percent).toEqual({ value: null, kind: 'unknown' })
  })
})
