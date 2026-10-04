import { createServer, type Server, type Socket } from 'node:net'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import type { CoreEvent } from '../src/shared/api'
import { Broker } from '../src/main/broker'
import { FrameDecoder, encodeFrame } from '../src/main/framing'
import { startFixture, waitFor, type FixtureCore } from './fixture-harness'

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

async function connectedBroker(core: FixtureCore, overrides: Partial<ConstructorParameters<typeof Broker>[0]> = {}) {
  const broker = new Broker({
    socketPath: core.paths.socketPath,
    readToken: () => readFileSync(core.paths.tokenPath, 'utf8').trim(),
    profileId: 'default',
    clientVersion: 'test',
    reconnectDelaysMs: [50],
    ...overrides
  })
  const events: CoreEvent[] = []
  broker.on('event', (e: CoreEvent) => events.push(e))
  broker.connect()
  cleanups.push(() => broker.close())
  await waitFor(() => broker.linkState === 'ready')
  await broker.subscribe()
  return { broker, events }
}

async function withFixture(): Promise<FixtureCore> {
  const core = await startFixture()
  cleanups.push(() => core.stop())
  return core
}

function uuid(): string {
  return crypto.randomUUID()
}

describe('broker against the fixture core', () => {
  it('handshakes, submits, and receives committed messages and tool activity', async () => {
    const core = await withFixture()
    const { broker, events } = await connectedBroker(core)
    const status = await broker.request('status.get')
    expect(status).toMatchObject({ ok: true, result: { phase: 'ready' } })

    const created = await broker.request('conversations.create', { title: 'T' })
    expect(created.ok).toBe(true)
    const cid = (created as { result: { conversation: { id: string } } }).result.conversation.id
    const sub = uuid()
    const sent = await broker.request('submission.send', { client_submission_id: sub, conversation_id: cid, text: 'hi' }, sub)
    expect(sent).toMatchObject({ ok: true, result: { disposition: 'accepted' } })

    await waitFor(() => events.some((e) => e.type === 'request.completed'))
    const types = events.map((e) => e.type)
    expect(types).toEqual(expect.arrayContaining(['message.committed', 'request.started', 'tool.started', 'tool.settled', 'request.completed']))
    const user = events.find((e) => e.type === 'message.committed' && (e.payload.message as { role: string }).role === 'user')
    expect((user?.payload.message as { client_submission_id?: string }).client_submission_id).toBe(sub)
    const reply = events.find((e) => e.type === 'message.committed' && (e.payload.message as { role: string }).role === 'assistant')
    expect((reply?.payload.message as { text: string }).text).toBe('Echo: hi')
  })

  it('admits a submission once, however many times the same ID is sent', async () => {
    const core = await withFixture()
    const { broker, events } = await connectedBroker(core)
    const created = (await broker.request('conversations.create', {})) as { ok: true; result: { conversation: { id: string } } }
    const cid = created.result.conversation.id
    const sub = uuid()
    const first = await broker.request('submission.send', { client_submission_id: sub, conversation_id: cid, text: 'once' }, sub)
    const again = await broker.request('submission.send', { client_submission_id: sub, conversation_id: cid, text: 'once' }, uuid())
    expect(first).toEqual(again)
    await waitFor(() => events.some((e) => e.type === 'request.completed'))
    const userMessages = events.filter((e) => e.type === 'message.committed' && (e.payload.message as { role: string }).role === 'user')
    expect(userMessages).toHaveLength(1)
  })

  it('stops the exact running task and reports requested, then confirmed', async () => {
    const core = await withFixture()
    const { broker, events } = await connectedBroker(core)
    const cid = ((await broker.request('conversations.create', {})) as { ok: true; result: { conversation: { id: string } } }).result.conversation.id
    const sub = uuid()
    const sent = (await broker.request('submission.send', { client_submission_id: sub, conversation_id: cid, text: 'slow task' }, sub)) as {
      ok: true
      result: { request_id: string }
    }
    await waitFor(() => events.some((e) => e.type === 'request.started'))
    const stale = await broker.request('control.stop', { control_command_id: uuid(), conversation_id: cid, request_id: sent.result.request_id, generation: 99 })
    expect(stale).toMatchObject({ ok: false, error: { code: 'stale_binding' } })
    const command = uuid()
    const stop = await broker.request('control.stop', { control_command_id: command, conversation_id: cid, request_id: sent.result.request_id, generation: 1 }, command)
    expect(stop).toMatchObject({ ok: true, result: { disposition: 'requested' } })
    await waitFor(() => events.some((e) => e.type === 'request.cancelled'))
    const receipt = events.find((e) => e.type === 'control.receipt' && e.payload.control_command_id === command)
    expect(receipt?.payload).toMatchObject({ kind: 'stop', disposition: 'confirmed' })
  })

  it('queues a steer into the running task and reports when it was consumed', async () => {
    const core = await withFixture()
    const { broker, events } = await connectedBroker(core)
    const cid = ((await broker.request('conversations.create', {})) as { ok: true; result: { conversation: { id: string } } }).result.conversation.id
    const sub = uuid()
    const sent = (await broker.request('submission.send', { client_submission_id: sub, conversation_id: cid, text: 'slow work' }, sub)) as {
      ok: true
      result: { request_id: string }
    }
    await waitFor(() => events.some((e) => e.type === 'request.started'))
    const command = uuid()
    const steer = await broker.request('control.steer', { control_command_id: command, conversation_id: cid, request_id: sent.result.request_id, generation: 1, text: 'use the other host' }, command)
    expect(steer).toMatchObject({ ok: true, result: { disposition: 'queued' } })
    await waitFor(() => events.some((e) => e.type === 'control.receipt' && e.payload.control_command_id === command))
    const stop = uuid()
    await broker.request('control.stop', { control_command_id: stop, conversation_id: cid, request_id: sent.result.request_id, generation: 1 }, stop)
    const receipt = events.find((e) => e.type === 'control.receipt' && e.payload.control_command_id === command)
    expect(receipt?.payload).toMatchObject({ kind: 'steer', disposition: 'consumed' })
  })

  it('catches up after a dropped connection without duplicating events', async () => {
    const core = await withFixture()
    const { broker, events } = await connectedBroker(core)
    const cid = ((await broker.request('conversations.create', {})) as { ok: true; result: { conversation: { id: string } } }).result.conversation.id
    const sub = uuid()
    await broker.request('submission.send', { client_submission_id: sub, conversation_id: cid, text: 'slow drop test' }, sub)
    await waitFor(() => events.some((e) => e.type === 'tool.settled'))
    ;(broker as unknown as { socket: Socket }).socket.destroy()
    await waitFor(() => broker.linkState === 'reconnecting')
    await waitFor(() => broker.linkState === 'ready')
    const stop = uuid()
    const started = events.find((e) => e.type === 'request.started')!
    await broker.request('control.stop', { control_command_id: stop, conversation_id: cid, request_id: String(started.payload.request_id), generation: 1 }, stop)
    await waitFor(() => events.some((e) => e.type === 'request.cancelled'))
    const seqs = events.map((e) => e.seq)
    expect(new Set(seqs).size).toBe(seqs.length)
    expect([...seqs].sort((a, b) => a - b)).toEqual(seqs)
    // Every event from the first to the last arrived, including those emitted while disconnected.
    const first = seqs[0]!
    const last = seqs[seqs.length - 1]!
    expect(seqs).toHaveLength(last - first + 1)
  })

  it('refuses a client with the wrong token', async () => {
    const core = await withFixture()
    const broker = new Broker({
      socketPath: core.paths.socketPath,
      readToken: () => '0'.repeat(64),
      profileId: 'default',
      clientVersion: 'test',
      reconnectDelaysMs: [5_000]
    })
    const byes: string[] = []
    broker.on('bye', (reason: string) => byes.push(reason))
    broker.connect()
    cleanups.push(() => broker.close())
    await waitFor(() => byes.length > 0)
    expect(byes[0]).toBe('unauthorized')
    expect(broker.linkState).not.toBe('ready')
  })

  it('shuts down when the app’s end of the parent-link pipe closes', async () => {
    const core = await withFixture()
    const exited = new Promise<number | null>((r) => core.child.once('exit', (code) => r(code)))
    core.child.stdin?.end()
    expect(await exited).toBe(0)
  })
})

