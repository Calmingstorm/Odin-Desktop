<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { init, state } from './store'
import ConfirmDialog from './components/ConfirmDialog.vue'
import ConversationList from './components/ConversationList.vue'
import MessageList from './components/MessageList.vue'
import Composer from './components/Composer.vue'
import SearchPanel from './components/SearchPanel.vue'
import StatusBar from './components/StatusBar.vue'
import WorkPanel from './components/WorkPanel.vue'
import SettingsView from './views/Settings.vue'
import { activeCount, work } from './stores/work'

function onKey(event: KeyboardEvent): void {
  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'f') {
    event.preventDefault()
    state.search.open = !state.search.open
  } else if (event.ctrlKey && event.key === ',') {
    event.preventDefault()
    state.view = state.view === 'settings' ? 'chat' : 'settings'
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
    <main v-if="state.view === 'chat'" class="main">
      <header class="topbar">
        <h1>{{ active?.title ?? 'Odin' }}</h1>
        <button class="ghost work-toggle" :aria-expanded="work.open" title="Agents, tasks, loops, processes and schedules" @click="work.open = !work.open">
          Work<span v-if="activeCount()" class="badge">{{ activeCount() }}</span>
        </button>
        <button class="ghost" title="Settings (Ctrl+,)" @click="state.view = 'settings'">Settings</button>
      </header>
      <SearchPanel v-if="state.search.open" />
      <WorkPanel v-if="work.open" />
      <MessageList class="messages" />
      <div class="composer">
        <Composer />
      </div>
    </main>
    <SettingsView v-else class="main" />
    <StatusBar class="statusbar" />
    <ConfirmDialog />
  </div>
</template>
