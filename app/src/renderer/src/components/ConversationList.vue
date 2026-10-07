<script setup lang="ts">
import { computed, onBeforeUpdate, onUpdated, ref } from 'vue'
import { isBusy, newConversation, select, state } from '../store'
import ConversationMenu from './ConversationMenu.vue'
import Icon from './Icon.vue'
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

/** When the conversation last changed: the time today, the weekday this week, else the date. */
function when(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const now = new Date()
  if (at.toDateString() === now.toDateString()) return at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const days = (now.getTime() - at.getTime()) / 86_400_000
  if (days >= 0 && days < 6) return at.toLocaleDateString([], { weekday: 'short' })
  return at.toLocaleDateString([], { month: 'short', day: 'numeric' })
}
</script>

<template>
  <nav ref="nav" aria-label="Conversations">
    <div class="sidebar-head">
      <h2 class="sidebar-title">Chats</h2>
      <div class="head-actions">
        <button class="new-conversation" aria-label="New conversation" title="New conversation" @click="newConversation">
          <Icon name="plus" :size="17" :stroke="2.4" />
        </button>
      </div>
    </div>
    <button class="conv-search" title="Search all conversations (Ctrl+Shift+F)" :aria-expanded="state.search.open" :aria-controls="state.search.open ? 'conversation-search' : undefined" @click="state.search.open = !state.search.open">
      <Icon name="search" :size="15" />
      <span class="conv-search-label">Search</span>
      <kbd aria-hidden="true">Ctrl+Shift+F</kbd>
    </button>
    <p v-if="state.conversationsUnavailable" class="notice sidebar-notice" role="status">{{ unavailableText('Conversations') }}</p>
    <ul class="conversations">
      <li v-for="c in visible" :key="c.id" :class="['conv-row', { active: c.id === state.activeId }]">
        <button :class="['conv', { active: c.id === state.activeId, archived: c.archived }]" :aria-current="c.id === state.activeId ? 'page' : undefined" :aria-label="`${c.title}${c.inherited_from ? `, thread from ${c.inherited_from.title}` : ''}${c.archived ? ', archived' : ''}${isBusy(c.id) ? ', Odin is working' : c.unread > 0 && c.id !== state.activeId ? `, ${c.unread} unread` : ''}`" @click="select(c.id)">
          <span class="conv-title"><span v-if="c.inherited_from" class="thread-mark" aria-hidden="true">↳ </span>{{ c.title }}</span>
          <span v-if="isBusy(c.id)" class="busy-dot" aria-hidden="true" />
          <span v-else-if="c.unread > 0 && c.id !== state.activeId" class="unread" aria-hidden="true">
            {{ unreadLabel(c.unread) }}
          </span>
        </button>
        <!-- Outside the row's button: its name is its label, and visible text inside a control must be part of it. -->
        <time class="conv-time" :datetime="c.updated_at" aria-hidden="true">{{ when(c.updated_at) }}</time>
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
