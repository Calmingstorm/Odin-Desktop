<script setup lang="ts">
// Choose, change or remove a chat picture: yours, or a personality's. The picture is cropped to its centred square and
// saved at 256 x 256 by the app; it is display only.
import { ref, useId } from 'vue'
import type { DisplayPictureTarget } from '../../../shared/api'
import { ACCEPTED_PICTURES, removeDisplayPicture, saveDisplayPicture } from '../stores/display-profile'
import Icon from './Icon.vue'

const props = defineProps<{
  target: DisplayPictureTarget
  picture: string | null
  /** What the picture is for, in the control names: "your picture", "Clippy's picture". */
  label: string
  /** Shown when no picture is set (Odin's mark for a personality); the person icon otherwise. */
  fallback?: string
}>()

const inputId = `avatar-file-${useId()}`
const busy = ref(false)
const error = ref('')
const note = ref('')

async function run(change: () => Promise<string | null>, done: string): Promise<void> {
  busy.value = true
  error.value = ''
  note.value = ''
  try {
    const failure = await change()
    if (failure) error.value = failure
    else note.value = done
  } finally {
    busy.value = false
  }
}

async function chosen(event: Event): Promise<void> {
  const field = event.target as HTMLInputElement
  const file = field.files?.[0]
  field.value = ''
  if (file) await run(() => saveDisplayPicture(props.target, file), 'Saved.')
}

async function remove(): Promise<void> {
  if (!busy.value) await run(() => removeDisplayPicture(props.target), 'Removed.')
}
</script>

<template>
  <div class="avatar-picker">
    <span class="avatar-preview" aria-hidden="true">
      <img v-if="picture" :src="picture" alt="" />
      <img v-else-if="fallback" class="fallback" :src="fallback" alt="" />
      <Icon v-else name="person" :size="22" />
    </span>
    <!-- The file input stays focusable; its visible label is the button-styled control beside the preview. -->
    <input :id="inputId" class="sr-only avatar-file" type="file" :accept="ACCEPTED_PICTURES.join(',')" :disabled="busy" :aria-label="`${picture ? 'Change' : 'Choose'} ${label}`" @change="chosen" />
    <label :for="inputId" class="ghost avatar-choose" :aria-disabled="busy">{{ picture ? 'Change picture…' : 'Choose picture…' }}</label>
    <button v-if="picture" class="ghost" :aria-disabled="busy" :aria-label="`Remove ${label}`" @click="remove">Remove</button>
    <p v-if="error" class="warn" role="alert">{{ error }}</p>
    <p v-else-if="note" class="manage-note" role="status">{{ note }}</p>
  </div>
</template>

<style scoped>
.avatar-picker { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.avatar-preview {
  display: grid; place-items: center; flex: none; width: 48px; height: 48px; overflow: hidden;
  border-radius: 50%; background: var(--raise); color: var(--muted);
}
.avatar-preview img { width: 100%; height: 100%; object-fit: cover; }
.avatar-preview img.fallback { object-fit: contain; }
.avatar-picker > p { flex-basis: 100%; margin: 0; }
button[aria-disabled="true"], .avatar-choose[aria-disabled="true"] { opacity: .6; cursor: default; }
.avatar-choose { display: inline-flex; align-items: center; cursor: pointer; }
.avatar-file:focus-visible + .avatar-choose { outline: 2px solid var(--accent, #91baff); outline-offset: 2px; }
</style>
