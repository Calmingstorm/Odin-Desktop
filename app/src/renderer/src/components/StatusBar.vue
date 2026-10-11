<script setup lang="ts">
// Compact connection facts and actionable warnings. Full reports remain one click away.
import { computed } from 'vue'
import { COMMANDS } from '../commands'
import { openSettings, state } from '../store'
import { linkLabel, status } from '../stores/status'

// Only facts from the connected core: nothing stale is shown while the link is down.
const core = computed(() => (state.app.link === 'ready' && status.epoch === state.recoveryEpoch &&
  (!state.app.coreInstanceId || status.core?.core_instance_id === state.app.coreInstanceId) ? status.core : null))
const problems = computed(() => (core.value?.providers ?? []).filter((p) => ['degraded', 'unavailable', 'error', 'failed'].includes(p.health)))
const unknownEffects = computed(() => Object.values(state.views).reduce((sum, view) => sum +
  (view?.unresolved.reduce((total, outcome) => total + outcome.unknown_effects, 0) ?? 0), 0))

function report(name: 'status' | 'usage'): void {
  void COMMANDS.find((c) => c.name === name)?.run('')
}

</script>

<template>
  <footer class="status" tabindex="0" aria-label="Odin status">
    <span :class="['link-text', state.app.link]">{{ linkLabel(state.app.link, state.app.linkProblem) }}</span>
    <button class="status-item core-status" title="Open the full /status report." @click="report('status')">Status</button>
    <button class="status-item" title="Open the full /usage report." @click="report('usage')">Usage</button>
    <span v-if="state.app.link === 'ready' && status.coreError" role="status">{{ status.coreError }}</span>
    <span v-if="core && core.phase !== 'ready'" class="warn">Odin is {{ core.phase }}</span>
    <button v-for="p in problems" :key="p.name" class="status-item warn" :title="`Review ${p.name} in Models and providers`" @click="openSettings('models')">{{ p.name }} {{ p.health }}</button>
    <span v-if="state.app.link === 'ready' && status.usageError" :class="{ warn: !status.usageUnavailable }" role="status">{{ status.usageError }}</span>
    <span v-if="state.app.unreceipted" class="warn">{{ state.app.unreceipted }} awaiting receipt</span>
    <span v-if="unknownEffects" class="warn">{{ unknownEffects }} {{ unknownEffects === 1 ? 'action with an unknown outcome' : 'actions with unknown outcomes' }}</span>
    <span v-if="state.app.cleanupWarning" class="warn">Cleanup needs attention</span>
  </footer>
</template>
