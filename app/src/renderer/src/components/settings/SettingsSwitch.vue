<script setup lang="ts">
defineProps<{ id: string; label: string; checked: boolean; disabled?: boolean; describedBy?: string; invalid?: boolean }>()
const emit = defineEmits<{ change: [checked: boolean] }>()
</script>

<template>
  <input
    :id="id"
    class="settings-switch"
    type="checkbox"
    role="switch"
    :aria-label="label"
    :aria-describedby="describedBy || undefined"
    :aria-invalid="invalid || undefined"
    :checked="checked"
    :disabled="disabled"
    @change="emit('change', ($event.target as HTMLInputElement).checked)"
  />
</template>
