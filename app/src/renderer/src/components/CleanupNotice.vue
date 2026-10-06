<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { state } from '../store'

const warning = computed(() => state.app.cleanupWarning)
const busy = ref(false)
const error = ref('')
watch(() => warning.value?.id, () => { error.value = '' })

async function acknowledge(): Promise<void> {
  const id = warning.value?.id
  if (!id || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await window.odin.acknowledgeCleanup(id)
    // A pushed new warning is authoritative. An older response must not erase it or change its token.
    if (warning.value?.id !== id) return
    if (result.ok) state.app = result.result
    else error.value = result.error.message
  } catch {
    if (warning.value?.id === id) error.value = 'Could not acknowledge cleanup. The notice remains unchanged.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section v-if="warning" class="cleanup-notice" aria-labelledby="cleanup-notice-title">
    <div class="cleanup-notice-heading">
      <h2 id="cleanup-notice-title">Cleanup unknown</h2>
      <button type="button" class="ghost" :disabled="busy" :aria-busy="busy" @click="acknowledge">Acknowledge</button>
    </div>
    <p>Notice retained at <time :datetime="warning.at">{{ warning.at }}</time>.</p>
    <ul class="cleanup-records" aria-label="Retained cleanup warnings">
      <li v-for="(record, index) in warning.records" :key="index">
        <time :datetime="record.at">{{ record.at }}</time>: {{ record.reason }}
        <span v-if="record.processOutcome !== undefined"> · Process outcome: {{ record.processOutcome }}</span>
        <span v-if="record.shutdownAccepted !== undefined"> · Shutdown accepted: {{ record.shutdownAccepted ? 'yes' : 'no' }}</span>
        <span v-if="record.unsaved !== undefined"> · Unsaved state: {{ record.unsaved ? 'yes' : 'no' }}</span>
        <span v-if="record.unreceipted !== undefined"> · Awaiting receipt: {{ record.unreceipted }}</span>
      </li>
    </ul>
    <p>No effects are labelled undone. No work is replayed. Acknowledgment only archives this notice; resource quarantine and reconciliation remain unchanged.</p>
    <p v-if="error" class="cleanup-notice-error" role="status">{{ error }}</p>
  </section>
</template>

<style scoped>
.cleanup-notice {
  grid-column: 1 / -1;
  grid-row: 1;
  padding: 10px 16px;
  max-height: 35vh;
  overflow-y: auto;
  overflow-wrap: anywhere;
  background: var(--panel-2);
  border-bottom: 1px solid var(--warn);
}
.cleanup-notice-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { color: var(--warn); font-size: 14px; margin: 0; }
p { margin: 6px 0 0; }
.cleanup-records { margin: 6px 0; padding-left: 22px; }
.cleanup-notice-error { color: var(--bad); }
</style>
