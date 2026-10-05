<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { matchCommands, parseCommand } from '../commands'
import { canAct, loadFailure, retry, send, state, stop, stopPending, type ComposerMode } from '../store'
import {
  addFiles,
  addPasted,
  attachmentsFor,
  clearAttachments,
  composer,
  loadDraft,
  pickFiles,
  readyAttachments,
  removeAttachment,
  saveDraft,
  setKnowledge
} from '../stores/composer'
import AttachmentTray from './AttachmentTray.vue'
import CommandPalette from './CommandPalette.vue'

const text = ref('')
const mode = ref<ComposerMode>('steer')
const busy = ref(false)
const dragging = ref(false)
const selected = ref(0)
const runningRequest = computed(() => (state.activeId ? (state.views[state.activeId]?.running ?? null) : null))
const running = computed(() => Boolean(runningRequest.value))
const stopping = computed(() =>
  Boolean(runningRequest.value && stopPending(runningRequest.value.request_id, runningRequest.value.generation))
)
// Until the open conversation's snapshot arrives, nothing is routed; the draft can still be edited.
const ready = computed(() => canAct(state.activeId))
const loadError = computed(() => loadFailure())
const loading = computed(() => state.app.link === 'ready' && Boolean(state.activeId) && !ready.value && !loadError.value)
const attachments = computed(() => attachmentsFor(state.activeId))
const uploading = computed(() => attachments.value.some((a) => a.status === 'uploading'))
const failedAttachment = computed(() => attachments.value.some((a) => a.status === 'failed'))
const paletteOpen = computed(() => text.value.startsWith('/') && !text.value.includes('\n'))
const matches = computed(() => (paletteOpen.value ? matchCommands(text.value) : []))
const canSend = computed(
  () =>
    ready.value &&
    !busy.value &&
    !uploading.value &&
    !failedAttachment.value &&
    (text.value.trim().length > 0 || attachments.value.length > 0)
)
const buttonLabel = computed(() => (running.value ? (mode.value === 'steer' ? 'Steer' : 'Queue') : 'Send'))
const placeholder = computed(() =>
  running.value ? (mode.value === 'steer' ? 'Steer the current task…' : 'Queue a follow-up…') : 'Message Odin… (/ for commands)'
)

// Each conversation keeps its own draft, saved as you type.
let switching = false
watch(
  () => state.activeId,
  async (id) => {
    selected.value = 0
    if (!id) {
      text.value = ''
      return
    }
    switching = true
    const draft = await loadDraft(id)
    if (state.activeId === id) text.value = draft
    switching = false
  },
  { immediate: true }
)
watch(text, (value) => {
  if (state.activeId && !switching) saveDraft(state.activeId, value)
  if (selected.value >= matches.value.length) selected.value = 0
})

async function submit(): Promise<void> {
  if (paletteOpen.value && matches.value.length) return runCommand()
  const conversationId = state.activeId
  if (!conversationId || !canSend.value) return
  const refs = readyAttachments(conversationId)
  if (refs === null) return
  busy.value = true
  const accepted = await send(text.value.trim(), running.value ? mode.value : 'queue', refs)
  busy.value = false
  if (accepted) {
    text.value = ''
    clearAttachments(conversationId)
  }
}

async function runCommand(): Promise<void> {
  const command = matches.value[selected.value]
  if (!command) return
  const { arg } = parseCommand(text.value)
  busy.value = true
  const outcome = await command.run(arg)
  busy.value = false
  if (outcome !== false) text.value = ''
}

function onKey(event: KeyboardEvent): void {
  if (paletteOpen.value && matches.value.length) {
    const count = matches.value.length
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      selected.value = (selected.value + (event.key === 'ArrowDown' ? 1 : count - 1)) % count
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      const command = matches.value[selected.value]
      if (command) text.value = `/${command.name} `
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      text.value = ''
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void submit()
  } else if (event.key === '.' && event.ctrlKey) {
    event.preventDefault()
    void stop()
  }
}

function pick(index: number): void {
  selected.value = index
  void runCommand()
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (files.length && state.activeId) void addFiles(state.activeId, files)
}

function onPaste(event: ClipboardEvent): void {
  const files = Array.from(event.clipboardData?.files ?? [])
  if (!files.length || !state.activeId) return // ordinary text paste
  event.preventDefault()
  void addPasted(state.activeId, files)
}

function onRemove(id: string): void {
  if (state.activeId) removeAttachment(state.activeId, id)
}

function onKnowledge(id: string, checked: boolean): void {
  if (state.activeId) setKnowledge(state.activeId, id, checked)
}

function attach(): void {
  if (state.activeId) void pickFiles(state.activeId)
}
</script>

<template>
  <div v-if="state.panel" class="panel" role="status">
    <div class="panel-head">
      <strong>{{ state.panel.title }}</strong>
      <button type="button" class="ghost" @click="state.panel = null">Close</button>
    </div>
    <pre class="panel-text">{{ state.panel.text }}</pre>
  </div>
  <form
    :class="['composer-form', { dragging }]"
    @submit.prevent="submit"
    @dragover.prevent="dragging = true"
    @dragleave="dragging = false"
    @drop.prevent="onDrop"
  >
    <div v-if="running" class="mode" role="radiogroup" aria-label="While Odin is working">
      <label><input v-model="mode" type="radio" value="steer" /> Steer the current task</label>
      <label><input v-model="mode" type="radio" value="queue" /> Queue as a follow-up</label>
    </div>
    <CommandPalette v-if="paletteOpen" :commands="matches" :selected="selected" @pick="pick" />
    <AttachmentTray
      v-if="attachments.length"
      :items="attachments"
      @remove="onRemove"
      @knowledge="onKnowledge"
    />
    <div class="row">
      <textarea
        v-model="text"
        rows="3"
        aria-label="Message"
        :placeholder="placeholder"
        :disabled="!state.activeId"
        @keydown="onKey"
        @paste="onPaste"
      />
      <div class="buttons">
        <button type="submit" class="primary" :disabled="!canSend && !(paletteOpen && matches.length)">{{ buttonLabel }}</button>
        <button type="button" class="ghost" title="Attach files" :disabled="!state.activeId" @click="attach">Attach</button>
        <button v-if="running" type="button" class="danger" title="Stop the current task (Ctrl+.)" :disabled="stopping" @click="stop">
          {{ stopping ? 'Stopping…' : 'Stop' }}
        </button>
      </div>
    </div>
    <p v-if="composer.errors.length" class="notice error" role="alert">{{ composer.errors.join(' ') }}</p>
    <p v-if="loadError" class="notice error" role="alert">
      Couldn't load from Odin: {{ loadError }}
      <button type="button" class="ghost" @click="retry">Retry</button>
    </p>
    <p v-else-if="loading" class="notice" role="status">Loading this conversation…</p>
    <p v-else-if="uploading" class="notice" role="status">Waiting for attachments to finish uploading…</p>
    <p v-else-if="failedAttachment" class="notice error" role="status">Remove the attachment that failed before sending.</p>
    <p v-else-if="state.notice" class="notice" role="status">{{ state.notice }}</p>
  </form>
</template>
