<script setup lang="ts">
import { computed } from 'vue'
import { setAutostart, state } from '../store'

const LABELS: Record<string, string> = {
  starting: 'Starting',
  connecting: 'Connecting to Odin',
  ready: 'Connected',
  reconnecting: 'Reconnecting',
  'core-restarting': 'Odin is restarting',
  'core-failed': 'Odin stopped unexpectedly'
}
const label = computed(() => LABELS[state.app.link] ?? state.app.link)

function onAutostart(event: Event): void {
  void setAutostart((event.target as HTMLInputElement).checked)
}
</script>

<template>
  <footer class="status">
    <span :class="['link', state.app.link]">● {{ label }}</span>
    <span v-if="state.app.coreInstanceId" class="core">core {{ state.app.coreInstanceId.slice(0, 8) }}</span>
    <span v-if="state.app.unreceipted" class="warn">{{ state.app.unreceipted }} awaiting receipt</span>
    <label class="autostart"><input type="checkbox" :checked="state.autostart" @change="onAutostart" /> Start at login</label>
  </footer>
</template>
