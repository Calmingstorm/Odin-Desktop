// The composer's per-conversation state: the saved draft and the attachments waiting to be sent.
// Attachments upload as soon as they are added, so sending is quick; nothing is sent while one is still uploading or
// has failed, and the user always decides whether an attachment goes into knowledge.
import { reactive } from 'vue'
import type { AttachmentProgress, Result, StagedAttachment, StagedBatch } from '../../../shared/api'

export interface ComposerAttachment {
  id: string
  name: string
  size: number
  mime: string
  /** A blob: URL for an image the window already holds; picked files have none. */
  previewUrl?: string
  status: 'uploading' | 'ready' | 'failed'
  sent: number
  ref?: string
  error?: string
  addToKnowledge: boolean
}

export const composer = reactive({
  attachments: {} as Record<string, ComposerAttachment[] | undefined>,
  drafts: {} as Record<string, string | undefined>,
  /** Why the last files couldn't be attached, until the next attempt. */
  errors: [] as string[]
})

let listening = false

function listen(): void {
  if (listening) return
  listening = true
  window.odin.onAttachmentProgress((progress: AttachmentProgress) => {
    for (const list of Object.values(composer.attachments)) {
      const item = list?.find((a) => a.id === progress.id)
      if (item) item.sent = progress.sent
    }
  })
}

export function attachmentsFor(conversationId: string | null): ComposerAttachment[] {
  return conversationId ? (composer.attachments[conversationId] ?? []) : []
}

export async function loadDraft(conversationId: string): Promise<string> {
  const known = composer.drafts[conversationId]
  if (known !== undefined) return known
  const loaded = await window.odin.getDraft(conversationId)
  const text = loaded.ok ? loaded.result.text : ''
  composer.drafts[conversationId] ??= text
  return composer.drafts[conversationId] ?? ''
}

const saveTimers = new Map<string, ReturnType<typeof setTimeout>>()

/** Keeps the draft in memory now and in the profile shortly after typing stops. */
export function saveDraft(conversationId: string, text: string): void {
  composer.drafts[conversationId] = text
  const pending = saveTimers.get(conversationId)
  if (pending) clearTimeout(pending)
  saveTimers.set(
    conversationId,
    setTimeout(() => {
      saveTimers.delete(conversationId)
      void window.odin.setDraft(conversationId, text)
    }, 300)
  )
}

/** Files dropped on the composer or chosen in the system picker. */
export async function addFiles(conversationId: string, files: readonly File[]): Promise<void> {
  listen()
  await addBatch(conversationId, await window.odin.attachFiles(files), files)
}

export async function pickFiles(conversationId: string): Promise<void> {
  listen()
  await addBatch(conversationId, await window.odin.pickFiles(), [])
}

/** Clipboard images have no file on disk, so their bytes are attached directly; pasted files keep their path. */
export async function addPasted(conversationId: string, files: readonly File[]): Promise<void> {
  listen()
  const images = files.filter((f) => f.type.startsWith('image/'))
  const others = files.filter((f) => !f.type.startsWith('image/'))
  if (others.length) await addFiles(conversationId, others)
  for (const image of images) {
    const staged = await window.odin.attachBytes({
      name: image.name || `pasted-image.${image.type.split('/')[1] ?? 'png'}`,
      mime: image.type,
      data: new Uint8Array(await image.arrayBuffer())
    })
    if (staged.ok) start(conversationId, staged.result, URL.createObjectURL(image))
    else composer.errors = [staged.error.message]
  }
}

async function addBatch(conversationId: string, batch: Result<StagedBatch>, files: readonly File[]): Promise<void> {
  if (!batch.ok) {
    composer.errors = [batch.error.message]
    return
  }
  composer.errors = batch.result.errors
  for (const staged of batch.result.staged) {
    const source = files.find((f) => f.name === staged.name && f.size === staged.size)
    const preview = source && source.type.startsWith('image/') ? URL.createObjectURL(source) : undefined
    start(conversationId, staged, preview)
  }
}

function start(conversationId: string, staged: StagedAttachment, previewUrl?: string): void {
  // Push through the reactive object, so the composer sees the new attachment.
  if (!composer.attachments[conversationId]) composer.attachments[conversationId] = []
  composer.attachments[conversationId]!.push({ ...staged, previewUrl, status: 'uploading', sent: 0, addToKnowledge: false })
  void upload(conversationId, staged.id)
}

async function upload(conversationId: string, id: string): Promise<void> {
  const result = await window.odin.uploadAttachment({ id, conversation_id: conversationId })
  const item = composer.attachments[conversationId]?.find((a) => a.id === id)
  if (!item) return // removed while uploading
  if (result.ok) {
    item.status = 'ready'
    item.ref = result.result.ref
    item.sent = item.size
  } else if (result.error.code === 'cancelled') remove(conversationId, id)
  else {
    item.status = 'failed'
    item.error = result.error.message
  }
}

export function setKnowledge(conversationId: string, id: string, value: boolean): void {
  const item = composer.attachments[conversationId]?.find((a) => a.id === id)
  if (item) item.addToKnowledge = value
}

/** Removes an attachment from the composer, stopping its upload if it is still running. */
export function removeAttachment(conversationId: string, id: string): void {
  const item = composer.attachments[conversationId]?.find((a) => a.id === id)
  if (item?.status === 'uploading') void window.odin.cancelAttachment(id)
  remove(conversationId, id)
}

function remove(conversationId: string, id: string): void {
  const list = composer.attachments[conversationId]
  const item = list?.find((a) => a.id === id)
  if (item?.previewUrl) URL.revokeObjectURL(item.previewUrl)
  composer.attachments[conversationId] = list?.filter((a) => a.id !== id)
}

/** The attachments to send, or null while any is still uploading or has failed. */
export function readyAttachments(conversationId: string): Array<{ ref: string; add_to_knowledge: boolean }> | null {
  const list = attachmentsFor(conversationId)
  if (list.some((a) => a.status !== 'ready' || !a.ref)) return null
  return list.map((a) => ({ ref: a.ref as string, add_to_knowledge: a.addToKnowledge }))
}

export function clearAttachments(conversationId: string): void {
  for (const item of attachmentsFor(conversationId)) if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
  composer.attachments[conversationId] = []
}
