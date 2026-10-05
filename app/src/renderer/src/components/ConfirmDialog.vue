<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { dialog } from '../dialog'

const text = ref('')
const confirmButton = ref<HTMLButtonElement | null>(null)
const input = ref<HTMLInputElement | null>(null)

watch(
  () => dialog.current,
  async (current) => {
    if (!current) return
    text.value = current.input?.value ?? ''
    await nextTick()
    // As in Odin's WebUI, the confirm action takes focus; Escape always cancels.
    if (current.input) {
      input.value?.focus()
      input.value?.select()
    } else confirmButton.value?.focus()
  }
)

function confirm(): void {
  const current = dialog.current
  if (current) current.resolve(current.input ? text.value : true)
}

function cancel(): void {
  dialog.current?.resolve(null)
}
</script>

<template>
  <div v-if="dialog.current" class="dialog-backdrop" @click.self="cancel" @keydown.escape="cancel">
    <form class="dialog" role="dialog" aria-modal="true" :aria-label="dialog.current.title" @submit.prevent="confirm">
      <h2>{{ dialog.current.title }}</h2>
      <p v-if="dialog.current.message">{{ dialog.current.message }}</p>
      <label v-if="dialog.current.input" class="dialog-input">
        <span>{{ dialog.current.input.label }}</span>
        <input ref="input" v-model="text" :maxlength="dialog.current.input.maxLength ?? 200" />
      </label>
      <div class="dialog-buttons">
        <button type="button" class="ghost" @click="cancel">Cancel</button>
        <button ref="confirmButton" type="submit" :class="dialog.current.danger ? 'danger' : 'primary'">
          {{ dialog.current.confirmLabel }}
        </button>
      </div>
    </form>
  </div>
</template>
