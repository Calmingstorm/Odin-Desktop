// The only holder of the core socket (docs/design/protocol.md). The window never talks to the core directly.
//
// Delivery rules it enforces:
// - Events are deduplicated by `seq`; the last received cursor is kept for catch-up after a reconnect.
// - Exactly one event subscription per connection, renewed by the broker itself after every reconnect. A
//   subscription is stream control, not a command: its answer is applied whenever it arrives, even after the request
//   timed out, and before the events that follow it. It is never re-sent as an unreceipted command.
// - A reset (the core can't replay the interval since our cursor) is emitted as 'reset', so every view is rebuilt
//   from snapshots. The missing interval is never treated as empty.
// - A request with no receipt is never re-sent with a new ID. Its frame is kept and re-sent with the SAME ID after
//   reconnecting; the core answers a known ID with its original result, which is emitted as a late 'receipt'.
// - On Windows the link is a named pipe with the sealed session (windows-session.ts): the token never crosses it, and
//   the link becomes ready, re-sends and re-subscribes only after the sealed welcome opens. The first sealed frame must
//   be that welcome (or a refusal) and pass its checks; anything else, a second welcome included, closes the
//   connection, and nothing after a refusal is applied. Each connection has fresh nonces and keys. A connection at its key budget closes so the next one handshakes new keys; a command it couldn't seal
//   was never sent, and says so.
import { randomUUID } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { createConnection, type Socket } from 'node:net'
import type { CoreError, CoreEvent, LinkState } from '../shared/api'
import { DEFAULT_MAX_FRAME, FrameDecoder, ProtocolError, encodeFrame } from './framing'
import { ClientSession, PREAUTH_MAX_FRAME, SealedDecoder, SessionRefused, type SealedDirection } from './windows-session'

export const PROTOCOL = { major: 0, minor: 3 } as const

export interface BrokerOptions {
  socketPath: string
  /** Read at handshake time so the token never sits in long-lived state. */
  readToken: () => string
  profileId: string
  clientVersion: string
  requestTimeoutMs?: number
  helloTimeoutMs?: number
  reconnectDelaysMs?: number[]
  /** The Windows transport: `socketPath` is the engine's pipe name and the session is sealed. Defaults to Windows. */
  sealed?: boolean
}

export interface Welcome {
  protocol: { major: number; minor: number }
  core: { instance_id: string; version: string }
  profile_id: string
  capabilities: string[]
  features: string[]
  max_frame: number
  event_high: string
}

export type Settled = { ok: true; result: unknown } | { ok: false; error: CoreError }

interface Pending {
  frame: Record<string, unknown>
  resolve: (settled: Settled) => void
  timer: NodeJS.Timeout
  /** Stream control (a subscription): never kept for a same-ID re-send. */
  control: boolean
}

const NOT_CONNECTED: CoreError = {
  code: 'not_connected',
  message: 'Odin is not connected yet.',
  disposition: 'not_dispatched'
}

const NOT_SENT_REKEYING: CoreError = {
  code: 'not_connected',
  message: 'Odin is reconnecting. Nothing was sent.',
  disposition: 'not_dispatched'
}

const NO_RECEIPT: CoreError = {
  code: 'no_receipt',
  message: 'No receipt yet. It will be reconciled when the core answers; the command is never re-sent under a new ID.',
  disposition: 'outcome_unknown'
}

export class Broker extends EventEmitter {
  private socket: Socket | null = null
  private decoder = new FrameDecoder()
  private link: LinkState = 'starting'
  private welcomeFrame: Welcome | null = null
  private readonly pending = new Map<string, Pending>()
  private readonly unreceipted = new Map<string, Record<string, unknown>>()
  private lastSeq = 0
  private lastCursor: string | null = null
  private wantEvents = false
  /** The current connection's subscription request; its answer is applied even when it arrives late. */
  private subscriptionId: string | null = null
  private closedByUs = false
  private quiescing = false
  private startupShutdownWait = false
  private reconnectAttempt = 0
  private reconnectTimer: NodeJS.Timeout | null = null
  private helloTimer: NodeJS.Timeout | null = null
  private maxFrame = DEFAULT_MAX_FRAME
  private readonly sealed: boolean
  /** This connection's handshake, and once it is authenticated, its sealed directions. */
  private session: ClientSession | null = null
  private sealer: SealedDirection | null = null
  private sealedDecoder: SealedDecoder | null = null
  /** A sealed connection's session: proven and awaiting its one welcome, then open. */
  private sessionState: 'none' | 'awaiting' | 'open' = 'none'
  private readonly requestTimeoutMs: number
  private readonly helloTimeoutMs: number
  private readonly reconnectDelaysMs: number[]

