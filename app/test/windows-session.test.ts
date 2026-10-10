import { createServer, type Server, type Socket } from 'node:net'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { Broker } from '../src/main/broker'
import { FrameDecoder, ProtocolError, encodeFrame } from '../src/main/framing'
import {
  CLIENT_TO_SERVER,
  ClientSession,
  SEAL_OVERHEAD,
  SERVER_TO_CLIENT,
  SealedDecoder,
  SealedDirection,
  SessionRefused,
  proofMatches,
  sessionKeys,
  sessionProof,
  sessionTranscript,
  type TranscriptFields
} from '../src/main/windows-session'
import { waitFor } from './fixture-harness'

// The engine's own vectors (tests/fixtures), so both implementations agree byte for byte.
const vectors = JSON.parse(readFileSync(join(__dirname, '../../tests/fixtures/windows-session-vectors.json'), 'utf8'))

function vectorFields(overrides: Partial<TranscriptFields> = {}): TranscriptFields {
  const f = vectors.fields
  return {
    offered: f.offered,
    selected: f.selected,
    client: f.client,
    profileId: f.profile_id,
    endpoint: f.endpoint,
    clientNonce: Buffer.from(vectors.client_nonce, 'hex'),
    serverNonce: Buffer.from(vectors.server_nonce, 'hex'),
    instanceId: f.instance_id,
    maxFrame: f.max_frame,
    features: f.features,
    ...overrides
  }
}

function vectorKeys() {
  const transcript = sessionTranscript(vectorFields())
  return { transcript, keys: sessionKeys(vectors.token, vectorFields().clientNonce, vectorFields().serverNonce, transcript) }
}

describe('the sealed session matches the engine', () => {
  it('derives the same transcript, keys and proofs', () => {
    const { transcript, keys } = vectorKeys()
    expect(transcript.toString('hex')).toBe(vectors.transcript)
    expect(keys.proof.toString('hex')).toBe(vectors.keys.proof)
    expect(keys.c2s.toString('hex')).toBe(vectors.keys.c2s)
    expect(keys.s2c.toString('hex')).toBe(vectors.keys.s2c)
    expect(sessionProof(keys, 'server', transcript).toString('hex')).toBe(vectors.server_proof)
    expect(sessionProof(keys, 'client', transcript).toString('hex')).toBe(vectors.client_proof)
  })

  it('seals and opens the same frames in both directions', () => {
    const { keys } = vectorKeys()
    for (const [key, direction, frames] of [
      [keys.c2s, CLIENT_TO_SERVER, vectors.client_to_server],
      [keys.s2c, SERVER_TO_CLIENT, vectors.server_to_client]
    ] as const) {
      const sealer = new SealedDirection(key, direction)
      for (const frame of frames) {
        expect(sealer.seal(Buffer.from(frame.payload, 'utf8')).toString('hex')).toBe(frame.sealed)
      }
      const decoder = new SealedDecoder(new SealedDirection(key, direction))
      const opened = decoder.push(Buffer.concat(frames.map((frame: { sealed: string }) => Buffer.from(frame.sealed, 'hex'))))
      expect(opened).toEqual(frames.map((frame: { payload: string }) => JSON.parse(frame.payload)))
    }
  })
})

