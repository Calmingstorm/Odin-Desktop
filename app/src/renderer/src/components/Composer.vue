<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { dispatch, matchCommands, parseCommand } from '../commands'
import { canAct, chatUnavailable, loadFailure, retry, send, state, stop, stopPending, type ComposerMode } from '../store'
import { unavailableText } from '../capability'
import { status } from '../stores/status'
import {
  addFiles,
  addPasted,
  attachmentsFor,
  box,
  composer,
  edit,
  pickFiles,
  removeAttachment,
  runBoxCommand,
  sendBox,
  setKnowledge,
  showDraft
} from '../stores/composer'
import AttachmentTray from './AttachmentTray.vue'
import CommandPalette from './CommandPalette.vue'

// The box's text is its conversation's draft (stores/composer.ts); typing saves it.
const text = computed({ get: () => box.text, set: (value: string) => edit(value) })
const mode = ref<ComposerMode>('steer')
const busy = ref(false)
const dragging = ref(false)
const stopButton = ref<HTMLButtonElement | null>(null)
const selected = ref(0)
const paletteDismissed = ref(false)
const runningRequest = computed(() => (state.activeId ? (state.views[state.activeId]?.running ?? null) : null))
const running = computed(() => Boolean(runningRequest.value))
watch(running, async (active) => {
  if (active || document.activeElement !== stopButton.value) return
  await nextTick()
  if (document.activeElement === document.body) document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')?.focus()
})
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
// The status bar already owns a refused usage report; don't repeat that same message below the box.
const notice = computed(() => state.app.link === 'ready' && status.usageUnavailable && state.notice === status.usageError ? '' : state.notice)
const paletteOpen = computed(() => !paletteDismissed.value && text.value.startsWith('/') && !text.value.includes('\n'))
// Dismissing suggestions changes only their presentation, not what a completed slash command executes.
const matches = computed(() => (text.value.startsWith('/') && !text.value.includes('\n') ? matchCommands(text.value) : []))
const canSend = computed(
  () =>
    ready.value &&
    box.owner === state.activeId &&
    !busy.value &&
    !uploading.value &&
    !failedAttachment.value &&
    (text.value.trim().length > 0 || attachments.value.length > 0)
)
const buttonLabel = computed(() => (running.value ? (mode.value === 'steer' ? 'Steer' : 'Queue') : 'Send'))
const placeholder = computed(() =>
  chatUnavailable() ? 'Chat unavailable. Use /status or /usage for core reports.' : running.value ? (mode.value === 'steer' ? 'Steer the current task…' : 'Queue a follow-up…') : 'Message Odin… (/ for commands)'
)

// Each conversation keeps its own draft. While switching, the box belongs to no conversation until the next draft
// has loaded, so nothing typed or shown can be sent to the wrong one.
watch(
  () => state.activeId,
  (id) => {
    selected.value = 0
    void showDraft(id, () => state.activeId === id)
  },
  { immediate: true }
)
watch(text, () => {
  paletteDismissed.value = false
  if (selected.value >= matches.value.length) selected.value = 0
})

async function submit(): Promise<void> {
  if (matches.value.length) return runCommand()
  if (!canSend.value) return
  busy.value = true
  await sendBox(state.activeId, (body, refs) => send(body, running.value ? mode.value : 'queue', refs))
  busy.value = false
}

async function runCommand(): Promise<void> {
  if (busy.value) return
  const command = matches.value[selected.value]
  if (!command) return
  const { arg } = parseCommand(text.value)
  busy.value = true
  await runBoxCommand(() => dispatch(command, arg))
  busy.value = false
}

function onKey(event: KeyboardEvent): void {
  if (event.isComposing) return
  if (paletteOpen.value && event.key === 'Escape') {
    event.preventDefault()
    paletteDismissed.value = true
    return
  }
  if (paletteOpen.value && matches.value.length) {
    const count = matches.value.length
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      selected.value = (selected.value + (event.key === 'ArrowDown' ? 1 : count - 1)) % count
      return
    }
    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      selected.value = event.key === 'Home' ? 0 : count - 1
      return
    }
    if (event.key === 'Tab' && !event.shiftKey) {
      event.preventDefault()
      const command = matches.value[selected.value]
      if (command) {
        text.value = `/${command.name} `
        // Complete once, then let the next Tab leave the field instead of trapping focus.
        void nextTick(() => { paletteDismissed.value = true })
      }
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
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
  if (chatUnavailable()) return
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (files.length && state.activeId) void addFiles(state.activeId, files)
}

