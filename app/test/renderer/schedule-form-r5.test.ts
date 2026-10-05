import { describe, expect, it } from 'vitest'
import type { ScheduleRow } from '../../src/shared/api'
import { blankForm, buildSave, formFor } from '../../src/renderer/src/schedule-form'

const ROW: ScheduleRow = {
  id: 'r5-retries', description: 'Reminder', action: 'reminder', channel_id: 'c1',
  created_at: '2026-10-05T12:00:00Z',
  cron: '0 9 * * *', max_retries: 2, retry_backoff_seconds: 60
}

describe('15.R5.3: scheduler-aligned retry validation and actionable clear guidance', () => {
  it.each(['0', '-1', '0.5', 'not a number'])('rejects invalid backoff %s on create and update', (value) => {
    const create = { ...blankForm(), description: ROW.description, channel_id: ROW.channel_id, cron: ROW.cron!, retry_backoff_seconds: value }
    expect(typeof buildSave(create)).toBe('string')
    expect(typeof buildSave({ ...formFor(ROW), retry_backoff_seconds: value }, ROW)).toBe('string')
  })

  it('accepts minimum backoff 1 and zero retries, both for create and update', () => {
    const create = { ...blankForm(), description: ROW.description, channel_id: ROW.channel_id, cron: ROW.cron!, max_retries: '0', retry_backoff_seconds: '1' }
    expect(buildSave(create)).toEqual({ action: 'reminder', description: ROW.description, channel_id: ROW.channel_id, cron: ROW.cron, max_retries: 0, retry_backoff_seconds: 1 })
    expect(buildSave({ ...formFor(ROW), max_retries: '0', retry_backoff_seconds: '1' }, ROW)).toEqual({ id: ROW.id, max_retries: 0, retry_backoff_seconds: 1 })
  })

  it('keeps blank create defaults omitted', () => {
    expect(buildSave({ ...blankForm(), description: ROW.description, channel_id: ROW.channel_id, cron: ROW.cron! })).toEqual({ action: 'reminder', description: ROW.description, channel_id: ROW.channel_id, cron: ROW.cron })
  })

  it('backoff-clear advice gives the real minimum and disables retries via their count, not a zero wait', () => {
    const answer = buildSave({ ...formFor(ROW), retry_backoff_seconds: '' }, ROW)
    expect(typeof answer).toBe('string')
    expect(answer).toMatch(/(?:at least 1|1 or more|>=\s*1|minimum.*1)/i)
    expect(answer).toMatch(/(?:max_retries|number of retries|retries to 0|0 retries)/i)
    expect(answer).not.toMatch(/enter 0 for none/)
    // Following the advice must actually be representable as a valid update.
    expect(buildSave({ ...formFor(ROW), max_retries: '0' }, ROW)).toEqual({ id: ROW.id, max_retries: 0 })
  })

  it('retry-count clear advice still accurately recommends valid zero', () => {
    expect(buildSave({ ...formFor(ROW), max_retries: '' }, ROW)).toMatch(/enter 0 for none/)
  })
})
