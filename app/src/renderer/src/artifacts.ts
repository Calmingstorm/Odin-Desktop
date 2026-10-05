// Inline images: fetched once through the main process and shown from blob: URLs (the page's CSP allows blob:
// images). SVG is never rendered inline, since it can carry active content; it is offered as a file instead.
// An image a message is showing is never revoked; released ones stay cached, least recently released dropped first,
// within a memory budget. A failed fetch is not cached, so the next view of that message tries again.
import type { ArtifactRef, Result } from '../../shared/api'

export const RELEASED_IMAGE_BUDGET = 128 * 1024 * 1024

type Fetch = (ref: string) => Promise<Result<{ data: Uint8Array }>>

interface Entry {
  url: Promise<string | null>
  bytes: number
  users: number
}

export interface ImageHandle {
  /** A blob: URL, or null when the image can't be shown (too large, gone); then it is offered as a file. */
  url: Promise<string | null>
  /** Call once when the message stops showing the image. */
  release(): void
}

export function showsInline(artifact: ArtifactRef): boolean {
  return artifact.kind === 'image' && artifact.available && artifact.mime.startsWith('image/') && artifact.mime !== 'image/svg+xml'
}

export class ImageCache {
  /** In release order: the first entries are the least recently released. */
  private readonly entries = new Map<string, Entry>()

  constructor(
    private readonly fetch: Fetch,
    private readonly budget = RELEASED_IMAGE_BUDGET
  ) {}

  acquire(artifact: ArtifactRef): ImageHandle {
    const ref = artifact.ref
    let entry = this.entries.get(ref)
    if (!entry) {
      const created: Entry = { url: Promise.resolve(null), bytes: 0, users: 0 }
      const forget = (): null => {
        if (this.entries.get(ref) === created) this.entries.delete(ref)
        return null
      }
      created.url = this.fetch(ref).then((answer) => {
        if (!answer.ok) return forget()
        created.bytes = answer.result.data.byteLength
        const url = URL.createObjectURL(new Blob([new Uint8Array(answer.result.data)], { type: artifact.mime }))
        this.trim()
        return url
      }, forget)
      entry = created
      this.entries.set(ref, entry)
    }
    const held = entry
    held.users += 1
    let released = false
    return {
      url: held.url,
      release: () => {
        if (released) return
        released = true
        held.users -= 1
        if (held.users > 0 || this.entries.get(ref) !== held) return
        this.entries.delete(ref)
        this.entries.set(ref, held)
        this.trim()
      }
    }
  }

  /** The cached refs, least recently released first, with how many messages show each. */
  cached(): Array<[string, number]> {
    return [...this.entries].map(([ref, entry]) => [ref, entry.users])
  }

  /** Revokes released images, least recently released first, until they fit the budget. */
  private trim(): void {
    let size = 0
    for (const entry of this.entries.values()) if (entry.users === 0) size += entry.bytes
    for (const [ref, entry] of this.entries) {
      if (size <= this.budget) return
      if (entry.users > 0) continue
      this.entries.delete(ref)
      size -= entry.bytes
      void entry.url.then((url) => url && URL.revokeObjectURL(url))
    }
  }
}

export const images = new ImageCache((ref) => window.odin.fetchArtifact(ref))
