<script setup lang="ts">
// The model and context are in the chat header (ChatStatus), and the connection indicator is in the rail.
import { computed } from 'vue'
import { COMMANDS } from '../commands'
import { setAutostart, state } from '../store'
import { linkLabel, status } from '../stores/status'

// Only facts from the connected core: nothing stale is shown while the link is down.
const core = computed(() => (state.app.link === 'ready' ? status.core : null))

function report(name: 'status' | 'usage'): void {
  void COMMANDS.find((c) => c.name === name)?.run('')
}

function onAutostart(event: Event): void {
  void setAutostart((event.target as HTMLInputElement).checked)
}
</script>

<template>
  <footer class="status" tabindex="0" aria-label="Odin status">
    <span v-if="state.app.link !== 'ready'" :class="['link-text', state.app.link]">{{ linkLabel(state.app.link) }}</span>
    <button v-if="core" class="status-item core-status" title="Status from the connected core. Click for the full /status report." @click="report('status')">Core {{ core.version }} · {{ core.phase }}</button>
    <span v-else-if="state.app.link === 'ready' && status.coreError" role="status">{{ status.coreError }}</span>
    <span v-if="core && core.phase !== 'ready'" class="warn">Odin is {{ core.phase }}</span>
    <span v-for="p in core?.providers ?? []" :key="p.name" :class="['provider', p.health]" :title="`${p.name}: ${p.health}`">
      ● {{ p.name }}
    </span>
    <span v-if="state.app.coreInstanceId" class="core">core {{ state.app.coreInstanceId.slice(0, 8) }}</span>
    <span v-if="state.app.link === 'ready' && status.usageError" :class="{ warn: !status.usageUnavailable }" role="status">{{ status.usageError }}</span>
    <span v-if="state.app.unreceipted" class="warn">{{ state.app.unreceipted }} awaiting receipt</span>
    <label class="autostart"><input type="checkbox" :checked="state.autostart" @change="onAutostart" /> Start at login</label>
  </footer>
</template>
