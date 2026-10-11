// The Windows app-to-engine session (docs/design/protocol.md, "Windows: the sealed session").
//
// The same flow as the engine's src/desktop/ipc_auth.py, with Node's built-in crypto. The token never crosses the pipe:
// the engine proves it holds the profile's token first, then the client does, and every later frame in both directions
// is sealed with AES-256-GCM. tests/fixtures/windows-session-vectors.json binds both implementations byte for byte.
import { createCipheriv, createDecipheriv, createHash, createHmac, hkdfSync, randomBytes, timingSafeEqual } from 'node:crypto'
import { DEFAULT_MAX_FRAME, ProtocolError } from './framing'

export const SESSION_LABEL = 'odin-desktop/windows-session/v1'
export const AUTH_VERSION = 1
export const NONCE_BYTES = 32
export const TAG_BYTES = 16
/** The frame counter and the GCM tag. */
export const SEAL_OVERHEAD = 8 + TAG_BYTES
export const PREAUTH_MAX_FRAME = 4096
export const CLIENT_TO_SERVER = 0x01
export const SERVER_TO_CLIENT = 0x02
// Re-handshake well before GCM's limits; a nonce and key pair is never reused.
const FRAME_LIMIT = 2n ** 32n
const BYTE_LIMIT = 2n ** 36n
const HEX64 = /^[0-9a-f]{64}$/

export interface Version {
  major: number
  minor: number
}

export interface TranscriptFields {
  offered: Version
  selected: Version
  client: { name: string; version: string }
  profileId: string
  endpoint: string
  clientNonce: Buffer
  serverNonce: Buffer
  instanceId: string
  maxFrame: number
  features: string[]
}

export interface SessionKeys {
  proof: Buffer
  c2s: Buffer
  s2c: Buffer
}

/** The engine's proof didn't match: it doesn't hold this profile's token. */
export class SessionRefused extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'SessionRefused'
  }
}

function encodeString(value: string): Buffer {
  const data = Buffer.from(value, 'utf8')
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length, 0)
  return Buffer.concat([length, data])
}

function encodeInteger(value: number): Buffer {
  const encoded = Buffer.alloc(8)
  encoded.writeBigUInt64BE(BigInt(value), 0)
  return encoded
}

/** SHA-256 over the handshake's fields in their fixed order. */
export function sessionTranscript(fields: TranscriptFields): Buffer {
  const count = Buffer.alloc(4)
  count.writeUInt32BE(fields.features.length, 0)
  return createHash('sha256')
    .update(
      Buffer.concat([
        encodeString(SESSION_LABEL),
        encodeInteger(AUTH_VERSION),
        encodeInteger(fields.offered.major),
        encodeInteger(fields.offered.minor),
        encodeInteger(fields.selected.major),
        encodeInteger(fields.selected.minor),
        encodeString(fields.client.name),
        encodeString(fields.client.version),
        encodeString(fields.profileId),
        encodeString(fields.endpoint),
        fields.clientNonce,
        fields.serverNonce,
        encodeString(fields.instanceId),
        encodeInteger(fields.maxFrame),
        count,
        ...fields.features.map(encodeString)
      ])
    )
    .digest()
}

/** The proof key and the two directional AEAD keys, from the token's 32 raw bytes. */
export function sessionKeys(token: string, clientNonce: Buffer, serverNonce: Buffer, transcript: Buffer): SessionKeys {
  if (!HEX64.test(token)) throw new SessionRefused('the IPC token is not 64 hex characters')
  const material = Buffer.from(token, 'hex')
  const salt = Buffer.concat([clientNonce, serverNonce])
  const derive = (label: string): Buffer =>
    Buffer.from(hkdfSync('sha256', material, salt, Buffer.concat([Buffer.from(label, 'ascii'), transcript]), 32))
  return { proof: derive('proof'), c2s: derive('c2s'), s2c: derive('s2c') }
}

export function sessionProof(keys: SessionKeys, role: 'server' | 'client', transcript: Buffer): Buffer {
  const label = role === 'server' ? 'server proof v1' : 'client proof v1'
  return createHmac('sha256', keys.proof).update(Buffer.concat([Buffer.from(label, 'ascii'), transcript])).digest()
}

