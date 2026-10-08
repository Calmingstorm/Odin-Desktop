<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { backToLatest, chatUnavailable, loadFailure, loadOlder, resumeTarget, retry, select, state, steersFor, stopPending, type SteerLine } from '../store'
import { unavailableText } from '../capability'
import { chatAnnouncement, type ChatAnnouncementState } from '../chat-announcements'
import { assistantName } from '../assistant-name'
import { loadPersonality } from '../stores/state'
import Message from './Message.vue'
import ResumeBanner from './ResumeBanner.vue'
import ToolActivity from './ToolActivity.vue'
import Icon from './Icon.vue'

const scroller = ref<HTMLElement | null>(null)
const content = ref<HTMLElement | null>(null)
const view = computed(() => (state.activeId ? state.views[state.activeId] : undefined))
const messages = computed(() => view.value?.messages ?? [])
const running = computed(() => view.value?.running ?? null)
const queuedCount = computed(() => view.value?.queued.length ?? 0)
const pending = computed(() => state.pending.filter((p) => p.conversation_id === state.activeId))
const loadError = computed(() => loadFailure())
const conversation = computed(() => state.conversations.find((c) => c.id === state.activeId) ?? null)
/** A window around a search hit outside the loaded history; the live view underneath stays as it was. */
const jump = computed(() => (state.jump && state.jump.conversationId === state.activeId ? state.jump : null))
const steers = computed(() =>
  running.value && state.activeId ? steersFor(state.activeId, running.value.request_id, running.value.generation) : []
)
const stopping = computed(() => Boolean(running.value && stopPending(running.value.request_id, running.value.generation)))
/** A failure or stop need not produce an assistant reply. Its tool receipts must remain inspectable. */
const terminalTools = computed(() => {
  const v = view.value
  if (!v) return []
  const withReply = new Set(v.messages.filter((m) => m.role === 'assistant').map((m) => m.request_id))
  return Object.entries(v.tools).filter(([id, entries]) =>
    entries.length && id !== v.running?.request_id && !v.queued.some((q) => q.request_id === id) && !withReply.has(id)
  )
})
/** Keep settled Stop/Steer receipts visible even when the running task card disappears. */
const controlReceipts = computed(() => {
  const v = view.value
  if (!v) return []
  const receipts = new Map(Object.values(v.controls).map((c) => [c.control_command_id, c]))
  for (const local of state.controls.filter((c) => c.conversation_id === state.activeId)) {
    if (!receipts.has(local.control_command_id)) receipts.set(local.control_command_id, local)
  }
  return [...receipts.values()].filter((c) =>
    c.kind === 'stop' || c.request_id !== v.running?.request_id || c.generation !== v.running?.generation
  ).slice(-20)
})

const STOP_TEXT: Record<string, string> = {
  sending: 'sending…',
  'awaiting-receipt': 'sent, waiting for confirmation',
  unknown: 'outcome unknown; it will not be sent again',
  requested: 'requested; waiting for the task to stop',
  confirmed: 'confirmed by Odin',
  not_running: 'not used: the task was not running',
  stale_binding: 'not used: the request binding changed',
  'not-delivered': 'not delivered'
}
const announcement = ref('')
const historyPaging = ref(false)
const olderUsed = ref(false)
const taskState = computed<ChatAnnouncementState>(() => {
  const last = view.value?.recent.at(-1)
  return {
    running: running.value ? `${running.value.request_id}:${running.value.generation}` : null,
    stopping: stopping.value,
    terminal: last ? `${last.request_id}:${last.generation}:${last.outcome}` : null,
    outcome: last?.outcome ?? null,
    queued: queuedCount.value,
    consumed: steers.value.filter((s) => s.status === 'consumed').map((s) => s.control_command_id),
    steerQueued: steers.value.filter((s) => s.status === 'queued').map((s) => s.control_command_id),
    unknown: [
      ...pending.value.filter((p) => p.status === 'unknown').map((p) => p.client_submission_id),
      ...steers.value.filter((s) => s.status === 'unknown').map((s) => s.control_command_id),
      ...(view.value?.unresolved ?? []).map((o) => `${o.request_id}:${o.generation}`),
      ...state.controls.filter((c) => c.conversation_id === state.activeId && c.status === 'unknown').map((c) => c.control_command_id)
    ]
  }
})
let lastConversation: string | null = null
watch(() => state.activeId, () => { olderUsed.value = false })
watch(taskState, (next, previous) => {
  const sameConversation = lastConversation === state.activeId
  const line = chatAnnouncement(sameConversation ? previous : undefined, next)
  if (line || !sameConversation) announcement.value = line
  lastConversation = state.activeId
}, { immediate: true })

