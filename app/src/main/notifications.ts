// Desktop notifications for what Odin delivers. D13: like Discord, they show message previews by default and the
// user adjusts them in settings. The policy is pure functions; the Notifier wires it to the OS, the window and the
// core's acknowledgements (protocol.md, Notifications). A notification the OS accepted is not proof anyone saw it.

import type { NotificationChange, NotificationSettings, QuietHours } from '../shared/api'

export const DEFAULT_NOTIFICATION_SETTINGS: NotificationSettings = {
  enabled: true,
  previews: true,
  quietHours: { enabled: false, start: '22:00', end: '08:00' },
  muted: []
}

export interface NotificationIntent {
  conversation_id: string
  message_id: string
  category: string
  preview: string
  dedupe_key: string
}

export type Suppression = 'duplicate' | 'stale' | 'disabled' | 'muted' | 'window_focused' | 'quiet_hours'

export type Decision = { show: true; title: string; body: string } | { show: false; reason: Suppression }

/** An intent older than this was caught up after a restart or reconnect: it shows as unread, not as a notification. */
export const STALE_MS = 2 * 60_000
const PREVIEW_CHARS = 200

export function minutesOf(time: string): number | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(time)
  return match ? Number(match[1]) * 60 + Number(match[2]) : null
}

/** Whether `at` falls in the quiet window. Equal start and end means no quiet window. */
export function inQuietHours(quiet: QuietHours, at: Date): boolean {
  const start = minutesOf(quiet.start)
  const end = minutesOf(quiet.end)
  if (!quiet.enabled || start === null || end === null || start === end) return false
  const now = at.getHours() * 60 + at.getMinutes()
  return start < end ? now >= start && now < end : now >= start || now < end
}

export interface DecisionContext {
  now: Date
  /** When the core emitted the intent. */
  emittedAt: Date
  windowFocused: boolean
  /** The conversation's title, when the app knows it. */
  title: string | null
  /** Whether this dedupe key was handled already. */
  seen: boolean
}

export function decide(intent: NotificationIntent, settings: NotificationSettings, context: DecisionContext): Decision {
  if (context.seen) return { show: false, reason: 'duplicate' }
  if (context.now.getTime() - context.emittedAt.getTime() > STALE_MS) return { show: false, reason: 'stale' }
  if (!settings.enabled) return { show: false, reason: 'disabled' }
  if (settings.muted.includes(intent.conversation_id)) return { show: false, reason: 'muted' }
  if (context.windowFocused) return { show: false, reason: 'window_focused' }
  if (inQuietHours(settings.quietHours, context.now)) return { show: false, reason: 'quiet_hours' }
  const preview = intent.preview.replace(/\s+/g, ' ').trim()
  const body = !settings.previews
    ? 'New message from Odin'
    : preview.length > PREVIEW_CHARS
      ? `${preview.slice(0, PREVIEW_CHARS - 1)}…`
      : preview || 'New message from Odin'
  return { show: true, title: context.title ? `Odin · ${context.title}` : 'Odin', body }
}

/** The tray's tooltip: how much is unread, and where. */
export function trayTooltip(conversations: Iterable<{ unread: number }>): string {
  let messages = 0
  let places = 0
  for (const conversation of conversations) {
    if (conversation.unread > 0) {
      messages += conversation.unread
      places += 1
    }
  }
  if (!messages) return 'Odin'
  const unread = `${messages} unread message${messages === 1 ? '' : 's'}`
  return places === 1 ? `Odin: ${unread}` : `Odin: ${unread} in ${places} conversations`
}

/** Applies a partial change from settings. Muting is per conversation, through setMuted. */
export function mergeSettings(current: NotificationSettings, change: NotificationChange): NotificationSettings {
  return {
    ...current,
    enabled: change.enabled ?? current.enabled,
    previews: change.previews ?? current.previews,
    quietHours: { ...current.quietHours, ...change.quietHours }
  }
}

