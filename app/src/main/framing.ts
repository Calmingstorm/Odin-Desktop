// Length-prefixed JSON frames (docs/design/protocol.md, "Framing").
// Each frame is a 4-byte unsigned big-endian length followed by that many bytes of UTF-8 JSON holding one object.

export const DEFAULT_MAX_FRAME = 4 * 1024 * 1024

export class ProtocolError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ProtocolError'
  }
}

export function encodeFrame(message: Record<string, unknown>, maxFrame = DEFAULT_MAX_FRAME): Buffer {
  const body = Buffer.from(JSON.stringify(message), 'utf8')
  if (body.length > maxFrame) {
    throw new ProtocolError(`frame of ${body.length} bytes exceeds the ${maxFrame}-byte limit`)
  }
  const header = Buffer.alloc(4)
  header.writeUInt32BE(body.length, 0)
  return Buffer.concat([header, body])
}

/** Accumulates socket chunks and yields complete frames. One decoder per connection. */
export class FrameDecoder {
  private buffered: Buffer = Buffer.alloc(0)

  constructor(private maxFrame = DEFAULT_MAX_FRAME) {}

  setMaxFrame(maxFrame: number): void {
    this.maxFrame = maxFrame
  }

  /** Bytes received but not yet a complete frame. */
  get pendingBytes(): number {
    return this.buffered.length
  }

  push(chunk: Buffer): Record<string, unknown>[] {
    this.buffered = this.buffered.length === 0 ? chunk : Buffer.concat([this.buffered, chunk])
    const frames: Record<string, unknown>[] = []
    while (this.buffered.length >= 4) {
      const length = this.buffered.readUInt32BE(0)
      if (length > this.maxFrame) {
        throw new ProtocolError(`incoming frame of ${length} bytes exceeds the ${this.maxFrame}-byte limit`)
      }
      if (this.buffered.length < 4 + length) break
      const body = this.buffered.subarray(4, 4 + length)
      this.buffered = this.buffered.subarray(4 + length)
      let parsed: unknown
      try {
        parsed = JSON.parse(body.toString('utf8'))
      } catch {
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