function onPaste(event: ClipboardEvent): void {
  if (chatUnavailable()) return
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
  if (state.activeId && !chatUnavailable()) void pickFiles(state.activeId)
}

async function stopTask(event: MouseEvent): Promise<void> {
  if (stopping.value) return
  const button = event.currentTarget as HTMLButtonElement
  const wasFocused = document.activeElement === button
  await stop()
  await nextTick()
  if (wasFocused && !button.isConnected && document.activeElement === document.body) {
    document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')?.focus()
  }
}

async function closeReport(): Promise<void> {
  state.panel = null
  await nextTick()
  document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')?.focus()
}
</script>

<template>
  <div v-if="state.panel" class="panel" role="region" :aria-label="state.panel.title">
    <div class="panel-head">
      <strong>{{ state.panel.title }}</strong>
      <button type="button" class="ghost" aria-label="Close command report" @click="closeReport">Close</button>
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
      <label><input v-model="mode" name="composer-mode" type="radio" value="steer" /> Steer the current task</label>
      <label><input v-model="mode" name="composer-mode" type="radio" value="queue" /> Queue as a follow-up</label>
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
        aria-autocomplete="list"
        :aria-controls="paletteOpen && matches.length ? 'command-palette' : undefined"
        :aria-activedescendant="paletteOpen && matches[selected] ? `command-option-${matches[selected]?.name}` : undefined"
        :aria-invalid="composer.errors.length > 0 || failedAttachment ? true : undefined"
        :aria-describedby="['composer-help', composer.errors.length ? 'composer-errors' : '', failedAttachment ? 'composer-attachment-error' : ''].filter(Boolean).join(' ')"
        :placeholder="placeholder"
        :disabled="!state.activeId && !chatUnavailable()"
        @keydown="onKey"
        @paste="onPaste"
      />
      <div class="buttons">
        <button type="submit" class="primary" :disabled="!busy && !canSend && !matches.length" :aria-disabled="busy">{{ buttonLabel }}</button>
        <button type="button" class="ghost" aria-label="Attach files" :disabled="!state.activeId || chatUnavailable()" @click="attach">Attach</button>
        <button v-if="running" ref="stopButton" type="button" class="danger" aria-label="Stop the current task" title="Stop the current task (Ctrl+.)" :aria-disabled="stopping" @click="stopTask">
          {{ stopping ? 'Stopping…' : 'Stop' }}
        </button>
      </div>
    </div>
    <p id="composer-help" class="composer-help">Enter to send; Shift+Enter for a new line. For commands, use Up/Down or Home/End, Tab to complete, Enter to run, Escape to dismiss.</p>
    <p v-if="composer.errors.length" id="composer-errors" class="notice error" role="alert">{{ composer.errors.join(' ') }}</p>
    <p v-if="chatUnavailable()" class="notice" role="status">{{ unavailableText('Chat') }} Sending messages and attachments is unavailable.</p>
    <p v-else-if="loadError" class="notice error" role="alert">
      Couldn't load from Odin: {{ loadError }}
      <button type="button" class="ghost" @click="retry">Retry</button>
    </p>
    <p v-else-if="loading" class="notice" role="status">Loading this conversation…</p>
    <p v-else-if="uploading" class="notice" role="status">Waiting for attachments to finish uploading…</p>
    <p v-if="failedAttachment" id="composer-attachment-error" class="notice error" role="status">Remove the attachment that failed before sending.</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
  </form>
</template>

<style scoped>
.composer-help { font-size: .8rem; color: var(--muted); margin: .4rem 0; }
textarea:focus-visible, button:focus-visible, input:focus-visible { outline: 2px solid var(--accent, #91baff); outline-offset: 3px; }
button[aria-disabled="true"] { opacity: .65; }
</style>
