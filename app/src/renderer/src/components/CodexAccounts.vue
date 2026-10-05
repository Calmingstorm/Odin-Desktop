<script setup lang="ts">
import { onMounted } from 'vue'
import type { CodexAccount, QuotaWindow } from '../../../shared/api'
import { ask } from '../dialog'
import { accountIdentity, activateAccount, beginLogin, labelAccount, loadCodex, removeAccount, settings, stopLogin } from '../stores/settings'
import { unavailableText } from '../capability'

onMounted(loadCodex)

function windowName(minutes: number): string {
  if (minutes >= 10080) return 'weekly'
  if (minutes >= 1440) return `${Math.round(minutes / 1440)}-day`
  return `${Math.round(minutes / 60)}-hour`
}

function resets(window: QuotaWindow): string {
  if (!window.resets_at) return ''
  return `, resets ${new Date(window.resets_at * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}`
}

/** Odin's quota as reported by the account's own replies: percent used, never a guess. */
function quota(account: CodexAccount): string {
  const windows = [account.quota?.primary, account.quota?.secondary].filter((w): w is QuotaWindow => Boolean(w))
  if (!windows.length) return 'Quota not reported yet'
  return windows.map((w) => `${Math.round(w.used_percent)}% of the ${windowName(w.window_minutes)} limit used${resets(w)}`).join('; ')
}

async function rename(account: CodexAccount): Promise<void> {
  const label = await ask({
    title: 'Label this account',
    message: '',
    confirmLabel: 'Save',
    input: { value: account.label ?? '', label: 'Label', maxLength: 80 }
  })
  if (typeof label === 'string') await labelAccount(account, label.trim())
}

async function remove(account: CodexAccount): Promise<void> {
  const confirmed = await ask({
    title: 'Remove this account?',
    message: `Odin stops using ${account.email ?? 'this account'}. You can sign in with it again later.`,
    confirmLabel: 'Remove',
    danger: true
  })
  if (confirmed) await removeAccount(account)
}
</script>

<template>
  <section class="panel codex-accounts" aria-label="Codex accounts">
    <header class="panel-head">
      <h3>Codex accounts</h3>
      <span class="panel-hint">Odin uses one at a time and moves to the next when one hits its limit.</span>
      <button v-if="!settings.codex.unavailable" class="ghost" :disabled="settings.codex.login?.status === 'waiting'" @click="beginLogin">Add account</button>
    </header>
    <p v-if="settings.codex.unavailable" class="capability-unavailable" role="status">{{ unavailableText('Codex accounts') }}</p>
    <template v-else>
      <div v-if="settings.codex.login" class="login" role="status">
      <template v-if="settings.codex.login.status === 'waiting'">
        <p>
          Open <a :href="settings.codex.login.url" target="_blank" rel="noopener noreferrer">{{ settings.codex.login.url }}</a>
          and enter <code class="login-code">{{ settings.codex.login.code }}</code>. Odin adds the account once you approve it.
        </p>
        <button class="ghost" @click="stopLogin">Stop waiting</button>
      </template>
      <p v-else-if="settings.codex.login.status === 'done'">{{ settings.codex.login.message }}</p>
      <p v-else-if="settings.codex.login.status === 'stopped'">Stopped waiting. A login you finish in the browser is still added.</p>
      <p v-else class="warn">{{ settings.codex.login.message }}</p>
      </div>
      <p v-if="settings.codex.error" class="warn">{{ settings.codex.error }}</p>
      <p v-if="settings.codex.stale && !settings.codex.busy" class="warn">
        The list couldn't be refreshed after your last change, so it may be out of date.
        <button class="ghost" @click="loadCodex">Refresh</button>
      </p>
      <p v-else-if="settings.codex.status && !settings.codex.status.configured" class="panel-hint">Codex isn't configured.</p>
      <ul class="accounts">
        <li v-for="account in settings.codex.status?.accounts ?? []" :key="account.index" :class="['account', { current: account.is_current }]">
          <p v-if="account.error" class="warn">Account {{ account.index + 1 }}: {{ account.error }}</p>
          <template v-else>
            <div class="account-line">
              <strong>{{ account.label || account.email }}</strong>
              <span class="account-meta">{{ account.email }} · {{ account.plan_type }}</span>
              <span v-if="account.is_current" class="in-use">In use</span>
              <span v-if="account.limit_reached" class="warn">Limit reached</span>
              <span v-if="account.quota_check_failed" class="warn">Quota check failed</span>
              <span v-if="account.expired" class="warn">Sign-in expired</span>
            </div>
            <div class="account-meta">{{ quota(account) }}</div>
            <div class="account-actions">
              <button v-if="!account.is_current" class="ghost" :disabled="settings.codex.busy || settings.codex.stale" @click="activateAccount(account)">
                Use this account
              </button>
              <button class="ghost" :disabled="settings.codex.busy || settings.codex.stale" @click="rename(account)">Label…</button>
              <button class="ghost danger-item" :disabled="settings.codex.busy || settings.codex.stale" @click="remove(account)">Remove…</button>
            </div>
            <p v-if="settings.codex.notes[accountIdentity(account)]" class="account-note">{{ settings.codex.notes[accountIdentity(account)] }}</p>
          </template>
        </li>
      </ul>
    </template>
  </section>
</template>