  constructor(private readonly options: BrokerOptions) {
    super()
    this.requestTimeoutMs = options.requestTimeoutMs ?? 30_000
    this.helloTimeoutMs = options.helloTimeoutMs ?? 5_000
    this.reconnectDelaysMs = options.reconnectDelaysMs ?? [500, 1_000, 2_000, 5_000, 10_000]
    this.sealed = options.sealed ?? process.platform === 'win32'
  }

  get linkState(): LinkState {
    return this.link
  }

  get coreInstanceId(): string | null {
    return this.welcomeFrame?.core.instance_id ?? null
  }

  get unreceiptedCount(): number {
    return this.unreceipted.size
  }

  get cursor(): string | null {
    return this.lastCursor
  }

  connect(): void {
    if (this.quiescing) return
    this.closedByUs = false
    this.openSocket()
  }

  /** Exit freezes reconnect/reconciliation before asking the current core to stop.
   * Existing receipt handlers remain live. Uncertain commands retain their original identities.
   */
  quiesce(): void {
    this.quiescing = true
    // Initial socket retries are connection establishment, not reconciliation.
    // Keep only those alive until Exit's bounded readiness wait ends.
    this.startupShutdownWait = this.welcomeFrame === null && !this.closedByUs
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    if (this.startupShutdownWait && !this.socket) this.openSocket()
  }

  /** Wait within Exit's request budget, never reconnect to a replacement core. */
  waitForShutdownReady(timeoutMs: number, signal?: AbortSignal): Promise<boolean> {
    if (signal?.aborted) return Promise.resolve(false)
    if (this.link === 'ready' && !this.closedByUs) return Promise.resolve(true)
    if (!this.startupShutdownWait || timeoutMs <= 0) return Promise.resolve(false)
    return new Promise((resolve) => {
      const finish = (ready: boolean): void => {
        clearTimeout(timer)
        this.off('state', changed)
        this.off('shutdown-closed', closed)
        signal?.removeEventListener('abort', closed)
        this.startupShutdownWait = false
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
        resolve(ready)
      }
      const changed = (state: LinkState): void => { if (state === 'ready') finish(true) }
      const closed = (): void => finish(false)
      const timer = setTimeout(() => finish(false), timeoutMs)
      this.on('state', changed)
      this.once('shutdown-closed', closed)
      signal?.addEventListener('abort', closed, { once: true })
    })
  }

  /** Ends the connection on purpose; no reconnect. */
  close(): void {
    this.closedByUs = true
    this.startupShutdownWait = false
    this.emit('shutdown-closed')
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    if (this.helloTimer) clearTimeout(this.helloTimer)
    this.reconnectTimer = null
    // Destroying our socket must not discard the in-flight identities before
    // onClose can see them. Shutdown evidence includes these unknown receipts.
    this.settleDisconnected()
    this.socket?.destroy()
    this.socket = null
  }

  /** Sends a command and settles with its receipt. Never throws. */
  request(method: string, params: Record<string, unknown> = {}, id: string = randomUUID()): Promise<Settled> {
    return this.send(method, params, id, false)
  }

  private send(method: string, params: Record<string, unknown>, id: string, control: boolean): Promise<Settled> {
    if (this.quiescing && method !== 'runtime.shutdown') {
      return Promise.resolve({ ok: false, error: {
        code: 'busy', message: 'Odin is stopping.', disposition: 'not_dispatched'
      } })
    }
    const socket = this.socket
    if (this.link !== 'ready' || !socket) return Promise.resolve({ ok: false, error: NOT_CONNECTED })
    const frame = { t: 'req', id, method, params }
    let bytes: Buffer
    try {
      bytes = encodeFrame(frame, this.maxFrame)
    } catch (error) {
      return Promise.resolve({ ok: false, error: { code: 'bad_request', message: (error as Error).message } })
    }
    return new Promise<Settled>((resolve) => {
      const timer = setTimeout(() => {
        if (!this.pending.delete(id)) return
        if (!control) this.unreceipted.set(id, frame)
        resolve({ ok: false, error: NO_RECEIPT })
      }, this.requestTimeoutMs)
      this.pending.set(id, { frame, resolve, timer, control })
      if (!this.write(socket, bytes)) {
        // Never written, so never in doubt: not kept for a re-send.
        clearTimeout(timer)
        this.pending.delete(id)
        resolve({ ok: false, error: NOT_SENT_REKEYING })
      }
    })
  }

  /** Turns the event stream on: now if connected, and again after every reconnect. Idempotent. */
  startEvents(): void {
    if (this.wantEvents) return
    this.wantEvents = true
    if (this.link === 'ready') void this.subscribe()
  }

