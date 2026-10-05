// Local wall clock to instant, with the daylight-saving cases explicit, in fixed zones rather than the machine's.
import { describe, expect, it } from 'vitest'
import { analyzeLocalDateTime, localWallClock, offsetLabel, type Zone } from '../../src/renderer/src/schedule-time'

// New York in 2026: EDT (UTC-4) from 8 March 07:00 UTC to 1 November 06:00 UTC, EST (UTC-5) otherwise.
const START = Date.UTC(2026, 2, 8, 7)
const END = Date.UTC(2026, 10, 1, 6)
const newYork: Zone = { offsetMinutes: (ms) => (ms >= START && ms < END ? 240 : 300) }
// Lord Howe Island: UTC+11 in summer, UTC+10:30 otherwise, so its clocks move by 30 minutes. Back on 5 April 2026.
const LH_END = Date.UTC(2026, 3, 4, 15)
const lordHowe: Zone = { offsetMinutes: (ms) => (ms < LH_END ? -660 : -630) }

describe('a datetime-local value as an instant', () => {
  it('resolves an ordinary time, honouring seconds when given', () => {
    expect(analyzeLocalDateTime('2026-07-04T09:00', newYork)).toMatchObject({ state: 'ok', iso: '2026-07-04T13:00:00.000Z' })
    expect(analyzeLocalDateTime('2026-12-04T09:00:30', newYork)).toMatchObject({ state: 'ok', iso: '2026-12-04T14:00:30.000Z' })
  })

  it('refuses a time the clocks skip', () => {
    expect(analyzeLocalDateTime('2026-03-08T02:30', newYork)).toEqual({ state: 'nonexistent', typed: '2026-03-08T02:30' })
  })

  it('offers both instants of a time that happens twice, earlier first, with their offsets', () => {
    const twice = analyzeLocalDateTime('2026-11-01T01:30', newYork)
    expect(twice.state).toBe('ambiguous')
    if (twice.state !== 'ambiguous') return
    expect(twice.options.map((o) => [o.iso, o.offset])).toEqual([
      ['2026-11-01T05:30:00.000Z', 'UTC-4'],
      ['2026-11-01T06:30:00.000Z', 'UTC-5']
    ])
  })

  it('finds both instants when the clocks move by half an hour', () => {
    const twice = analyzeLocalDateTime('2026-04-05T01:45', lordHowe)
    expect(twice.state === 'ambiguous' && twice.options.map((o) => o.offset)).toEqual(['UTC+11', 'UTC+10:30'])
  })

  it('treats empty, malformed and out-of-range input plainly', () => {
    expect(analyzeLocalDateTime('', newYork)).toEqual({ state: 'empty' })
    expect(analyzeLocalDateTime('2026-07-04T09:00garbage', newYork).state).toBe('invalid')
    expect(analyzeLocalDateTime('2026-07-04T09:00:61', newYork).state).toBe('invalid')
  })

  it('shows an instant as the wall clock a datetime-local input expects', () => {
    expect(localWallClock(Date.UTC(2026, 6, 4, 13, 0, 5), true, newYork)).toBe('2026-07-04T09:00:05')
    expect(offsetLabel(Date.UTC(2026, 0, 1), lordHowe)).toBe('UTC+11')
    expect(offsetLabel(Date.UTC(2026, 5, 1), lordHowe)).toBe('UTC+10:30')
  })
})
