<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { jumpTo, moreResults, runSearch, state } from '../store'

const box = ref<HTMLInputElement | null>(null)
const query = ref(state.search.query)

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
</script>

<template>
  <aside class="search-panel" aria-label="Search">
    <form class="search-form" role="search" @submit.prevent="submit">
      <input
        ref="box"
        v-model="query"
        type="search"
        placeholder="Search all conversations"
        aria-label="Search all conversations"
        @keydown.escape="state.search.open = false"
      />
      <button type="button" class="ghost" title="Close search" @click="state.search.open = false">✕</button>
    </form>
    <p v-if="state.search.loading" class="search-note">Searching…</p>
    <p v-else-if="state.search.error" :class="['search-note', { warn: !state.search.unavailable }]" :role="state.search.unavailable ? 'status' : 'alert'">{{ state.search.error }}</p>
    <p v-else-if="state.search.query && !state.search.hits.length" class="search-note">No matches.</p>
    <ul class="search-hits">
      <li v-for="hit in state.search.hits" :key="hit.message_id">
        <button class="hit" @click="jumpTo(hit)">
          <span class="hit-meta">{{ titleOf(hit.conversation_id) }} · {{ when(hit.created_at) }}</span>
          <span class="hit-snippet">{{ hit.snippet }}</span>
        </button>
      </li>
    </ul>
    <button v-if="state.search.nextCursor" class="ghost more" :disabled="state.search.loading" @click="moreResults">
      More results
    </button>
  </aside>
</template>
