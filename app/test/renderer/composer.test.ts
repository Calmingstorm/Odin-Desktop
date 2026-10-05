// The composer's attachments and drafts, driven through a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AttachmentProgress, AttachmentRef, Result } from '../../src/shared/api'

type Composer = typeof import('../../src/renderer/src/stores/composer')

let holdDrafts = false
let heldDrafts: Array<() => void> = []
let drafts: Record<string, string> = {}
let perTurn = 10

function fakeBridge() {
  const uploads: Array<{ id: string; resolve: (r: Result<AttachmentRef>) => void }> = []
  const progress: Array<(p: AttachmentProgress) => void> = []
  const calls = { cancel: [] as string[], setDraft: [] as Array<[string, string]>, attachBytes: [] as Array<{ name: string; mime: string }> }
  const api = {
    attachFiles: async (files: readonly File[]) => ({
      ok: true,
      result: { staged: files.map((f) => ({ id: `id-${f.name}`, name: f.name, mime: f.type || 'application/octet-stream', size: f.size })), errors: [] }
    }),
    pickFiles: async () => ({
      ok: true,
      result: { staged: [{ id: 'id-picked', name: 'picked.pdf', mime: 'application/pdf', size: 10 }], errors: ["shortcut.lnk isn't a regular file."] }
    }),
    attachBytes: async (p: { name: string; mime: string; data: Uint8Array }) => {
      calls.attachBytes.push({ name: p.name, mime: p.mime })
      return { ok: true, result: { id: 'id-pasted', name: p.name, mime: p.mime, size: p.data.length } }
    },
    uploadAttachment: (p: { id: string }) => new Promise<Result<AttachmentRef>>((resolve) => uploads.push({ id: p.id, resolve })),
    cancelAttachment: async (id: string) => {
      calls.cancel.push(id)
      return { ok: true, result: { cancelled: true } }
    },
    onAttachmentProgress: (listener: (p: AttachmentProgress) => void) => (progress.push(listener), () => undefined),
    getDraft: (id: string) => {
      const answer = { ok: true, result: { text: drafts[id] ?? (id === 'c1' ? 'saved draft' : '') } }
      if (!holdDrafts) return Promise.resolve(answer)
      return new Promise((resolve) => heldDrafts.push(() => resolve(answer)))
    },
    status: async () => ({
      ok: true,
      result: { phase: 'ready', core_instance_id: 'core', version: 'test', capabilities: [], limits: { chunk_bytes: 1024, attachment_bytes: 1 << 20, attachments_per_turn: perTurn } }
    }),
    setDraft: async (id: string, text: string) => {
      calls.setDraft.push([id, text])
      return { ok: true, result: { saved: true } }
    }
  }
  return { api, uploads, progress, calls }
}

let composer: Composer
let bridge: ReturnType<typeof fakeBridge>

const file = (name: string, size: number, type = 'text/plain'): File => new File([new Uint8Array(size)], name, { type })
const uploaded = (id: string): Result<AttachmentRef> => ({ ok: true, result: { ref: `ref-${id}`, name: id, mime: 'text/plain', size: 1 } })

async function until(check: () => boolean): Promise<void> {
  for (let i = 0; i < 300; i++) {
    if (check()) return
    await new Promise((r) => setTimeout(r, 2))
  }
  throw new Error('timed out waiting for condition')
}

beforeEach(async () => {
  vi.resetModules()
  holdDrafts = false
  heldDrafts = []
  drafts = {}
  perTurn = 10
  bridge = fakeBridge()
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge.api }
  composer = await import('../../src/renderer/src/stores/composer')
})

describe('composer attachments', () => {
  it('uploads as soon as files are added, shows progress, and holds sending until every upload is done', async () => {
    await composer.addFiles('c1', [file('a.txt', 10), file('b.txt', 20)])
    expect(bridge.uploads.map((u) => u.id)).toEqual(['id-a.txt', 'id-b.txt'])
    expect(composer.readyAttachments('c1')).toBeNull()
    bridge.progress.forEach((l) => l({ id: 'id-a.txt', sent: 5, size: 10 }))
    expect(composer.attachmentsFor('c1')[0]!.sent).toBe(5)
    for (const u of bridge.uploads) u.resolve(uploaded(u.id))
    await until(() => composer.attachmentsFor('c1').every((a) => a.status === 'ready'))
    composer.setKnowledge('c1', 'id-b.txt', true)
    expect(composer.readyAttachments('c1')).toEqual([
      { ref: 'ref-id-a.txt', add_to_knowledge: false },
      { ref: 'ref-id-b.txt', add_to_knowledge: true }
    ])
    expect(composer.readyAttachments('c2')).toEqual([]) // each conversation has its own
  })

  it('blocks sending after a failed upload until that attachment is removed', async () => {
    await composer.addFiles('c1', [file('big.bin', 30)])
    bridge.uploads[0]!.resolve({ ok: false, error: { code: 'too_large', message: 'big.bin is larger than the 25 MiB limit.' } })
    await until(() => composer.attachmentsFor('c1')[0]?.status === 'failed')
    expect(composer.attachmentsFor('c1')[0]!.error).toMatch(/larger than/)
    expect(composer.readyAttachments('c1')).toBeNull()
    composer.removeAttachment('c1', 'id-big.bin')
    expect(composer.readyAttachments('c1')).toEqual([])
  })

  it('cancels an upload that is removed while it runs, and ignores its late answer', async () => {
    await composer.addFiles('c1', [file('a.txt', 10)])
    composer.removeAttachment('c1', 'id-a.txt')
    expect(bridge.calls.cancel).toEqual(['id-a.txt'])
    bridge.uploads[0]!.resolve(uploaded('id-a.txt'))
    await new Promise((r) => setTimeout(r, 5))
    expect(composer.attachmentsFor('c1')).toEqual([])
  })

  it('attaches pasted images as bytes, and shows why a picked file was refused', async () => {
    await composer.addPasted('c1', [file('', 4, 'image/png')])
    expect(bridge.calls.attachBytes).toEqual([{ name: 'pasted-image.png', mime: 'image/png' }])
    await composer.pickFiles('c1')
    expect(composer.composer.errors).toEqual(["shortcut.lnk isn't a regular file."])
    expect(composer.attachmentsFor('c1').map((a) => a.name)).toEqual(['pasted-image.png', 'picked.pdf'])
  })
})

