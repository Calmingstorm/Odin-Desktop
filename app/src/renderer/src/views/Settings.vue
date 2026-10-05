<script setup lang="ts">
import { computed, onMounted, ref, type Component } from 'vue'
import CodexAccounts from '../components/CodexAccounts.vue'
import SchemaForm from '../components/SchemaForm.vue'
import { NAV, groupsFor, sectionTitle } from '../settings-form'
import { state } from '../store'
import { loadSettings, settings } from '../stores/settings'
import General from './settings/General.vue'
import Hosts from './settings/Hosts.vue'
import Mcp from './settings/Mcp.vue'
import Personality from './settings/Personality.vue'
import Records from './settings/Records.vue'
import Skills from './settings/Skills.vue'
import State from './settings/State.vue'
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
  state: State,
  records: Records
}

const active = ref('general')
const fields = computed(() => settings.meta?.fields ?? [])
// A section shows once it has something in it.
const sections = computed(() => NAV.filter((n) => PANELS[n.id] || groupsFor(n.id, fields.value).length))
const groups = computed(() => groupsFor(active.value, fields.value))
const title = computed(() => NAV.find((n) => n.id === active.value)?.title ?? '')

onMounted(loadSettings)
</script>

<template>
  <div class="settings">
    <nav class="settings-nav" aria-label="Settings sections">
      <button class="ghost back" @click="state.view = 'chat'">← Back to chat</button>
      <button
        v-for="section in sections"
        :key="section.id"
        :class="['settings-nav-item', { active: section.id === active }]"
        :aria-current="section.id === active ? 'page' : undefined"
        @click="active = section.id"
      >
        {{ section.title }}
      </button>
    </nav>
    <section class="settings-body">
      <h2>{{ title }}</h2>
      <p v-if="settings.error" class="warn">
        {{ settings.error }} <button class="ghost" @click="loadSettings">Try again</button>
      </p>
      <component :is="PANELS[active]" v-if="PANELS[active]" />
      <div v-for="group in groups" :key="group.section" class="settings-group">
        <h3 class="settings-group-title">{{ sectionTitle(group.section) }}</h3>
        <SchemaForm :fields="group.fields" />
      </div>
    </section>
  </div>
</template>
