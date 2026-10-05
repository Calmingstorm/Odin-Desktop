import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { ArtifactRef, CoreEvent } from '../src/shared/api'
import { ArtifactStore, safeFileName } from '../src/main/artifacts'
import type { Requester } from '../src/main/attachments'
import { Broker } from '../src/main/broker'
import { startFixture, waitFor } from './fixture-harness'

const cleanups: Array<() => Promise<void> | void> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
})

function scratch(): string {
  const dir = mkdtempSync(join(tmpdir(), 'odin-artifacts-'))
  cleanups.push(() => rmSync(dir, { recursive: true, force: true }))
  return dir
}

/** Sends `text` to the fixture core and returns what Odin's reply produced, with a store over a private cache. */
async function produced(text: string) {
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
  const created = (await broker.request('conversations.create', {})) as { ok: true; result: { conversation: { id: string; rev: number } } }
  const conversation = created.result.conversation
  const sub = crypto.randomUUID()
  await broker.request('submission.send', { client_submission_id: sub, conversation_id: conversation.id, text }, sub)
  await waitFor(() => events.some((e) => e.type === 'request.completed'))
  const reply = events.find((e) => e.type === 'message.committed' && (e.payload.message as { role: string }).role === 'assistant')!
  const artifacts = (reply.payload.message as { artifacts?: ArtifactRef[] }).artifacts ?? []
  const reads: string[] = []
  const counting: Requester = {
    request: (method, params, id) => {
      if (method === 'artifacts.read') reads.push(String(params?.ref))
      return broker.request(method, params, id)
    }
  }
  const cache = scratch()
  const opened: string[] = []
  const revealed: string[] = []
  const store = new ArtifactStore(counting, cache, () => 16, {
    openPath: async (path) => {
      opened.push(path)
      return ''
    },
    showItemInFolder: (path) => revealed.push(path)
  })
  const byName = (name: string): ArtifactRef => {
    const found = artifacts.find((a) => a.name === name)
    if (!found) throw new Error(`no artifact named ${name}`)
    return found
  }
  return { broker, store, conversation, artifacts, byName, cache, opened, revealed, reads }
}

