// Notification intents and acknowledgements against the fixture core, over the real broker.
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'
import type { CoreEvent } from '../src/shared/api'
import { Broker } from '../src/main/broker'
import { startFixture, waitFor } from './fixture-harness'

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

describe('notification intents', () => {
  it('announce a committed reply with a cut, scrubbed preview and a dedupe key, and record what the app did', async () => {
    const core = await startFixture()
    cleanups.push(() => core.stop())
    const broker = new Broker({
      socketPath: core.paths.socketPath,
      readToken: () => readFileSync(core.paths.tokenPath, 'utf8').trim(),
      profileId: 'default',
      clientVersion: 'test',
      reconnectDelaysMs: [50]
    })
    const events: CoreEvent[] = []
    broker.on('event', (e: CoreEvent) => events.push(e))
    broker.connect()
    cleanups.push(() => broker.close())
    await waitFor(() => broker.linkState === 'ready')
    await broker.subscribe()
    const created = (await broker.request('conversations.create', {})) as { ok: true; result: { conversation: { id: string } } }
    const conversationId = created.result.conversation.id
    const sub = crypto.randomUUID()
    const text = `token=abc123 ${'word '.repeat(80)}`
    await broker.request('submission.send', { client_submission_id: sub, conversation_id: conversationId, text }, sub)
    await waitFor(() => events.some((e) => e.type === 'notification.intent'))

    const committed = events.find((e) => e.type === 'message.committed' && (e.payload.message as { role: string }).role === 'assistant')!
    const announced = events.find((e) => e.type === 'notification.intent')!
    expect(events.indexOf(announced)).toBeGreaterThan(events.indexOf(committed)) // never before the reply is committed
    const messageId = (committed.payload.message as { id: string }).id
    expect(announced.payload).toMatchObject({ conversation_id: conversationId, message_id: messageId, category: 'reply', dedupe_key: `reply:${messageId}` })
    const preview = String(announced.payload.preview)
    expect(preview).toContain('token=•••')
    expect(preview).not.toContain('abc123')
    expect(preview.length).toBeLessThanOrEqual(240)

    const id = crypto.randomUUID()
    const ack = { dedupe_key: `reply:${messageId}`, outcome: 'shown' }
    expect(await broker.request('notifications.ack', ack, id)).toEqual({ ok: true, result: { disposition: 'recorded' } })
    expect(await broker.request('notifications.ack', ack, id)).toEqual({ ok: true, result: { disposition: 'recorded' } })
    const other = crypto.randomUUID()
    expect(await broker.request('notifications.ack', { dedupe_key: 'x', outcome: 'seen' }, other)).toMatchObject({
      ok: false,
      error: { code: 'bad_request' }
    })
  })
})
