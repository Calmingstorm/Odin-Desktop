<script setup lang="ts">
import { ref } from 'vue'
import type { ToolEntry } from '../store'

const props = defineProps<{ entries: ToolEntry[]; live?: boolean }>()
const open = ref(Boolean(props.live))

function mark(entry: ToolEntry): string {
  if (entry.outcome === 'success') return '✓'
  if (entry.outcome === 'failure') return '✕'
  if (entry.outcome === 'unknown') return '?'
  return '…'
}
</script>

<template>
  <div v-if="entries.length" class="tools">
    <button class="tools-toggle" :aria-expanded="open" @click="open = !open">
      {{ entries.length }} tool call{{ entries.length === 1 ? '' : 's' }} {{ open ? '▾' : '▸' }}
    </button>
    <ul v-if="open" class="tool-list">
      <li v-for="e in entries" :key="e.invocation_id" :class="['tool', e.outcome ?? 'running']">
        <span class="mark" :title="e.outcome ?? 'running'">{{ mark(e) }}</span>
        <code class="name">{{ e.tool }}</code>
        <span v-if="e.target" class="target">{{ e.target }}</span>
        <span class="summary">{{ e.summary }}</span>
        <span v-if="e.exit_code !== undefined" class="exit">exit {{ e.exit_code }}</span>
        <span v-if="e.duration_ms !== undefined" class="dur">{{ (e.duration_ms / 1000).toFixed(1) }}s</span>
      </li>
    </ul>
  </div>
</template>
