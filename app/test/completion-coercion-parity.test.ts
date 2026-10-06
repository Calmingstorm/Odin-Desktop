import { describe, expect, test } from 'vitest'
import { MANAGEMENT_SCHEMAS } from '../src/main/schemas'

describe('completion bridge preserves pinned query conversion and fallback', () => {
  test.each([
    ['auditFailures', { window: 'invalid' }],
    ['knowledgeDuplicates', { threshold: 'invalid' }],
    ['recoveryRecent', { limit: 'invalid' }],
    ['trajectoriesRead', { filename: 'fixture.jsonl', limit: 'invalid', errors_only: '1' }],
    ['trajectoriesSearch', { limit: 'invalid', errors_only: 'true' }]
  ])('%s lets the real owner apply its fallback', (method, params) => {
    expect(MANAGEMENT_SCHEMAS[method as keyof typeof MANAGEMENT_SCHEMAS]!.parse(params)).toEqual(params)
  })
})
