import type { CoreError, Result } from '../../shared/api'

/** A refused capability is an expected core limit, not a broken screen or an empty dataset. */
export function isUnavailable(error: Pick<CoreError, 'code'>): boolean {
  return error.code === 'capability_unavailable'
}

export function unavailableText(feature: string): string {
  const verb = feature === 'Conversations' || feature === 'Core settings' || feature === 'Codex accounts' ? 'are' : 'is'
  return `${feature} ${verb} unavailable in this core.`
}

/** Preserve real failures; only the protocol's explicit capability refusal gets the plain state. */
export function resultMessage(result: Result<unknown>, feature: string): string {
  return result.ok ? '' : isUnavailable(result.error) ? unavailableText(feature) : result.error.message
}
