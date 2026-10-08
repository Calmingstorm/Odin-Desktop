<script setup lang="ts">
// The left rail: chats, work, the theme and settings. Keyboard shortcuts stay: Ctrl+, for settings.
import { computed } from 'vue'
import Icon from './Icon.vue'
import appIcon from '../../../../resources/icon.svg'
import { openSettings, setAppearance, state } from '../store'
import { linkLabel } from '../stores/status'
import { activeCount, work } from '../stores/work'

const active = computed(() => activeCount())
const workLabel = computed(() => (active.value ? `Work, ${active.value} active` : 'Work'))
const themeLabel = computed(() => (state.dark ? 'Switch to light theme' : 'Switch to dark theme'))

function showChats(): void {
  state.view = 'chat'
}

/** Work lives beside the chat: from settings, it opens with the chat. */
function toggleWork(): void {
  if (state.view !== 'chat') {
    work.open = true
    state.view = 'chat'
  } else {
    work.open = !work.open
  }
}

function toggleTheme(): void {
  void setAppearance(state.dark ? 'light' : 'dark')
}
</script>

<template>
  <nav class="rail" aria-label="Odin">
    <span class="rail-mark" aria-hidden="true"><img class="app-icon" :src="appIcon" width="40" height="40" alt="" /></span>
    <button
      type="button"
      class="rail-button"
      aria-label="Chats"
      title="Chats"
      :aria-current="state.view === 'chat' ? 'page' : undefined"
      @click="showChats"
    >
      <Icon name="chats" />
    </button>
    <button
      type="button"
      class="rail-button work-toggle"
      :aria-label="workLabel"
      :aria-expanded="state.view === 'chat' && work.open"
      title="Agents, tasks, loops, processes and schedules"
      @click="toggleWork"
    >
      <Icon name="work" />
      <span v-if="active" class="rail-count" aria-hidden="true">{{ active }}</span>
    </button>
    <span class="rail-spacer"></span>
    <span :class="['link', 'rail-link', state.app.link]" role="status" aria-atomic="true" :title="linkLabel(state.app.link)">
      <span class="rail-dot" aria-hidden="true"></span><span class="sr-only">{{ linkLabel(state.app.link) }}</span>
    </span>
    <button type="button" class="rail-button theme-toggle" :aria-label="themeLabel" :title="themeLabel" @click="toggleTheme">
      <Icon :name="state.dark ? 'sun' : 'moon'" :size="19" />
    </button>
    <button
      type="button"
      class="rail-button settings-toggle"
      aria-label="Settings"
      title="Settings (Ctrl+,)"
      :aria-current="state.view === 'settings' ? 'page' : undefined"
      @click="openSettings()"
    >
      <Icon name="settings" />
    </button>
  </nav>
</template>

<style scoped>
.rail-mark { background: transparent; }
.app-icon { display: block; width: 100%; height: 100%; }
</style>
