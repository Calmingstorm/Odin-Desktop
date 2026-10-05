<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onBeforeUpdate, onMounted, onUpdated, ref } from 'vue'
import type { SearchHit } from '../../../shared/api'
import { jumpTo, moreResults, runSearch, state } from '../store'

const box = ref<HTMLInputElement | null>(null)
const query = ref(state.search.query)
const panel = ref<HTMLElement | null>(null)
const opener = document.activeElement as HTMLElement | null
let focusedBeforeUpdate: HTMLElement | null = null
let pagingTrigger: HTMLElement | null = null
const invalid = computed(() => Boolean(state.search.error && !state.search.unavailable))
const statusText = computed(() => state.search.loading ? 'Searching…' : state.search.error ? '' : state.search.query ? state.search.hits.length ? `${state.search.hits.length} results${state.search.nextCursor ? ', more available' : ''}.` : 'No matches.' : '')

onBeforeUnmount(() => {
  if (document.activeElement && panel.value?.contains(document.activeElement) && opener?.isConnected) opener.focus()
})
onBeforeUpdate(() => {
  const active = document.activeElement as HTMLElement | null
  focusedBeforeUpdate = active && panel.value?.contains(active) ? active : null
})
onUpdated(() => {
  // Results remain mounted while loading. If a settled search removes the focused hit/page control,
  // keep the user in Search, rather than silently dropping focus onto the document body.
  if (focusedBeforeUpdate && focusedBeforeUpdate !== pagingTrigger && !focusedBeforeUpdate.isConnected && document.activeElement === document.body) box.value?.focus()
})

onMounted(async () => {
  await nextTick()
  box.value?.focus()
})

function titleOf(id: string): string {
  return state.conversations.find((c) => c.id === id)?.title ?? 'Deleted conversation'
}

function when(iso: string): string {
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

function submit(): void {
  const value = query.value.trim()
  if (value) void runSearch(value)
}

async function openHit(event: MouseEvent, hit: SearchHit): Promise<void> {
  const trigger = event.currentTarget as HTMLElement
  await jumpTo(hit)
  await nextTick()
  // A user who tabs away while the message loads owns focus. Only completed, still-current navigation moves it.
  if (document.activeElement === trigger && state.highlightId === hit.message_id && state.activeId === hit.conversation_id) {
    document.getElementById(`m-${hit.message_id}`)?.focus()
  }
}

async function more(event: MouseEvent): Promise<void> {
  if (state.search.loading) return
  const trigger = event.currentTarget as HTMLElement
  pagingTrigger = trigger
  const previous = new Set(state.search.hits.map((hit) => hit.message_id))
  await moreResults()
  await nextTick()
  // The final page removes More results; focus the first new hit instead of losing the keyboard position.
  if (!trigger.isConnected && focusedBeforeUpdate === trigger && document.activeElement === document.body) {
    const added = state.search.hits.find((hit) => !previous.has(hit.message_id))
    const target = added ? document.getElementById(`search-hit-${added.message_id}`) : box.value
    target?.focus()
  }
  pagingTrigger = null
}
</script>

<template>
  <aside id="conversation-search" ref="panel" class="search-panel" aria-label="Conversation search" @keydown.esc.stop.prevent="state.search.open = false">
    <form class="search-form" role="search" @submit.prevent="submit">
      <input
        ref="box"
        v-model="query"
        type="search"
        placeholder="Search all conversations"
        aria-label="Search all conversations"
        :aria-invalid="invalid || undefined"
        :aria-describedby="state.search.error ? 'conversation-search-error' : undefined"
      />
      <button type="button" class="ghost" aria-label="Close search" @click="state.search.open = false">✕</button>
    </form>
    <p class="search-note" role="status" aria-atomic="true">{{ statusText }}</p>
    <p v-if="state.search.error" id="conversation-search-error" :class="['search-note', { warn: !state.search.unavailable }]" :role="state.search.unavailable ? 'status' : 'alert'">{{ state.search.error }}</p>
    <ul class="search-hits" aria-label="Search results">
      <li v-for="hit in state.search.hits" :key="hit.message_id">
        <button :id="`search-hit-${hit.message_id}`" class="hit" @click="openHit($event, hit)">
          <span class="hit-meta">{{ titleOf(hit.conversation_id) }} · {{ when(hit.created_at) }}</span>
          <span class="hit-snippet">{{ hit.snippet }}</span>
        </button>
      </li>
    </ul>
    <button v-if="state.search.nextCursor" class="ghost more" :aria-disabled="state.search.loading || undefined" @click="more">
      More results
    </button>
  </aside>
</template>
