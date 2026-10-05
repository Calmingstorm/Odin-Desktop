<script setup lang="ts">
import { computed, onBeforeUpdate, onUpdated, ref } from 'vue'
import { isBusy, newConversation, select, state } from '../store'
import ConversationMenu from './ConversationMenu.vue'
import { unavailableText } from '../capability'

// The menu floats above the page, anchored to its ⋯ button, so the scrolling list can't clip it.
const menu = ref<{ id: string; top: number; left: number } | null>(null)
const nav = ref<HTMLElement | null>(null)
let opener: HTMLElement | null = null
let focusedBeforeUpdate: HTMLElement | null = null

function closeMenu(): void {
  // Restore before Rename/Reset/Delete capture their dialog opener, not a soon-removed menu item.
  if (opener?.isConnected) opener.focus()
  menu.value = null
}

onBeforeUpdate(() => {
  const active = document.activeElement as HTMLElement | null
  focusedBeforeUpdate = active && nav.value?.contains(active) ? active : null
})
onUpdated(() => {
  // Archive/delete can remove a focused row. Do not steal focus if the user has moved elsewhere.
  if (focusedBeforeUpdate && !focusedBeforeUpdate.isConnected && document.activeElement === document.body) {
    const target = nav.value?.querySelector<HTMLButtonElement>('.conv.active') ?? nav.value?.querySelector<HTMLButtonElement>('.conv, .new-conversation')
    target?.focus()
  }
})

function toggleMenu(event: MouseEvent | KeyboardEvent, id: string): void {
  if (menu.value?.id === id) {
    closeMenu()
    return
  }
  opener = event.currentTarget as HTMLElement
  const rect = opener.getBoundingClientRect()
  menu.value = { id, top: rect.bottom + 4, left: rect.right }
}
const visible = computed(() => state.conversations.filter((c) => state.showArchived || !c.archived))
const archivedCount = computed(() => state.conversations.filter((c) => c.archived).length)

function unreadLabel(count: number): string {
  return count > 99 ? '99+' : String(count)
}
</script>

<template>
  <nav ref="nav" aria-label="Conversations">
    <div class="sidebar-head">
      <span class="brand">Odin</span>
      <div class="head-actions">
        <button class="ghost" title="Search all conversations (Ctrl+Shift+F)" :aria-expanded="state.search.open" :aria-controls="state.search.open ? 'conversation-search' : undefined" @click="state.search.open = !state.search.open">
          Search
        </button>
        <button class="ghost new-conversation" aria-label="New conversation" @click="newConversation">+ New</button>
      </div>
    </div>
    <p v-if="state.conversationsUnavailable" class="notice sidebar-notice" role="status">{{ unavailableText('Conversations') }}</p>
    <ul class="conversations">
      <li v-for="c in visible" :key="c.id" class="conv-row">
        <button :class="['conv', { active: c.id === state.activeId, archived: c.archived }]" :aria-current="c.id === state.activeId ? 'page' : undefined" :aria-label="`${c.title}${c.inherited_from ? `, thread from ${c.inherited_from.title}` : ''}${c.archived ? ', archived' : ''}${isBusy(c.id) ? ', Odin is working' : c.unread > 0 && c.id !== state.activeId ? `, ${c.unread} unread` : ''}`" @click="select(c.id)">
          <span class="conv-title"><span v-if="c.inherited_from" class="thread-mark" aria-hidden="true">↳ </span>{{ c.title }}</span>
          <span v-if="isBusy(c.id)" class="busy-dot" aria-hidden="true" />
          <span v-else-if="c.unread > 0 && c.id !== state.activeId" class="unread" aria-hidden="true">
            {{ unreadLabel(c.unread) }}
          </span>
        </button>
        <button class="conv-more" :aria-label="`Actions for ${c.title}`" aria-haspopup="menu" :aria-expanded="menu?.id === c.id" :aria-controls="menu?.id === c.id ? `conversation-menu-${c.id}` : undefined" @click.stop="toggleMenu($event, c.id)" @keydown.down.prevent="toggleMenu($event, c.id)">
          ⋯
        </button>
        <ConversationMenu v-if="menu?.id === c.id" :id="`conversation-menu-${c.id}`" :conversation="c" :top="menu.top" :left="menu.left" @close="closeMenu" />
      </li>
    </ul>
    <button v-if="archivedCount" class="ghost show-archived" @click="state.showArchived = !state.showArchived">
      {{ state.showArchived ? 'Hide archived' : `Show archived (${archivedCount})` }}
    </button>
  </nav>
</template>
