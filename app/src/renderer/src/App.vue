<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, watch } from 'vue'
import { init, openSettings, state } from './store'
import FirstRunBanner from './components/FirstRunBanner.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import CleanupNotice from './components/CleanupNotice.vue'
import ChatStatus from './components/ChatStatus.vue'
import ConversationList from './components/ConversationList.vue'
import IconRail from './components/IconRail.vue'
import MessageList from './components/MessageList.vue'
import Composer from './components/Composer.vue'
import SearchPanel from './components/SearchPanel.vue'
import StatusBar from './components/StatusBar.vue'
import WorkPanel from './components/WorkPanel.vue'
import SettingsView from './views/Settings.vue'
import { work } from './stores/work'
import { dialog } from './dialog'

let settingsOpener: HTMLElement | null = null
watch(() => state.view, async (view) => {
  const focusAtTransition = document.activeElement
  if (view === 'settings') {
    settingsOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    if (state.view !== view || dialog.current) return
    document.querySelector<HTMLElement>('.settings-nav .back')?.focus()
  } else {
    await nextTick()
    if (state.view !== view) return
    // Explicit work navigation owns its history focus, and a rail button keeps the focus it has; generic Back/Ctrl+,
    // restoration must not pre-empt either.
    if (focusAtTransition instanceof HTMLElement && focusAtTransition.closest('.work-link, .rail')) return
    if (dialog.current) return
    if (settingsOpener?.isConnected) settingsOpener.focus()
    else document.querySelector<HTMLElement>('[aria-label="Message"]')?.focus()
    settingsOpener = null
  }
})

function onKey(event: KeyboardEvent): void {
  // Background view shortcuts are not part of a modal's keyboard context.
  if (dialog.current) return
  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'f') {
    event.preventDefault()
    state.search.open = !state.search.open
  } else if (event.ctrlKey && event.key === ',') {
    event.preventDefault()
    if (state.view === 'settings') state.view = 'chat'
    else openSettings()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  void init()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

const active = computed(() => state.conversations.find((c) => c.id === state.activeId) ?? null)
const workOpen = computed(() => state.view === 'chat' && work.open)
</script>

<template>
  <div class="shell" :class="{ 'work-open': workOpen, 'settings-open': state.view === 'settings' }">
    <CleanupNotice />
    <IconRail />
    <ConversationList v-show="state.view === 'chat'" class="sidebar" />
    <main v-if="state.view === 'chat'" class="main">
      <header class="topbar">
        <h1>{{ active?.title ?? 'Odin' }}</h1>
        <ChatStatus />
      </header>
      <FirstRunBanner v-if="!state.setupReminderHidden" dismissible />
      <SearchPanel v-if="state.search.open" />
      <MessageList class="messages" />
      <div class="composer">
        <Composer />
      </div>
    </main>
    <SettingsView v-else class="main" />
    <WorkPanel v-if="workOpen" class="work-column" />
    <StatusBar class="statusbar" />
    <ConfirmDialog />
  </div>
</template>