const OUTCOME_TEXT: Record<string, string> = {
  failed: 'The task failed.',
  cancelled: 'The task was stopped.',
  interrupted: 'The task was interrupted.',
  suspended: 'The task is suspended and can be resumed.'
}

/** The last task's outcome when it didn't simply complete. A task that can resume shows the resume banner instead. */
const outcomeLine = computed(() => {
  const v = view.value
  const last = v?.recent[v.recent.length - 1]
  if (!v || !last || v.running || last.outcome === 'completed' || resumeTarget(v)) return ''
  return OUTCOME_TEXT[last.outcome] ?? `The task ended: ${last.outcome}.`
})

/** Every task whose unknown effects aren't reconciled yet, however long ago it ran. */
const unresolvedLines = computed(() =>
  (view.value?.unresolved ?? []).map(
    (o) => `A task from ${time(o.at)} has ${o.unknown_effects} action(s) with an unknown outcome. They will not be repeated.`
  )
)

const STEER_TEXT: Record<string, string> = {
  sending: 'sending…',
  'awaiting-receipt': 'sent, waiting for confirmation',
  unknown: 'outcome unknown; it will not be sent again',
  queued: 'waiting for Odin to read it',
  consumed: 'Odin has read it',
  closed: 'not used: the task ended first',
  stale_binding: 'not used: a different task was running',
  'not-delivered': 'not delivered'
}

function steerState(item: SteerLine): string {
  const text = STEER_TEXT[item.status] ?? item.status
  return item.detail ? `${text}: ${item.detail}` : text
}

/** The scroll to the end in progress. A newer one, a search result coming into view, or the list going away ends it. */
let scrollRun = 0
// Bottom-following is reader intent, not a fresh distance check after an image has already grown.
let pinned = true
let writtenTop: number | null = null
let readerScrolling = false
let contentObserver: ResizeObserver | null = null

function takeScroll(): void {
  scrollRun += 1
  // Input cancels an in-flight placement; only an actual scroll changes follow intent.
  // Downward wheel at the bottom and clicks on message controls may not scroll at all.
  writtenTop = null
  readerScrolling = true
}

function onHistoryKey(event: KeyboardEvent): void {
  if (event.key === 'End') {
    // End at an already settled bottom produces no scroll event, but still means follow the latest.
    void scrollToEnd()
  } else if (['Home', 'PageUp', 'PageDown', 'ArrowUp', 'ArrowDown', ' '].includes(event.key)) {
    takeScroll()
  }
}

function onScroll(): void {
  const el = scroller.value
  if (!el || !readerScrolling || el.scrollTop === writtenTop) return
  // Browser layout/clamping scroll events are not reader intent. Only input can relinquish the pin.
  scrollRun += 1
  pinned = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  if (pinned) readerScrolling = false
  writtenTop = null
}

function canFollow(): boolean {
  return pinned && !state.highlightId && !jump.value && !historyPaging.value
}

// The chat names the assistant after the active personality. A failed read keeps the default name.
onMounted(() => { loadPersonality().catch(() => undefined) })

onMounted(() => {
  if (typeof ResizeObserver === 'undefined') return
  contentObserver = new ResizeObserver(() => {
    // Covers image decoding, file/report cards, tool expansion and late fonts/layout, even after the initial scroll.
    if (canFollow()) void scrollToEnd()
  })
  if (content.value) contentObserver.observe(content.value)
  if (scroller.value) contentObserver.observe(scroller.value)
})

/**
 * Scrolls to the latest message. Messages skipped while off screen (content-visibility) have estimated heights that
 * settle as they render, so the end moves; keep going, a frame at a time, until it stays put.
 */
async function scrollToEnd(): Promise<void> {
  const run = ++scrollRun
  pinned = true
  readerScrolling = false
  await nextTick()
  const el = scroller.value
  if (!el) return
  let height = -1
  let steady = 0
  for (let frame = 0; frame < 60 && run === scrollRun; frame++) {
    el.scrollTop = el.scrollHeight
    writtenTop = el.scrollTop
    await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined)))
    const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 2
    // Done once the end hasn't moved for three frames: the messages scrolled into view have rendered.
    steady = atEnd && el.scrollHeight === height ? steady + 1 : 0
    if (steady >= 3) return
    height = el.scrollHeight
  }
}

