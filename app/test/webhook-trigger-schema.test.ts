import { describe, expect, it } from 'vitest'
import { MANAGEMENT_SCHEMAS, scheduleTriggerSchema, webhookIngressStatusSchema } from '../src/main/schemas'

describe('named schedule trigger bridge', () => {
  it('accepts retained source/event/repo conditions, without extra authority or confirmation', () => {
    for (const source of ['generic', 'github', 'gitea', 'gitlab']) {
      expect(MANAGEMENT_SCHEMAS.schedulesSave.safeParse({ action: 'reminder', description: 'Hook', channel_id: 'c1',
        trigger: { source, event: 'push', repo: 'project' } }).success).toBe(true)
    }
    expect(scheduleTriggerSchema.safeParse({ event: 'push', source: null }).success).toBe(true)
    expect(scheduleTriggerSchema.safeParse({ repo: 'project' }).success).toBe(true)
  })
  it('refuses malformed and empty matchers before the core, but allows condition-only edits', () => {
    for (const trigger of [{}, { source: null }, { event: 7 }, { secret: 'never' }, { source: 'unknown' }]) {
      expect(MANAGEMENT_SCHEMAS.schedulesSave.safeParse({ id: 's1', trigger }).success).toBe(false)
    }
    expect(MANAGEMENT_SCHEMAS.schedulesSave.safeParse({ id: 's1', trigger: { event: 'deploy' } }).success).toBe(true)
  })
})

describe('actual ingress status projection', () => {
  it('strips unexpected secret fields and preserves observed not-bound versus accepting', () => {
    const status = { reason: 'not_bound', address: null, eligible_schedules: 1, unknown_deliveries: 2 }
    expect(webhookIngressStatusSchema.parse({ ...status, secret: 'must-not-cross' })).toEqual(status)
    expect(webhookIngressStatusSchema.parse({ ...status, reason: 'accepting', address: ['::1', 45678, 0, 0] }).address)
      .toEqual(['::1', 45678, 0, 0])
    expect(webhookIngressStatusSchema.safeParse({ ...status, reason: 'configured' }).success).toBe(false)
    expect(webhookIngressStatusSchema.safeParse({ ...status, eligible_schedules: -1 }).success).toBe(false)
  })
})