/** Constant-time comparison of a hex proof from the wire. */
export function proofMatches(expected: Buffer, supplied: unknown): boolean {
  return typeof supplied === 'string' && HEX64.test(supplied) && timingSafeEqual(expected, Buffer.from(supplied, 'hex'))
}

/** One direction of a session: its key, its counter and its byte budget. */
export class SealedDirection {
  private counter = 0n
  private sealedBytes = 0n

  constructor(
    private readonly key: Buffer,
    private readonly direction: number
  ) {}

  private nonce(counter: bigint): Buffer {
    const nonce = Buffer.alloc(12)
    nonce.write('ODW', 0, 'ascii')
    nonce[3] = this.direction
    nonce.writeBigUInt64BE(counter, 4)
    return nonce
  }

  private account(size: number): void {
    if (this.counter >= FRAME_LIMIT || this.sealedBytes + BigInt(size) > BYTE_LIMIT) {
      throw new ProtocolError('session key exhausted; reconnect')
    }
  }

  /** L (4 bytes) + counter (8 bytes) + ciphertext and tag; the AAD is the nonce and L. */
  seal(payload: Buffer): Buffer {
    this.account(payload.length)
    const nonce = this.nonce(this.counter)
    const header = Buffer.alloc(4)
    header.writeUInt32BE(8 + payload.length + TAG_BYTES, 0)
    const counter = Buffer.alloc(8)
    counter.writeBigUInt64BE(this.counter, 0)
    const cipher = createCipheriv('aes-256-gcm', this.key, nonce, { authTagLength: TAG_BYTES })
    cipher.setAAD(Buffer.concat([nonce, header]))
    const sealed = Buffer.concat([header, counter, cipher.update(payload), cipher.final(), cipher.getAuthTag()])
    this.counter += 1n
    this.sealedBytes += BigInt(payload.length)
    return sealed
  }

  /** Accepts only the exact next counter, and advances only after the tag verifies. */
  open(header: Buffer, body: Buffer): Buffer {
    if (body.length < SEAL_OVERHEAD || body.readBigUInt64BE(0) !== this.counter) {
      throw new ProtocolError('sealed frame out of order')
    }
    this.account(body.length - SEAL_OVERHEAD)
    const nonce = this.nonce(this.counter)
    const decipher = createDecipheriv('aes-256-gcm', this.key, nonce, { authTagLength: TAG_BYTES })
    decipher.setAAD(Buffer.concat([nonce, header]))
    decipher.setAuthTag(body.subarray(body.length - TAG_BYTES))
    let payload: Buffer
    try {
      payload = Buffer.concat([decipher.update(body.subarray(8, body.length - TAG_BYTES)), decipher.final()])
    } catch {
      throw new ProtocolError('sealed frame rejected')
    }
    this.counter += 1n
    this.sealedBytes += BigInt(payload.length)
    return payload
  }
}

/** Opens sealed frames from a byte stream and yields their plaintext frames. One per connection. */
export class SealedDecoder {
  private buffered: Buffer = Buffer.alloc(0)

  constructor(
    private readonly direction: SealedDirection,
    private maxFrame = DEFAULT_MAX_FRAME
  ) {}

  setMaxFrame(maxFrame: number): void {
    this.maxFrame = maxFrame
  }

  push(chunk: Buffer): Record<string, unknown>[] {
    this.buffered = this.buffered.length === 0 ? chunk : Buffer.concat([this.buffered, chunk])
    const frames: Record<string, unknown>[] = []
    while (this.buffered.length >= 4) {
      const size = this.buffered.readUInt32BE(0)
      // Bounded before the body is waited for or anything is allocated.
      if (size < SEAL_OVERHEAD || size > this.maxFrame + SEAL_OVERHEAD) throw new ProtocolError('invalid sealed frame size')
      if (this.buffered.length < 4 + size) break
      const header = Buffer.from(this.buffered.subarray(0, 4))
      const body = Buffer.from(this.buffered.subarray(4, 4 + size))
      this.buffered = this.buffered.subarray(4 + size)
      let parsed: unknown
      try {
        parsed = JSON.parse(this.direction.open(header, body).toString('utf8'))
      } catch (error) {
        if (error instanceof ProtocolError) throw error
        throw new ProtocolError('frame is not valid JSON')
      }
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new ProtocolError('frame is not a JSON object')
      }
      frames.push(parsed as Record<string, unknown>)
    }
    return frames
  }
}

