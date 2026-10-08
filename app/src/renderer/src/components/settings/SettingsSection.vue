<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <section class="settings-section">
    <header class="settings-section-header">
      <h3>{{ title }}</h3>
      <p v-if="description">{{ description }}</p>
    </header>
    <div class="settings-card"><slot /></div>
  </section>
</template>
