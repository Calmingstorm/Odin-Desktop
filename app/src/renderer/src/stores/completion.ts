// Refused capabilities invalidate old data; failed refreshes preserve explicitly stale answers.
import { reactive } from 'vue'
import type { Result } from '../../../shared/api'
import { isUnavailable } from '../capability'
export interface CompletionRead {
  value: unknown
  loaded: boolean
  busy: boolean
  error: string
  unavailable: boolean
  label: string
}
export const completion = reactive<Record<string, CompletionRead>>({})
const epochs = new Map<string, number>()
export async function readCompletion(key: string, run: () => Promise<Result<unknown>>, label = ''): Promise<void> {
  const epoch = (epochs.get(key) ?? 0) + 1
  epochs.set(key, epoch)
  completion[key] ??= { value: null, loaded: false, busy: false, error: '', unavailable: false, label: '' }
  // Mutate the proxy read back from the reactive map, not the raw object just inserted.
  const row = completion[key]!
  row.busy = true
  let result: Result<unknown>
  try { result = await run() }
  catch { result = { ok: false, error: { code: 'internal', message: 'Could not read the core response.' } } }
  if (epochs.get(key) !== epoch) return
  row.busy = false
  if (!result.ok) {
    row.unavailable = isUnavailable(result.error)
    row.error = row.unavailable ? '' : result.error.message
    if (row.unavailable) { row.value = null; row.loaded = false; row.label = '' }
    return
  }
  row.value = result.result
  row.loaded = true
  row.error = ''
  row.unavailable = false
  row.label = label
}
