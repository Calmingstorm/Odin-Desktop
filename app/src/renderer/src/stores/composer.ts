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

/** How many attachments one message may carry, as the core announces it; null until known. */
let perTurn: number | null = null

async function perTurnLimit(): Promise<number | null> {
  if (perTurn !== null) return perTurn
  const status = await window.odin.status()
  const announced = status.ok ? status.result.limits?.attachments_per_turn : undefined
  if (typeof announced === 'number' && announced > 0) perTurn = announced
  return perTurn
}

/** Places granted to attachments still on their way into the composer, by conversation. */
const reserved = new Map<string, number>()

function release(conversationId: string): void {
  const left = (reserved.get(conversationId) ?? 0) - 1
  if (left > 0) reserved.set(conversationId, left)
  else reserved.delete(conversationId)
}

/**
 * Keeps a batch within the core's per-turn limit, saying honestly what didn't fit. The places it grants are reserved
 * at once, so batches added at the same time can't share one; each is released as its attachment arrives or fails.
 */
async function fitting<T>(conversationId: string, items: readonly T[]): Promise<readonly T[]> {
  const limit = await perTurnLimit()
  const used = attachmentsFor(conversationId).length + (reserved.get(conversationId) ?? 0)
  const room = limit === null ? items.length : Math.max(0, limit - used)
  const kept = items.slice(0, room)
  reserved.set(conversationId, (reserved.get(conversationId) ?? 0) + kept.length)
  if (limit !== null && items.length > room) {
    composer.errors = [
      ...composer.errors,
      `Odin takes up to ${limit} attachment${limit === 1 ? '' : 's'} per message; ${items.length - room} weren't added.`
    ]
  }
  return kept
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
/** Each draft's revision. Every change moves it on, so what finishes late clears a draft only if nothing touched it since. */
const revisions = new Map<string, number>()

export function draftRevision(conversationId: string): number {
  return revisions.get(conversationId) ?? 0
}

/** Keeps the draft in memory now and in the profile shortly after typing stops. */
export function saveDraft(conversationId: string, text: string): void {
  revisions.set(conversationId, draftRevision(conversationId) + 1)
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
  for (const image of await fitting(conversationId, images)) {
    try {
      const staged = await window.odin.attachBytes({
        name: image.name || `pasted-image.${image.type.split('/')[1] ?? 'png'}`,
        mime: image.type,
        data: new Uint8Array(await image.arrayBuffer())
      })
      if (staged.ok) start(conversationId, staged.result, URL.createObjectURL(image))
      else composer.errors = [staged.error.message]
    } finally {
      release(conversationId)
    }
  }
}

async function addBatch(conversationId: string, batch: Result<StagedBatch>, files: readonly File[]): Promise<void> {
  if (!batch.ok) {
    composer.errors = [batch.error.message]
    return
  }
  composer.errors = batch.result.errors
  const kept = await fitting(conversationId, batch.result.staged)
  for (const staged of batch.result.staged) if (!kept.includes(staged)) void window.odin.cancelAttachment(staged.id)
  for (const staged of kept) {
    const source = files.find((f) => f.name === staged.name && f.size === staged.size)
    const preview = source && source.type.startsWith('image/') ? URL.createObjectURL(source) : undefined
    start(conversationId, staged, preview)
    release(conversationId)
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

/** Removes an attachment from the composer: stops its upload, and releases what the main process holds for it. */
export function removeAttachment(conversationId: string, id: string): void {
  void window.odin.cancelAttachment(id)
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

/**
 * What the composer box shows, and the conversation it belongs to: none while switching, so nothing is sent to the
 * wrong one. `pending` is the conversation whose draft is loading; what is typed meanwhile is that draft.
 */
export const box = reactive({ owner: null as string | null, pending: null as string | null, text: '' })

/** Shows a conversation's draft once it has loaded, unless the user has moved on by then. */
export async function showDraft(conversationId: string | null, stillCurrent: () => boolean): Promise<void> {
  box.owner = null
  box.pending = conversationId
  box.text = '' // the previous draft is already saved under its own conversation
  if (!conversationId) return
  // Typing during the load is saved as this draft, so the loaded text is whatever was typed, if anything was.
  const draft = await loadDraft(conversationId)
  if (!stillCurrent()) return
  box.pending = null
  box.text = draft
  box.owner = conversationId
}

/** The user typed: the text is the draft of the conversation the box belongs to, or is loading. */
export function edit(text: string): void {
  box.text = text
  const target = box.owner ?? box.pending
  if (target) saveDraft(target, text)
}

/** After a send or a command, clears the draft it came from, only if nothing touched it since; the box follows. */
export function clearSubmitted(conversationId: string, revision: number): void {
  if (draftRevision(conversationId) !== revision) return
  saveDraft(conversationId, '')
  if (box.owner === conversationId) box.text = ''
}

/** Runs a slash command typed in the box. Once it has run, only the draft it came from is cleared, if untouched. */
export async function runBoxCommand<T>(run: () => Promise<T>): Promise<T> {
  const owner = box.owner ?? box.pending
  const revision = owner ? draftRevision(owner) : -1
  const submitted = box.text
  const outcome = await run()
  if (outcome === false) return outcome
  if (owner) clearSubmitted(owner, revision)
  else if (!box.owner && !box.pending && box.text === submitted) box.text = '' // no conversation, so nothing saved
  return outcome
}

/**
 * Sends the box's text and attachments to the conversation it belongs to, which must be the open one. Afterwards
 * only what was sent goes: the draft if it is still the text that was sent, and the attachments sent with it.
 */
export async function sendBox(
  openConversation: string | null,
  deliver: (text: string, attachments: Array<{ ref: string; add_to_knowledge: boolean }>) => Promise<boolean>
): Promise<boolean> {
  const conversationId = box.owner
  if (!conversationId || conversationId !== openConversation) return false
  const refs = readyAttachments(conversationId)
  if (refs === null) return false
  const revision = draftRevision(conversationId)
  const sentIds = attachmentsFor(conversationId).map((a) => a.id)
  const accepted = await deliver(box.text.trim(), refs)
  if (!accepted) return false
  clearSubmitted(conversationId, revision)
  removeSent(conversationId, sentIds)
  return true
}

/** After a send, removes exactly the attachments that went with it; any added since stay. */
export function removeSent(conversationId: string, ids: readonly string[]): void {
  for (const id of ids) remove(conversationId, id)
}
