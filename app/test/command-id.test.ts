// Review round 3: an unanswered command names its ID, so the window waits for that command's receipt.
import { describe, expect, it } from 'vitest'
import { withCommandId } from '../src/main/command-id'

describe('an unanswered command keeps its ID', () => {
  it('names the ID only on an unknown outcome of a command', () => {
    const unknown = { ok: false as const, error: { code: 'no_receipt', message: 'No receipt yet.', disposition: 'outcome_unknown' } }
    expect(withCommandId(unknown, 'id-1')).toEqual({ ok: false, error: { ...unknown.error, command_id: 'id-1' } })
    const refused = { ok: false as const, error: { code: 'bad_request', message: 'no', disposition: 'not_dispatched' } }
    expect(withCommandId(refused, 'id-1')).toBe(refused)
    expect(withCommandId(unknown, undefined)).toBe(unknown)
    expect(withCommandId({ ok: true, result: 1 }, 'id-1')).toEqual({ ok: true, result: 1 })
  })
})
