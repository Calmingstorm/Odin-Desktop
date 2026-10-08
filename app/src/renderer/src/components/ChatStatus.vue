<script setup lang="ts">
// The chat header's model and context, from the connected core. Each opens its full report, as the status bar did.
import { computed } from 'vue'
import { COMMANDS } from '../commands'
import { basis, count, percent, share } from '../format'
import { state } from '../store'
import { status } from '../stores/status'

// Only facts from the connected core: nothing stale is shown while the link is down.
const current = computed(() => state.app.link === 'ready' && status.epoch === state.recoveryEpoch)
const core = computed(() => (current.value && (!state.app.coreInstanceId || status.core?.core_instance_id === state.app.coreInstanceId) ? status.core : null))
const usage = computed(() => (current.value ? status.usage : null))
const context = computed(() => (usage.value?.context ? share(usage.value.context.used, usage.value.context.budget) : null))
const hasContext = computed(() => context.value?.value !== null && context.value?.value !== undefined && context.value.kind !== 'unknown')
const quota = computed(() => usage.value?.quota[0] ?? null)

const usageTitle = computed(() => {
  const u = usage.value
  if (!u) return ''
  return [
    ...(hasContext.value ? [`Context: ${count(u.context.used)} of ${count(u.context.budget)} tokens (${basis(context.value!)})`] : []),
    ...u.quota.map(
      (q) =>
        `Quota, ${q.account} (${q.window}): ${percent(q.used_percent)} used (${basis(q.used_percent)})` +
        (q.resets_at ? `, resets ${new Date(q.resets_at).toLocaleString()}` : '')
    ),
    `Tokens (${u.period}): ${count(u.tokens)} (${basis(u.tokens)})`,
    'Click for the full /usage report.'
  ].join('\n')
})

function report(name: 'status' | 'usage'): void {
  void COMMANDS.find((c) => c.name === name)?.run('')
}
</script>

<template>
  <div v-if="core?.model || usage" class="chat-status">
    <button
      v-if="core?.model"
      class="status-item chat-model"
      :title="`Model and effort, served by ${core.model.provider}. Click for the full /status report.`"
      @click="report('status')"
    >
      {{ core.model.main }} · {{ core.model.effort }}
    </button>
    <button v-if="usage" class="status-item chat-context" :title="usageTitle" @click="report('usage')">
      <template v-if="hasContext">Context {{ percent(context!) }} · </template><template v-if="quota">Quota {{ percent(quota.used_percent) }} · </template>{{ count(usage.tokens) }} tokens in {{ usage.period }}
    </button>
  </div>
</template>
