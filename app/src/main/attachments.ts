// Files the user attaches. The main process reads them, never the window, and only files the user picked or dropped;
// it uploads each to the core in bounded chunks and gets back a core-owned reference (protocol.md, Attachments).
import { createHash, randomUUID } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { open, stat } from 'node:fs/promises'
import { basename, extname, isAbsolute } from 'node:path'
import type { AttachmentRef, CoreError, Result, StagedAttachment } from '../shared/api'
import type { Settled } from './broker'

export interface AttachmentLimits {
  attachment_bytes: number
  chunk_bytes: number
}

type Source = { kind: 'path'; path: string } | { kind: 'bytes'; data: Buffer }

interface Entry extends StagedAttachment {
  source: Source
  cancelled: boolean
  uploading: boolean
}

export interface Requester {
  request(method: string, params?: Record<string, unknown>, id?: string): Promise<Settled>
}

const TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.bmp': 'image/bmp',
  '.svg': 'image/svg+xml',
  '.pdf': 'application/pdf',
  '.txt': 'text/plain',
  '.md': 'text/markdown',
  '.log': 'text/plain',
  '.csv': 'text/csv',
  '.json': 'application/json',
  '.yaml': 'application/yaml',
  '.yml': 'application/yaml',
  '.xml': 'application/xml',
  '.html': 'text/html',
  '.py': 'text/x-python',
  '.js': 'text/javascript',
  '.ts': 'text/plain',
  '.sh': 'text/x-shellscript',
  '.zip': 'application/zip',
  '.gz': 'application/gzip',
  '.tar': 'application/x-tar',
  '.exe': 'application/x-msdownload'
}

export function mimeFor(name: string): string {
  return TYPES[extname(name).toLowerCase()] ?? 'application/octet-stream'
}

function failure(code: string, message: string): { ok: false; error: CoreError } {
  return { ok: false, error: { code, message, disposition: 'not_dispatched' } }
}

export class AttachmentManager extends EventEmitter {
  private readonly entries = new Map<string, Entry>()

  constructor(
    private readonly core: Requester,
    private readonly limits: () => AttachmentLimits
  ) {
    super()
  }

  /** A file the user picked or dropped. Only an absolute path to a regular file within the size limit is accepted. */
  async stagePath(path: string): Promise<Result<StagedAttachment>> {
    if (typeof path !== 'string' || !path || !isAbsolute(path)) return failure('bad_request', 'That file has no usable path.')
    let info
    try {
      info = await stat(path)
    } catch {
      return failure('not_found', `Can't read ${basename(path)}.`)
    }
    if (!info.isFile()) return failure('unsupported_type', `${basename(path)} isn't a regular file.`)
    const name = basename(path)
    return this.stage({ kind: 'path', path }, name, mimeFor(name), info.size)
  }

  /** Bytes the window already holds, such as a pasted image. */
  stageBytes(name: string, mime: string, data: Buffer): Result<StagedAttachment> {
    return this.stage({ kind: 'bytes', data }, name || 'pasted', mime || mimeFor(name), data.length)
  }

  private stage(source: Source, name: string, mime: string, size: number): Result<StagedAttachment> {
    if (size < 0) return failure('bad_request', `${name} has no size.`) // empty files are fine, as in Odin
    const limit = this.limits().attachment_bytes
    if (size > limit) return failure('too_large', `${name} is larger than the ${Math.round(limit / (1024 * 1024))} MiB limit.`)
    const entry: Entry = { id: randomUUID(), name, mime, size, source, cancelled: false, uploading: false }
    this.entries.set(entry.id, entry)
    return { ok: true, result: { id: entry.id, name, mime, size } }
  }

  /** Uploads a staged attachment and returns the core's reference. Progress is emitted as 'progress'. */
  async upload(id: string, conversationId: string): Promise<Result<AttachmentRef>> {
    const entry = this.entries.get(id)
    if (!entry) return failure('not_found', 'That attachment is gone; attach it again.')
    if (entry.uploading) return failure('busy', 'That attachment is already uploading.')
    entry.uploading = true
    let uploadId: string | undefined
    const cancelUpload = async (): Promise<void> => {
      if (!uploadId) return
      // Cancellation is best-effort cleanup, not a reason to hide the original
      // failed/unknown receipt. An unreachable core expires the upload itself.
      try { await this.core.request('attachments.cancel', { upload_id: uploadId }) } catch { /* core TTL owns cleanup */ }
    }
    try {
      const begun = await this.core.request('attachments.begin', {
        client_attachment_id: entry.id,
        conversation_id: conversationId,
        name: entry.name,
        size: entry.size,
        mime: entry.mime
      })
      if (!begun.ok) return this.drop(id, begun)
      const { upload_id: begunId, chunk_bytes: offered } = begun.result as { upload_id: string; chunk_bytes: number }
      uploadId = begunId
      // From here on, any way out other than a commit cancels the upload in the core.
      const abandon = async <T>(result: Result<T>): Promise<Result<T>> => {
        await cancelUpload()
        return this.drop(id, result)
      }
      const chunkBytes = Math.max(1, Math.min(offered || this.limits().chunk_bytes, this.limits().chunk_bytes))
      const digest = createHash('sha256')
      let offset = 0
      try {
        for await (const chunk of this.chunks(entry, chunkBytes)) {
          if (entry.cancelled) return abandon(failure('cancelled', 'Attachment cancelled.'))
          digest.update(chunk)
          const sent = await this.core.request('attachments.chunk', { upload_id: uploadId, offset, data_b64: chunk.toString('base64') })
          if (!sent.ok) return abandon(sent)
          offset += chunk.length
          this.emit('progress', { id, sent: offset, size: entry.size })
        }
      } catch {
        return abandon(failure('internal', `Couldn't read ${entry.name}.`))
      }
      if (offset !== entry.size) return abandon(failure('bad_request', `${entry.name} changed while it was being attached.`))
      // A cancel that came during the last chunk still wins: nothing is committed after it.
      if (entry.cancelled) return abandon(failure('cancelled', 'Attachment cancelled.'))
      const committed = await this.core.request('attachments.commit', { upload_id: uploadId, sha256: digest.digest('hex') })
      if (!committed.ok) return abandon(committed)
      this.entries.delete(id)
      return { ok: true, result: (committed.result as { attachment: AttachmentRef }).attachment }
    } catch {
      await cancelUpload()
      return this.drop(id, failure('internal', `Couldn't attach ${entry.name}.`))
    } finally {
      entry.uploading = false
    }
  }

  /** Forgets a staged attachment, including any bytes it holds, and passes the failure on. */
  private drop<T>(id: string, result: Result<T>): Result<T> {
    this.entries.delete(id)
    return result
  }

  /** Stops an upload between chunks, or drops an attachment that hasn't started. */
  cancel(id: string): void {
    const entry = this.entries.get(id)
    if (!entry) return
    if (entry.uploading) entry.cancelled = true
    else this.entries.delete(id)
  }

  private async *chunks(entry: Entry, size: number): AsyncGenerator<Buffer> {
    if (entry.source.kind === 'bytes') {
      for (let at = 0; at < entry.source.data.length; at += size) yield entry.source.data.subarray(at, at + size)
      return
    }
    const handle = await open(entry.source.path, 'r')
    try {
      for (;;) {
        const buffer = Buffer.alloc(size)
        const { bytesRead } = await handle.read(buffer, 0, size, null)
        if (bytesRead === 0) return
        yield buffer.subarray(0, bytesRead)
      }
    } finally {
      await handle.close()
    }
  }
}
