<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { renderMarkdown } from '../markdown'
import { loadOlder, state, steersFor, stopPending, type ControlItem } from '../store'
import ToolActivity from './ToolActivity.vue'

const scroller = ref<HTMLElement | null>(null)
const view = computed(() => (state.activeId ? state.views[state.activeId] : undefined))
const messages = computed(() => view.value?.messages ?? [])
const running = computed(() => view.value?.running ?? null)
const queuedCount = computed(() => view.value?.queued.length ?? 0)
const pending = computed(() => state.pending.filter((p) => p.conversation_id === state.activeId))
const steers = computed(() => (running.value ? steersFor(running.value.request_id) : []))
const stopping = computed(() => Boolean(running.value && stopPending(running.value.request_id)))

const OUTCOME_TEXT: Record<string, string> = {
  failed: 'The task failed.',
  cancelled: 'The task was stopped.',
  interrupted: 'The task was interrupted.',
  suspended: 'The task is suspended and can be resumed.'
}

/** The last task's outcome when it didn't simply complete, plus every recent task that left unknown effects. */
const outcomeLines = computed(() => {
  const v = view.value
  if (!v) return []
  const lines: string[] = []
  const last = v.recent[v.recent.length - 1]
  const showLast = Boolean(last && !v.running && last.outcome !== 'completed')
  if (last && showLast) {
    const base = OUTCOME_TEXT[last.outcome] ?? `The task ended: ${last.outcome}.`
    lines.push(last.unknown_effects ? `${base} ${unknownText(last.unknown_effects)}` : base)
  }
  for (const o of v.recent) {
    if (o.unknown_effects <= 0 || (o === last && showLast)) continue
    lines.push(o === last ? unknownText(o.unknown_effects) : `An earlier task: ${unknownText(o.unknown_effects)}`)
  }
  return lines
})

function unknownText(count: number): string {
  return `${count} action(s) have an unknown outcome and will not be repeated.`
}

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

function steerState(item: ControlItem): string {
  const text = STEER_TEXT[item.status] ?? item.status
  return item.detail ? `${text}: ${item.detail}` : text
}

watch(
  () => [messages.value.length, pending.value.length, running.value?.request_id, steers.value.length, state.activeId],
  async () => {
    await nextTick()
    scroller.value?.scrollTo({ top: scroller.value.scrollHeight })
  }
)

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function who(role: string): string {
  return role === 'user' ? 'You' : role === 'assistant' ? 'Odin' : 'Notice'
}

function older(): void {
  if (state.activeId) void loadOlder(state.activeId)
}
</script>

<template>
  <section ref="scroller" class="message-scroll">
    <p v-if="!state.loaded || !view?.hasData" class="empty">{{ state.app.link === 'ready' ? 'Loading…' : 'Connecting to Odin…' }}</p>
    <template v-else>
      <div v-if="view.hasMore" class="older">
        <button class="ghost" :disabled="view.loadingOlder" @click="older">
          {{ view.loadingOlder ? 'Loading…' : 'Load older messages' }}
        </button>
      </div>
      <p v-if="!messages.length && !pending.length && !running" class="empty">Ask Odin anything.</p>
      <article v-for="m in messages" :key="m.id" :class="['msg', m.role]">
        <ToolActivity
          v-if="m.role === 'assistant' && m.request_id && view.tools[m.request_id]?.length"
          :entries="view.tools[m.request_id] ?? []"
        />
        <div class="meta">
          <span class="who">{{ who(m.role) }}</span>
          <time :datetime="m.created_at">{{ time(m.created_at) }}</time>
        </div>
        <div class="body md" v-html="renderMarkdown(m.text)" />
      </article>
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
        <ToolActivity :entries="view.tools[running.request_id] ?? []" live />
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
      <p v-for="(line, index) in outcomeLines" :key="index" class="outcome" role="status">{{ line }}</p>
    </template>
  </section>
</template>
