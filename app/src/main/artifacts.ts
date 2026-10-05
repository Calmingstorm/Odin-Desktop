// Files Odin produced, by core reference (protocol.md, Results). The main process fetches them in bounded chunks and
// keeps a private copy in the profile cache (owner-only), which it opens, saves or reveals. The window never executes
// their content; it shows images and offers files.
import { createHash, randomBytes } from 'node:crypto'
import { once } from 'node:events'
import { createWriteStream } from 'node:fs'
import { mkdir, rename, rm, stat } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { finished } from 'node:stream/promises'
import type { CoreError, Result } from '../shared/api'
import type { Requester } from './attachments'

/** Images larger than this are offered as files instead of being shown inline. */
export const INLINE_IMAGE_BYTES = 20 * 1024 * 1024

export interface DesktopActions {
  openPath(path: string): Promise<string>
  showItemInFolder(path: string): void
}

type Failure = { ok: false; error: CoreError }

function failure(code: string, message: string): Failure {
  return { ok: false, error: { code, message, disposition: 'not_dispatched' } }
}

/** The core said the file is gone while it was being fetched or checked. */
const GONE = failure('not_found', 'That file is no longer available.')

/** A file name safe to create in a directory: no separators, control characters or leading dots. */
export function safeFileName(name: string): string {
  const cleaned = name
    .replace(/[\\/\u0000-\u001f\u007f]/g, '_')
    .replace(/^\.+/, '')
    .trim()
    .slice(0, 200)
  return cleaned || 'file'
}

export class ArtifactStore {
  /** Cache fills in progress, so a second request for the same file waits for the first. */
  private readonly filling = new Map<string, Promise<Result<string>>>()
  /** How many times each reference was forgotten. A fill that started before the latest one never reports success. */
  private readonly generations = new Map<string, number>()

  constructor(
    private readonly core: Requester,
    private readonly cacheDir: string,
    private readonly chunkBytes: () => number,
    private readonly desktop: DesktopActions
  ) {}

  /** The whole artifact in memory, for showing an image inline. */
  async fetchBytes(ref: string, maxBytes = INLINE_IMAGE_BYTES): Promise<Result<Buffer>> {
    const parts: Buffer[] = []
    let total = 0
    const done = await this.read(ref, async (chunk, size) => {
      if (size > maxBytes) return failure('too_large', 'Too large to show here; open or save it instead.')
      parts.push(chunk)
      total += chunk.length
      return null
    })
    if (!done.ok) return done
    return { ok: true, result: Buffer.concat(parts, total) }
  }

  /** Each reference gets its own cache directory: a hash of the exact reference, so distinct ones never collide. */
  private dirFor(ref: string): string {
    return join(this.cacheDir, 'artifacts', createHash('sha256').update(ref).digest('hex'))
  }

  private generationOf(ref: string): number {
    return this.generations.get(ref) ?? 0
  }

  /** Drops the cached copy of a file the core no longer has. Fills still on their way for it report it gone. */
  async forget(ref: string): Promise<void> {
    this.generations.set(ref, this.generationOf(ref) + 1)
    await rm(this.dirFor(ref), { recursive: true, force: true })
  }

  /** Whether the core still has a file: one byte read. A file it no longer has is forgotten here too. */
  async check(ref: string): Promise<Result<{ available: boolean }>> {
    const answer = await this.core.request('artifacts.read', { ref, offset: 0, length: 1 })
    if (answer.ok) return { ok: true, result: { available: true } }
    if (answer.error.code !== 'not_found' && answer.error.code !== 'expired') return answer
    await this.forget(ref)
    return { ok: true, result: { available: false } }
  }

  /** The private cached copy, fetched once and checked with the core each time it is used. */
  cached(ref: string, name: string): Promise<Result<string>> {
    const path = join(this.dirFor(ref), safeFileName(name))
    const pending = this.filling.get(path)
    if (pending) return pending
    const fill = this.fill(ref, path).finally(() => this.filling.delete(path))
    this.filling.set(path, fill)
    return fill
  }

