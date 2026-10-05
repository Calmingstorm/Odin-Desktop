import { describe, expect, it } from 'vitest'
import { FrameDecoder, ProtocolError, encodeFrame } from '../src/main/framing'

describe('framing', () => {
  it('round-trips a frame', () => {
    const decoder = new FrameDecoder()
    expect(decoder.push(encodeFrame({ t: 'ping', n: 1 }))).toEqual([{ t: 'ping', n: 1 }])
  })

  it('reassembles frames split across chunks and splits frames sharing a chunk', () => {
    const bytes = Buffer.concat([encodeFrame({ a: 1 }), encodeFrame({ b: 'two' })])
    const decoder = new FrameDecoder()
    const out = [...decoder.push(bytes.subarray(0, 3)), ...decoder.push(bytes.subarray(3, 9)), ...decoder.push(bytes.subarray(9))]
    expect(out).toEqual([{ a: 1 }, { b: 'two' }])
  })

  it('refuses frames over the limit, in both directions', () => {
    expect(() => encodeFrame({ big: 'x'.repeat(100) }, 50)).toThrow(ProtocolError)
    const header = Buffer.alloc(4)
    header.writeUInt32BE(1000, 0)
    expect(() => new FrameDecoder(100).push(header)).toThrow(ProtocolError)
  })

  it('refuses frames that are not JSON objects', () => {
    const body = Buffer.from('[1,2]')
    const header = Buffer.alloc(4)
    header.writeUInt32BE(body.length, 0)
    expect(() => new FrameDecoder().push(Buffer.concat([header, body]))).toThrow('not a JSON object')
    const bad = Buffer.from('{nope')
    header.writeUInt32BE(bad.length, 0)
    expect(() => new FrameDecoder().push(Buffer.concat([header, bad]))).toThrow('not valid JSON')
  })
})
