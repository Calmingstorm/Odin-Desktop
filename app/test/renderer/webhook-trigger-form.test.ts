import { describe, expect, it } from 'vitest'
import type { ScheduleRow } from '../../src/shared/api'
import { blankForm, buildSave, formFor } from '../../src/renderer/src/schedule-form'

const row = (trigger: ScheduleRow['trigger']): ScheduleRow => ({ id: 's1', description: 'Delivery', action: 'reminder', channel_id: 'c1', paused: false, created_at: '', trigger })
describe('inbound trigger form uses scheduler matching without narrowing D17', () => {
  it('creates a trigger instead of cron, distinct from outgoing action', () => {
    const form = { ...blankForm(), description: 'Delivery', channel_id: 'c1', timing: 'trigger' as const, trigger_source: 'github' as const, trigger_event: 'push', trigger_repo: 'team/' }
    expect(buildSave(form)).toEqual({ action: 'reminder', description: 'Delivery', channel_id: 'c1', trigger: { source: 'github', event: 'push', repo: 'team/' } })
  })
  it.each([{ event: 'deploy' }, { source: null, event: 'deploy', repo: null }])('preserves unspecified source and unchanged event-only timing %j', (trigger) => {
    const original = row(trigger)
    const form = formFor(original)
    expect(form.trigger_source).toBe('')
    form.description = 'Renamed'
    expect(buildSave(form, original)).toEqual({ id: 's1', description: 'Renamed' })
  })
  it('replaces timing and edits/clears filters through trigger as a whole', () => {
    const original = row({ source: 'github', event: 'push', repo: 'old' })
    const form = formFor(original)
    form.trigger_source = ''; form.trigger_repo = ''; form.trigger_event = 'deploy'
    expect(buildSave(form, original)).toEqual({ id: 's1', trigger: { event: 'deploy' } })
    form.timing = 'cron'; form.cron = '0 9 * * *'
    expect(buildSave(form, original)).toEqual({ id: 's1', cron: '0 9 * * *' })
  })
  it('allows GitLab scheduler matching and arbitrary event strings, including whitespace', () => {
    const form = { ...blankForm(), description: 'Delivery', channel_id: 'c1', timing: 'trigger' as const, trigger_source: 'gitlab' as const, trigger_event: 'custom event ' }
    expect(buildSave(form)).toMatchObject({ trigger: { source: 'gitlab', event: 'custom event ' } })
  })
  it('requires at least one condition as the core does, but accepts repository-only', () => {
    const form = { ...blankForm(), description: 'Delivery', channel_id: 'c1', timing: 'trigger' as const }
    expect(buildSave(form)).toContain('Trigger must have at least one condition')
    form.trigger_repo = 'repo'
    expect(buildSave(form)).toMatchObject({ trigger: { repo: 'repo' } })
  })
})
