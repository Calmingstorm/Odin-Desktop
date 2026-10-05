import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { AttachmentProgress, CoreEvent } from '../src/shared/api'
import { AttachmentManager, mimeFor, type AttachmentLimits } from '../src/main/attachments'
import { Broker } from '../src/main/broker'
import { startFixture, waitFor, type FixtureCore } from './fixture-harness'

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

async function setup(limits: AttachmentLimits = { attachment_bytes: 25 * 1024 * 1024, chunk_bytes: 512 * 1024 }) {
  const core: FixtureCore = await startFixture()
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
  const dir = mkdtempSync(join(tmpdir(), 'odin-attach-'))
  cleanups.push(() => rmSync(dir, { recursive: true, force: true }))
  const manager = new AttachmentManager(broker, () => limits)
  return { broker, events, manager, conversationId: created.result.conversation.id, dir }
}

describe('attachment manager against the fixture core', () => {
  it('uploads a file in chunks, verified by digest, and sends it with a message', async () => {
    const { broker, events, manager, conversationId, dir } = await setup()
    const path = join(dir, 'notes.txt')
    writeFileSync(path, Buffer.alloc(1_300_000, 'a'))
    const progress: number[] = []
    manager.on('progress', (p: AttachmentProgress) => progress.push(p.sent))
    const staged = await manager.stagePath(path)
    expect(staged).toMatchObject({ ok: true, result: { name: 'notes.txt', mime: 'text/plain', size: 1_300_000 } })
    if (!staged.ok) return
    const uploaded = await manager.upload(staged.result.id, conversationId)
    expect(uploaded.ok).toBe(true)
    if (!uploaded.ok) return
    expect(progress).toEqual([524_288, 1_048_576, 1_300_000])

    const sub = crypto.randomUUID()
    const sent = await broker.request('submission.send', { client_submission_id: sub, conversation_id: conversationId, text: '', attachments: [{ ref: uploaded.result.ref, add_to_knowledge: true }] }, sub)
    expect(sent.ok).toBe(true)
    await waitFor(() => events.some((e) => e.type === 'request.completed'))
    const user = events.find((e) => e.type === 'message.committed' && (e.payload.message as { role: string }).role === 'user')
    expect((user?.payload.message as { attachments: unknown[] }).attachments).toEqual([{ ref: uploaded.result.ref, name: 'notes.txt', mime: 'text/plain', size: 1_300_000 }])
    const reply = events.find((e) => e.type === 'message.committed' && (e.payload.message as { role: string }).role === 'assistant')
    expect((reply?.payload.message as { text: string }).text).toContain('notes.txt (1300000 bytes), added to knowledge')
  })

  it('refuses before any byte moves: too large, an unsupported type, a folder, or a relative path', async () => {
    const { manager, conversationId, dir } = await setup({ attachment_bytes: 10, chunk_bytes: 4 })
    writeFileSync(join(dir, 'big.bin'), Buffer.alloc(11))
    expect(await manager.stagePath(join(dir, 'big.bin'))).toMatchObject({ ok: false, error: { code: 'too_large' } })
    mkdirSync(join(dir, 'folder'))
    expect(await manager.stagePath(join(dir, 'folder'))).toMatchObject({ ok: false, error: { code: 'unsupported_type' } })
    expect(await manager.stagePath('relative.txt')).toMatchObject({ ok: false, error: { code: 'bad_request' } })
    writeFileSync(join(dir, 'tool.exe'), Buffer.alloc(5))
    const staged = await manager.stagePath(join(dir, 'tool.exe'))
    expect(staged.ok).toBe(true)
    if (staged.ok) expect(await manager.upload(staged.result.id, conversationId)).toMatchObject({ ok: false, error: { code: 'unsupported_type' } })
  })

  it('stops an upload between chunks when it is cancelled', async () => {
    const { manager, conversationId, dir } = await setup({ attachment_bytes: 1024 * 1024, chunk_bytes: 1024 })
    writeFileSync(join(dir, 'slow.bin'), Buffer.alloc(200 * 1024))
    const staged = await manager.stagePath(join(dir, 'slow.bin'))
    if (!staged.ok) throw new Error('not staged')
    manager.once('progress', () => manager.cancel(staged.result.id))
    expect(await manager.upload(staged.result.id, conversationId)).toMatchObject({ ok: false, error: { code: 'cancelled' } })
    expect(await manager.upload(staged.result.id, conversationId)).toMatchObject({ ok: false, error: { code: 'not_found' } })
  })

  it('uploads bytes that have no file behind them, such as a pasted image', async () => {
    const { manager, conversationId } = await setup()
    const staged = manager.stageBytes('pasted-image.png', 'image/png', Buffer.from([137, 80, 78, 71, 1, 2, 3]))
    if (!staged.ok) throw new Error('not staged')
    expect(await manager.upload(staged.result.id, conversationId)).toMatchObject({ ok: true, result: { name: 'pasted-image.png', mime: 'image/png', size: 7 } })
  })

  it('guesses types from the file name, and calls the rest octet streams', () => {
    expect(mimeFor('photo.JPG')).toBe('image/jpeg')
    expect(mimeFor('report.pdf')).toBe('application/pdf')
    expect(mimeFor('mystery')).toBe('application/octet-stream')
  })
})
