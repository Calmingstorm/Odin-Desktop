<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SettingEditor from '../../components/settings/SettingEditor.vue'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import SettingsRow from '../../components/settings/SettingsRow.vue'
import { settingsControlId } from '../../settings-accessibility'
import { ADVANCED_CATEGORIES, ADVANCED_FIELDS, advancedMatches } from '../../settings-presentation'
import { settings } from '../../stores/settings'
const search = ref('')
const props = defineProps<{ reveal?: string }>()
watch(() => props.reveal, () => { search.value = '' })
const sections = computed(() => ADVANCED_CATEGORIES.map((title) => ({ title, entries: ADVANCED_FIELDS.filter((entry) => entry.category === title && advancedMatches(entry, search.value)).map((entry) => ({ ...entry, field: settings.meta?.fields.find((field) => field.path === entry.path), hasChildren: settings.meta?.fields.some((field) => field.path.startsWith(`${entry.path}.`)) })).filter((entry) => entry.field || entry.hasChildren) })).filter((section) => section.entries.length))
</script>
<template>
  <label class="settings-search">Search Advanced settings <input v-model="search" type="search" placeholder="Find a limit or policy" /></label>
  <p v-if="!settings.meta && !settings.unavailable" role="status">Loading Advanced settings.</p>
  <div v-else-if="settings.meta && !sections.length" role="status">
    <p>{{ search.trim() ? 'No matching Advanced settings. Clear the search to browse all categories.' : 'Advanced settings are not available yet. Refresh saved settings to try again.' }}</p>
    <button v-if="search.trim()" class="ghost" @click="search = ''">Clear search</button>
  </div>
  <SettingsSection v-for="section in sections" :key="section.title" :title="section.title">
    <template v-for="entry in section.entries" :key="entry.path">
      <SettingEditor v-if="entry.field" :field="entry.field" :label="entry.label" :help="entry.help" :editor="entry.field.type === 'object' || entry.field.type === 'array' ? 'long' : 'short'" />
      <SettingsRow v-else :id="settingsControlId('curated', entry.path)" tabindex="-1" :label="entry.label" description="Read-only. Refresh saved settings before editing this group."><span class="settings-editor-readonly">Read-only</span></SettingsRow>
    </template>
  </SettingsSection>
</template>
