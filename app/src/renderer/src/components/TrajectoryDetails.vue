<script setup lang="ts">
import { reactive, ref } from 'vue'
import CompletionResult from './CompletionResult.vue'
import SettingsSection from './settings/SettingsSection.vue'
import SettingsRow from './settings/SettingsRow.vue'
import { completion, readCompletion } from '../stores/completion'
const filename = ref('')
const api = window.odin
const messageId = ref('')
const filters = reactive({ channel_id: '', user_id: '', tool_name: '', errors_only: false, limit: 100 })
function selected(): Record<string, string | number | boolean> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== '' && value !== false))
}
/** The listed file names; choosing one fills the filename to read. */
function files(value: unknown): string[] {
  const list = (value as { files?: unknown } | undefined)?.files
  return Array.isArray(list) ? list.filter((name): name is string => typeof name === 'string') : []
}
async function readTrace(search: boolean): Promise<void> {
  const params = selected()
  const label = JSON.stringify(search ? params : { ...params, filename: filename.value })
  await readCompletion('traces', () => search ? window.odin.trajectoriesSearch(params) : window.odin.trajectoriesRead({ ...params, filename: filename.value }), label)
}
</script>
<template>
  <SettingsSection title="Trajectories" aria-label="Trajectories" description="Saved records of each request: the model calls and tool calls it made.">
    <SettingsRow label="Trajectory files" description="One file per day. Choose one to read it below.">
      <button class="ghost" @click="readCompletion('trace-files', () => api.trajectoriesList({}))">List trajectory files</button>
      <template #note>
        <CompletionResult v-slot="{ value }" resource="trace-files" feature="Trajectory listing">
          <p v-if="!files(value).length" class="panel-hint">No trajectory files yet.</p>
          <ul v-else class="trace-files">
            <li v-for="name in files(value)" :key="name"><button class="ghost" :aria-pressed="filename === name" @click="filename = name">{{ name }}</button></li>
          </ul>
        </CompletionResult>
      </template>
    </SettingsRow>
    <template v-if="!completion['trace-files']?.unavailable">
      <SettingsRow label="Filters" description="Apply to reading a file and to searching all files." full-width>
        <div class="filter-grid">
          <label class="control-field">Conversation
            <input v-model="filters.channel_id" />
          </label>
          <label class="control-field">User
            <input v-model="filters.user_id" />
          </label>
          <label class="control-field">Tool
            <input v-model="filters.tool_name" />
          </label>
          <label class="control-field">Limit
            <input v-model.number="filters.limit" type="number" min="1" max="500" />
          </label>
        </div>
        <label class="toggle-inline"><input v-model="filters.errors_only" type="checkbox" /> Errors only</label>
      </SettingsRow>
      <SettingsRow label="Read a file" description="Entries from one day's file.">
        <label class="control-field">File name
          <input v-model="filename" placeholder="trace.jsonl" />
        </label>
        <button class="ghost" :disabled="!filename" @click="readTrace(false)">Read trajectory</button>
      </SettingsRow>
      <SettingsRow label="Search all files" description="Entries from every file that match the filters.">
        <button class="ghost" @click="readTrace(true)">Search trajectories</button>
        <template #note><CompletionResult resource="traces" feature="Trajectory selection" /></template>
      </SettingsRow>
      <SettingsRow label="One request" description="The trajectory of a single request, by its message ID.">
        <label class="control-field">Message ID
          <input v-model="messageId" />
        </label>
        <button class="ghost" :disabled="!messageId" @click="readCompletion('trace-message', () => api.trajectoriesMessage({ message_id: messageId }), messageId)">Read message trajectory</button>
        <template #note><CompletionResult resource="trace-message" feature="Message trajectory" /></template>
      </SettingsRow>
    </template>
  </SettingsSection>
</template>
