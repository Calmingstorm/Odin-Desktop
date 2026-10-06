<script setup lang="ts">
import { reactive, ref } from 'vue'
import CompletionResult from './CompletionResult.vue'
import { completion, readCompletion } from '../stores/completion'
const filename = ref('')
const api = window.odin
const messageId = ref('')
const filters = reactive({ channel_id: '', user_id: '', tool_name: '', errors_only: false, limit: 100 })
function selected(): Record<string, string | number | boolean> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== '' && value !== false))
}
async function readTrace(search: boolean): Promise<void> {
  const params = selected()
  const label = JSON.stringify(search ? params : { ...params, filename: filename.value })
  await readCompletion('traces', () => search ? window.odin.trajectoriesSearch(params) : window.odin.trajectoriesRead({ ...params, filename: filename.value }), label)
}
</script>
<template>
  <section class="panel" aria-label="Trajectories">
    <header class="panel-head"><h3>Trajectories</h3><button class="ghost" @click="readCompletion('trace-files', () => api.trajectoriesList({}))">List trajectory files</button></header>
    <CompletionResult resource="trace-files" feature="Trajectory listing" />
    <template v-if="!completion['trace-files']?.unavailable">
      <label>Trajectory filename <input v-model="filename" placeholder="trace.jsonl" /></label>
      <label>Trace channel <input v-model="filters.channel_id" /></label>
      <label>Trace user <input v-model="filters.user_id" /></label>
      <label>Trace tool <input v-model="filters.tool_name" /></label>
      <label>Trace limit <input v-model.number="filters.limit" type="number" min="1" max="500" /></label>
      <label><input v-model="filters.errors_only" type="checkbox" /> Trace errors only</label>
      <button class="ghost" :disabled="!filename" @click="readTrace(false)">Read trajectory</button>
      <button class="ghost" @click="readTrace(true)">Search trajectories</button>
      <CompletionResult resource="traces" feature="Trajectory selection" />
      <label>Trace message ID <input v-model="messageId" /></label>
      <button class="ghost" :disabled="!messageId" @click="readCompletion('trace-message', () => api.trajectoriesMessage({ message_id: messageId }), messageId)">Read message trajectory</button>
      <CompletionResult resource="trace-message" feature="Message trajectory" />
    </template>
  </section>
</template>
