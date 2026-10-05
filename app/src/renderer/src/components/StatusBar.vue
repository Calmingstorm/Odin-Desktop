<script setup lang="ts">
import { computed } from 'vue'
import { COMMANDS } from '../commands'
import { basis, count, percent, share } from '../format'
import { setAutostart, state } from '../store'
import { status } from '../stores/status'

const LABELS: Record<string, string> = {
  starting: 'Starting',
  connecting: 'Connecting to Odin',
  ready: 'Connected',
  reconnecting: 'Reconnecting',
  'core-restarting': 'Odin is restarting',
  'core-failed': 'Odin stopped unexpectedly'
}
const label = computed(() => LABELS[state.app.link] ?? state.app.link)

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

function onAutostart(event: Event): void {
  void setAutostart((event.target as HTMLInputElement).checked)
}
</script>

<template>
  <footer class="status" tabindex="0" aria-label="Odin status">
    <span :class="['link', state.app.link]" role="status" aria-atomic="true">● {{ label }}</span>
    <button v-if="core" class="status-item core-status" title="Status from the connected core. Click for the full /status report." @click="report('status')">Core {{ core.version }} · {{ core.phase }}</button>
    <span v-else-if="state.app.link === 'ready' && status.coreError" role="status">{{ status.coreError }}</span>
    <span v-if="core && core.phase !== 'ready'" class="warn">Odin is {{ core.phase }}</span>
    <button
      v-if="core?.model"
      class="status-item"
      :title="`Model and effort, served by ${core.model.provider}. Click for the full /status report.`"
      @click="report('status')"
    >
      {{ core.model.main }} · {{ core.model.effort }}
    </button>
    <span v-for="p in core?.providers ?? []" :key="p.name" :class="['provider', p.health]" :title="`${p.name}: ${p.health}`">
      ● {{ p.name }}
    </span>
    <button v-if="usage && context" class="status-item" :title="usageTitle" @click="report('usage')">
      Context {{ percent(context) }} · Quota {{ quota ? percent(quota.used_percent) : '—' }} · {{ count(usage.tokens) }} tokens in 24h
    </button>
    <span v-if="state.app.coreInstanceId" class="core">core {{ state.app.coreInstanceId.slice(0, 8) }}</span>
    <span v-if="state.app.link === 'ready' && status.usageError" :class="{ warn: !status.usageUnavailable }" role="status">{{ status.usageError }}</span>
    <span v-if="state.app.unreceipted" class="warn">{{ state.app.unreceipted }} awaiting receipt</span>
    <label class="autostart"><input type="checkbox" :checked="state.autostart" @change="onAutostart" /> Start at login</label>
  </footer>
</template>
