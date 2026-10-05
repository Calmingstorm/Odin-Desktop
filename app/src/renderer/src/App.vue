<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { init, state } from './store'
import ConfirmDialog from './components/ConfirmDialog.vue'
import ConversationList from './components/ConversationList.vue'
import MessageList from './components/MessageList.vue'
import Composer from './components/Composer.vue'
import SearchPanel from './components/SearchPanel.vue'
import StatusBar from './components/StatusBar.vue'

function onKey(event: KeyboardEvent): void {
  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'f') {
    event.preventDefault()
    state.search.open = !state.search.open
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  void init()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

const active = computed(() => state.conversations.find((c) => c.id === state.activeId) ?? null)
</script>

<template>
  <div class="shell">
    <ConversationList class="sidebar" />
    <main class="main">
      <header class="topbar">
        <h1>{{ active?.title ?? 'Odin' }}</h1>
      </header>
      <SearchPanel v-if="state.search.open" />
      <MessageList class="messages" />
      <div class="composer">
        <Composer />
      </div>
    </main>
    <StatusBar class="statusbar" />
    <ConfirmDialog />
  </div>
</template>
