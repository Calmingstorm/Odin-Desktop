<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ArtifactRef } from '../../../shared/api'

const props = defineProps<{ artifact: ArtifactRef; /** Only the buttons, under an image already on screen. */ actionsOnly?: boolean }>()
const busy = ref(false)
const status = ref('')

const extension = computed(() => props.artifact.name.split('.').pop()?.slice(0, 4).toUpperCase() || 'FILE')
const size = computed(() => {
  const bytes = props.artifact.size
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
})

async function act(kind: 'open' | 'save' | 'reveal'): Promise<void> {
  busy.value = true
  status.value = ''
  const params = { ref: props.artifact.ref, name: props.artifact.name }
  const result =
    kind === 'open'
      ? await window.odin.openArtifact(params)
      : kind === 'save'
        ? await window.odin.saveArtifact(params)
        : await window.odin.revealArtifact(params)
  busy.value = false
  if (!result.ok) status.value = result.error.message
  else if (kind === 'save' && (result.result as { saved: boolean }).saved) status.value = 'Saved.'
}
</script>

<template>
  <div :class="['file-card', { unavailable: !artifact.available, 'actions-only': actionsOnly }]">
    <span v-if="!actionsOnly" class="file-icon" aria-hidden="true">{{ extension }}</span>
    <div v-if="!actionsOnly" class="file-body">
      <span class="file-name" :title="artifact.name">{{ artifact.name }}</span>
      <span class="file-meta">{{ artifact.available ? `${size} · ${artifact.mime}` : 'No longer available' }}</span>
      <span v-if="status" class="file-status" role="status">{{ status }}</span>
    </div>
    <span v-if="actionsOnly && status" class="file-status" role="status">{{ status }}</span>
    <div v-if="artifact.available" class="file-actions">
      <button class="ghost" :disabled="busy" title="Open with your default app" @click="act('open')">Open</button>
      <button class="ghost" :disabled="busy" @click="act('save')">Save as…</button>
      <button class="ghost" :disabled="busy" @click="act('reveal')">Show in folder</button>
    </div>
  </div>
</template>
