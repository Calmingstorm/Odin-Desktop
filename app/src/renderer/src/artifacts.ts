// Inline images: fetched once through the main process and shown from blob: URLs (the page's CSP allows blob:
// images). SVG is never rendered inline, since it can carry active content; it is offered as a file instead.
// An image a message is showing is never revoked; released ones stay cached, least recently released dropped first,
// within a memory budget. A failed fetch is not cached, so the next view of that message tries again. Bytes held here
// are checked with the core before they are shown again, since the file may have expired there meanwhile and the
// event saying so may have been missed; an image the core no longer has is dropped and offered as a file.
import type { ArtifactRef, Result } from '../../shared/api'

export const RELEASED_IMAGE_BUDGET = 128 * 1024 * 1024

type Fetch = (ref: string) => Promise<Result<{ data: Uint8Array }>>
/** Whether the core still has the file: true, false, or null when it can't say (then what is held is shown). */
type Check = (ref: string) => Promise<boolean | null>

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

const revoke = (entry: Entry): void => void entry.url.then((url) => url && URL.revokeObjectURL(url))

export class ImageCache {
  /** In release order: the first entries are the least recently released. */
  private readonly entries = new Map<string, Entry>()

  constructor(
    private readonly fetch: Fetch,
    private readonly budget = RELEASED_IMAGE_BUDGET,
    private readonly check: Check = async () => null
  ) {}

  acquire(artifact: ArtifactRef): ImageHandle {
    const ref = artifact.ref
    const existing = this.entries.get(ref)
    if (existing) {
      existing.users += 1
      const url = this.check(ref).then(
        (present) => {
          if (present !== false) return existing.url
          this.invalidate(ref)
          return null
        },
        () => existing.url
      )
      return this.handle(ref, existing, url)
    }
    const created: Entry = { url: Promise.resolve(null), bytes: 0, users: 1 }
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
    this.entries.set(ref, created)
    return this.handle(ref, created, created.url)
  }

  /** The core no longer has the file: nothing new shows these bytes, and they go once no message shows them. */
  invalidate(ref: string): void {
    const entry = this.entries.get(ref)
    if (!entry) return
    this.entries.delete(ref)
    if (entry.users === 0) revoke(entry)
  }

  /** The cached refs, least recently released first, with how many messages show each. */
  cached(): Array<[string, number]> {
    return [...this.entries].map(([ref, entry]) => [ref, entry.users])
  }

  private handle(ref: string, entry: Entry, url: Promise<string | null>): ImageHandle {
    let released = false
    return {
      url,
      release: () => {
        if (released) return
        released = true
        entry.users -= 1
        if (entry.users > 0) return
        if (this.entries.get(ref) !== entry) {
          revoke(entry) // dropped while shown: its bytes go with the last message showing them
          return
        }
        this.entries.delete(ref)
        this.entries.set(ref, entry)
        this.trim()
      }
    }
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
      revoke(entry)
    }
  }
}

export const images = new ImageCache(
  (ref) => window.odin.fetchArtifact(ref),
  RELEASED_IMAGE_BUDGET,
  async (ref) => {
    const answer = await window.odin.checkArtifact(ref)
    return answer.ok ? answer.result.available : null
  }
)
