<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { init, state } from './store'
import ConversationList from './components/ConversationList.vue'
import MessageList from './components/MessageList.vue'
import Composer from './components/Composer.vue'
import StatusBar from './components/StatusBar.vue'

onMounted(() => {
  void init()
})

const active = computed(() => state.conversations.find((c) => c.id === state.activeId) ?? null)
</script>

<template>
  <div class="shell">
    <ConversationList class="sidebar" />
    <main class="main">
      <header class="topbar">
        <h1>{{ active?.title ?? 'Odin' }}</h1>
      </header>
      <MessageList class="messages" />
      <div class="composer">
        <Composer />
      </div>
    </main>
    <StatusBar class="statusbar" />
  </div>
</template>
