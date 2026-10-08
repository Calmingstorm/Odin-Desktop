import { describe, expect, it } from 'vitest'
import { MANAGEMENT } from '../src/shared/api'
import { MANAGEMENT_SCHEMAS } from '../src/main/schemas'
describe('reviewed named outbound bridge contract', () => {
  it('maps four IPC/preload entries to existing routes; external test is a command', () => {
    expect(MANAGEMENT.outboundWebhooksList).toEqual({ channel: 'odin:manage:webhooks.outbound.list', core: 'webhooks.outbound.list', command: false })
    for (const [name, core] of [['outboundWebhooksSave', 'save'], ['outboundWebhooksDelete', 'delete'], ['outboundWebhooksTest', 'test']] as const) expect(MANAGEMENT[name]).toEqual({ channel: `odin:manage:webhooks.outbound.${core}`, core: `webhooks.outbound.${core}`, command: true })
  })
  it('requires revision; owner keep/replace/remove are omission/value/empty fields', () => {
    const schema = MANAGEMENT_SCHEMAS.outboundWebhooksSave
    expect(schema.safeParse({ id: 'target1', expected_revision: 'rev1' }).success).toBe(true)
    expect(schema.safeParse({ id: 'target1', expected_revision: 'rev1', secret: '', url: 'https://example.com' }).success).toBe(true)
    expect(schema.safeParse({ url: 'https://u:p@example.com', expected_revision: 'rev1', secret: 'replacement', events: ['health'] }).success).toBe(true)
    expect(schema.safeParse({ id: 'target1', secret: 'replacement' }).success).toBe(false)
    expect(MANAGEMENT_SCHEMAS.outboundWebhooksDelete.safeParse({ id: 'target1' }).success).toBe(false)
    expect(MANAGEMENT_SCHEMAS.outboundWebhooksTest.safeParse({ id: 'target1' }).success).toBe(false)
    expect(MANAGEMENT_SCHEMAS.outboundWebhooksTest.safeParse({ id: 'target1', expected_revision: 'rev1' }).success).toBe(true)
    expect(MANAGEMENT_SCHEMAS.outboundWebhooksTest.safeParse({ id: 'target1', expected_revision: 1 }).success).toBe(false)
  })
  it('rejects global knobs, invented intents, invalid events, overbound secrets and generic routes', () => {
    for (const change of [{ rate_limit_seconds: 0 }, { targets: [] }, { url_intent: 'keep' }, { method: 'other' }, { events: ['made-up'] }, { events: ['all', 'health'] }, { secret: 'x'.repeat(257) }]) expect(MANAGEMENT_SCHEMAS.outboundWebhooksSave.safeParse({ expected_revision: 'rev1', id: 'target1', ...change }).success).toBe(false)
    expect(MANAGEMENT_SCHEMAS.outboundWebhooksList.safeParse({ id: 'target1' }).success).toBe(false)
    expect(MANAGEMENT_SCHEMAS.outboundWebhooksTest.safeParse({ id: 'target1', url: 'https://example.com' }).success).toBe(false)
    expect(MANAGEMENT_SCHEMAS.outboundWebhooksSave.safeParse({ expected_revision: 'rev1', name: 'No endpoint' }).success).toBe(false)
  })
})
