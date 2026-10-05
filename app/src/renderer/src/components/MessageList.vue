<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { backToLatest, chatUnavailable, loadFailure, loadOlder, resumeTarget, retry, select, state, steersFor, stopPending, type SteerLine } from '../store'
import { unavailableText } from '../capability'
import Message from './Message.vue'
import ResumeBanner from './ResumeBanner.vue'
import ToolActivity from './ToolActivity.vue'

const scroller = ref<HTMLElement | null>(null)
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

/**
 * Scrolls to the latest message. Messages skipped while off screen (content-visibility) have estimated heights that
 * settle as they render, so the end moves; keep going, a frame at a time, until it stays put.
 */
async function scrollToEnd(): Promise<void> {
  const run = ++scrollRun
  await nextTick()
  const el = scroller.value
  if (!el) return
  let height = -1
  let steady = 0
  for (let frame = 0; frame < 60 && run === scrollRun; frame++) {
    el.scrollTop = el.scrollHeight
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
  () => {
    if (!state.highlightId) void scrollToEnd()
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
    scrollRun += 1 // the search result owns the view now
    await nextTick()
    if (state.highlightId) document.getElementById(`m-${state.highlightId}`)?.scrollIntoView({ block: 'center' })
  }
)

onBeforeUnmount(() => {
  scrollRun += 1
})

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function older(): void {
  if (state.activeId) void loadOlder(state.activeId)
}


</script>

<template>
  <section ref="scroller" class="message-scroll">
    <p v-if="chatUnavailable()" class="empty" role="status">{{ unavailableText('Chat') }}</p>
    <div v-else-if="!view?.hasData && loadError" class="empty" role="alert">
      <p>Couldn't load from Odin: {{ loadError }}</p>
      <button class="ghost" @click="retry">Retry</button>
    </div>
    <p v-else-if="!state.loaded || !view?.hasData" class="empty">{{ state.app.link === 'ready' ? 'Loading…' : 'Connecting to Odin…' }}</p>
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
      <div v-if="view.hasMore" class="older">
        <button class="ghost" :disabled="view.loadingOlder" @click="older">
          {{ view.loadingOlder ? 'Loading…' : 'Load older messages' }}
        </button>
      </div>
      <p v-if="!messages.length && !pending.length && !running" class="empty">Ask Odin anything.</p>
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
      <p v-if="outcomeLine" class="outcome" role="status">{{ outcomeLine }}</p>
      <ResumeBanner v-if="state.activeId" :conversation-id="state.activeId" />
      <p v-for="(line, index) in unresolvedLines" :key="index" class="outcome unresolved" role="status">{{ line }}</p>
    </template>
  </section>
</template>