describe('the sealed session refuses', () => {
  const sealedFrames = (direction = CLIENT_TO_SERVER) =>
    (direction === CLIENT_TO_SERVER ? vectors.client_to_server : vectors.server_to_client).map(
      (frame: { sealed: string }) => Buffer.from(frame.sealed, 'hex')
    )

  it('tampered ciphertext, tags and counters', () => {
    const { keys } = vectorKeys()
    const [first] = sealedFrames()
    const tampered = Buffer.from(first)
    tampered[20] = tampered[20]! ^ 1
    expect(() => new SealedDecoder(new SealedDirection(keys.c2s, CLIENT_TO_SERVER)).push(tampered)).toThrow(
      'sealed frame rejected'
    )
    const [, second] = sealedFrames()
    expect(() => new SealedDecoder(new SealedDirection(keys.c2s, CLIENT_TO_SERVER)).push(second)).toThrow(
      'sealed frame out of order'
    )
    // The direction is part of the nonce: a frame reflected back is not accepted.
    expect(() => new SealedDecoder(new SealedDirection(keys.c2s, SERVER_TO_CLIENT)).push(first)).toThrow(
      'sealed frame rejected'
    )
  })

  it('a frame replayed into a fresh session', () => {
    const [first] = sealedFrames()
    const other = sessionKeys(vectors.token, randomBytes(32), randomBytes(32), randomBytes(32))
    expect(() => new SealedDecoder(new SealedDirection(other.c2s, CLIENT_TO_SERVER)).push(first)).toThrow(
      'sealed frame rejected'
    )
  })

  it('frames shorter than a tag, and declared lengths over the bound before the body arrives', () => {
    const { keys } = vectorKeys()
    const short = Buffer.alloc(4 + SEAL_OVERHEAD - 1)
    short.writeUInt32BE(SEAL_OVERHEAD - 1, 0)
    expect(() => new SealedDecoder(new SealedDirection(keys.c2s, CLIENT_TO_SERVER)).push(short)).toThrow(
      'invalid sealed frame size'
    )
    const huge = Buffer.alloc(4)
    huge.writeUInt32BE(1024 + SEAL_OVERHEAD + 1, 0)
    expect(() => new SealedDecoder(new SealedDirection(keys.c2s, CLIENT_TO_SERVER), 1024).push(huge)).toThrow(
      'invalid sealed frame size'
    )
  })

  it('changed transcript fields and a reflected server proof', () => {
    const { transcript, keys } = vectorKeys()
    const serverProof = sessionProof(keys, 'server', transcript)
    expect(proofMatches(serverProof, vectors.client_proof)).toBe(false)
    for (const change of [{ profileId: 'other' }, { endpoint: '\\\\.\\pipe\\other' }, { offered: { major: 0, minor: 1 } }]) {
      const changed = sessionTranscript(vectorFields(change))
      const changedKeys = sessionKeys(vectors.token, vectorFields().clientNonce, vectorFields().serverNonce, changed)
      expect(proofMatches(sessionProof(changedKeys, 'server', changed), vectors.server_proof)).toBe(false)
    }
    expect(proofMatches(serverProof, 'not hex')).toBe(false)
    expect(() => sessionKeys('short', randomBytes(32), randomBytes(32), transcript)).toThrow(SessionRefused)
  })

  it('a malformed or unexpected challenge', () => {
    const session = () =>
      new ClientSession({
        token: vectors.token, profileId: 'default', endpoint: 'pipe', client: { name: 'c', version: '1' },
        offered: { major: 0, minor: 3 }, features: []
      })
    const challenge = {
      t: 'challenge', server_nonce: 'ab'.repeat(32), protocol: { major: 0, minor: 3 }, max_frame: 4096,
      core: { instance_id: 'core' }, server_proof: '00'.repeat(32)
    }
    expect(() => session().answer({ ...challenge, server_nonce: 'xyz' })).toThrow('invalid session nonce')
    expect(() => session().answer({ ...challenge, extra: true })).toThrow('unexpected handshake frame')
    expect(() => session().answer({ ...challenge, t: 'welcome' })).toThrow('unexpected handshake frame')
    expect(() => session().answer({ ...challenge, protocol: { major: -1, minor: 0 } })).toThrow('invalid protocol version')
    expect(() => session().answer({ ...challenge, max_frame: 0 })).toThrow('invalid max_frame')
    expect(() => session().answer({ ...challenge, core: { instance_id: 1 } })).toThrow('unexpected handshake frame')
    expect(() => session().answer(challenge)).toThrow(SessionRefused)
    const used = session()
    expect(() => used.answer(challenge)).toThrow(SessionRefused)
    expect(() => used.answer(challenge)).toThrow(ProtocolError) // never a second handshake on one connection
  })
})

// --- the broker against a fake sealed core -----------------------------------------------------

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

const TOKEN = 'cd'.repeat(32)

interface FakeOptions {
  token?: string
  plainWelcome?: boolean
  onRequest?: (frame: Record<string, unknown>, connection: number) => Record<string, unknown> | null
}