watch(
  () => [messages.value.length, pending.value.length, running.value?.request_id, steers.value.length, state.activeId],
  (next, previous) => {
    const el = scroller.value
    const switched = next[4] !== previous?.[4]
    const focusedHistory = Boolean(el?.contains?.(document.activeElement))
    const nearEnd = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80
    if (!state.highlightId && !historyPaging.value && (switched || (pinned && !focusedHistory && nearEnd))) void scrollToEnd()
  }
)

// Back to the latest messages, from a search window or a notification: scroll there once they are on screen.
watch(
  () => state.latestScroll,
  () => void scrollToEnd()
)

watch(
  () => [state.highlightId, jump.value?.messageId],
  async () => {
    if (!state.highlightId) return
    pinned = false
    readerScrolling = false // search placement is not a reader scroll and must finish settling
    const run = ++scrollRun // the search result owns the view now
    await nextTick()
    const id = state.highlightId
    if (!id) return
    const target = document.getElementById(`m-${id}`)
    const view = scroller.value
    if (!target) return
    const tall = (): boolean => Boolean(view && 'offsetHeight' in target && target.offsetHeight > view.clientHeight)
    // A message taller than the view opens at its start, where reading begins; centring it would land mid-message.
    let start = tall()
    const place = (): void => target.scrollIntoView({ block: start ? 'start' : 'center' })
    place()
    if (!view || !('isConnected' in target)) return
    // Its place settles over a few frames. A message that never rendered here, and the ones around it, have only
    // estimated heights until they are brought into view, and estimated blocks become real as they render, so the
    // message moves; in a hidden window that waits until it is shown. Keep it where it was placed (a tall one at its
    // start) until it stays put, as the scroll to the end does, unless the view changes hands meanwhile.
    const offset = (): number | null => typeof target.getBoundingClientRect === 'function' && typeof view.getBoundingClientRect === 'function'
      ? target.getBoundingClientRect().top - view.getBoundingClientRect().top
      : null
    let placed = offset()
    let steady = 0
    for (let frame = 0; frame < 60 && steady < 3; frame++) {
      await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined)))
      if (run !== scrollRun || state.highlightId !== id || !target.isConnected) return
      const grew = !start && tall()
      const at = offset()
      if (!grew) {
        if (placed === null || at === null) return // nothing to measure: the placement stands
        if (Math.abs(at - placed) <= 1) {
          steady += 1
          continue
        }
      }
      start ||= grew
      steady = 0
      place()
      placed = offset()
    }
  }
)

onBeforeUnmount(() => {
  scrollRun += 1
  contentObserver?.disconnect()
})

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

async function older(): Promise<void> {
  const id = state.activeId
  const el = scroller.value
  if (!id || !el || !view.value?.hasMore || view.value.loadingOlder || historyPaging.value) return
  scrollRun += 1
  pinned = false
  historyPaging.value = true
  olderUsed.value = true
  const beforeHeight = el.scrollHeight
  const beforeTop = el.scrollTop
  await loadOlder(id)
  await nextTick()
  if (state.activeId === id && scroller.value === el) el.scrollTop = beforeTop + el.scrollHeight - beforeHeight
  historyPaging.value = false
}


</script>

