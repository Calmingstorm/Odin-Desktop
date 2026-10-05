import { describe, expect, it } from 'vitest'
import { basis, compact, count, percent, share } from '../../src/renderer/src/format'

describe('numbers the core reports', () => {
  it('shows measured values as they are, marks estimates, and never invents an unknown', () => {
    expect(count({ value: 12_400, kind: 'measured' })).toBe('12.4K')
    expect(count({ value: 12_400, kind: 'estimated' })).toBe('~12.4K')
    expect(count({ value: null, kind: 'unknown' })).toBe('—')
    expect(count({ value: 5, kind: 'unknown' })).toBe('—')
    expect(percent({ value: 41.4, kind: 'measured' })).toBe('41%')
    expect(compact(2_000_000)).toBe('2M')
    expect(compact(950)).toBe('950')
  })

  it('takes a share as uncertain as the less certain of its two values', () => {
    expect(share({ value: 50, kind: 'measured' }, { value: 200, kind: 'measured' })).toEqual({ value: 25, kind: 'measured' })
    expect(share({ value: 50, kind: 'estimated' }, { value: 200, kind: 'measured' })).toEqual({ value: 25, kind: 'estimated' })
    expect(share({ value: 50, kind: 'measured' }, { value: null, kind: 'unknown' })).toEqual({ value: null, kind: 'unknown' })
    expect(share({ value: 50, kind: 'measured' }, { value: 0, kind: 'measured' })).toEqual({ value: null, kind: 'unknown' })
  })

  it('says what each tag means', () => {
    expect(basis({ value: 1, kind: 'measured' })).toBe('measured')
    expect(basis({ value: null, kind: 'unknown' })).toMatch(/doesn't know/)
  })
})