  /** Opens the cached copy in the desktop's default app for its type. */
  async open(ref: string, name: string): Promise<Result<{ opened: boolean }>> {
    const path = await this.cached(ref, name)
    if (!path.ok) return path
    const problem = await this.desktop.openPath(path.result)
    return problem ? failure('internal', problem) : { ok: true, result: { opened: true } }
  }

  async reveal(ref: string, name: string): Promise<Result<{ revealed: boolean }>> {
    const path = await this.cached(ref, name)
    if (!path.ok) return path
    this.desktop.showItemInFolder(path.result)
    return { ok: true, result: { revealed: true } }
  }

  /** Writes a copy where the user chose. A cancelled dialog saves nothing. */
  async saveAs(ref: string, target: string | null): Promise<Result<{ saved: boolean }>> {
    if (!target) return { ok: true, result: { saved: false } }
    const written = await this.download(ref, target, 0o644)
    return written.ok ? { ok: true, result: { saved: true } } : written
  }

  private async fill(ref: string, path: string): Promise<Result<string>> {
    const generation = this.generationOf(ref)
    const current = (): boolean => this.generationOf(ref) === generation
    let present = false
    try {
      present = (await stat(path)).isFile()
    } catch {
      /* not cached yet */
    }
    if (present) {
      // A copy is only as good as the core's reference: one deleted or expired since is gone here too.
      const check = await this.core.request('artifacts.read', { ref, offset: 0, length: 1 })
      if (!current()) return GONE
      if (check.ok) return { ok: true, result: path }
      if (check.error.code === 'not_found' || check.error.code === 'expired') await this.forget(ref)
      return check
    }
    await mkdir(dirname(path), { recursive: true, mode: 0o700 })
    return this.download(ref, path, 0o600, current)
  }

  /**
   * Writes to a new temporary file beside `path`, then renames it into place, so a failed read or write never leaves
   * a partial file at `path` and never touches any other existing file.
   */
  private async download(ref: string, path: string, mode: number, current: () => boolean = () => true): Promise<Result<string>> {
    const temp = `${path}.${randomBytes(4).toString('hex')}.part`
    const out = createWriteStream(temp, { mode, flags: 'wx' })
    let writeFailed = false
    out.on('error', () => {
      writeFailed = true
    })
    const done = await this.read(ref, async (chunk) => {
      if (writeFailed) return failure('internal', "Couldn't write the file.")
      try {
        if (!out.write(chunk)) await once(out, 'drain')
      } catch {
        return failure('internal', "Couldn't write the file.")
      }
      return null
    })
    out.end()
    const wrote = await finished(out).then(
      () => !writeFailed,
      () => false
    )
    if (done.ok && wrote && current()) {
      try {
        await rename(temp, path)
        if (current()) return { ok: true, result: path }
        await rm(path, { force: true }) // forgotten while it was moved into place
        return GONE
      } catch {
        /* reported below */
      }
    }
    await rm(temp, { force: true })
    if (done.ok && wrote && !current()) return GONE
    return done.ok ? failure('internal', "Couldn't write the file.") : done
  }

  /** Reads every chunk in order; `each` may stop the read with a failure. */
  private async read(ref: string, each: (chunk: Buffer, size: number) => Promise<Failure | null>): Promise<Result<true>> {
    let offset = 0
    for (;;) {
      const answer = await this.core.request('artifacts.read', { ref, offset, length: this.chunkBytes() })
      if (!answer.ok) return answer
      const { data_b64: data, size, eof } = answer.result as { data_b64: string; size: number; eof: boolean }
      const chunk = Buffer.from(data, 'base64')
      const stop = await each(chunk, size)
      if (stop) return stop
      offset += chunk.length
      if (eof) return { ok: true, result: true }
      if (chunk.length === 0) return failure('internal', 'The file stopped short.')
    }
  }
}
