<script setup lang="ts">
import { computed, ref } from 'vue'
import { send, state, stop, stopPending, type ComposerMode } from '../store'

const text = ref('')
const mode = ref<ComposerMode>('steer')
const busy = ref(false)
const runningRequest = computed(() => (state.activeId ? (state.views[state.activeId]?.running ?? null) : null))
const running = computed(() => Boolean(runningRequest.value))
const stopping = computed(() => Boolean(runningRequest.value && stopPending(runningRequest.value.request_id)))
const ready = computed(() => state.app.link === 'ready' && Boolean(state.activeId))
const buttonLabel = computed(() => (running.value ? (mode.value === 'steer' ? 'Steer' : 'Queue') : 'Send'))
const placeholder = computed(() =>
  running.value ? (mode.value === 'steer' ? 'Steer the current task…' : 'Queue a follow-up…') : 'Message Odin…'
)

async function submit(): Promise<void> {
  const value = text.value.trim()
  if (!value || !ready.value || busy.value) return
  busy.value = true
  const accepted = await send(value, running.value ? mode.value : 'queue')
  busy.value = false
  if (accepted) text.value = ''
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void submit()
  } else if (event.key === '.' && event.ctrlKey) {
    event.preventDefault()
    void stop()
  }
}
</script>

<template>
  <form class="composer-form" @submit.prevent="submit">
    <div v-if="running" class="mode" role="radiogroup" aria-label="While Odin is working">
      <label><input v-model="mode" type="radio" value="steer" /> Steer the current task</label>
      <label><input v-model="mode" type="radio" value="queue" /> Queue as a follow-up</label>
    </div>
    <div class="row">
      <textarea
        v-model="text"
        rows="3"
        aria-label="Message"
        :placeholder="placeholder"
        :disabled="!ready"
        @keydown="onKey"
      />
      <div class="buttons">
        <button type="submit" class="primary" :disabled="!ready || busy || !text.trim()">{{ buttonLabel }}</button>
        <button v-if="running" type="button" class="danger" title="Stop the current task (Ctrl+.)" :disabled="stopping" @click="stop">
          {{ stopping ? 'Stopping…' : 'Stop' }}
        </button>
      </div>
    </div>
    <p v-if="state.notice" class="notice" role="status">{{ state.notice }}</p>
  </form>
</template>
