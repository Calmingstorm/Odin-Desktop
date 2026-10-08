// The assistant's name in chat, from the active personality. Kept apart from the settings stores so chat components
// can read it without their machinery; stores/state.ts updates it whenever it reads the personality.
import { reactive } from 'vue'
import type { Personality } from '../../shared/api'

export const activePersonality = reactive({ value: null as Personality | null })

/** The active personality's name up to its first comma, or Odin. */
export function assistantName(personality: Personality | null = activePersonality.value): string {
  if (!personality) return 'Odin'
  const name = personality.preset === 'custom' ? personality.custom_name : personality.presets[personality.preset]?.name
  return (name ?? '').split(',')[0]!.trim() || 'Odin'
}
