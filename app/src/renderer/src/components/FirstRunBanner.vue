<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FirstRunStatus } from '../../../shared/api'
import { dismissSetupReminder, openSettings, state } from '../store'
import { loadCodex, loadSettings, settings } from '../stores/settings'
import { refreshStatus, status } from '../stores/status'

const props = defineProps<{ dismissible?: boolean }>()

const projection = computed(() => {
  if (state.app.link !== 'ready' || status.epoch !== state.recoveryEpoch ||
      (state.app.coreInstanceId && status.core?.core_instance_id !== state.app.coreInstanceId)) return null
  return status.core?.first_run ?? null
})
const labels: Record<FirstRunStatus['state'], string> = {
  fresh: 'Not configured', incomplete: 'Setup incomplete', saved: 'Saved, not effective yet',
  'effective-ready': 'Ready', degraded: 'Provider degraded'
}
const reasons: Record<FirstRunStatus['reason'], string> = {
  provider_not_configured: 'Choose a model and provider in Settings. You can do this later.',
  provider_configuration_incomplete: 'The selected provider needs more configuration.',
  provider_runtime_unavailable: 'Settings are saved, but the provider is not available in the running core.',
  provider_identity_not_adopted: 'Settings are saved, but the running core has not adopted this provider yet.',
  provider_effective: '',
  provider_health_degraded: 'The core reports a problem with the running provider.',
  provider_health_unknown: 'The core cannot confirm provider health yet.',
  keyring_unavailable: 'The profile keyring is unavailable or locked. Retry to unlock it with the system prompt.',
  credential_state_unavailable: 'The core could not read credential state. Retry without re-entering saved credentials.'
}
// Only the current core's projection qualifies operational warnings and unlock.
const keyringFailed = computed(() => Boolean(projection.value?.keyring_unavailable || projection.value?.reason === 'keyring_unavailable' ||
  (state.app.link === 'ready' && settings.metaEpoch === state.recoveryEpoch &&
    settings.metaCoreInstanceId === state.app.coreInstanceId && settings.meta?.status.keyring_error)))
const operational = computed(() => Boolean(projection.value && (
  projection.value.state === 'saved' || projection.value.state === 'degraded' || keyringFailed.value ||
  projection.value.reason === 'credential_state_unavailable')))
const invitation = computed(() => Boolean(projection.value && state.setupReminderLoaded && !state.setupReminderHidden &&
  (projection.value.state === 'fresh' || projection.value.state === 'incomplete')))
const visible = computed(() => state.view === 'chat' && (operational.value || invitation.value || keyringFailed.value))
const retrying = ref(false)
const retryError = ref('')
const dismissing = ref(false)
const dismissError = ref('')
async function later(): Promise<void> {
  if (dismissing.value) return
  dismissing.value = true
  dismissError.value = ''
  if (!await dismissSetupReminder()) dismissError.value = 'Could not save this preference. Try again.'
  dismissing.value = false
}
async function retry(): Promise<void> {
  if (retrying.value || (!projection.value && !keyringFailed.value) || state.app.link !== 'ready') return
  retrying.value = true
  retryError.value = ''
  const epoch = state.recoveryEpoch
  const instance = state.app.coreInstanceId
  const current = (): boolean => epoch === state.recoveryEpoch && instance === state.app.coreInstanceId && state.app.link === 'ready'
  try {
    // Only this explicit owner click may ask the core for a bounded native unlock.
    // Reads, refresh timers and mounting Settings must never call this operation.
    if (keyringFailed.value) {
      const answer = await window.odin.secretsUnlock()
      if (!current()) return
      if (!answer.ok) {
        retryError.value = 'The profile keyring could not be unlocked. Retry after dismissing any system prompt.'
        return
      }
    }
    if (!current()) return
    // Rehydrate after success, without replaying secret writes or authorizing a device login.
    await Promise.all([loadSettings(), loadCodex()])
    if (!current()) return
    await refreshStatus()
  } catch {
    if (current()) retryError.value = 'Could not refresh setup status. Try again when the core is connected.'
  } finally {
    retrying.value = false
  }
}
</script>

<template>
  <section v-if="visible" class="first-run-banner panel" :aria-label="operational || keyringFailed ? 'Provider attention' : 'Provider setup'" role="status"
    data-testid="first-run-banner" :data-state="projection?.state ?? 'keyring-attention'" :data-kind="operational || keyringFailed ? 'operational' : 'invitation'">
    <strong>{{ keyringFailed ? 'Keyring needs attention' : (projection ? labels[projection.state] : '') }}</strong>
    <p v-if="projection && reasons[projection.reason]">{{ reasons[projection.reason] }}</p>
    <p v-if="keyringFailed && projection?.reason !== 'keyring_unavailable'" class="warn">The profile keyring is unavailable or locked. Retry to unlock it with the system prompt.</p>
    <p v-if="retryError" class="warn">{{ retryError }}</p>
    <p v-if="dismissError" class="warn">{{ dismissError }}</p>
    <div class="first-run-actions">
      <button class="ghost" data-testid="first-run-models" @click="openSettings('models')">Open Models and providers</button>
      <button v-if="invitation && !operational && !keyringFailed" class="ghost" data-testid="first-run-general" @click="openSettings('general')">Startup and notifications</button>
      <button class="ghost"
        data-testid="first-run-retry" :disabled="retrying || state.app.link !== 'ready'" @click="retry">{{ retrying ? 'Retrying…' : 'Retry' }}</button>
      <button v-if="props.dismissible && invitation && !operational && !keyringFailed" class="ghost" data-testid="first-run-later" :disabled="dismissing" @click="later">Set up later</button>
    </div>
  </section>
</template>