describe('broker receipts', () => {
  it('re-sends an unanswered command with the same ID after reconnecting, and surfaces the late receipt', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'odin-fake-core-'))
    const socketPath = join(dir, 'core.sock')
    const seenIds: string[] = []
    let connection = 0
    const server: Server = createServer((socket) => {
      connection += 1
      const mine = connection
      const decoder = new FrameDecoder()
      socket.on('data', (chunk) => {
        for (const frame of decoder.push(chunk)) {
          if (frame.t === 'hello') {
            socket.write(encodeFrame({ t: 'welcome', protocol: { major: 0, minor: 1 }, core: { instance_id: 'fake', version: '0' }, profile_id: 'default', capabilities: [], features: [], max_frame: 4194304, event_high: '0' }))
          } else if (frame.t === 'req') {
            seenIds.push(String(frame.id))
            // First connection: swallow the command (the receipt is "lost") and drop the link.
            if (mine === 1) setTimeout(() => socket.destroy(), 150)
            else socket.write(encodeFrame({ t: 'res', id: frame.id, ok: true, result: { disposition: 'accepted' } }))
          }
        }
      })
    })
    await new Promise<void>((r) => server.listen(socketPath, () => r()))
    cleanups.push(() => {
      server.close()
      rmSync(dir, { recursive: true, force: true })
    })

    const broker = new Broker({ socketPath, readToken: () => 'x'.repeat(64), profileId: 'default', clientVersion: 'test', requestTimeoutMs: 100, reconnectDelaysMs: [50] })
    const receipts: Array<{ id: string }> = []
    broker.on('receipt', (r: { id: string }) => receipts.push(r))
    broker.connect()
    cleanups.push(() => broker.close())
    await waitFor(() => broker.linkState === 'ready')

    const id = crypto.randomUUID()
    const first = await broker.request('submission.send', { client_submission_id: id }, id)
    expect(first).toMatchObject({ ok: false, error: { code: 'no_receipt', disposition: 'outcome_unknown' } })
    expect(broker.unreceiptedCount).toBe(1)

    await waitFor(() => receipts.length === 1, 5_000)
    expect(receipts[0]!.id).toBe(id)
    expect(seenIds).toEqual([id, id])
    expect(broker.unreceiptedCount).toBe(0)
  })
})