  /** Subscribes on the current connection from the last received cursor. Its answer is applied in onResponse. */
  subscribe(): Promise<Settled> {
    this.wantEvents = true
    const id = randomUUID()
    this.subscriptionId = id
    return this.send('events.subscribe', { after: this.lastCursor }, id, true)
  }

  /** Applies a subscription answer, in stream order, however late it arrives. */
  private onSubscribed(settled: Settled): void {
    if (!settled.ok) return
    const result = settled.result as { event_high?: string; reset_required?: boolean }
    if (result.reset_required && typeof result.event_high === 'string') {
      this.lastCursor = result.event_high
      this.lastSeq = Number(result.event_high) || 0
      this.emit('reset', { event_high: result.event_high })
    }
  }

  private openSocket(): void {
    this.setLink(this.welcomeFrame ? 'reconnecting' : 'connecting')
    const socket = createConnection(this.options.socketPath)
    this.socket = socket
    this.session = this.sealer = this.sealedDecoder = null
    this.sessionState = 'none'
    // Before the proofs a sealed link takes only small plain frames.
    this.decoder = new FrameDecoder(this.sealed ? PREAUTH_MAX_FRAME : this.maxFrame)
    socket.on('connect', () => this.sendHello(socket))
    socket.on('data', (chunk: Buffer) => this.onData(socket, chunk))
    socket.on('error', () => {
      /* 'close' follows and handles reconnection */
    })
    socket.on('close', () => this.onClose(socket))
  }

  private sendHello(socket: Socket): void {
    let token: string
    try {
      token = this.options.readToken()
    } catch {
      socket.destroy()
      return
    }
    const client = { name: 'odin-desktop-app', version: this.options.clientVersion }
    if (this.sealed) {
      // Fresh nonce, no token: the engine proves itself first (windows-session.ts).
      this.session = new ClientSession({
        token, profileId: this.options.profileId, endpoint: this.options.socketPath, client, offered: PROTOCOL, features: []
      })
      socket.write(encodeFrame(this.session.hello()))
    } else {
      socket.write(encodeFrame({ t: 'hello', protocol: PROTOCOL, client, profile_id: this.options.profileId, token, features: [] }))
    }
    this.helloTimer = setTimeout(() => socket.destroy(), this.helloTimeoutMs)
  }

  /** The one send path. Sealing assigns each frame's counter as it is written, so order holds.
   *
   * A sealed link never falls back to plain frames. When its session can seal no more (its key budget is spent), the
   * connection closes and the next one handshakes fresh keys. Returns whether the frame was written.
   */
  private write(socket: Socket, bytes: Buffer): boolean {
    if (!this.sealed) {
      socket.write(bytes)
      return true
    }
    let frame: Buffer | undefined
    try {
      frame = this.sealer?.seal(bytes.subarray(4))
    } catch {
      frame = undefined
    }
    if (!frame) {
      socket.destroy()
      return false
    }
    socket.write(frame)
    return true
  }

  /** Before the proofs a sealed link accepts only the engine's challenge, or its plain refusal. */
  private preauth(socket: Socket, frames: Record<string, unknown>[]): Record<string, unknown>[] {
    const [frame] = frames
    if (frame === undefined) return []
    if (frame.t === 'bye' && frames.length === 1) return frames
    if (frame.t !== 'challenge' || frames.length !== 1 || this.decoder.pendingBytes || !this.session) {
      throw new ProtocolError('unexpected frame before the session is authenticated')
    }
    const answer = this.session.answer(frame)
    socket.write(encodeFrame(answer.proof))
    this.sealer = answer.send
    this.sealedDecoder = new SealedDecoder(answer.receive, answer.maxFrame)
    this.sessionState = 'awaiting'
    return []
  }

  private onData(socket: Socket, chunk: Buffer): void {
    if (socket !== this.socket) return
    let frames: Record<string, unknown>[]
    try {
      if (this.sealedDecoder) {
        frames = this.sealedDecoder.push(chunk)
      } else {
        frames = this.decoder.push(chunk)
        if (this.sealed) frames = this.preauth(socket, frames)
      }
    } catch (error) {
      if (error instanceof ProtocolError || error instanceof SessionRefused) this.emit('protocol-error', error.message)
      socket.destroy()
      return
    }
    for (const frame of frames) {
      if (!this.sealed) {
        this.handleFrame(socket, frame)
        continue
      }
      // A sealed link applies nothing after its connection was refused, nothing before the one welcome it
      // accepts (no receipt, event or cursor), and no second welcome.
      if (socket.destroyed || socket !== this.socket) return
      if (frame.t === 'welcome') {
        if (this.sessionState !== 'awaiting') return this.refuse(socket, 'the sealed session takes one welcome')
        this.onWelcome(socket, frame as unknown as Welcome)
        if (socket.destroyed) return // refused, or its re-sends could not be sealed
        this.sessionState = 'open'
        continue
      }
      if (this.sessionState !== 'open' && frame.t !== 'bye') {
        return this.refuse(socket, 'the sealed session must open with the welcome')
      }
      this.handleFrame(socket, frame)
    }
  }

