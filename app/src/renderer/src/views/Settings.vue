<script setup lang="ts">
import { computed, onMounted, toRef, nextTick, ref, type Component } from 'vue'
import CodexAccounts from '../components/CodexAccounts.vue'
import { NAV, navOf } from '../settings-form'
import { presentationFor, presentationDestination, restartFields } from '../settings-presentation'
import { settingsControlId } from '../settings-accessibility'
import Advanced from './settings/Advanced.vue'
import DataPrivacy from './settings/DataPrivacy.vue'
import { state } from '../store'
import { loadSettings, settings } from '../stores/settings'
import General from './settings/General.vue'
import Hosts from './settings/Hosts.vue'
import Mcp from './settings/Mcp.vue'
import Personality from './settings/Personality.vue'
import Skills from './settings/Skills.vue'
import Tools from './settings/Tools.vue'
import Work from './settings/Work.vue'

/** Panels for what isn't a plain setting: the app's own settings, accounts, tools, skills and MCP servers. */
const PANELS: Record<string, Component> = {
  general: General,
  models: CodexAccounts,
  tools: Tools,
  skills: Skills,
  mcp: Mcp,
  hosts: Hosts,
  work: Work,
  personality: Personality,
  data: DataPrivacy,
  advanced: Advanced
}

const active = toRef(state, 'settingsSection')
const fields = computed(() => settings.meta?.fields ?? [])
// A section shows once it has something in it.
const sections = NAV
const title = computed(() => active.value === 'advanced' ? 'Advanced settings' : NAV.find((n) => n.id === active.value)?.title ?? 'General')
const needsRestart = computed(() => restartFields(fields.value).length > 0)
const pending = computed(() => {
  const seen = new Set<string>()
  return restartFields(fields.value).filter((field) => {
    const presentation = presentationFor(field.path)
    if (!presentation || !presentationDestination(field.path) || seen.has(presentation.path)) return false
    seen.add(presentation.path)
    return true
  })
})
const exitNote = ref('')
const revealed = ref('')
async function exit(): Promise<void> {
  try { const result = await window.odin.exitOdin(); exitNote.value = result.ok ? 'Odin is closing…' : result.error.message }
  catch { exitNote.value = 'Exit could not be requested. Use Exit Odin in the application menu.' }
}
async function reveal(path: string): Promise<void> {
  revealed.value = `${path}:${Date.now()}`
  active.value = presentationDestination(path) ?? navOf(path)
  if (!PANELS[active.value]) active.value = 'general'
  await nextTick()
  const presentation = presentationFor(path)
  const target = document.getElementById(settingsControlId(presentation ? 'curated' : 'field', presentation?.path ?? path))
    ?? document.getElementById('settings-section-title')
  for (let parent = target?.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === 'DETAILS') (parent as HTMLDetailsElement).open = true
  }
  target?.scrollIntoView?.({ block: 'nearest' })
  target?.focus()
}

onMounted(() => void loadSettings())
</script>

<template>
  <main class="settings" aria-label="Settings">
    <h1 class="sr-only">Settings</h1>
    <nav class="settings-nav" aria-label="Settings sections">
      <button class="ghost back" @click="state.view = 'chat'">← Back to chat</button>
      <button
        v-for="section in sections"
        :key="section.id"
        :data-testid="`settings-section-${section.id}`"
        :class="['settings-nav-item', { active: section.id === active }]"
        :aria-current="section.id === active ? 'page' : undefined"
        @click="active = section.id"
      >
        {{ section.title }}
      </button>
    </nav>
    <section class="settings-body" tabindex="0" :aria-label="`${title} settings content`">
      <div class="settings-content">
      <button v-if="active === 'advanced'" class="ghost" @click="active = 'general'">← General</button>
      <h2 id="settings-section-title" tabindex="-1">{{ title }}</h2>
      <aside v-if="needsRestart" class="settings-restart" aria-label="Changes requiring restart">
        <p>Some changes need Odin to restart. Exit Odin, then open it again.</p>
        <div class="settings-actions"><button v-for="field in pending" :key="field.path" class="ghost" @click="reveal(field.path)">{{ presentationFor(field.path)?.label }}</button></div>
        <button class="ghost" @click="exit">Exit Odin</button>
        <p v-if="exitNote" role="status">{{ exitNote }}</p>
        <p class="settings-help">Closing the window keeps Odin running.</p>
      </aside>
      <p v-if="settings.error" class="warn" role="status">
        {{ settings.error }} <button class="ghost" @click="loadSettings(true)">Try again</button>
      </p>
      <p v-if="settings.unavailable" class="capability-unavailable" role="status">Settings are unavailable.</p>
      <aside v-if="settings.notice" class="settings-restart"><p role="status">{{ settings.notice }}</p><button class="ghost" @click="loadSettings(true)">Refresh saved settings</button></aside>
      <Advanced v-if="active === 'advanced'" :reveal="revealed" />
      <component :is="PANELS[active]" v-else-if="PANELS[active]" v-bind="active === 'models' || active === 'tools' ? { reveal: revealed } : {}" />
      </div>
    </section>
  </main>
</template>
