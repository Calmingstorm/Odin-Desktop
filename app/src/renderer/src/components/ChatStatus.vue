<script setup lang="ts">
// The chat header's model and context, from the connected core. Each opens its full report, as the status bar did.
import { computed } from 'vue'
import { COMMANDS } from '../commands'
import { basis, count, percent, share } from '../format'
import { state } from '../store'
import { status } from '../stores/status'

// Only facts from the connected core: nothing stale is shown while the link is down.
const core = computed(() => (state.app.link === 'ready' ? status.core : null))
const usage = computed(() => (state.app.link === 'ready' ? status.usage : null))
const context = computed(() => (usage.value ? share(usage.value.context.used, usage.value.context.budget) : null))
const quota = computed(() => usage.value?.quota[0] ?? null)

const usageTitle = computed(() => {
  const u = usage.value
  if (!u) return ''
  return [
    `Context: ${count(u.context.used)} of ${count(u.context.budget)} tokens (${basis(context.value ?? u.context.used)})`,
    ...u.quota.map(
      (q) =>
        `Quota, ${q.account} (${q.window}): ${percent(q.used_percent)} used (${basis(q.used_percent)})` +
        (q.resets_at ? `, resets ${new Date(q.resets_at).toLocaleString()}` : '')
    ),
    `Tokens in the last 24 hours: ${count(u.tokens)} (${basis(u.tokens)})`,
    'Click for the full /usage report.'
  ].join('\n')
})

function report(name: 'status' | 'usage'): void {
  void COMMANDS.find((c) => c.name === name)?.run('')
}
</script>

<template>
  <div v-if="core?.model || (usage && context)" class="chat-status">
    <button
      v-if="core?.model"
      class="status-item chat-model"
      :title="`Model and effort, served by ${core.model.provider}. Click for the full /status report.`"
      @click="report('status')"
    >
      {{ core.model.main }} · {{ core.model.effort }}
    </button>
    <button v-if="usage && context" class="status-item chat-context" :title="usageTitle" @click="report('usage')">
      Context {{ percent(context) }} · Quota {{ quota ? percent(quota.used_percent) : '—' }} · {{ count(usage.tokens) }} tokens in 24h
    </button>
  </div>
</template>
