// Exit's shutdown request behind requests the core is still answering. The core serves each connection's requests in
// order, so a shutdown request sent while earlier ones are being answered waits behind them; its own bound must not
// run out while they are (the Windows installer acceptance hit this right after a hidden start).
import { mkdtempSync, rmSync } from 'node:fs'
import { createServer, type Server, type Socket } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { Broker } from '../src/main/broker'
import { FrameDecoder, encodeFrame } from '../src/main/framing'
import { boundedShutdown, shutdownTurn, stopKeepingReceipts } from '../src/main/shutdown'
import { waitFor } from './fixture-harness'

const cleanups: Array<() => void> = []
afterEach(() => { for (const cleanup of cleanups.splice(0).reverse()) cleanup() })

/** A core that answers one request at a time, each after `answerMs` (or its own entry in `slow`), and never answers
 * `stuck` methods. */
async function orderedCore(answerMs: number, stuck: string[] = [], slow: Record<string, number> = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'odin-ordered-core-'))
  const socketPath = join(dir, 'core.sock')
  const received: string[] = []
  const sockets: Socket[] = []
  const server: Server = createServer((socket) => {
    sockets.push(socket)
    const decoder = new FrameDecoder()
    const queue: Record<string, unknown>[] = []
    let busy = false
    const next = (): void => {
      const frame = queue.shift()
      if (!frame || busy) { if (frame) queue.unshift(frame); return }
      busy = true
      if (stuck.includes(String(frame.method))) return // the connection's later requests wait forever
      setTimeout(() => {
        socket.write(encodeFrame({ t: 'res', id: frame.id, ok: true, result: { disposition: 'accepted' } }))
        busy = false
        next()
      }, slow[String(frame.method)] ?? answerMs)
    }
    socket.on('data', (chunk) => {
      for (const frame of decoder.push(chunk)) {
        if (frame.t === 'hello') {
          socket.write(encodeFrame({ t: 'welcome', protocol: { major: 0, minor: 3 }, core: { instance_id: 'ordered', version: '0' },
            profile_id: 'default', capabilities: [], features: [], max_frame: 4194304, event_high: '0' }))
        } else if (frame.t === 'req') {
          received.push(String(frame.method))
          queue.push(frame)
          next()
        }
      }
    })
  })
  await new Promise<void>((resolve) => server.listen(socketPath, () => resolve()))
  cleanups.push(() => {
    for (const socket of sockets) socket.destroy()
    server.close()
    rmSync(dir, { recursive: true, force: true })
  })
  return { socketPath, received }
}

async function ready(socketPath: string, requestTimeoutMs?: number): Promise<Broker> {
  const broker = new Broker({ socketPath, readToken: () => 'x'.repeat(64), profileId: 'default', clientVersion: 'test',
    sealed: false, reconnectDelaysMs: [50], ...(requestTimeoutMs ? { requestTimeoutMs } : {}) })
  cleanups.push(() => broker.close())
  broker.connect()
  await waitFor(() => broker.linkState === 'ready')
  return broker
}

/** Exit with the app's own steps; `stopMs` is how long the core takes to exit once it is told to stop. */
function exit(broker: Broker, requestTimeoutMs: number, turnMs: number, stopMs = 0) {
  return boundedShutdown({
    stopAdmission: () => broker.quiesce(), persist: () => undefined,
    readyForShutdown: () => shutdownTurn(broker, turnMs),
    requestShutdown: async () => (await broker.request('runtime.shutdown', { reason: 'exit' })).ok,
    stopCore: () => stopKeepingReceipts(async () => {
      await new Promise((resolve) => setTimeout(resolve, stopMs))
      return 'exited'
    }, broker),
    unreceipted: () => broker.unreceiptedCount,
    finish: () => undefined, release: () => undefined, exit: () => undefined, requestTimeoutMs
  })()
}

