import { computed } from 'vue'
import { state } from './store'
import { status } from './stores/status'

/**
 * The running core's own account of provider setup. Only the current core's projection counts: after a link loss or a
 * core replacement it is unknown until that core answers, never the last one seen.
 */
export const setupProjection = computed(() => {
  if (state.app.link !== 'ready' || status.epoch !== state.recoveryEpoch ||
      (state.app.coreInstanceId && status.core?.core_instance_id !== state.app.coreInstanceId)) return null
  return status.core?.first_run ?? null
})

/** The core says no provider is set up yet, so a chat request can't reach a model. Unknown is not missing. */
export const setupMissing = computed(() => setupProjection.value?.state === 'fresh' || setupProjection.value?.state === 'incomplete')

/** Codex is the chosen provider and no account is stored: signing in is the one step left. */
export const codexSignInNeeded = computed(() => setupMissing.value && setupProjection.value?.provider === 'codex' &&
  setupProjection.value?.credential_present === false)
