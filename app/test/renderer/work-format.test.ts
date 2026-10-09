import { describe, expect, it } from 'vitest'
import { workStartedMillis } from '../../src/renderer/src/work-format'

describe('real Work projection formatting', () => {
  it('accepts real manager epoch seconds and legacy ISO timestamps without invalid dates', () => {
    expect(workStartedMillis(1791264600)).toBe(Date.parse('2026-10-06T05:30:00Z'))
    expect(workStartedMillis('2026-10-06T05:30:00Z')).toBe(1791264600000)
    expect(workStartedMillis(null)).toBe(0)
    expect(workStartedMillis('unavailable')).toBe(0)
  })
})
