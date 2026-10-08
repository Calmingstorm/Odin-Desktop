<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { settingsControlId } from '../../settings-accessibility'
import SettingEditor from '../../components/settings/SettingEditor.vue'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import { ADVANCED_CATEGORIES, ADVANCED_FIELDS, advancedMatches } from '../../settings-presentation'
import { settings } from '../../stores/settings'
const search = ref('')
const props = defineProps<{ reveal?: string }>()
watch(() => props.reveal, () => { search.value = '' })
const structured = new Set(['openai_compatible.model_profiles', 'sessions.context_budget_overrides', 'openai_codex.context_budget_overrides', 'tools.governor.host_overrides'])
const sections = computed(() => ADVANCED_CATEGORIES.map((title) => ({ title, entries: ADVANCED_FIELDS.filter((entry) => entry.category === title && advancedMatches(entry, search.value)).map((entry) => ({ ...entry, field: settings.meta?.fields.find((field) => field.path === entry.path), staged: structured.has(entry.path) })).filter((entry) => entry.field || entry.staged && settings.meta) })).filter((section) => section.entries.length))
</script>
<template>
  <p class="settings-intro">Limits, compatibility and retention for this profile. Saving persists a value; runtime adoption depends on the core.</p>
  <label class="settings-search">Search Advanced settings <input v-model="search" type="search" placeholder="Find a limit or policy" /></label>
  <p v-if="!settings.meta && !settings.unavailable" role="status">Loading Advanced settings.</p>
  <p v-else-if="settings.meta && !sections.length" role="status">No matching Advanced settings. Try a different search.</p>
  <SettingsSection v-for="section in sections" :key="section.title" :title="section.title">
    <template v-for="entry in section.entries" :key="entry.path">
      <div v-if="entry.staged" :id="settingsControlId('curated', entry.path)" tabindex="-1" class="settings-row"><div class="settings-row-copy"><strong>{{ entry.label }}</strong><p>This structured setting needs its owner-backed record editor{{ entry.path === 'tools.governor.host_overrides' ? ' and explicit permission-change confirmation' : '' }}. That editor is staged for the next settings slice; current values are not changed here.</p></div><span class="settings-editor-readonly">Read-only</span></div>
      <SettingEditor v-else :field="entry.field!" :label="entry.label" :help="entry.help" :editor="entry.field?.type === 'object' || entry.field?.type === 'array' ? 'long' : 'short'" />
    </template>
  </SettingsSection>
</template>
