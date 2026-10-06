import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ScheduleRow } from '../../src/shared/api'
import { scheduleRecovery, scheduleRunLabel } from '../../src/renderer/src/schedule-observations'
import { flush, mount, type Mounted } from './component-host'

const missed: NonNullable<ScheduleRow['missed_run']> = {
  due_at: '2026-10-05T12:00:00Z', observed_at: '2026-10-06T12:00:00Z', lateness_seconds: 86400,
  missed_count: 128, omitted_count: 127, count_truncated: true, policy: 'manual', workflow_catchup_limit: 0
}
const row: ScheduleRow = {
  id: 'recovery', description: 'Missed harmless check', action: 'check', channel_id: 'c1',
  created_at: '2026-10-05T12:00:00Z', cron: '0 * * * *', paused: false,
  recovery_required: 'Missed action; run explicitly. No effects were replayed.', missed_run: missed, settlement: 'unknown'
}
let view: Mounted | undefined

beforeEach(() => { vi.resetModules() })
afterEach(() => { view?.unmount(); view = undefined })

describe('real schedule recovery observations', () => {
  it('keeps unknown settlement and bounded missed count honest', () => {
    const lines = scheduleRecovery(row).join(' ')
    expect(lines).toContain('at least 128')
    expect(lines).toContain('not replayed automatically')
    expect(lines).toContain('Last run settlement: unknown.')
    expect(lines).not.toMatch(/succeeded|completed/i)
  })

  it('describes coalesced reminders, without pretending every missed run was delivered', () => {
    expect(scheduleRecovery({ ...row, recovery_required: undefined, missed_run: { ...missed, policy: 'coalesced' } }).join(' '))
      .toContain('one catch-up notice, not one delivery per missed run')
    expect(scheduleRecovery({ ...row, missed_run: null, recovery_required: null, settlement: null })).toEqual([])
  })

  it('does not label skipped history as a failure', () => {
    expect(scheduleRunLabel({ status: 'success' })).toBe('Succeeded')
    expect(scheduleRunLabel({ status: 'failure' })).toBe('Failed')
    expect(scheduleRunLabel({ status: 'skipped' })).toBe('Not run')
    expect(scheduleRunLabel({ status: 'unknown' })).toBe('Unknown')
  })

  it('renders recovery-required instead of Active and offers explicit Run now', async () => {
    const runs = vi.fn(async () => ({ ok: true, result: { status: 'success' } }))
    ;(globalThis as unknown as { window: unknown }).window = { odin: {
      schedulesList: async () => ({ ok: true, result: [row] }), schedulesRun: runs,
      workList: async () => ({ ok: true, result: { items: [] } })
    } }
    ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
    view = mount((await import('../../src/renderer/src/views/settings/Work.vue')).default)
    await flush()
    expect(view.root.textContent()).toContain('Recovery required')
    expect(view.root.textContent()).toContain('Last run settlement: unknown.')
    expect(view.root.findAll((host) => host.props.class === 'state-chip connected')).toHaveLength(0)
    expect(runs).not.toHaveBeenCalled()
    const run = view.root.button('Run now')
    expect(run.props.disabled).toBeFalsy()
    run.fire('click')
    await flush()
    expect(runs).toHaveBeenCalledOnce()
  })
})
