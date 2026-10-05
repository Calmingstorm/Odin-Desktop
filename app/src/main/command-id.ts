// An unanswered command names its ID in the answer the window gets, so the window can wait for that command's late
// receipt instead of sending the same change again under a new ID.
import type { Result } from '../shared/api'

export function withCommandId<T>(result: Result<T>, commandId: string | undefined): Result<T> {
  if (result.ok || !commandId) return result
  const unknown = result.error.code === 'no_receipt' || result.error.disposition === 'outcome_unknown'
  return unknown ? { ok: false, error: { ...result.error, command_id: commandId } } : result
}
