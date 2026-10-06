<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FirstRunStatus } from '../../../shared/api'
import { openSettings, state } from '../store'
import { loadCodex, loadSettings, settings } from '../stores/settings'
import { refreshStatus, status } from '../stores/status'

defineProps<{ dismissible?: boolean }>()

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
  provider_effective: 'The core has adopted the saved model and provider. This is not a generation or connection test.',
  provider_health_degraded: 'The core reports a problem with the running provider.',
  provider_health_unknown: 'The core cannot confirm provider health yet.',
  keyring_unavailable: 'The profile keyring is unavailable or locked. Retry to unlock it with the system prompt.',
  credential_state_unavailable: 'The core could not read credential state. Retry without re-entering saved credentials.'
}
const keyringFailed = computed(() => projection.value?.keyring_unavailable || Boolean(settings.meta?.status.keyring_error))
const retrying = ref(false)
const retryError = ref('')
async function retry(): Promise<void> {
  if (retrying.value) return
  retrying.value = true
  retryError.value = ''
  const epoch = state.recoveryEpoch
  const instance = state.app.coreInstanceId
  try {
    // Only this explicit owner click may ask the core for a bounded native unlock.
    // Reads, refresh timers and mounting Settings must never call this operation.
    if (keyringFailed.value) {
      const answer = await window.odin.secretsUnlock()
      if (!answer.ok) {
        retryError.value = 'The profile keyring could not be unlocked. Retry after dismissing any system prompt.'
        return
      }
    }
    if (epoch !== state.recoveryEpoch || instance !== state.app.coreInstanceId || state.app.link !== 'ready') return
    // Rehydrate after success, without replaying secret writes or authorizing a device login.
    await Promise.all([loadSettings(), loadCodex()])
    await refreshStatus()
  } catch {
    retryError.value = 'Could not refresh setup status. Try again when the core is connected.'
  } finally {
    retrying.value = false
  }
}
</script>

<template>
  <section class="first-run-banner panel" aria-label="Provider readiness" role="status"
    data-testid="first-run-banner" :data-state="projection?.state ?? 'unavailable'">
    <strong>{{ projection ? labels[projection.state] : 'Readiness unavailable' }}</strong>
    <p>{{ projection ? reasons[projection.reason] : (status.coreError || 'Waiting for current core status. Settings and chat remain available.') }}</p>
    <p v-if="keyringFailed && projection?.reason !== 'keyring_unavailable'" class="warn">The profile keyring is unavailable or locked. Retry to unlock it with the system prompt.</p>
    <p v-if="retryError" class="warn">{{ retryError }}</p>
    <div class="first-run-actions">
      <button class="ghost" data-testid="first-run-models" @click="openSettings('models')">Open Models and providers</button>
      <button class="ghost" data-testid="first-run-general" @click="openSettings('general')">Startup and notifications</button>
      <button v-if="keyringFailed || !projection || projection.state !== 'effective-ready'" class="ghost"
        data-testid="first-run-retry" :disabled="retrying || state.app.link !== 'ready'" @click="retry">{{ retrying ? 'Retrying…' : 'Retry' }}</button>
      <button v-if="dismissible" class="ghost" data-testid="first-run-later" @click="state.setupReminderHidden = true">Set up later</button>
    </div>
  </section>
</template>
