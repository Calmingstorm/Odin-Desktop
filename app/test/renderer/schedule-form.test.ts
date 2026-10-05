// The schedule form's bodies: Odin's checks for a new schedule, and only what changed for an edit.
import { describe, expect, it } from 'vitest'
import type { ScheduleRow } from '../../src/shared/api'
import { blankForm, buildSave, formFor, type ScheduleForm } from '../../src/renderer/src/schedule-form'
import type { Zone } from '../../src/renderer/src/schedule-time'

const START = Date.UTC(2026, 2, 8, 7)
const END = Date.UTC(2026, 10, 1, 6)
const newYork: Zone = { offsetMinutes: (ms) => (ms >= START && ms < END ? 240 : 300) }
const form = (fields: Partial<ScheduleForm>): ScheduleForm => ({ ...blankForm(), description: 'Check', channel_id: 'c1', cron: '0 9 * * *', ...fields })

describe('a new schedule', () => {
  it('sends every field it fills in, per kind', () => {
    expect(buildSave(form({ action: 'reminder', message: 'Stand up' }), undefined, newYork)).toEqual({
      action: 'reminder', description: 'Check', channel_id: 'c1', cron: '0 9 * * *', message: 'Stand up'
    })
    expect(
      buildSave(form({ action: 'check', tool_name: 'run_command', tool_input: '{"command": "uptime"}', report_format: 'paginated_embed_v1' }), undefined, newYork)
    ).toEqual({
      action: 'check', description: 'Check', channel_id: 'c1', cron: '0 9 * * *', tool_name: 'run_command', tool_input: { command: 'uptime' },
      report_format: 'paginated_embed_v1'
    })
    expect(
      buildSave(form({ action: 'webhook', channel_id: '', webhook_url: 'https://x.test/h', webhook_expected: '200, 204', max_retries: '2' }), undefined, newYork)
    ).toEqual({
      action: 'webhook', description: 'Check', channel_id: '', cron: '0 9 * * *',
      webhook_config: { url: 'https://x.test/h', method: 'POST', expected_status_codes: [200, 204] }, max_retries: 2
    })
  })

  it("says what is wrong, as Odin's form does", () => {
    expect(buildSave(form({ description: ' ' }), undefined, newYork)).toBe('Describe the schedule.')
    expect(buildSave(form({ channel_id: '' }), undefined, newYork)).toBe('Choose the conversation it reports to.')
    expect(buildSave(form({ action: 'check' }), undefined, newYork)).toBe('Choose the tool the check runs.')
    expect(buildSave(form({ action: 'check', tool_name: 'run_command', tool_input: '[1]' }), undefined, newYork)).toBe('The tool input is a JSON object.')
    expect(buildSave(form({ action: 'workflow', steps: '[{"tool_name": "x", "tool_input": {}, "on_failure": "retry"}]' }), undefined, newYork)).toMatch(/^Steps are a JSON list/)
    expect(buildSave(form({ action: 'webhook', webhook_url: 'https://x.test', webhook_expected: '200, 9000' }), undefined, newYork)).toMatch(/HTTP codes/)
    expect(buildSave(form({ max_retries: '-1' }), undefined, newYork)).toBe('Retries are a whole number, 0 or more.')
  })

  it('sends a one-time run as an explicit instant, and makes a repeated hour a choice', () => {
    expect(buildSave(form({ timing: 'once', run_at: '2026-07-04T09:00' }), undefined, newYork)).toMatchObject({ run_at: '2026-07-04T13:00:00.000Z' })
    expect(buildSave(form({ timing: 'once', run_at: '2026-03-08T02:30' }), undefined, newYork)).toMatch(/clocks skip it/)
    expect(buildSave(form({ timing: 'once', run_at: '2026-11-01T01:30' }), undefined, newYork)).toMatch(/happens twice/)
    expect(buildSave(form({ timing: 'once', run_at: '2026-11-01T01:30', occurrence: 1 }), undefined, newYork)).toMatchObject({
      run_at: '2026-11-01T06:30:00.000Z'
    })
  })
})

describe('changing a schedule', () => {
  const row: ScheduleRow = {
    id: 'ab12cd34', description: 'Disk check', action: 'check', channel_id: 'c1', created_at: '2026-10-01T00:00:00Z', cron: '0 9 * * *',
    timezone: 'America/New_York', one_time: false, tool_name: 'run_command', tool_input: { command: 'df -h' }, max_retries: 0, retry_backoff_seconds: 60
  }

  it('sends nothing but the id and what changed', () => {
    const edited = { ...formFor(row, newYork), description: 'Disk space' }
    expect(buildSave(edited, row, newYork)).toEqual({ id: 'ab12cd34', description: 'Disk space' })
    expect(buildSave(formFor(row, newYork), row, newYork)).toBe('Nothing changed.')
  })

  it('sends new timing whole, replacing the old', () => {
    expect(buildSave({ ...formFor(row, newYork), cron: '0 10 * * *' }, row, newYork)).toEqual({ id: 'ab12cd34', cron: '0 10 * * *', cron_timezone: 'America/New_York' })
    expect(buildSave({ ...formFor(row, newYork), timing: 'once', run_at: '2026-12-01T08:00' }, row, newYork)).toEqual({
      id: 'ab12cd34', run_at: '2026-12-01T13:00:00.000Z'
    })
  })

  it("shows a one-time run on this computer's clock", () => {
    const once: ScheduleRow = { ...row, cron: null, one_time: true, run_at: '2026-07-04T13:00:00+00:00' }
    expect(formFor(once, newYork)).toMatchObject({ timing: 'once', run_at: '2026-07-04T09:00', cron_timezone: '' })
  })
})