<template>
  <p class="chat-announcement" role="status" aria-live="polite" aria-atomic="true">{{ announcement }}</p>
  <section id="conversation-history" ref="scroller" class="message-scroll" tabindex="0" aria-label="Conversation history" @scroll.passive="onScroll" @wheel.passive="takeScroll" @keydown="onHistoryKey" @pointerdown="takeScroll">
    <div ref="content" class="message-content">
    <p v-if="chatUnavailable()" class="empty" role="status">{{ unavailableText('Chat') }}</p>
    <div v-else-if="!view?.hasData && loadError" class="empty" role="alert">
      <p>Couldn't load from Odin: {{ loadError }}</p>
      <button class="ghost" @click="retry">Retry</button>
    </div>
    <p v-else-if="!view?.hasData" class="empty" role="status">{{ state.app.link === 'ready' ? 'Loading…' : 'Connecting to Odin…' }}</p>
    <template v-else-if="jump">
      <div class="jump-banner" role="status">
        <span>Showing messages around a search result.</span>
        <button class="ghost" @click="backToLatest">Back to latest</button>
      </div>
      <p v-if="jump.hasBefore" class="jump-edge">Earlier messages aren't shown here.</p>
      <Message
        v-for="m in jump.items"
        :key="m.id"
        :message="m"
        :conversation-id="jump.conversationId"
        :tools="m.request_id ? view.tools[m.request_id] : undefined"
        :highlight="m.id === state.highlightId"
      />
      <p v-if="jump.hasAfter" class="jump-edge">Later messages aren't shown here.</p>
    </template>
    <template v-else>
      <p v-if="conversation?.inherited_from" class="inherited">
        A thread continued from “{{ conversation.inherited_from.title }}”. Odin carries that conversation's context into
        this one.
        <button class="ghost" @click="select(conversation.inherited_from.conversation_id)">Open the original</button>
      </p>
      <p v-if="view.status === 'loading'" class="history-loading" role="status">Refreshing conversation. The displayed history remains available.</p>
      <div v-if="view.hasMore || olderUsed" class="older">
        <button class="ghost" :aria-disabled="view.loadingOlder || !view.hasMore" :aria-label="view.loadingOlder ? 'Loading… older messages' : view.hasMore ? 'Load older messages' : 'All older messages loaded'" @click="older">
          {{ view.loadingOlder ? 'Loading…' : view.hasMore ? 'Load older messages' : 'All older messages loaded' }}
        </button>
      </div>
      <p v-if="!messages.length && !pending.length && !running" class="empty">Ask {{ assistantName() }} anything.</p>
      <Message
        v-for="m in messages"
        :key="m.id"
        :message="m"
        :conversation-id="state.activeId ?? ''"
        :tools="m.request_id ? view.tools[m.request_id] : undefined"
        :highlight="m.id === state.highlightId"
        actions
      />
      <article v-for="p in pending" :key="p.client_submission_id" class="msg user pending">
        <span class="avatar" aria-hidden="true"><Icon name="person" :size="18" /></span>
        <div class="meta">
          <span class="who">You</span>
          <span class="state">{{
            p.status === 'sending' ? 'sending…' : p.status === 'unknown' ? 'outcome unknown; it will not be sent again' : 'sent, waiting for confirmation'
          }}</span>
        </div>
        <div class="body plain">{{ p.text }}</div>
      </article>
      <div v-if="running" class="working">
        <ToolActivity :entries="view.tools[running.request_id] ?? []" :request-id="running.request_id" live />
        <ul v-if="steers.length" class="steers" aria-label="Steering for this task">
          <li v-for="s in steers" :key="s.control_command_id" :class="['steer', s.status]">
            <span class="steer-text">{{ s.text ?? 'Steer' }}</span>
            <span class="steer-state">{{ steerState(s) }}</span>
          </li>
        </ul>
        <div class="working-line">
          <span class="spinner" aria-hidden="true" />
          <span>{{ stopping ? 'Stopping…' : 'Odin is working…' }}</span>
          <span v-if="queuedCount" class="queued">{{ queuedCount }} follow-up{{ queuedCount === 1 ? '' : 's' }} queued</span>
        </div>
      </div>
      <p v-if="outcomeLine" class="outcome">{{ outcomeLine }}</p>
      <ul v-if="controlReceipts.length" class="steers control-receipts" aria-label="Control receipts">
        <li v-for="c in controlReceipts" :key="c.control_command_id" class="steer">
          <span class="steer-text">{{ c.kind === 'stop' ? 'Stop' : 'Steer' }}</span>
          <span class="steer-state">{{ (c.kind === 'stop' ? STOP_TEXT : STEER_TEXT)[c.status] ?? c.status }}</span>
        </li>
      </ul>
      <div v-for="[requestId, entries] in terminalTools" :key="requestId" class="terminal-tools">
        <ToolActivity :entries="entries" :request-id="requestId" />
      </div>
      <ResumeBanner v-if="state.activeId" :conversation-id="state.activeId" />
      <p v-for="(line, index) in unresolvedLines" :key="index" class="outcome unresolved">{{ line }}</p>
    </template>
    </div>
  </section>
</template>

<style scoped>
.chat-announcement { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.message-scroll { overflow-anchor: none; }
.message-content { display: flow-root; }
.message-scroll:focus-visible, button:focus-visible { outline: 2px solid var(--accent, #91baff); outline-offset: -3px; }
button[aria-disabled="true"] { opacity: .65; }
</style>
