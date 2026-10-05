// Composer drafts per conversation, kept in the profile so they survive restarts. Owner-only file (0600).
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

const MAX_DRAFT_CHARS = 32_000
const MAX_DRAFTS = 500

export class DraftStore {
  private drafts: Record<string, string>
  private timer: NodeJS.Timeout | null = null

  constructor(
    private readonly path: string,
    private readonly delayMs = 400
  ) {
    this.drafts = load(path)
  }

  get(conversationId: string): string {
    return this.drafts[conversationId] ?? ''
  }

  /** Saves soon; a burst of keystrokes becomes one write. An empty draft is removed. */
  set(conversationId: string, text: string): void {
    const value = text.slice(0, MAX_DRAFT_CHARS)
    delete this.drafts[conversationId] // re-inserting keeps the most recently edited last
    if (value) this.drafts[conversationId] = value
    const ids = Object.keys(this.drafts)
    for (const id of ids.slice(0, Math.max(0, ids.length - MAX_DRAFTS))) delete this.drafts[id]
    this.schedule()
  }

  /** Writes now, for example before the app exits. */
  flush(): void {
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    mkdirSync(dirname(this.path), { recursive: true, mode: 0o700 })
    const temporary = `${this.path}.tmp`
    writeFileSync(temporary, JSON.stringify(this.drafts), { mode: 0o600 })
    renameSync(temporary, this.path)
  }

  private schedule(): void {
    if (this.timer) clearTimeout(this.timer)
    this.timer = setTimeout(() => {
      try {
        this.flush()
      } catch {
        /* a lost draft write is retried by the next edit */
      }
    }, this.delayMs)
  }
}

function load(path: string): Record<string, string> {
  try {
    const data: unknown = JSON.parse(readFileSync(path, 'utf8'))
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {}
    return Object.fromEntries(Object.entries(data).filter(([, value]) => typeof value === 'string')) as Record<string, string>
  } catch {
    return {}
  }
}
