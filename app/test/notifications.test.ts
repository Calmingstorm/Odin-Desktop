import { describe, expect, it } from 'vitest'
import type { NotificationSettings } from '../src/shared/api'
import {
  ConversationIndex,
  DEFAULT_NOTIFICATION_SETTINGS,
  Notifier,
  STALE_MS,
  decide,
  inQuietHours,
  loadSettings,
  mergeSettings,
  setMuted,
  trayTooltip,
  type NotificationIntent,
  type Outcome
} from '../src/main/notifications'

const at = (time: string): Date => new Date(`2026-10-05T${time}:00`)
const NOW = at('12:00')

function intent(fields: Partial<NotificationIntent> = {}): NotificationIntent {
  return { conversation_id: 'c1', message_id: 'm1', category: 'reply', preview: 'Backups finished.', dedupe_key: 'reply:m1', ...fields }
}

function context(fields: Partial<Parameters<typeof decide>[2]> = {}): Parameters<typeof decide>[2] {
  return { now: NOW, emittedAt: NOW, windowFocused: false, title: 'Backups', seen: false, ...fields }
}

const settings = (fields: Partial<NotificationSettings> = {}): NotificationSettings => ({ ...DEFAULT_NOTIFICATION_SETTINGS, ...fields })

describe('quiet hours', () => {
  it('cover a window within one day', () => {
    const quiet = { enabled: true, start: '09:00', end: '17:00' }
    expect(inQuietHours(quiet, at('09:00'))).toBe(true)
    expect(inQuietHours(quiet, at('16:59'))).toBe(true)
    expect(inQuietHours(quiet, at('17:00'))).toBe(false)
    expect(inQuietHours(quiet, at('08:59'))).toBe(false)
  })

  it('cover a window across midnight', () => {
    const quiet = { enabled: true, start: '22:00', end: '08:00' }
    expect(inQuietHours(quiet, at('23:30'))).toBe(true)
    expect(inQuietHours(quiet, at('07:59'))).toBe(true)
    expect(inQuietHours(quiet, at('08:00'))).toBe(false)
    expect(inQuietHours(quiet, at('12:00'))).toBe(false)
  })

  it('are off when disabled, empty, or malformed', () => {
    expect(inQuietHours({ enabled: false, start: '00:00', end: '23:59' }, NOW)).toBe(false)
    expect(inQuietHours({ enabled: true, start: '12:00', end: '12:00' }, NOW)).toBe(false)
    expect(inQuietHours({ enabled: true, start: '25:00', end: '08:00' }, NOW)).toBe(false)
  })
})

describe('whether to show a notification', () => {
  it('shows the preview by default, titled with the conversation (D13)', () => {
    expect(decide(intent(), settings(), context())).toEqual({ show: true, title: 'Odin · Backups', body: 'Backups finished.' })
    expect(decide(intent(), settings(), context({ title: null }))).toMatchObject({ title: 'Odin' })
  })

  it('collapses whitespace and cuts a long preview, and hides it when previews are off', () => {
    const long = decide(intent({ preview: `line one\n\n${'x'.repeat(300)}` }), settings(), context())
    expect(long.show && long.body.startsWith('line one xxx')).toBe(true)
    expect(long.show && long.body.length).toBe(200)
    expect(long.show && long.body.endsWith('…')).toBe(true)
    expect(decide(intent(), settings({ previews: false }), context())).toMatchObject({ body: 'New message from Odin' })
  })

  it('holds back duplicates, catch-up after a restart, and anything the user turned off, in that order', () => {
    const quiet = { enabled: true, start: '11:00', end: '13:00' }
    const all = settings({ enabled: false, muted: ['c1'], quietHours: quiet })
    expect(decide(intent(), all, context({ seen: true, windowFocused: true }))).toEqual({ show: false, reason: 'duplicate' })
    const old = new Date(NOW.getTime() - STALE_MS - 1)
    expect(decide(intent(), settings(), context({ emittedAt: old }))).toEqual({ show: false, reason: 'stale' })
    expect(decide(intent(), all, context())).toEqual({ show: false, reason: 'disabled' })
    expect(decide(intent(), settings({ muted: ['c1'], quietHours: quiet }), context())).toEqual({ show: false, reason: 'muted' })
    expect(decide(intent(), settings({ quietHours: quiet }), context({ windowFocused: true }))).toEqual({
      show: false,
      reason: 'window_focused'
    })
    expect(decide(intent(), settings({ quietHours: quiet }), context())).toEqual({ show: false, reason: 'quiet_hours' })
    expect(decide(intent({ conversation_id: 'c2' }), settings({ muted: ['c1'] }), context()).show).toBe(true)
  })
})

