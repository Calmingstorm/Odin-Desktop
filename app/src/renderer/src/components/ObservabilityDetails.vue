<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import CompletionResult from './CompletionResult.vue'
import SettingsSection from './settings/SettingsSection.vue'
import SettingsRow from './settings/SettingsRow.vue'
import { readCompletion } from '../stores/completion'
import { act, management } from '../stores/management'
import { ask } from '../dialog'
import { isUnavailable, settingsUnavailableText as unavailableText } from '../capability'
import { isUnknownOutcome, onLateReceipt } from '../store'
const host = ref('')
const sshUser = ref('')
const closeUnavailable = ref(false)
let alive = true
let pendingClose: string | undefined
onUnmounted(() => { alive = false })
onLateReceipt((receipt) => {
  if (!alive || receipt.id !== pendingClose) return
  if (!receipt.settled.ok && isUnknownOutcome(receipt.settled.error)) return
  pendingClose = undefined
  if (!receipt.settled.ok && isUnavailable(receipt.settled.error)) closeUnavailable.value = true
})
const sections = [
  { key: 'stats', feature: 'Runtime statistics', help: 'Requests, tool calls and context compression since Odin started.', run: () => window.odin.observabilityStats({}) },
  { key: 'recovery-stats', feature: 'Recovery statistics', help: 'How often model requests were retried or recovered.', run: () => window.odin.recoveryStats({}) },
  { key: 'recovery-recent', feature: 'Recent recovery', help: 'The latest recovery events.', run: () => window.odin.recoveryRecent({ limit: 20 }) },
  { key: 'capacity', feature: 'Capacity breaker', help: 'Whether model capacity limits are pausing requests.', run: () => window.odin.capacitySnapshot({}) },
  { key: 'ssh-pools', feature: 'SSH connection pools', help: 'Open SSH connections to your hosts.', run: () => window.odin.poolsSsh({}) },
  { key: 'http-pools', feature: 'HTTP connection pools', help: 'Open web connections Odin keeps for reuse.', run: () => window.odin.poolsHttp({}) }
]
const refreshPools = async (): Promise<void> => {
  await Promise.all(sections.slice(-2).map((section) => readCompletion(section.key, section.run)))
}
async function closePools(all: boolean): Promise<void> {
  const params: { host?: string; ssh_user?: string } = all ? {} : { host: host.value, ...(sshUser.value ? { ssh_user: sshUser.value } : {}) }
  if (!all && !params.host) return
  if (!await ask({ title: all ? 'Close all SSH connection pools?' : 'Close this host pool?', message: all ? 'Existing SSH connections will be closed. New work opens new connections. HTTP pools are unchanged.' : `Close SSH connections for ${params.host}.`, confirmLabel: 'Close connections' })) return
  await act('connection-pools', async () => {
    const result = await window.odin.poolsClose(params)
    if (!result.ok && isUnknownOutcome(result.error)) pendingClose = result.error.command_id
    if (!result.ok && isUnavailable(result.error)) closeUnavailable.value = true
    return result
  }, receipt, refreshPools)
}

/** The core's closure answer in words: one host ({closed, host}) or every pool ({closed_count}). */
function receipt(answer: unknown): string {
  const value = (answer && typeof answer === 'object' ? answer : {}) as { closed?: unknown; host?: unknown; closed_count?: unknown }
  if (typeof value.closed_count === 'number') return `Closed ${value.closed_count} SSH connection${value.closed_count === 1 ? '' : 's'}.`
  if (typeof value.host === 'string') return value.closed === true ? `Closed the SSH connection to ${value.host}.` : `No SSH connection to ${value.host} was open.`
  return 'Closed.'
}
</script>
<template>
  <SettingsSection title="Diagnostics" aria-label="Diagnostics" description="Read-only reports from the running engine.">
    <section v-for="section in sections" :key="section.key" :aria-label="section.feature">
      <SettingsRow :label="section.feature" :description="section.help">
        <button class="ghost" @click="readCompletion(section.key, section.run)">Read {{ section.feature }}</button>
        <template #note><CompletionResult :resource="section.key" :feature="section.feature" /></template>
      </SettingsRow>
    </section>
  </SettingsSection>
  <SettingsSection title="Connection pool actions" aria-label="Connection pool actions">
    <p v-if="closeUnavailable" role="status">{{ unavailableText('Connection pool actions') }}</p>
    <template v-else>
      <SettingsRow label="Host connections" description="Close existing SSH connections to one host; new work opens new ones.">
        <label class="control-field">Host
          <input v-model="host" />
        </label>
        <label class="control-field">SSH user (optional)
          <input v-model="sshUser" />
        </label>
        <button class="ghost" :disabled="!host || management.busy['connection-pools']" @click="closePools(false)">Close host pool…</button>
      </SettingsRow>
      <SettingsRow label="All connections" description="Close every SSH connection. Web connections are unchanged.">
        <button class="ghost" :disabled="management.busy['connection-pools']" @click="closePools(true)">Close all pools…</button>
      </SettingsRow>
    </template>
    <p v-if="management.notes['connection-pools']" role="status">{{ management.notes['connection-pools'] }}</p>
  </SettingsSection>
</template>
