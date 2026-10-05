<script setup lang="ts">
import { computed, ref } from 'vue'
import { isBusy, newConversation, select, state } from '../store'
import ConversationMenu from './ConversationMenu.vue'
import { unavailableText } from '../capability'

// The menu floats above the page, anchored to its ⋯ button, so the scrolling list can't clip it.
const menu = ref<{ id: string; top: number; left: number } | null>(null)

function toggleMenu(event: MouseEvent, id: string): void {
  if (menu.value?.id === id) {
    menu.value = null
    return
  }
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  menu.value = { id, top: rect.bottom + 4, left: rect.right }
}
const visible = computed(() => state.conversations.filter((c) => state.showArchived || !c.archived))
const archivedCount = computed(() => state.conversations.filter((c) => c.archived).length)

function unreadLabel(count: number): string {
  return count > 99 ? '99+' : String(count)
}
</script>

<template>
  <nav aria-label="Conversations">
    <div class="sidebar-head">
      <span class="brand">Odin</span>
      <div class="head-actions">
        <button class="ghost" title="Search all conversations (Ctrl+Shift+F)" @click="state.search.open = !state.search.open">
          Search
        </button>
        <button class="ghost" title="New conversation" @click="newConversation">+ New</button>
      </div>
    </div>
    <p v-if="state.conversationsUnavailable" class="notice" role="status">{{ unavailableText('Conversations') }}</p>
    <ul class="conversations">
      <li v-for="c in visible" :key="c.id" class="conv-row">
        <button :class="['conv', { active: c.id === state.activeId, archived: c.archived }]" @click="select(c.id)">
          <span class="conv-title"><span v-if="c.inherited_from" class="thread-mark" title="Thread">↳ </span>{{ c.title }}</span>
          <span v-if="isBusy(c.id)" class="busy-dot" title="Odin is working in this conversation" />
          <span v-else-if="c.unread > 0 && c.id !== state.activeId" class="unread" :title="`${c.unread} unread`">
            {{ unreadLabel(c.unread) }}
          </span>
        </button>
        <button class="conv-more" :aria-label="`Actions for ${c.title}`" :aria-expanded="menu?.id === c.id" @click.stop="toggleMenu($event, c.id)">
          ⋯
        </button>
        <ConversationMenu v-if="menu?.id === c.id" :conversation="c" :top="menu.top" :left="menu.left" @close="menu = null" />
      </li>
    </ul>
    <button v-if="archivedCount" class="ghost show-archived" @click="state.showArchived = !state.showArchived">
      {{ state.showArchived ? 'Hide archived' : `Show archived (${archivedCount})` }}
    </button>
  </nav>
</template>