describe('saved settings', () => {
  it('load valid fields and fall back to the defaults for anything else', () => {
    expect(loadSettings(undefined)).toEqual(DEFAULT_NOTIFICATION_SETTINGS)
    expect(loadSettings('garbage')).toEqual(DEFAULT_NOTIFICATION_SETTINGS)
    expect(
      loadSettings({ enabled: false, previews: 'no', quietHours: { enabled: true, start: '23:00', end: '7am' }, muted: ['c1', 'c1', 4, 'c2'] })
    ).toEqual({ enabled: false, previews: true, quietHours: { enabled: true, start: '23:00', end: '08:00' }, muted: ['c1', 'c2'] })
  })

  it('merge a partial change without touching the rest, and mute one conversation at a time', () => {
    const current = settings({ muted: ['c1'] })
    expect(mergeSettings(current, { quietHours: { enabled: true } })).toEqual({
      ...current,
      quietHours: { enabled: true, start: '22:00', end: '08:00' }
    })
    expect(setMuted(current, 'c2', true).muted).toEqual(['c1', 'c2'])
    expect(setMuted(setMuted(current, 'c2', true), 'c2', true).muted).toEqual(['c1', 'c2'])
    expect(setMuted(current, 'c1', false).muted).toEqual([])
  })
})

describe('the tray tooltip', () => {
  it('says how much is unread and where', () => {
    expect(trayTooltip([])).toBe('Odin')
    expect(trayTooltip([{ unread: 0 }, { unread: 1 }])).toBe('Odin: 1 unread message')
    expect(trayTooltip([{ unread: 2 }, { unread: 3 }])).toBe('Odin: 5 unread messages in 2 conversations')
  })

  it('follows the conversation list and its events', () => {
    const index = new ConversationIndex()
    index.reset([{ id: 'c1', title: 'Chat', unread: 1 }])
    index.upsert({ id: 'c2', title: 'Backups', unread: 2 })
    expect(index.tooltip()).toBe('Odin: 3 unread messages in 2 conversations')
    expect(index.titleOf('c2')).toBe('Backups')
    index.remove('c2')
    expect(index.tooltip()).toBe('Odin: 1 unread message')
    expect(index.titleOf('c2')).toBeNull()
  })
})

describe('the notifier', () => {
  function notifier(answer: 'shown' | 'failed' = 'shown', current: () => NotificationSettings = () => settings()) {
    const shown: Array<{ title: string; body: string; onClick: () => void }> = []
    const acks: Array<[string, Outcome]> = []
    const opened: string[] = []
    const n = new Notifier({
      settings: current,
      windowFocused: () => false,
      titleOf: () => 'Backups',
      show: async (notification) => {
        shown.push(notification)
        return answer
      },
      open: (id) => opened.push(id),
      ack: (key, outcome) => acks.push([key, outcome]),
      now: () => NOW
    })
    return { n, shown, acks, opened }
  }

  it('shows each intent once, tells the core what happened, and opens the conversation on click', async () => {
    const { n, shown, acks, opened } = notifier()
    expect(await n.handle(intent(), NOW)).toBe('shown')
    expect(await n.handle(intent(), NOW)).toBe('duplicate')
    expect(shown).toHaveLength(1)
    expect(acks).toEqual([['reply:m1', 'shown']])
    shown[0]!.onClick()
    expect(opened).toEqual(['c1'])
  })

  it('reports suppressed and failed notifications honestly', async () => {
    const muted = notifier('shown', () => settings({ muted: ['c1'] }))
    expect(await muted.n.handle(intent(), NOW)).toBe('suppressed')
    expect(muted.shown).toHaveLength(0)
    expect(muted.acks).toEqual([['reply:m1', 'suppressed']])
    const failing = notifier('failed')
    expect(await failing.n.handle(intent(), NOW)).toBe('failed')
    expect(failing.acks).toEqual([['reply:m1', 'failed']])
  })

  it('remembers a bounded number of intents', async () => {
    const { n, shown } = notifier()
    for (let i = 0; i <= 1000; i++) await n.handle(intent({ dedupe_key: `k${i}` }), NOW)
    expect(await n.handle(intent({ dedupe_key: 'k0' }), NOW)).toBe('shown') // the oldest was forgotten
    expect(await n.handle(intent({ dedupe_key: 'k1000' }), NOW)).toBe('duplicate')
    expect(shown).toHaveLength(1002)
  })
})
