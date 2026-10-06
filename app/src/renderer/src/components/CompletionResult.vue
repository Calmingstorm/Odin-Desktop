<script setup lang="ts">
import { completion } from '../stores/completion'
import { unavailableText } from '../capability'
defineProps<{ resource: string; feature: string }>()
</script>
<template>
  <p v-if="completion[resource]?.unavailable" role="status">{{ unavailableText(feature) }}</p>
  <template v-else>
    <p v-if="completion[resource]?.busy" role="status">Reading {{ feature }}.</p>
    <p v-if="completion[resource]?.error" class="warn" role="status">{{ completion[resource]?.error }}{{ completion[resource]?.loaded ? ' Showing the last successful read.' : '' }}</p>
    <p v-if="!completion[resource]?.loaded && !completion[resource]?.busy && !completion[resource]?.error" class="panel-hint">Not read yet.</p>
    <template v-if="completion[resource]?.loaded">
      <p v-if="completion[resource]?.label" class="panel-hint">{{ completion[resource]?.label }}</p>
      <pre class="manage-json">{{ JSON.stringify(completion[resource]?.value, null, 2) }}</pre>
    </template>
  </template>
</template>
