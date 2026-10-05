<script setup lang="ts">
import type { ComposerAttachment } from '../stores/composer'

defineProps<{ items: ComposerAttachment[] }>()
const emit = defineEmits<{ remove: [id: string]; knowledge: [id: string, value: boolean] }>()

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
        <span class="attachment-meta">
          <template v-if="a.status === 'uploading'">{{ size(a.sent) }} of {{ size(a.size) }}</template>
          <template v-else-if="a.status === 'failed'">{{ a.error }}</template>
          <template v-else>{{ size(a.size) }}</template>
        </span>
        <progress v-if="a.status === 'uploading'" :value="a.sent" :max="a.size" />
        <label v-if="a.status === 'ready'" class="knowledge" title="Odin keeps it for later searches, not just this message">
          <input type="checkbox" :checked="a.addToKnowledge" @change="emit('knowledge', a.id, ($event.target as HTMLInputElement).checked)" />
          Add to knowledge
        </label>
      </div>
      <button type="button" class="remove" :aria-label="`Remove ${a.name}`" @click="emit('remove', a.id)">✕</button>
    </li>
  </ul>
</template>
