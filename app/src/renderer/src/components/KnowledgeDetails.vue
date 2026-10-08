<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import type { Result } from '../../../shared/api'
import { isUnavailable, settingsUnavailableText as unavailableText } from '../capability'
import SettingsSection from './settings/SettingsSection.vue'
import SettingsRow from './settings/SettingsRow.vue'
import { ask } from '../dialog'
import { act, management } from '../stores/management'
import { loadKnowledge } from '../stores/state'

// These endpoints return core records, not UI measurements. Keep every returned field as JSON.
type ReadKey = 'chunks' | 'duplicates' | 'version' | 'diff' | 'learned'
type ReadState = { value: unknown; loaded: boolean; busy: boolean; error: string; unavailable: boolean; request: string }
const fresh = (): ReadState => ({ value: undefined, loaded: false, busy: false, error: '', unavailable: false, request: '' })
const reads = reactive<Record<ReadKey, ReadState>>({ chunks: fresh(), duplicates: fresh(), version: fresh(), diff: fresh(), learned: fresh() })
const epochs: Record<ReadKey, number> = { chunks: 0, duplicates: 0, version: 0, diff: 0, learned: 0 }
const readLabels: Record<ReadKey, string> = { chunks: 'Knowledge chunks', duplicates: 'Knowledge duplicates', version: 'Knowledge version', diff: 'Knowledge diff', learned: 'Learned context' }
const knowledgeReads: ReadKey[] = ['chunks', 'duplicates', 'version', 'diff']
const json = (value: unknown): string => JSON.stringify(value, null, 2) ?? 'No JSON value returned.'

// Older cores can omit a bridge method; this is unavailable, not an empty result.
async function call<T>(method: (() => Promise<Result<T>>) | undefined): Promise<Result<T>> {
  if (!method) return { ok: false, error: { code: 'capability_unavailable', message: 'This bridge method is unavailable.', disposition: 'not_dispatched' } }
  try {
    return await method()
  } catch (error) {
    return { ok: false, error: { code: 'bridge_error', message: error instanceof Error ? error.message : String(error) } }
  }
}

async function read(key: ReadKey, request: string, run: () => Promise<Result<unknown>>): Promise<void> {
  const epoch = ++epochs[key]
  Object.assign(reads[key], fresh(), { busy: true, request })
  const result = await run()
  if (epochs[key] !== epoch) return
  reads[key].busy = false
  if (result.ok) {
    reads[key].value = result.result
    reads[key].loaded = true
  } else {
    reads[key].unavailable = isUnavailable(result.error)
    reads[key].error = reads[key].unavailable ? '' : result.error.message
  }
}

const chunkSource = ref('')
const threshold = ref('')
const versionSource = ref('')
const version = ref('')
const diffSource = ref('')
const v1 = ref('')
const v2 = ref('')
const keepSource = ref('')
const removeSource = ref('')
const mergeUnavailable = ref(false)
const mergeConfirming = ref(false)
const integer = (text: string | number): number | undefined => {
  if (!/^\d+$/.test(String(text).trim())) return undefined
  const value = Number(text)
  return Number.isSafeInteger(value) && value >= 0 ? value : undefined
}
const duplicateThreshold = (): number | undefined => String(threshold.value).trim() === '' ? undefined : Number(threshold.value)
const thresholdValid = (): boolean => String(threshold.value).trim() === '' || Number.isFinite(duplicateThreshold())

async function chunks(): Promise<void> {
  const source = chunkSource.value.trim()
  if (!source) return
  await read('chunks', json({ source }), () => call(window.odin.knowledgeChunks && (() => window.odin.knowledgeChunks({ source }))))
}

async function duplicates(): Promise<void> {
  if (!thresholdValid()) return
  const value = duplicateThreshold()
  const args = value === undefined ? {} : { threshold: value }
  await read('duplicates', json(args), () => call(window.odin.knowledgeDuplicates && (() => window.odin.knowledgeDuplicates(args))))
}

async function getVersion(): Promise<void> {
  const source = versionSource.value.trim()
  const number = integer(version.value)
  if (!source || number === undefined) return
  const args = { source, version: number }
  await read('version', json(args), () => call(window.odin.knowledgeVersion && (() => window.odin.knowledgeVersion(args))))
}

async function diff(): Promise<void> {
  const source = diffSource.value.trim()
  const first = integer(v1.value)
  const second = integer(v2.value)
  if (!source || first === undefined || second === undefined) return
  const args = { source, v1: first, v2: second }
  await read('diff', json(args), () => call(window.odin.knowledgeDiff && (() => window.odin.knowledgeDiff(args))))
}

function mergeLocked(keep = keepSource.value.trim(), remove = removeSource.value.trim()): boolean {
  return Boolean(management.busy.knowledge || management.busy[`knowledge:${keep}`] || management.busy[`knowledge:${remove}`])
}

