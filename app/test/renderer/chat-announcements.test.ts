import { describe, expect, it } from 'vitest'
import { chatAnnouncement, type ChatAnnouncementState } from '../../src/renderer/src/chat-announcements'

const idle: ChatAnnouncementState = {
  running: null, stopping: false, terminal: null, outcome: null, queued: 0, consumed: [], steerQueued: [], unknown: []
}

describe('chat structural announcements', () => {
  it('announces working, completed, queue, steer consumed and unknown states', () => {
    expect(chatAnnouncement(idle, { ...idle, running: 'r:1' })).toBe('Odin is working.')
    expect(chatAnnouncement(idle, { ...idle, terminal: 'r:1:completed', outcome: 'completed' })).toBe('Task completed.')
    expect(chatAnnouncement(idle, { ...idle, queued: 2 })).toBe('2 follow-ups queued.')
    expect(chatAnnouncement(idle, { ...idle, steerQueued: ['s'] })).toBe('Steer queued for Odin to read.')
    expect(chatAnnouncement({ ...idle, steerQueued: ['s'] }, { ...idle, consumed: ['s'] })).toBe('Odin has read the steer.')
    expect(chatAnnouncement(idle, { ...idle, unknown: ['u'] })).toContain('unknown outcome')
  })
  it('is quiet for unchanged state, tool events, and old completed history on navigation', () => {
    const current = { ...idle, running: 'r:1', queued: 1, consumed: ['s'], unknown: ['u'] }
    expect(chatAnnouncement(current, { ...current })).toBe('')
    expect(chatAnnouncement(undefined, { ...idle, terminal: 'old', outcome: 'completed' })).toBe('')
  })
  it('does not expose identifiers or content through live speech', () => {
    const secret = 'PRIVATE-REJECTED-REPLY-AND-SECRET'
    const next = { ...idle, running: secret, terminal: secret, queued: 1, consumed: [secret], unknown: [secret] }
    const line = chatAnnouncement(idle, next)
    expect(line).not.toContain(secret)
    expect(line).toContain('Odin is working.')
  })
})