  private refuse(socket: Socket, reason: string): void {
    this.emit('protocol-error', reason)
    socket.destroy()
  }

  private handleFrame(socket: Socket, frame: Record<string, unknown>): void {
    switch (frame.t) {
      case 'welcome':
        this.onWelcome(socket, frame as unknown as Welcome)
        return
      case 'res':
        this.onResponse(frame)
        return
      case 'evt':
        this.onEvent(frame)
        return
      case 'bye':
        this.emit('bye', String(frame.reason ?? 'unknown'))
        return
      case 'pong':
        return
      default:
        this.emit('protocol-error', `unknown frame type ${String(frame.t)}`)
        socket.destroy()
    }
  }

  private onWelcome(socket: Socket, welcome: Welcome): void {
    if (this.helloTimer) clearTimeout(this.helloTimer)
    this.helloTimer = null
    if (welcome.protocol?.major !== PROTOCOL.major || welcome.profile_id !== this.options.profileId) {
      this.emit('protocol-error', 'core is incompatible or serves a different profile')
      socket.destroy()
      return
    }
    if (typeof welcome.max_frame === 'number' && welcome.max_frame > 0) {
      this.maxFrame = welcome.max_frame
      this.decoder.setMaxFrame(welcome.max_frame)
      this.sealedDecoder?.setMaxFrame(welcome.max_frame)
    }
    const previous = this.welcomeFrame?.core.instance_id
    this.welcomeFrame = welcome
    this.reconnectAttempt = 0
    this.setLink('ready')
    // Re-send commands that never got a receipt, with their original IDs, then renew the one subscription. Both
    // happen before 'welcome' is emitted, so a listener can't add a second subscription on this connection.
    if (!this.quiescing) {
      for (const frame of this.unreceipted.values()) {
        if (!this.write(socket, encodeFrame(frame, this.maxFrame))) return // kept for the next connection
      }
      if (this.wantEvents) void this.subscribe()
      if (socket.destroyed) return
    }
    this.emit('welcome', welcome)
    if (previous && previous !== welcome.core.instance_id) this.emit('core-changed', welcome.core.instance_id)
  }

  private onResponse(frame: Record<string, unknown>): void {
    const id = String(frame.id)
    const settled: Settled =
      frame.ok === true
        ? { ok: true, result: frame.result }
        : { ok: false, error: (frame.error as CoreError) ?? { code: 'internal', message: 'malformed error' } }
    if (id === this.subscriptionId) this.onSubscribed(settled)
    const pending = this.pending.get(id)
    if (pending) {
      clearTimeout(pending.timer)
      this.pending.delete(id)
      pending.resolve(settled)
      return
    }
    if (this.unreceipted.delete(id)) this.emit('receipt', { id, settled })
  }

  private onEvent(frame: Record<string, unknown>): void {
    const seq = Number(frame.seq)
    if (!Number.isFinite(seq) || seq <= this.lastSeq) return
    this.lastSeq = seq
    this.lastCursor = String(frame.cursor)
    this.emit('event', frame as unknown as CoreEvent)
  }

  private onClose(socket: Socket): void {
    if (socket !== this.socket) return
    if (this.helloTimer) clearTimeout(this.helloTimer)
    this.helloTimer = null
    this.socket = null
    this.session = this.sealer = this.sealedDecoder = null // the next connection gets fresh keys
    this.subscriptionId = null // the next connection makes its own subscription
    this.settleDisconnected()
    if (this.closedByUs || (this.quiescing && !this.startupShutdownWait)) return
    const delay = this.reconnectDelaysMs[this.startupShutdownWait ? 0
      : Math.min(this.reconnectAttempt, this.reconnectDelaysMs.length - 1)] ?? 1_000
    this.reconnectAttempt += 1
    this.setLink(this.welcomeFrame ? 'reconnecting' : 'connecting')
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (!this.closedByUs && (!this.quiescing || this.startupShutdownWait)) this.openSocket()
    }, delay)
  }

  private settleDisconnected(): void {
    // In-flight commands lost their receipt: retain the original identities.
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer)
      if (!pending.control) this.unreceipted.set(id, pending.frame)
      pending.resolve({ ok: false, error: NO_RECEIPT })
    }
    this.pending.clear()
  }

  private setLink(state: LinkState): void {
    if (this.link === state) return
    this.link = state
    this.emit('state', state)
  }
}