describe('composer drafts', () => {
  it('loads a conversation’s saved draft and saves once typing pauses', async () => {
    expect(await composer.loadDraft('c1')).toBe('saved draft')
    composer.saveDraft('c1', 'x')
    composer.saveDraft('c1', 'xy')
    expect(await composer.loadDraft('c1')).toBe('xy') // the in-memory draft wins over the stored one
    await until(() => bridge.calls.setDraft.length === 1)
    expect(bridge.calls.setDraft).toEqual([['c1', 'xy']])
  })
})

describe('review round 1: the box belongs to one conversation', () => {
  const ready = async (conversationId: string, name: string): Promise<void> => {
    await composer.addFiles(conversationId, [file(name, 5)])
    const upload = bridge.uploads.find((u) => u.id === `id-${name}`)!
    upload.resolve(uploaded(upload.id))
    await until(() => composer.attachmentsFor(conversationId).every((a) => a.status === 'ready'))
  }

  it("never sends a draft while the next conversation's draft is loading", async () => {
    let open = 'cA'
    drafts = { cA: 'A draft', cB: 'B draft' }
    await composer.showDraft('cA', () => open === 'cA')
    holdDrafts = true
    open = 'cB'
    const showing = composer.showDraft('cB', () => open === 'cB')
    const sent: string[] = []
    expect(await composer.sendBox('cB', async (text) => (sent.push(text), true))).toBe(false)
    expect(composer.box.owner).toBeNull()
    heldDrafts.forEach((release) => release())
    await showing
    expect(await composer.sendBox('cB', async (text) => (sent.push(text), true))).toBe(true)
    expect(sent).toEqual(['B draft'])
  })

  it('clears only what a late send carried: newer text and newer attachments stay', async () => {
    drafts = { cA: 'hello' }
    await composer.showDraft('cA', () => true)
    await ready('cA', 'first.txt')
    let accept!: (value: boolean) => void
    const sending = composer.sendBox('cA', () => new Promise((resolve) => (accept = resolve)))
    composer.edit('hello world')
    await ready('cA', 'second.txt')
    accept(true)
    expect(await sending).toBe(true)
    expect(composer.box.text).toBe('hello world')
    expect(composer.composer.drafts.cA).toBe('hello world')
    expect(composer.attachmentsFor('cA').map((a) => a.name)).toEqual(['second.txt'])
  })

  it("leaves the open conversation's draft alone when an earlier one's send settles late", async () => {
    let open = 'cA'
    drafts = { cA: 'for A', cB: 'for B' }
    await composer.showDraft('cA', () => open === 'cA')
    let accept!: (value: boolean) => void
    const sending = composer.sendBox('cA', () => new Promise((resolve) => (accept = resolve)))
    open = 'cB'
    await composer.showDraft('cB', () => open === 'cB')
    accept(true)
    await sending
    expect(composer.box).toMatchObject({ owner: 'cB', text: 'for B' })
    expect(composer.composer.drafts.cA).toBe('')
    expect(composer.composer.drafts.cB).toBe('for B')
  })
})

describe('review round 1: attachment limits and cleanup', () => {
  it("adds no more than the core's per-turn limit, and says how many didn't fit", async () => {
    perTurn = 2
    await composer.addFiles('c1', [file('a.txt', 1), file('b.txt', 1), file('c.txt', 1)])
    expect(composer.attachmentsFor('c1').map((a) => a.name)).toEqual(['a.txt', 'b.txt'])
    expect(composer.composer.errors.join(' ')).toMatch(/up to 2 attachments per message; 1 weren't added/)
    expect(bridge.calls.cancel).toEqual(['id-c.txt']) // the one that didn't fit is released, not left staged
  })

  it('releases what the main process holds when a failed attachment is removed', async () => {
    await composer.addFiles('c1', [file('broken.bin', 3)])
    bridge.uploads[0]!.resolve({ ok: false, error: { code: 'internal', message: "Couldn't read broken.bin." } })
    await until(() => composer.attachmentsFor('c1')[0]?.status === 'failed')
    composer.removeAttachment('c1', 'id-broken.bin')
    expect(bridge.calls.cancel).toEqual(['id-broken.bin'])
  })
})