async function merge(): Promise<void> {
  const keep_source = keepSource.value.trim()
  const remove_source = removeSource.value.trim()
  if (!keep_source || !remove_source || keep_source === remove_source || mergeUnavailable.value || mergeConfirming.value || mergeLocked(keep_source, remove_source)) return
  mergeConfirming.value = true
  try {
    const confirmed = await ask({ title: 'Merge these knowledge sources?', message: `Keep ${keep_source} unchanged and delete ${remove_source} with all its chunks. This removes the duplicate source; it does not copy its content into the kept source.`, confirmLabel: 'Merge', danger: true })
    if (!confirmed || mergeLocked(keep_source, remove_source)) return
    // Existing State controls act per source. Hold both source locks as well as the global merge lock,
    // including while an unanswered command waits for its late receipt.
    const sourceKeys = [`knowledge:${keep_source}`, `knowledge:${remove_source}`]
    for (const key of sourceKeys) management.busy[key] = true
    await act('knowledge', async () => {
      const result = await call(window.odin.knowledgeMerge && (() => window.odin.knowledgeMerge({ keep_source, remove_source })))
      mergeUnavailable.value = !result.ok && isUnavailable(result.error)
      return result
    }, (answer) => json(answer), async () => {
      for (const key of sourceKeys) management.busy[key] = false
      // Old detail reads no longer describe the current sources after a merge receipt.
      for (const key of knowledgeReads) {
        epochs[key] += 1
        Object.assign(reads[key], fresh())
      }
      await loadKnowledge()
    })
  } finally {
    mergeConfirming.value = false
  }
}

const learnedKey = ref('')
const editContent = ref(false)
const learnedContent = ref('')
const editCategory = ref(false)
const learnedCategory = ref('')
const learnedUnavailable = ref(false)
const learnedConfirming = ref(false)
const learnedNoteKey = ref('')
const learnedLock = (): boolean => Boolean(management.busy[`learned:${learnedKey.value.trim()}`])

async function learned(): Promise<void> {
  await read('learned', '{}', () => call(window.odin.learnedList && (() => window.odin.learnedList({}))))
}

async function updateLearned(): Promise<void> {
  const key = learnedKey.value.trim()
  if (!key || (!editContent.value && !editCategory.value) || learnedUnavailable.value || reads.learned.unavailable || learnedLock()) return
  const args = { key, ...(editContent.value ? { content: learnedContent.value } : {}), ...(editCategory.value ? { category: learnedCategory.value } : {}) }
  learnedNoteKey.value = `learned:${key}`
  await act(learnedNoteKey.value, async () => {
    const result = await call(window.odin.learnedUpdate && (() => window.odin.learnedUpdate(args)))
    learnedUnavailable.value = !result.ok && isUnavailable(result.error)
    return result
  }, (answer) => json(answer), learned)
}

async function deleteLearned(): Promise<void> {
  const key = learnedKey.value.trim()
  if (!key || learnedUnavailable.value || reads.learned.unavailable || learnedLock() || learnedConfirming.value) return
  learnedConfirming.value = true
  try {
    const confirmed = await ask({ title: 'Delete this learned entry?', message: `Remove ${key} from learned context.`, confirmLabel: 'Delete', danger: true })
    if (!confirmed || management.busy[`learned:${key}`]) return
    learnedNoteKey.value = `learned:${key}`
    await act(learnedNoteKey.value, async () => {
      const result = await call(window.odin.learnedDelete && (() => window.odin.learnedDelete({ key })))
      learnedUnavailable.value = !result.ok && isUnavailable(result.error)
      return result
    }, (answer) => json(answer), learned)
  } finally {
    learnedConfirming.value = false
  }
}

onMounted(() => void learned())
</script>

