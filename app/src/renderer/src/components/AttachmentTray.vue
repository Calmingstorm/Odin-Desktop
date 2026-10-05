<script setup lang="ts">
import { nextTick } from 'vue'
import type { ComposerAttachment } from '../stores/composer'

defineProps<{ items: ComposerAttachment[] }>()
const emit = defineEmits<{ remove: [id: string]; knowledge: [id: string, value: boolean] }>()
async function remove(id: string, event: MouseEvent): Promise<void> {
  const button = event.currentTarget as HTMLButtonElement
  const row = button.closest('li')
  const next = row?.nextElementSibling?.querySelector<HTMLButtonElement>('button.remove') ?? row?.previousElementSibling?.querySelector<HTMLButtonElement>('button.remove')
  const wasFocused = document.activeElement === button
  emit('remove', id)
  await nextTick()
  if (wasFocused && (document.activeElement === document.body || document.activeElement === button)) {
    if (next?.isConnected) next.focus()
    else document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')?.focus()
  }
}

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <ul class="attachments" aria-label="Attachments">
    <li v-for="a in items" :key="a.id" :class="['attachment', a.status]">
      <img v-if="a.previewUrl" class="thumb" :src="a.previewUrl" alt="" />
      <span v-else class="thumb file" aria-hidden="true">{{ a.name.split('.').pop()?.slice(0, 4).toUpperCase() || 'FILE' }}</span>
      <div class="attachment-body">
        <span class="attachment-name" :title="a.name">{{ a.name }}</span>
        <span :id="`attachment-status-${a.id}`" class="attachment-meta">
          <template v-if="a.status === 'uploading'">{{ size(a.sent) }} of {{ size(a.size) }}</template>
          <template v-else-if="a.status === 'failed'">{{ a.error }}</template>
          <template v-else>{{ size(a.size) }}</template>
        </span>
        <progress v-if="a.status === 'uploading'" :aria-label="`Uploading ${a.name}`" :value="a.sent" :max="a.size" />
        <label v-if="a.status === 'ready'" class="knowledge" title="Odin keeps it for later searches, not just this message">
          <input type="checkbox" :aria-label="`Add ${a.name} to knowledge`" :checked="a.addToKnowledge" @change="emit('knowledge', a.id, ($event.target as HTMLInputElement).checked)" />
          Add to knowledge
        </label>
      </div>
      <button type="button" class="remove" :aria-label="`Remove ${a.name}`" :aria-describedby="`attachment-status-${a.id}`" @click="remove(a.id, $event)">✕</button>
    </li>
  </ul>
</template>

<style scoped>
button:focus-visible, input:focus-visible { outline: 2px solid var(--accent, #91baff); outline-offset: 3px; }
</style>
