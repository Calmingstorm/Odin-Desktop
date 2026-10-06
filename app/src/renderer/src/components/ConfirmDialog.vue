<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { dialog } from '../dialog'

const text = ref('')
const confirmButton = ref<HTMLButtonElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const form = ref<HTMLFormElement | null>(null)
let returnFocus: HTMLElement | null = null
let inertElements: HTMLElement[] = []

function release(): void {
  for (const element of inertElements) element.inert = false
  inertElements = []
  if (returnFocus?.isConnected) returnFocus.focus()
  returnFocus = null
}

function trap(event: KeyboardEvent): void {
  if (event.key !== 'Tab' || !form.value) return
  const stops = Array.from(form.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]'))
  const first = stops[0]
  const last = stops.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

watch(
  () => dialog.current,
  async (current) => {
    if (!current) {
      await nextTick()
      release()
      return
    }
    if (!returnFocus) returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    text.value = current.input?.value ?? ''
    await nextTick()
    // A modal excludes background content from focus AND the real Chromium AX tree.
    const shell = form.value?.closest('.shell')
    inertElements = shell ? Array.from(shell.children).filter((node): node is HTMLElement =>
      node instanceof HTMLElement && !node.contains(form.value)) : []
    for (const element of inertElements) element.inert = true
    // As in Odin's WebUI, the confirm action takes focus; Escape always cancels.
    if (current.input) {
      input.value?.focus()
      input.value?.select()
    } else confirmButton.value?.focus()
  }
)

onBeforeUnmount(release)

function confirm(): void {
  const current = dialog.current
  if (current) current.resolve(current.input ? text.value : true)
}

function cancel(): void {
  dialog.current?.resolve(null)
}
</script>

<template>
  <div v-if="dialog.current" class="dialog-backdrop" @click.self="cancel" @keydown.escape.stop.prevent="cancel" @keydown="trap">
    <div class="dialog" role="dialog" aria-modal="true" :aria-label="dialog.current.title" :aria-describedby="dialog.current.message ? 'confirm-dialog-message' : undefined">
    <form ref="form" @submit.prevent="confirm">
      <h2>{{ dialog.current.title }}</h2>
      <p v-if="dialog.current.message" id="confirm-dialog-message">{{ dialog.current.message }}</p>
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
  </div>
</template>
