import { createHash } from 'node:crypto'
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
    expect(reads.length).toBe(fetched + 1) // a later use checks with the core once, without downloading again
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

describe('review round 1: the private cache follows the core', () => {
  /** A core that serves each reference's own bytes, and can forget one. */
  function fakeCore(files: Record<string, string>) {
    const reads: string[] = []
    const requester: Requester = {
      request: async (method, params) => {
        const ref = String(params?.ref)
        reads.push(ref)
        if (method !== 'artifacts.read' || !(ref in files)) {
          return { ok: false, error: { code: 'not_found', message: 'that file is no longer available', disposition: 'not_dispatched' } }
        }
        const data = Buffer.from(files[ref]!)
        const offset = Number(params?.offset ?? 0)
        const chunk = data.subarray(offset, offset + Number(params?.length ?? data.length))
        return { ok: true, result: { data_b64: chunk.toString('base64'), size: data.length, eof: offset + chunk.length >= data.length } }
      }
    }
    return { requester, reads }
  }

  function storeFor(requester: Requester) {
    const cache = scratch()
    const opened: string[] = []
    const revealed: string[] = []
    const store = new ArtifactStore(requester, cache, () => 1024, {
      openPath: async (path) => (opened.push(path), ''),
      showItemInFolder: (path) => void revealed.push(path)
    })
    return { store, cache, opened, revealed }
  }

  /** The fake core, with reads that wait for the test: one-byte checks, or the chunks of a download. */
  function holdingCore(files: Record<string, string>) {
    const { requester } = fakeCore(files)
    const hold = { checks: false, chunks: false }
    const held: Array<() => void> = []
    const holding: Requester = {
      request: async (method, params) => {
        const check = Number(params?.length) === 1
        if ((check && hold.checks) || (!check && hold.chunks)) await new Promise<void>((resolve) => held.push(resolve))
        return requester.request(method, params)
      }
    }
    return { requester: holding, hold, held }
  }

  it('keeps references that a file name would make alike apart', async () => {
    const { requester } = fakeCore({ '.ref': 'first', ref: 'second' })
    const { store } = storeFor(requester)
    const first = await store.cached('.ref', 'notes.txt')
    const second = await store.cached('ref', 'notes.txt')
    if (!first.ok || !second.ok) throw new Error('not cached')
    expect(first.result).not.toBe(second.result)
    expect(readFileSync(first.result, 'utf8')).toBe('first')
    expect(readFileSync(second.result, 'utf8')).toBe('second')
  })

  it('checks a cached copy with the core each time, and drops it once the core no longer has the file', async () => {
    const files: Record<string, string> = { f1: 'kept here' }
    const { requester } = fakeCore(files)
    const { store, opened } = storeFor(requester)
    const cached = await store.cached('f1', 'notes.txt')
    if (!cached.ok) throw new Error('not cached')
    expect(await store.open('f1', 'notes.txt')).toEqual({ ok: true, result: { opened: true } })
    delete files.f1
    expect(await store.open('f1', 'notes.txt')).toMatchObject({ ok: false, error: { code: 'not_found' } })
    expect(opened).toHaveLength(1)
    expect(existsSync(cached.result)).toBe(false)
  })

  it('forgets a cached copy when the core says the file is unavailable', async () => {
    const { requester } = fakeCore({ f2: 'soon gone' })
    const { store } = storeFor(requester)
    const cached = await store.cached('f2', 'notes.txt')
    if (!cached.ok) throw new Error('not cached')
    await store.forget('f2')
    expect(existsSync(cached.result)).toBe(false)
  })

  it('reports a file forgotten during its check as gone, and never reveals it', async () => {
    const { requester, hold, held } = holdingCore({ f3: 'cached' })
    const { store, revealed } = storeFor(requester)
    expect((await store.cached('f3', 'notes.txt')).ok).toBe(true)
    hold.checks = true
    const revealing = store.reveal('f3', 'notes.txt')
    await waitFor(() => held.length === 1)
    await store.forget('f3')
    held[0]!()
    expect(await revealing).toEqual({ ok: false, error: { code: 'not_found', message: 'That file is no longer available.', disposition: 'not_dispatched' } })
    expect(revealed).toEqual([])
  })

  it('never puts a file forgotten during its download into the cache', async () => {
    const { requester, hold, held } = holdingCore({ f4: 'arriving' })
    const { store, cache } = storeFor(requester)
    hold.chunks = true
    const filling = store.cached('f4', 'notes.txt')
    await waitFor(() => held.length === 1)
    await store.forget('f4')
    held[0]!()
    expect(await filling).toMatchObject({ ok: false, error: { code: 'not_found' } })
    expect(existsSync(join(cache, 'artifacts', createHash('sha256').update('f4').digest('hex')))).toBe(false)
  })

  it('checks a file with one byte, and forgets one the core no longer has', async () => {
    const files: Record<string, string> = { f5: 'here' }
    const { requester } = fakeCore(files)
    const { store } = storeFor(requester)
    const cached = await store.cached('f5', 'notes.txt')
    if (!cached.ok) throw new Error('not cached')
    expect(await store.check('f5')).toEqual({ ok: true, result: { available: true } })
    delete files.f5
    expect(await store.check('f5')).toEqual({ ok: true, result: { available: false } })
    expect(existsSync(cached.result)).toBe(false)
  })
})