export interface ClientSessionOptions {
  token: string
  profileId: string
  endpoint: string
  client: { name: string; version: string }
  offered: Version
  features: string[]
}

export interface Answer {
  proof: Record<string, unknown>
  send: SealedDirection
  receive: SealedDirection
  maxFrame: number
}

function exactShape(message: Record<string, unknown>, keys: Record<string, string>): boolean {
  const names = Object.keys(message)
  return (
    names.length === Object.keys(keys).length &&
    names.every((name) => name in keys) &&
    Object.entries(keys).every(([name, kind]) =>
      kind === 'object'
        ? message[name] !== null && typeof message[name] === 'object' && !Array.isArray(message[name])
        : kind === 'integer'
          ? Number.isSafeInteger(message[name])
          : typeof message[name] === kind
    )
  )
}

/** A client's side of one handshake. Fresh random nonce per connection; nothing is ever stored. */
export class ClientSession {
  private readonly clientNonce = randomBytes(NONCE_BYTES)
  private answered = false

  constructor(private readonly options: ClientSessionOptions) {}

  /** The token-free hello: the version offer, the client and this connection's nonce. */
  hello(): Record<string, unknown> {
    return {
      t: 'hello',
      protocol: this.options.offered,
      client: this.options.client,
      profile_id: this.options.profileId,
      features: this.options.features,
      auth: { v: AUTH_VERSION, client_nonce: this.clientNonce.toString('hex') }
    }
  }

  /** Checks the engine's challenge and proof; returns this client's proof and the sealed directions. */
  answer(challenge: Record<string, unknown>): Answer {
    if (this.answered) throw new ProtocolError('unexpected handshake frame')
    this.answered = true
    const shape = {
      t: 'string',
      server_nonce: 'string',
      protocol: 'object',
      max_frame: 'integer',
      core: 'object',
      server_proof: 'string'
    }
    if (!exactShape(challenge, shape) || challenge.t !== 'challenge') throw new ProtocolError('unexpected handshake frame')
    const selected = challenge.protocol as Record<string, unknown>
    if (
      !exactShape(selected, { major: 'integer', minor: 'integer' }) ||
      (selected.major as number) < 0 ||
      (selected.minor as number) < 0
    ) {
      throw new ProtocolError('invalid protocol version')
    }
    const core = challenge.core as Record<string, unknown>
    if (!exactShape(core, { instance_id: 'string' })) throw new ProtocolError('unexpected handshake frame')
    const maxFrame = challenge.max_frame as number
    if (maxFrame < 1 || maxFrame > DEFAULT_MAX_FRAME) throw new ProtocolError('invalid max_frame')
    if (!HEX64.test(challenge.server_nonce as string)) throw new ProtocolError('invalid session nonce')
    const transcript = sessionTranscript({
      offered: this.options.offered,
      selected: selected as unknown as Version,
      client: this.options.client,
      profileId: this.options.profileId,
      endpoint: this.options.endpoint,
      clientNonce: this.clientNonce,
      serverNonce: Buffer.from(challenge.server_nonce as string, 'hex'),
      instanceId: core.instance_id as string,
      maxFrame,
      features: this.options.features
    })
    const keys = sessionKeys(this.options.token, this.clientNonce, Buffer.from(challenge.server_nonce as string, 'hex'), transcript)
    if (!proofMatches(sessionProof(keys, 'server', transcript), challenge.server_proof)) {
      throw new SessionRefused('engine proof refused')
    }
    return {
      proof: { t: 'proof', client_proof: sessionProof(keys, 'client', transcript).toString('hex') },
      send: new SealedDirection(keys.c2s, CLIENT_TO_SERVER),
      receive: new SealedDirection(keys.s2c, SERVER_TO_CLIENT),
      maxFrame
    }
  }
}