describe('Exit behind requests the core is still answering', () => {
  it('is accepted, with every receipt, while receipts keep coming past every bound', async () => {
    const core = await orderedCore(150)
    const broker = await ready(core.socketPath)
    const earlier = ['status.get', 'usage.get', 'work.list'].map((method) => broker.request(method))
    // 450 ms of answers: past the turn's 200 ms quiet bound (a receipt every 150 ms renews it) and the shutdown
    // request's 300 ms bound, which starts once they have settled.
    const record = await exit(broker, 300, 200)
    expect(record).toMatchObject({ state: 'process-exited', shutdownAccepted: true, unreceipted: 0 })
    expect((await Promise.all(earlier)).every((settled) => settled.ok)).toBe(true)
    expect(core.received).toEqual(['status.get', 'usage.get', 'work.list', 'runtime.shutdown'])
  })

  it('sends no shutdown request to a core that answers nothing for the bound', async () => {
    const core = await orderedCore(20, ['hosts.test'])
    const broker = await ready(core.socketPath)
    const began = Date.now()
    const earlier = broker.request('hosts.test')
    const record = await exit(broker, 300, 200)
    // Not its 30 s receipt deadline: the turn ends after 200 ms without a receipt, and the close settles it.
    expect(Date.now() - began).toBeLessThan(2_000)
    expect(await earlier).toMatchObject({ ok: false, error: { code: 'no_receipt' } })
    expect(record).toMatchObject({ state: 'unknown', shutdownAccepted: false, unreceipted: 1 })
    expect(core.received).toEqual(['hosts.test'])
  })

  it('counts a shutdown receipt that comes after its bound, while the core is stopped', async () => {
    // The core takes 400 ms to accept (a stalled loop, as timed on a loaded Windows runner), past the 200 ms bound,
    // and 600 ms to exit: the receipt lands on the connection still open, so the Exit is clean.
    const core = await orderedCore(20, [], { 'runtime.shutdown': 400 })
    const broker = await ready(core.socketPath)
    const record = await exit(broker, 200, 200, 600)
    expect(record).toMatchObject({ state: 'process-exited', shutdownAccepted: true, unreceipted: 0 })
    expect(core.received).toEqual(['runtime.shutdown'])
  })

  it('stays unknown when no receipt comes before the core has exited', async () => {
    const core = await orderedCore(20, ['runtime.shutdown'])
    const broker = await ready(core.socketPath)
    const record = await exit(broker, 200, 200, 100)
    expect(record).toMatchObject({ state: 'unknown', shutdownAccepted: false, unreceipted: 1 })
  })

  it('treats an aged request reaching its own receipt deadline as no answer: no shutdown request', async () => {
    // Exit 200 ms into a request whose 300 ms receipt deadline then passes: the local timeout is not the core answering.
    // The turn ends there, with neither a renewed quiet bound nor readiness, and no request goes behind it.
    const core = await orderedCore(20, ['hosts.test'])
    const broker = await ready(core.socketPath, 300)
    const earlier = broker.request('hosts.test')
    await new Promise((resolve) => setTimeout(resolve, 200))
    const began = Date.now()
    const record = await exit(broker, 300, 1_000)
    expect(Date.now() - began).toBeLessThan(800)
    expect(await earlier).toMatchObject({ ok: false, error: { code: 'no_receipt' } })
    expect(record).toMatchObject({ state: 'unknown', shutdownAccepted: false, unreceipted: 1 })
    expect(core.received).toEqual(['hosts.test'])
  })

  it('does not wait on for the requests queued behind one that went unanswered', async () => {
    // Two requests behind a stuck one: the first's receipt deadline ends the turn; the core would answer the others,
    // and a shutdown request, only after it.
    const core = await orderedCore(20, ['webhooks.outbound.test'])
    const broker = await ready(core.socketPath, 300)
    const earlier = [broker.request('webhooks.outbound.test'), broker.request('status.get')]
    await new Promise((resolve) => setTimeout(resolve, 200))
    const began = Date.now()
    const record = await exit(broker, 300, 1_000)
    expect(Date.now() - began).toBeLessThan(800)
    expect(record).toMatchObject({ state: 'unknown', shutdownAccepted: false })
    expect(core.received).toEqual(['webhooks.outbound.test', 'status.get'])
    await Promise.all(earlier)
  })

  it('answers at once with nothing in flight; a lost connection ends both waits, as no answer', async () => {
    const core = await orderedCore(10_000)
    const broker = await ready(core.socketPath)
    expect(await broker.requestsAnswered(5_000)).toBe(true)
    await broker.drained(5_000)
    const earlier = broker.request('status.get')
    const turn = broker.requestsAnswered(5_000)
    const drained = broker.drained(5_000)
    broker.close()
    expect(await turn).toBe(false)
    await drained
    expect(await earlier).toMatchObject({ ok: false, error: { code: 'no_receipt' } })
    expect(broker.listenerCount('answered') + broker.listenerCount('unanswered')).toBe(0)
  })
})
