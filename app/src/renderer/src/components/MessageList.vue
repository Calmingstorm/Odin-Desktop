<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { renderMarkdown } from '../markdown'
import { state } from '../store'
import ToolActivity from './ToolActivity.vue'

const scroller = ref<HTMLElement | null>(null)
const messages = computed(() => (state.activeId ? (state.messages[state.activeId] ?? []) : []))
const active = computed(() => (state.activeId ? state.active[state.activeId] : undefined))
const pending = computed(() => state.pending.filter((p) => p.conversation_id === state.activeId))
const outcome = computed(() => (state.activeId ? state.outcome[state.activeId] : undefined))

const OUTCOME_TEXT: Record<string, string> = {
  'request.failed': 'The task failed.',
  'request.cancelled': 'The task was stopped.',
  'request.interrupted': 'The task was interrupted.',
  'request.suspended': 'The task is suspended and can be resumed.'
}
const outcomeText = computed(() => {
  const o = outcome.value
  if (!o || o.type === 'request.completed') return ''
  const base = OUTCOME_TEXT[o.type] ?? o.type
  return o.unknown_effects ? `${base} ${o.unknown_effects} action(s) have an unknown outcome and will not be repeated.` : base
})

watch(
  () => [messages.value.length, pending.value.length, active.value?.request_id, state.activeId],
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
</script>

<template>
  <section ref="scroller" class="message-scroll">
    <p v-if="!state.loaded" class="empty">{{ state.app.link === 'ready' ? 'Loading…' : 'Connecting to Odin…' }}</p>
    <p v-else-if="!messages.length && !pending.length && !active" class="empty">Ask Odin anything.</p>
    <article v-for="m in messages" :key="m.id" :class="['msg', m.role]">
      <ToolActivity
        v-if="m.role === 'assistant' && m.request_id && state.tools[m.request_id]?.length"
        :entries="state.tools[m.request_id] ?? []"
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
        <span class="state">{{ p.status === 'sending' ? 'sending…' : 'waiting for receipt' }}</span>
      </div>
      <div class="body plain">{{ p.text }}</div>
    </article>
    <div v-if="active" class="working">
      <ToolActivity :entries="state.tools[active.request_id] ?? []" live />
      <div class="working-line">
        <span class="spinner" aria-hidden="true" />
        <span>{{ active.state === 'queued' ? 'Queued' : 'Odin is working…' }}</span>
      </div>
    </div>
    <p v-if="outcomeText" class="outcome" role="status">{{ outcomeText }}</p>
  </section>
</template>
