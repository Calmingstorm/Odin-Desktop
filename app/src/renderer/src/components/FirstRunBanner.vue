<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { odin } from '../bridge'
import type { FirstRunStatus } from '../../../shared/api'
import { dismissSetupReminder, openSettings, state } from '../store'
import { beginLogin, loadCodex, loadSettings, settings } from '../stores/settings'
import { refreshStatus } from '../stores/status'
import { codexSignInNeeded, setupProjection as projection } from '../provider-setup'
import CodexSignIn from './CodexSignIn.vue'

const props = defineProps<{ dismissible?: boolean }>()
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
// The chosen provider is Codex and no account is stored: the invitation is to sign in, right here.
const signIn = computed(() => invitation.value && !operational.value && !keyringFailed.value && codexSignInNeeded.value)
const waiting = computed(() => settings.codex.login?.status === 'waiting')
let signedInHere = false
async function signInHere(): Promise<void> {
  signedInHere = true
  await beginLogin()
}
// Once the core is ready after a sign-in started here, the banner goes and the message box takes focus, unless the
// user has already moved focus somewhere else.
watch(visible, async (now, before) => {
  if (!before || now || !signedInHere) return
  signedInHere = false
  await nextTick()
  if (typeof document.querySelector !== 'function' || (document.activeElement && document.activeElement !== document.body)) return
  document.querySelector<HTMLElement>('textarea[aria-label="Message"]')?.focus()
}, { flush: 'post' })
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
      const answer = await odin.secretsUnlock()
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
  <section v-if="visible" class="first-run-banner panel" :aria-label="operational || keyringFailed ? 'Provider attention' : 'Provider setup'"
    data-testid="first-run-banner" :data-state="projection?.state ?? 'keyring-attention'" :data-kind="operational || keyringFailed ? 'operational' : signIn ? 'sign-in' : 'invitation'">
    <!-- The live region carries the state only; a sign-in code below is shown, never announced. -->
    <div role="status">
      <template v-if="signIn">
        <strong>Sign in to start chatting</strong>
        <p>Odin uses Codex through your ChatGPT account. Sign in once, and you can start.</p>
      </template>
      <template v-else>
        <strong>{{ keyringFailed ? 'Keyring needs attention' : (projection ? labels[projection.state] : '') }}</strong>
        <p v-if="projection && reasons[projection.reason]">{{ reasons[projection.reason] }}</p>
      </template>
      <p v-if="keyringFailed && projection?.reason !== 'keyring_unavailable'" class="warn">The profile keyring is unavailable or locked. Retry to unlock it with the system prompt.</p>
      <p v-if="retryError" class="warn">{{ retryError }}</p>
      <p v-if="dismissError" class="warn">{{ dismissError }}</p>
      <p v-if="signIn && settings.codex.error" class="warn">{{ settings.codex.error }}</p>
    </div>
    <CodexSignIn v-if="signIn" />
    <div class="first-run-actions">
      <template v-if="signIn">
        <button v-if="!waiting" class="primary" data-testid="first-run-sign-in" :disabled="settings.codex.beginning" @click="signInHere">Sign in with ChatGPT</button>
        <button class="ghost" data-testid="first-run-other-provider" @click="openSettings('models', 'providers')">Use another provider</button>
        <button class="ghost" data-testid="first-run-import" @click="openSettings('general', 'importer')">Import from Odin</button>
      </template>
      <template v-else>
        <button class="ghost" data-testid="first-run-models" @click="openSettings('models')">Open Models and providers</button>
        <button v-if="invitation && !operational && !keyringFailed" class="ghost" data-testid="first-run-general" @click="openSettings('general')">Startup and notifications</button>
        <button class="ghost"
          data-testid="first-run-retry" :disabled="retrying || state.app.link !== 'ready'" @click="retry">{{ retrying ? 'Retrying…' : 'Retry' }}</button>
      </template>
      <!-- Stop waiting first: dismissing must not leave a sign-in polling out of sight. -->
      <button v-if="props.dismissible && invitation && !operational && !keyringFailed" class="ghost" data-testid="first-run-later" :disabled="dismissing || waiting" @click="later">Set up later</button>
    </div>
  </section>
</template>
