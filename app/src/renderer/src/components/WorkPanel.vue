<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { loadWork, work } from '../stores/work'
import WorkList from './WorkList.vue'

const panel = ref<HTMLElement | null>(null)
const refresh = ref<HTMLButtonElement | null>(null)
let opener: HTMLElement | null = null

onMounted(() => {
  opener = document.activeElement as HTMLElement | null
  refresh.value?.focus?.()
})

function restoreFocus(): void {
  if (opener?.isConnected && typeof opener.focus === 'function') opener.focus()
  else document.querySelector<HTMLButtonElement>('.work-toggle')?.focus()
}

function close(): void {
  work.open = false
  restoreFocus()
}

// An inline region, not a modal. Tab may leave it; the rest of chat stays available.
onBeforeUnmount(() => {
  if (panel.value?.contains?.(document.activeElement)) restoreFocus()
})
</script>

<template>
  <section ref="panel" class="work-panel" aria-label="Running work" @keydown.esc.prevent.stop="close">
    <header class="work-head">
      <strong>Work</strong>
      <span class="work-hint">Agents, tasks, loops, processes and schedules, with the controls Odin offers for each.</span>
      <button ref="refresh" class="ghost" aria-label="Refresh work" title="Fetch the list again" @click="loadWork">Refresh</button>
      <button class="ghost" aria-label="Close work" title="Close work" @click="close">✕</button>
    </header>
    <WorkList />
  </section>
</template>
