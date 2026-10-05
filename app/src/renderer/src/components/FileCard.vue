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
  if (busy.value || !props.artifact.available) return
  busy.value = true
  const params = { ref: props.artifact.ref, name: props.artifact.name }
  status.value = `${kind === 'save' ? 'Saving' : kind === 'open' ? 'Opening' : 'Locating'} ${params.name}…`
  try {
    const result =
      kind === 'open'
        ? await window.odin.openArtifact(params)
        : kind === 'save'
          ? await window.odin.saveArtifact(params)
          : await window.odin.revealArtifact(params)
    if (!result.ok) status.value = `${params.name}: ${result.error.message}`
    else if (kind === 'save') {
      status.value = (result.result as { saved: boolean }).saved ? `Saved ${params.name}.` : `Save cancelled for ${params.name}.`
    } else status.value = `${kind === 'open' ? 'Opened' : 'Shown in folder:'} ${params.name}.`
  } catch {
    status.value = `Could not ${kind} ${params.name}. Try again.`
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div :class="['file-card', { unavailable: !artifact.available, 'actions-only': actionsOnly }]">
    <span v-if="!actionsOnly" class="file-icon" aria-hidden="true">{{ extension }}</span>
    <div v-if="!actionsOnly" class="file-body">
      <span class="file-name" :title="artifact.name">{{ artifact.name }}</span>
      <span class="file-meta">{{ artifact.available ? `${size} · ${artifact.mime}` : 'No longer available' }}</span>
    </div>
    <span class="file-status" role="status" aria-atomic="true">{{ status }}</span>
    <div class="file-actions">
      <button type="button" class="ghost" :aria-disabled="busy || !artifact.available" :aria-label="`Open ${artifact.name}`" title="Open with your default app" @click="act('open')">Open</button>
      <button type="button" class="ghost" :aria-disabled="busy || !artifact.available" :aria-label="`Save ${artifact.name} as…`" @click="act('save')">Save as…</button>
      <button type="button" class="ghost" :aria-disabled="busy || !artifact.available" :aria-label="`Show ${artifact.name} in folder`" @click="act('reveal')">Show in folder</button>
    </div>
  </div>
</template>
