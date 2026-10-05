// The composer's attachments and drafts, driven through a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AttachmentProgress, AttachmentRef, Result } from '../../src/shared/api'

type Composer = typeof import('../../src/renderer/src/stores/composer')

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
    getDraft: async (id: string) => ({ ok: true, result: { text: id === 'c1' ? 'saved draft' : '' } }),
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