export function setMuted(current: NotificationSettings, conversationId: string, muted: boolean): NotificationSettings {
  const rest = current.muted.filter((id) => id !== conversationId)
  return { ...current, muted: muted ? [...rest, conversationId] : rest }
}

/** Reads saved settings, keeping only valid fields; anything else falls back to the defaults. */
export function loadSettings(saved: unknown): NotificationSettings {
  const value = (saved && typeof saved === 'object' ? saved : {}) as Record<string, unknown>
  const quiet = (value.quietHours && typeof value.quietHours === 'object' ? value.quietHours : {}) as Record<string, unknown>
  const defaults = DEFAULT_NOTIFICATION_SETTINGS
  const time = (v: unknown, fallback: string): string => (typeof v === 'string' && minutesOf(v) !== null ? v : fallback)
  return {
    enabled: typeof value.enabled === 'boolean' ? value.enabled : defaults.enabled,
    previews: typeof value.previews === 'boolean' ? value.previews : defaults.previews,
    quietHours: {
      enabled: typeof quiet.enabled === 'boolean' ? quiet.enabled : defaults.quietHours.enabled,
      start: time(quiet.start, defaults.quietHours.start),
      end: time(quiet.end, defaults.quietHours.end)
    },
    muted: Array.isArray(value.muted) ? [...new Set(value.muted.filter((id): id is string => typeof id === 'string'))] : []
  }
}

export type Outcome = 'shown' | 'suppressed' | 'failed'

export interface NotifierDeps {
  settings(): NotificationSettings
  windowFocused(): boolean
  titleOf(conversationId: string): string | null
  /** Shows one OS notification; resolves with whether the OS accepted it. */
  show(notification: { title: string; body: string; onClick: () => void }): Promise<'shown' | 'failed'>
  /** Brings the window forward on that conversation. */
  open(conversationId: string): void
  /** Tells the core what happened, through notifications.ack. */
  ack(dedupeKey: string, outcome: Outcome): void
  now(): Date
}

const SEEN_LIMIT = 1000

export class Notifier {
  private readonly seen = new Set<string>()

  constructor(private readonly deps: NotifierDeps) {}

  async handle(intent: NotificationIntent, emittedAt: Date): Promise<Outcome | 'duplicate'> {
    const decision = decide(intent, this.deps.settings(), {
      now: this.deps.now(),
      emittedAt,
      windowFocused: this.deps.windowFocused(),
      title: this.deps.titleOf(intent.conversation_id),
      seen: this.seen.has(intent.dedupe_key)
    })
    if (!decision.show && decision.reason === 'duplicate') return 'duplicate'
    this.seen.add(intent.dedupe_key)
    if (this.seen.size > SEEN_LIMIT) this.seen.delete(this.seen.values().next().value as string)
    if (!decision.show) {
      this.deps.ack(intent.dedupe_key, 'suppressed')
      return 'suppressed'
    }
    const outcome = await this.deps.show({
      title: decision.title,
      body: decision.body,
      onClick: () => this.deps.open(intent.conversation_id)
    })
    this.deps.ack(intent.dedupe_key, outcome)
    return outcome
  }
}

/** The conversations the main process knows about, for notification titles and the tray's unread count. */
export class ConversationIndex {
  private readonly items = new Map<string, { title: string; unread: number }>()

  reset(list: Array<{ id: string; title: string; unread: number }>): void {
    this.items.clear()
    for (const item of list) this.items.set(item.id, { title: item.title, unread: item.unread })
  }

  upsert(conversation: { id: string; title: string; unread: number }): void {
    this.items.set(conversation.id, { title: conversation.title, unread: conversation.unread })
  }

  remove(id: string): void {
    this.items.delete(id)
  }

  titleOf(id: string): string | null {
    return this.items.get(id)?.title ?? null
  }

  tooltip(): string {
    return trayTooltip(this.items.values())
  }
}
