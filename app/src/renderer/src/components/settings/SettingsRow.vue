<script setup lang="ts">
defineProps<{ label: string; description?: string; controlId?: string; fullWidth?: boolean }>()
</script>

<template>
  <div :class="['settings-row', { 'settings-row-full-width': fullWidth }]">
    <div class="settings-row-copy">
      <label v-if="controlId" :for="controlId" class="settings-row-label">{{ label }}</label>
      <span v-else class="settings-row-label">{{ label }}</span>
      <p v-if="description" :id="controlId ? `${controlId}-description` : undefined" class="settings-row-description">{{ description }}</p>
    </div>
    <div class="settings-row-control"><slot /></div>
    <div v-if="$slots.note" class="settings-row-note"><slot name="note" /></div>
  </div>
</template>
