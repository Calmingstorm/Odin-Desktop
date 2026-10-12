<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { odin } from '../bridge'
import { retryLogin, settings, stopLogin } from '../stores/settings'

// The one Codex device sign-in in progress, wherever it was started: the chat's setup banner or Settings. There is a
// single login and a single poller (stores/settings.ts); this only shows it and offers its controls.
const login = computed(() => settings.codex.login)
const copyStatus = ref('')
// Announced: the progress only. The temporary sign-in code is shown, never read out by a live region.
const announcement = computed(() => {
  if (!login.value) return ''
  if (login.value.status === 'waiting') return 'Waiting for sign-in approval in the browser.'
  if (login.value.status === 'stopped') return 'Stopped waiting. This app is no longer checking or finishing that login. Add an account to start again.'
  return login.value.message ?? (login.value.status === 'done' ? 'Account added.' : `Sign-in ${login.value.status}.`)
})
watch(() => settings.codex.login?.code, () => { copyStatus.value = '' })
async function copyCode(): Promise<void> {
  if (!login.value || login.value.status !== 'waiting') return
  const result = await odin.copyText(login.value.code)
  copyStatus.value = result.ok ? 'Sign-in code copied.' : 'Could not copy the sign-in code.'
}
async function openVerification(): Promise<void> {
  const result = await odin.codexOpenVerification()
  if (!result.ok) settings.codex.error = result.error.message
}
</script>

<template>
  <div v-if="login" class="login" data-testid="codex-sign-in">
    <p role="status" aria-atomic="true">{{ announcement }}</p>
    <template v-if="login.status === 'waiting'">
      <p>
        Open <button class="ghost" data-testid="codex-open-verification" aria-describedby="codex-login-browser" @click="openVerification">{{ login.url }}</button>
        and enter the sign-in code. Odin adds the account once you approve it.
      </p>
      <p id="codex-login-browser" class="panel-hint">Opens in your browser. The sign-in code is temporary; your stored credentials are never shown here.</p>
      <p>Sign-in code: <code class="login-code">{{ login.code }}</code></p>
      <button class="ghost" @click="copyCode">Copy sign-in code</button>
      <p v-if="copyStatus" role="status">{{ copyStatus }}</p>
      <button class="ghost" data-testid="codex-cancel-login" @click="stopLogin">Stop waiting</button>
    </template>
    <button v-if="login.status === 'failed'" class="ghost" data-testid="codex-retry-login" @click="retryLogin">Retry login</button>
  </div>
</template>
