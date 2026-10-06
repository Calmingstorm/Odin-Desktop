<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import CompletionResult from './CompletionResult.vue'
import { readCompletion } from '../stores/completion'
import { act, management } from '../stores/management'
import { ask } from '../dialog'
import { isUnavailable, unavailableText } from '../capability'
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
  { key: 'stats', feature: 'Runtime statistics', run: () => window.odin.observabilityStats({}) },
  { key: 'recovery-stats', feature: 'Recovery statistics', run: () => window.odin.recoveryStats({}) },
  { key: 'recovery-recent', feature: 'Recent recovery', run: () => window.odin.recoveryRecent({ limit: 20 }) },
  { key: 'capacity', feature: 'Capacity breaker', run: () => window.odin.capacitySnapshot({}) },
  { key: 'ssh-pools', feature: 'SSH connection pools', run: () => window.odin.poolsSsh({}) },
  { key: 'http-pools', feature: 'HTTP connection pools', run: () => window.odin.poolsHttp({}) }
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
  }, (answer) => JSON.stringify(answer), refreshPools)
}
</script>
<template>
  <section v-for="section in sections" :key="section.key" class="panel" :aria-label="section.feature">
    <header class="panel-head"><h3>{{ section.feature }}</h3><button class="ghost" @click="readCompletion(section.key, section.run)">Read {{ section.feature }}</button></header>
    <CompletionResult :resource="section.key" :feature="section.feature" />
  </section>
  <section class="panel" aria-label="Connection pool actions">
    <h3>Connection pool actions</h3>
    <p v-if="closeUnavailable" role="status">{{ unavailableText('Connection pool actions') }}</p>
    <template v-else>
      <label>Pool host <input v-model="host" /></label>
      <label>Pool SSH user (optional) <input v-model="sshUser" /></label>
      <button class="ghost" :disabled="!host || management.busy['connection-pools']" @click="closePools(false)">Close host pool…</button>
      <button class="ghost" :disabled="management.busy['connection-pools']" @click="closePools(true)">Close all pools…</button>
    </template>
    <p v-if="management.notes['connection-pools']" role="status">{{ management.notes['connection-pools'] }}</p>
  </section>
</template>