<template>
  <SettingsSection title="Knowledge details" aria-label="Knowledge details">
    <form aria-label="Read knowledge chunks" @submit.prevent="chunks">
      <SettingsRow label="Chunk source" control-id="knowledge-chunk-source"><input id="knowledge-chunk-source" v-model="chunkSource" required /></SettingsRow>
      <div class="panel-actions"><button class="ghost" type="submit" :disabled="!chunkSource.trim() || reads.chunks.busy">Read chunks</button></div>
    </form>
    <form aria-label="Find knowledge duplicates" @submit.prevent="duplicates">
      <SettingsRow label="Near-duplicate threshold (optional)" control-id="knowledge-duplicate-threshold"><input id="knowledge-duplicate-threshold" v-model="threshold" type="number" step="any" /></SettingsRow>
      <div class="panel-actions"><button class="ghost" type="submit" :disabled="!thresholdValid() || reads.duplicates.busy">Find duplicates</button></div>
    </form>
    <form aria-label="Read knowledge version" @submit.prevent="getVersion">
      <SettingsRow label="Version source" control-id="knowledge-version-source"><input id="knowledge-version-source" v-model="versionSource" required /></SettingsRow>
      <SettingsRow label="Version number" control-id="knowledge-version-number"><input id="knowledge-version-number" v-model="version" type="number" min="0" step="1" required /></SettingsRow>
      <div class="panel-actions"><button class="ghost" type="submit" :disabled="!versionSource.trim() || integer(version) === undefined || reads.version.busy">Read version</button></div>
    </form>
    <form aria-label="Read knowledge diff" @submit.prevent="diff">
      <SettingsRow label="Diff source" control-id="knowledge-diff-source"><input id="knowledge-diff-source" v-model="diffSource" required /></SettingsRow>
      <SettingsRow label="From version" control-id="knowledge-diff-from"><input id="knowledge-diff-from" v-model="v1" type="number" min="0" step="1" required /></SettingsRow>
      <SettingsRow label="To version" control-id="knowledge-diff-to"><input id="knowledge-diff-to" v-model="v2" type="number" min="0" step="1" required /></SettingsRow>
      <div class="panel-actions"><button class="ghost" type="submit" :disabled="!diffSource.trim() || integer(v1) === undefined || integer(v2) === undefined || reads.diff.busy">Read diff</button></div>
    </form>
    <div v-for="key in knowledgeReads" :key="key" class="knowledge-result" :aria-label="`${readLabels[key]} result`">
      <h4 class="sub-head">{{ readLabels[key] }}</h4>
      <p v-if="reads[key].busy" role="status">Reading…</p>
      <p v-else-if="reads[key].unavailable" role="status">{{ unavailableText(readLabels[key]) }}</p>
      <p v-else-if="reads[key].error" class="warn" role="alert">{{ reads[key].error }}</p>
      <template v-else-if="reads[key].loaded">
        <pre class="manage-json" :aria-label="`${readLabels[key]} request`">{{ reads[key].request }}</pre>
        <pre class="manage-json" :aria-label="`${readLabels[key]} JSON`">{{ json(reads[key].value) }}</pre>
      </template>
      <p v-else class="manage-desc">Not read yet.</p>
    </div>
    <form aria-label="Merge knowledge sources" @submit.prevent="merge">
      <h4 class="sub-head">Merge sources</h4>
      <SettingsRow label="Keep source" control-id="knowledge-merge-keep"><input id="knowledge-merge-keep" v-model="keepSource" required /></SettingsRow>
      <SettingsRow label="Remove source" control-id="knowledge-merge-remove"><input id="knowledge-merge-remove" v-model="removeSource" required /></SettingsRow>
      <div class="panel-actions"><button class="ghost danger-item" type="submit" :disabled="!keepSource.trim() || !removeSource.trim() || keepSource.trim() === removeSource.trim() || mergeLocked() || mergeConfirming || mergeUnavailable">Merge sources…</button></div>
    </form>
    <p v-if="mergeUnavailable" role="status">{{ unavailableText('Knowledge merge') }}</p>
    <pre v-if="management.notes.knowledge" class="manage-json" role="status" aria-label="Knowledge command receipt">{{ management.notes.knowledge }}</pre>
  </SettingsSection>

  <SettingsSection title="Learned context" aria-label="Learned context">
    <button class="ghost" :disabled="reads.learned.busy" @click="learned">Refresh learned context</button>
    <p v-if="reads.learned.busy" role="status">Reading…</p>
    <p v-else-if="reads.learned.unavailable" role="status">{{ unavailableText('Learned context') }}</p>
    <p v-else-if="reads.learned.error" class="warn" role="alert">{{ reads.learned.error }}</p>
    <pre v-else-if="reads.learned.loaded" class="manage-json" aria-label="Learned context JSON">{{ json(reads.learned.value) }}</pre>
    <p v-else class="manage-desc">Not read yet.</p>
    <form aria-label="Edit learned context" @submit.prevent="updateLearned">
      <label class="field-input">Learned entry key <input v-model="learnedKey" required /></label>
      <label><input v-model="editContent" type="checkbox" /> Change content</label>
      <label class="field-input">New learned content <textarea v-model="learnedContent" :disabled="!editContent" rows="4" /></label>
      <label><input v-model="editCategory" type="checkbox" /> Change category</label>
      <label class="field-input">New learned category <input v-model="learnedCategory" :disabled="!editCategory" /></label>
      <button class="ghost" type="submit" :disabled="!learnedKey.trim() || (!editContent && !editCategory) || learnedLock() || learnedUnavailable || reads.learned.unavailable">Update learned entry</button>
      <button class="ghost danger-item" type="button" :disabled="!learnedKey.trim() || learnedLock() || learnedConfirming || learnedUnavailable || reads.learned.unavailable" @click="deleteLearned">Delete learned entry…</button>
    </form>
    <p v-if="learnedUnavailable" role="status">{{ unavailableText('Learned context changes') }}</p>
    <pre v-if="learnedNoteKey && management.notes[learnedNoteKey]" class="manage-json" role="status" aria-label="Learned command receipt">{{ management.notes[learnedNoteKey] }}</pre>
  </SettingsSection>
</template>

<style scoped>
form > .panel-actions, form > .sub-head, .knowledge-result { margin: 12px var(--settings-padding); }
</style>