describe('artifact store against the fixture core', () => {
  it('fetches an image in bounded chunks and keeps private cached copies', async () => {
    const { store, artifacts, byName, cache, reads } = await produced('make a file and an image')
    expect(artifacts.map((a) => [a.name, a.kind])).toEqual([['notes.txt', 'file'], ['chart.png', 'image']])
    const image = await store.fetchBytes(byName('chart.png').ref)
    expect(image.ok && image.result.subarray(0, 4).toString('latin1')).toBe('\u0089PNG')
    expect(reads.length).toBeGreaterThan(3) // 16-byte chunks in this test
    const cached = await store.cached(byName('notes.txt').ref, 'notes.txt')
    if (!cached.ok) throw new Error('not cached')
    expect(cached.result.startsWith(cache)).toBe(true)
    expect(readFileSync(cached.result, 'utf8')).toBe('Generated notes\nline two\n')
    expect(statSync(cached.result).mode & 0o777).toBe(0o600)
    expect(statSync(dirname(cached.result)).mode & 0o777).toBe(0o700)
  })

  it('fetches a file once when two requests for it overlap, then serves the cached copy', async () => {
    const { store, byName, reads } = await produced('a file please')
    const notes = byName('notes.txt')
    const [first, second] = await Promise.all([store.cached(notes.ref, notes.name), store.cached(notes.ref, notes.name)])
    expect(first).toEqual(second)
    const fetched = reads.length
    expect(fetched).toBe(2) // 25 bytes in 16-byte chunks, read once
    await store.cached(notes.ref, notes.name)
    expect(reads.length).toBe(fetched)
    if (!first.ok) throw new Error('not cached')
    expect(readdirSync(dirname(first.result))).toEqual(['notes.txt']) // no temporary files left behind
  })

  it('opens any file in the default app, scripts included, and reveals the cached copy', async () => {
    const { store, byName, opened, revealed } = await produced('a file and a script')
    expect(await store.open(byName('notes.txt').ref, 'notes.txt')).toEqual({ ok: true, result: { opened: true } })
    const script = byName('cleanup.sh')
    expect(await store.open(script.ref, script.name)).toEqual({ ok: true, result: { opened: true } })
    expect(opened.map((p) => p.split('/').pop())).toEqual(['notes.txt', 'cleanup.sh'])
    expect(await store.reveal(script.ref, script.name)).toEqual({ ok: true, result: { revealed: true } })
    expect(revealed).toEqual([opened[1]])
  })

  it('saves where the user chose, replacing an existing file whole, and saves nothing when cancelled', async () => {
    const { store, byName } = await produced('save this file')
    const dir = scratch()
    const target = join(dir, 'saved-notes.txt')
    writeFileSync(target, 'an older file the user chose to replace')
    expect(await store.saveAs(byName('notes.txt').ref, target)).toEqual({ ok: true, result: { saved: true } })
    expect(readFileSync(target, 'utf8')).toBe('Generated notes\nline two\n')
    expect(readdirSync(dir)).toEqual(['saved-notes.txt'])
    expect(await store.saveAs(byName('notes.txt').ref, null)).toEqual({ ok: true, result: { saved: false } })
  })

  it('reports a write failure and a missing file without leaving partial files', async () => {
    const { store, byName } = await produced('one file')
    const dir = scratch()
    const missingDir = join(dir, 'gone', 'notes.txt')
    expect(await store.saveAs(byName('notes.txt').ref, missingDir)).toMatchObject({ ok: false, error: { code: 'internal' } })
    expect(existsSync(join(dir, 'gone'))).toBe(false)
    const target = join(dir, 'notes.txt')
    expect(await store.saveAs('f_missing', target)).toMatchObject({ ok: false, error: { code: 'not_found' } })
    expect(readdirSync(dir)).toEqual([])
  })

  it('refuses to load an image too large to show inline after the first chunk', async () => {
    const { store, byName, reads } = await produced('an image')
    expect(await store.fetchBytes(byName('chart.png').ref, 10)).toMatchObject({ ok: false, error: { code: 'too_large' } })
    expect(reads).toHaveLength(1)
  })

  it('pages a stored report without re-running anything', async () => {
    const { broker, byName } = await produced('report please')
    const report = byName('Health report')
    expect(report.kind).toBe('report')
    expect(await broker.request('reports.page', { report_id: report.ref, page: 2 })).toMatchObject({
      ok: true,
      result: { page: 2, pages: 3, text: '## Page 2\n\nStored result, page 2 of 3.' }
    })
    expect(await broker.request('reports.page', { report_id: report.ref, page: 9 })).toMatchObject({ ok: true, result: { page: 3 } })
  })

  it("finds messages by their files' names, and deleting the conversation deletes its files", async () => {
    const { broker, store, conversation, byName } = await produced('a script and a report')
    const found = (await broker.request('search.query', { query: 'cleanup.sh' })) as { ok: true; result: { hits: unknown[] } }
    expect(found.result.hits).toHaveLength(1)
    const listed = (await broker.request('conversations.list')) as { ok: true; result: { items: Array<{ id: string; rev: number }> } }
    const rev = listed.result.items.find((c) => c.id === conversation.id)!.rev
    expect(await broker.request('conversations.delete', { id: conversation.id, expected_rev: rev })).toMatchObject({ ok: true })
    expect(await store.fetchBytes(byName('cleanup.sh').ref)).toMatchObject({ ok: false, error: { code: 'not_found' } })
    expect(await broker.request('reports.page', { report_id: byName('Health report').ref, page: 1 })).toMatchObject({
      ok: false,
      error: { code: 'not_found' }
    })
  })
})

describe('file names written to disk', () => {
  it('has no separators, control characters or leading dots', () => {
    expect(safeFileName('../../etc/passwd')).toBe('_.._etc_passwd')
    expect(safeFileName('.bashrc')).toBe('bashrc')
    expect(safeFileName('a\u0000b\nc')).toBe('a_b_c')
    expect(safeFileName('...')).toBe('file')
    expect(safeFileName('x'.repeat(300))).toHaveLength(200)
  })
})