async function sealedCore(options: FakeOptions = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'odin-sealed-core-'))
  const socketPath = join(dir, 'core.sock')
  const hellos: Record<string, unknown>[] = []
  const raw: Buffer[] = []
  const requests: Array<{ id: string; connection: number }> = []
  const sockets: Socket[] = []
  let connection = 0
  const server: Server = createServer((socket) => {
    connection += 1
    const mine = connection
    sockets.push(socket)
    const plain = new FrameDecoder(4096)
    let transcript: Buffer | null = null
    let keys: ReturnType<typeof sessionKeys> | null = null
    let sender: SealedDirection | null = null
    let receiver: SealedDecoder | null = null
    const sealedWrite = (frame: Record<string, unknown>) => socket.write(sender!.seal(encodeFrame(frame).subarray(4)))
    socket.on('data', (chunk: Buffer) => {
      raw.push(chunk)
      if (receiver) {
        for (const frame of receiver.push(chunk)) {
          if (frame.t !== 'req') continue
          requests.push({ id: String(frame.id), connection: mine })
          const answer = options.onRequest ? options.onRequest(frame, mine) : { t: 'res', id: frame.id, ok: true, result: {} }
          if (answer) sealedWrite(answer)
        }
        return
      }
      for (const frame of plain.push(chunk)) {
        if (frame.t === 'hello') {
          hellos.push(frame)
          if (options.plainWelcome) {
            socket.write(encodeFrame({ t: 'welcome' }))
            continue
          }
          const auth = frame.auth as { client_nonce: string }
          const serverNonce = randomBytes(32)
          const fields: TranscriptFields = {
            offered: frame.protocol as { major: number; minor: number }, selected: { major: 0, minor: 3 },
            client: frame.client as { name: string; version: string }, profileId: String(frame.profile_id),
            endpoint: socketPath, clientNonce: Buffer.from(auth.client_nonce, 'hex'), serverNonce,
            instanceId: `core-${mine}`, maxFrame: 4194304, features: frame.features as string[]
          }
          transcript = sessionTranscript(fields)
          keys = sessionKeys(options.token ?? TOKEN, fields.clientNonce, serverNonce, transcript)
          socket.write(encodeFrame({
            t: 'challenge', server_nonce: serverNonce.toString('hex'), protocol: fields.selected,
            max_frame: fields.maxFrame, core: { instance_id: fields.instanceId },
            server_proof: sessionProof(keys, 'server', transcript).toString('hex')
          }))
        } else if (frame.t === 'proof') {
          if (!proofMatches(sessionProof(keys!, 'client', transcript!), frame.client_proof)) {
            socket.write(encodeFrame({ t: 'bye', reason: 'unauthorized' }))
            socket.destroy()
            return
          }
          sender = new SealedDirection(keys!.s2c, SERVER_TO_CLIENT)
          receiver = new SealedDecoder(new SealedDirection(keys!.c2s, CLIENT_TO_SERVER))
          sealedWrite({
            t: 'welcome', protocol: { major: 0, minor: 3 }, core: { instance_id: `core-${mine}`, version: '0' },
            profile_id: 'default', capabilities: [], features: [], max_frame: 4194304, event_high: '0'
          })
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
  const broker = new Broker({
    socketPath, readToken: () => TOKEN, profileId: 'default', clientVersion: 'test', sealed: true,
    reconnectDelaysMs: [50], requestTimeoutMs: 300
  })
  const errors: string[] = []
  broker.on('protocol-error', (message: string) => errors.push(message))
  cleanups.push(() => broker.close())
  return { broker, hellos, raw, requests, sockets, errors }
}

describe('the broker over a sealed link', () => {
  it('becomes ready only after the sealed welcome and never sends the token', async () => {
    const { broker, hellos, raw } = await sealedCore()
    broker.connect()
    await waitFor(() => broker.linkState === 'ready')
    expect(await broker.request('status.get')).toEqual({ ok: true, result: {} })
    expect(hellos).toHaveLength(1)
    expect(hellos[0]).not.toHaveProperty('token')
    const sent = Buffer.concat(raw)
    expect(sent.includes(Buffer.from(TOKEN))).toBe(false)
    expect(sent.includes(Buffer.from(TOKEN, 'hex'))).toBe(false)
    expect(sent.includes(Buffer.from('status.get'))).toBe(false)
  })

  it('refuses an engine that cannot prove the token, and an early welcome', async () => {
    for (const options of [{ token: 'ef'.repeat(32) }, { plainWelcome: true }]) {
      const { broker, errors } = await sealedCore(options)
      broker.connect()
      await waitFor(() => errors.length > 0)
      expect(broker.linkState).not.toBe('ready')
      expect(errors[0]).toMatch(/engine proof refused|before the session is authenticated/)
      broker.close()
    }
  })

  it('reconnects with fresh nonces and re-sends nothing before the new session authenticates', async () => {
    const answered = new Set<number>()
    const { broker, hellos, requests, sockets } = await sealedCore({
      onRequest: (frame, connection) => {
        if (connection === 1) return null // the first receipt is lost
        answered.add(connection)
        return { t: 'res', id: frame.id, ok: true, result: { connection } }
      }
    })
    const receipts: Array<{ id: string }> = []
    broker.on('receipt', (receipt: { id: string }) => receipts.push(receipt))
    broker.connect()
    await waitFor(() => broker.linkState === 'ready')
    const id = crypto.randomUUID()
    expect(await broker.request('submission.send', {}, id)).toMatchObject({ ok: false, error: { code: 'no_receipt' } })
    sockets[0]!.destroy()
    await waitFor(() => receipts.length === 1, 5_000)
    expect(receipts[0]!.id).toBe(id)
    expect(requests).toEqual([{ id, connection: 1 }, { id, connection: 2 }])
    const nonces = hellos.map((hello) => (hello.auth as { client_nonce: string }).client_nonce)
    expect(new Set(nonces).size).toBe(2)
    expect(answered).toEqual(new Set([2]))
  })
})
