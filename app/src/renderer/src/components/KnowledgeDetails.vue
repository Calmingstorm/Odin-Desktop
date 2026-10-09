<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import type { Result } from '../../../shared/api'
import { isUnavailable, settingsUnavailableText as unavailableText } from '../capability'
import SettingsSection from './settings/SettingsSection.vue'
import SettingsRow from './settings/SettingsRow.vue'
import { ask } from '../dialog'
import { act, management } from '../stores/management'
import { chunkCount, loadKnowledge, stateStore } from '../stores/state'

// These endpoints return core records. Each shows as readable content, with the complete record a click away.
type ReadKey = 'chunks' | 'duplicates' | 'version' | 'diff' | 'learned'
type ReadState = { value: unknown; loaded: boolean; busy: boolean; error: string; unavailable: boolean; request: string }
const fresh = (): ReadState => ({ value: undefined, loaded: false, busy: false, error: '', unavailable: false, request: '' })
const reads = reactive<Record<ReadKey, ReadState>>({ chunks: fresh(), duplicates: fresh(), version: fresh(), diff: fresh(), learned: fresh() })
const epochs: Record<ReadKey, number> = { chunks: 0, duplicates: 0, version: 0, diff: 0, learned: 0 }
const readLabels: Record<ReadKey, string> = { chunks: 'Knowledge chunks', duplicates: 'Knowledge duplicates', version: 'Knowledge version', diff: 'Knowledge diff', learned: 'Learned context' }
const knowledgeReads: ReadKey[] = ['chunks', 'duplicates', 'version', 'diff']
/** Whether a read has anything to show yet: a result, an error, or a read in progress. */
const shown = (key: ReadKey): boolean => reads[key].busy || reads[key].loaded || reads[key].unavailable || Boolean(reads[key].error)
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

/** The merge's own receipt and in-flight key. It sits outside the `knowledge:<source>` lock
 * names, because a document may be named "merge". The merge also holds the shared knowledge
 * lock, so adds wait for it. */
const MERGE = 'knowledge-merge'

function mergeLocked(keep = keepSource.value.trim(), remove = removeSource.value.trim()): boolean {
  return Boolean(management.busy.knowledge || management.busy[MERGE] || management.busy[`knowledge:${keep}`] || management.busy[`knowledge:${remove}`])
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
    const sourceKeys = ['knowledge', `knowledge:${keep_source}`, `knowledge:${remove_source}`]
    for (const key of sourceKeys) management.busy[key] = true
    let dispatched = false
    await act(MERGE, async () => {
      dispatched = true
      const result = await call(window.odin.knowledgeMerge && (() => window.odin.knowledgeMerge({ keep_source, remove_source })))
      mergeUnavailable.value = !result.ok && isUnavailable(result.error)
      return result
    }, (answer) => {
      const receipt = record(answer)
      return `Kept ${text(receipt.kept) || keep_source}. Removed ${text(receipt.removed) || remove_source}` +
        (typeof receipt.chunks_removed === 'number' ? ` and its ${chunkCount(receipt.chunks_removed)}.` : '.')
    }, async () => {
      for (const key of sourceKeys) management.busy[key] = false
      // Old detail reads no longer describe the current sources after a merge receipt.
      for (const key of knowledgeReads) {
        epochs[key] += 1
        Object.assign(reads[key], fresh())
      }
      await loadKnowledge()
    })
    // A command act declines to start never reaches the refresh that releases these locks.
    if (!dispatched) for (const key of sourceKeys) management.busy[key] = false
  } finally {
    mergeConfirming.value = false
  }
}

/** The saved documents, for the source menus. */
const sources = computed(() => stateStore.knowledge.map((item) => item.source))
type Row = Record<string, unknown>
const rows = (value: unknown): Row[] => (Array.isArray(value) ? value.filter((item): item is Row => Boolean(item) && typeof item === 'object') : [])
const record = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {})
const text = (value: unknown): string => (typeof value === 'string' ? value : value == null ? '' : String(value))
const when = (value: unknown): string => (typeof value === 'string' && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString() : '')

/** The learned entry being edited in place, if any. */
const editing = ref<{ key: string; content: string; category: string; original: { content: string; category: string } } | null>(null)
const learnedEntries = computed(() => rows(record(reads.learned.value).entries))
const learnedKey = computed(() => editing.value?.key ?? '')
const learnedUnavailable = ref(false)
const learnedConfirming = ref(false)
const learnedNoteKey = ref('')
const learnedLock = (): boolean => Boolean(management.busy[`learned:${learnedKey.value.trim()}`])
/** A receipt for an entry no longer listed, such as one just deleted, shows under the list. */
const listNote = computed(() => learnedNoteKey.value && !learnedEntries.value.some((entry) => `learned:${text(entry.key)}` === learnedNoteKey.value)
  ? management.notes[learnedNoteKey.value] ?? '' : '')

async function learned(): Promise<void> {
  await read('learned', '{}', () => call(window.odin.learnedList && (() => window.odin.learnedList({}))))
}

function startEdit(entry: Row): void {
  const content = text(entry.content), category = text(entry.category)
  editing.value = { key: text(entry.key), content, category, original: { content, category } }
}

async function updateLearned(): Promise<void> {
  const draft = editing.value
  const key = draft?.key.trim() ?? ''
  if (!draft || !key || learnedUnavailable.value || reads.learned.unavailable || learnedLock()) return
  const changes = { ...(draft.content !== draft.original.content ? { content: draft.content } : {}),
    ...(draft.category !== draft.original.category ? { category: draft.category } : {}) }
  if (!Object.keys(changes).length) return
  const args = { key, ...changes }
  const sent = { content: draft.content, category: draft.category }
  learnedNoteKey.value = `learned:${key}`
  await act(learnedNoteKey.value, async () => {
    const result = await call(window.odin.learnedUpdate && (() => window.odin.learnedUpdate(args)))
    learnedUnavailable.value = !result.ok && isUnavailable(result.error)
    return result
  }, () => {
    // Saved, now or by a late receipt. The editor closes only if nothing changed since
    // the save was sent; newer edits stay open, unsaved against what was saved.
    if (editing.value === draft) {
      if (draft.content === sent.content && draft.category === sent.category) editing.value = null
      else draft.original = { ...sent }
    }
    return 'Saved.'
  }, learned)
}

async function deleteLearned(key: string): Promise<void> {
  if (!key || learnedUnavailable.value || reads.learned.unavailable || management.busy[`learned:${key}`] || learnedConfirming.value) return
  learnedConfirming.value = true
  try {
    const confirmed = await ask({ title: 'Delete this learned entry?', message: `Remove ${key} from learned context.`, confirmLabel: 'Delete', danger: true })
    if (!confirmed || management.busy[`learned:${key}`]) return
    learnedNoteKey.value = `learned:${key}`
    await act(learnedNoteKey.value, async () => {
      const result = await call(window.odin.learnedDelete && (() => window.odin.learnedDelete({ key })))
      learnedUnavailable.value = !result.ok && isUnavailable(result.error)
      return result
    }, () => {
      // Only a confirmed deletion, now or by a late receipt, closes the entry's editor.
      if (editing.value?.key === key) editing.value = null
      return 'Deleted.'
    }, learned)
  } finally {
    learnedConfirming.value = false
  }
}

onMounted(() => void learned())
</script>

<template>
  <SettingsSection title="Knowledge details" aria-label="Knowledge details" description="Look inside saved documents: how they are split for search, their versions and repeated content.">
    <p v-if="!sources.length" class="manage-desc">No documents saved yet. Add one above.</p>
    <template v-else>
      <form aria-label="Read knowledge chunks" @submit.prevent="chunks">
        <SettingsRow label="Chunks" description="The pieces a document is split into for search.">
          <label class="control-field">Source
            <select id="knowledge-chunk-source" v-model="chunkSource" aria-label="Chunk source" required>
              <option value="" disabled>Choose a document</option>
              <option v-for="name in sources" :key="name" :value="name">{{ name }}</option>
            </select>
          </label>
          <button class="ghost" type="submit" :disabled="!chunkSource.trim() || reads.chunks.busy">Read chunks</button>
          <template v-if="shown('chunks')" #note>
            <div class="knowledge-result" :aria-label="`${readLabels.chunks} result`">
              <p v-if="reads.chunks.busy" class="manage-desc" role="status">Reading…</p>
              <p v-else-if="reads.chunks.unavailable" class="manage-desc" role="status">{{ unavailableText(readLabels.chunks) }}</p>
              <p v-else-if="reads.chunks.error" class="warn" role="alert">{{ reads.chunks.error }}</p>
              <template v-else-if="reads.chunks.loaded">
                <ol class="knowledge-chunks">
                  <li v-for="(chunk, index) in rows(reads.chunks.value)" :key="text(chunk.chunk_id) || index">
                    <p class="manage-desc">Chunk {{ Number(chunk.chunk_index ?? index) + 1 }}{{ chunk.total_chunks ? ` of ${chunk.total_chunks}` : '' }}{{ typeof chunk.char_count === 'number' ? ` · ${chunk.char_count} characters` : '' }}</p>
                    <pre class="manage-json">{{ text(chunk.content) }}</pre>
                  </li>
                </ol>
                <details class="raw-record"><summary>Raw record</summary><pre class="manage-json" :aria-label="`${readLabels.chunks} JSON`">{{ json(reads.chunks.value) }}</pre></details>
              </template>
            </div>
          </template>
        </SettingsRow>
      </form>
      <form aria-label="Find knowledge duplicates" @submit.prevent="duplicates">
        <SettingsRow label="Repeated content" description="Documents that hold the same or overlapping text. Overlap from 0 to 1; 0.5 when left empty.">
          <label class="control-field narrow">Threshold
            <input id="knowledge-duplicate-threshold" v-model="threshold" type="number" step="any" min="0" max="1" placeholder="0.5" aria-label="Near-duplicate threshold (optional)" />
          </label>
          <button class="ghost" type="submit" :disabled="!thresholdValid() || reads.duplicates.busy">Find duplicates</button>
          <template v-if="shown('duplicates')" #note>
            <div class="knowledge-result" :aria-label="`${readLabels.duplicates} result`">
              <p v-if="reads.duplicates.busy" class="manage-desc" role="status">Reading…</p>
              <p v-else-if="reads.duplicates.unavailable" class="manage-desc" role="status">{{ unavailableText(readLabels.duplicates) }}</p>
              <p v-else-if="reads.duplicates.error" class="warn" role="alert">{{ reads.duplicates.error }}</p>
              <template v-else-if="reads.duplicates.loaded">
                <p v-if="!rows(record(reads.duplicates.value).exact).length && !rows(record(reads.duplicates.value).near).length" class="manage-desc">No repeated content found.</p>
                <ul v-else class="knowledge-pairs">
                  <li v-for="(group, index) in rows(record(reads.duplicates.value).exact)" :key="`exact-${index}`">Same text in {{ Array.isArray(group.sources) ? group.sources.join(', ') : '' }}</li>
                  <li v-for="(pair, index) in rows(record(reads.duplicates.value).near)" :key="`near-${index}`">
                    <code>{{ text(pair.source_a) }}</code> and <code>{{ text(pair.source_b) }}</code>
                    <span class="manage-count">{{ typeof pair.overlap_ratio === 'number' ? `${Math.round(pair.overlap_ratio * 100)}% overlap` : typeof pair.similarity === 'number' ? `${Math.round(pair.similarity * 100)}% similar` : '' }}{{ pair.shared_chunks != null ? `, ${pair.shared_chunks} shared chunks` : '' }}</span>
                  </li>
                </ul>
                <details class="raw-record"><summary>Raw record</summary><pre class="manage-json" :aria-label="`${readLabels.duplicates} JSON`">{{ json(reads.duplicates.value) }}</pre></details>
              </template>
            </div>
          </template>
        </SettingsRow>
      </form>
      <form aria-label="Read knowledge version" @submit.prevent="getVersion">
        <SettingsRow label="A saved version" description="The text a document had at one version.">
          <label class="control-field wide">Source
            <select id="knowledge-version-source" v-model="versionSource" aria-label="Version source" required>
              <option value="" disabled>Choose a document</option>
              <option v-for="name in sources" :key="name" :value="name">{{ name }}</option>
            </select>
          </label>
          <label class="control-field narrow">Version
            <input id="knowledge-version-number" v-model="version" type="number" min="0" step="1" aria-label="Version number" required />
          </label>
          <button class="ghost" type="submit" :disabled="!versionSource.trim() || integer(version) === undefined || reads.version.busy">Read version</button>
          <template v-if="shown('version')" #note>
            <div class="knowledge-result" :aria-label="`${readLabels.version} result`">
              <p v-if="reads.version.busy" class="manage-desc" role="status">Reading…</p>
              <p v-else-if="reads.version.unavailable" class="manage-desc" role="status">{{ unavailableText(readLabels.version) }}</p>
              <p v-else-if="reads.version.error" class="warn" role="alert">{{ reads.version.error }}</p>
              <template v-else-if="reads.version.loaded">
                <p class="manage-desc">Version {{ text(record(reads.version.value).version) }}{{ record(reads.version.value).action ? ` · ${text(record(reads.version.value).action)}` : '' }}{{ typeof record(reads.version.value).chunk_count === 'number' ? ` · ${record(reads.version.value).chunk_count} chunks` : '' }}{{ when(record(reads.version.value).created_at) ? ` · ${when(record(reads.version.value).created_at)}` : '' }}</p>
                <pre v-if="text(record(reads.version.value).content)" class="manage-json">{{ text(record(reads.version.value).content) }}</pre>
                <p v-else class="manage-desc">This version keeps no text (a deletion).</p>
                <details class="raw-record"><summary>Raw record</summary><pre class="manage-json" :aria-label="`${readLabels.version} JSON`">{{ json(reads.version.value) }}</pre></details>
              </template>
            </div>
          </template>
        </SettingsRow>
      </form>
      <form aria-label="Read knowledge diff" @submit.prevent="diff">
        <SettingsRow label="Compare versions" description="What changed between two versions of a document.">
          <label class="control-field wide">Source
            <select id="knowledge-diff-source" v-model="diffSource" aria-label="Diff source" required>
              <option value="" disabled>Choose a document</option>
              <option v-for="name in sources" :key="name" :value="name">{{ name }}</option>
            </select>
          </label>
          <label class="control-field narrow">From
            <input id="knowledge-diff-from" v-model="v1" type="number" min="0" step="1" aria-label="From version" required />
          </label>
          <label class="control-field narrow">To
            <input id="knowledge-diff-to" v-model="v2" type="number" min="0" step="1" aria-label="To version" required />
          </label>
          <button class="ghost" type="submit" :disabled="!diffSource.trim() || integer(v1) === undefined || integer(v2) === undefined || reads.diff.busy">Read diff</button>
          <template v-if="shown('diff')" #note>
            <div class="knowledge-result" :aria-label="`${readLabels.diff} result`">
              <p v-if="reads.diff.busy" class="manage-desc" role="status">Reading…</p>
              <p v-else-if="reads.diff.unavailable" class="manage-desc" role="status">{{ unavailableText(readLabels.diff) }}</p>
              <p v-else-if="reads.diff.error" class="warn" role="alert">{{ reads.diff.error }}</p>
              <template v-else-if="reads.diff.loaded">
                <p v-if="typeof record(reads.diff.value).lines_added === 'number'" class="manage-desc">{{ record(reads.diff.value).lines_added }} lines added, {{ record(reads.diff.value).lines_removed }} removed.</p>
                <pre class="manage-json">{{ text(record(reads.diff.value).diff) || 'No differences.' }}</pre>
                <details class="raw-record"><summary>Raw record</summary><pre class="manage-json" :aria-label="`${readLabels.diff} JSON`">{{ json(reads.diff.value) }}</pre></details>
              </template>
            </div>
          </template>
        </SettingsRow>
      </form>
      <form aria-label="Merge knowledge sources" @submit.prevent="merge">
        <SettingsRow label="Merge two documents" description="Keep one document and delete the other, with all its chunks. Its text is not copied over.">
          <label class="control-field">Keep
            <select id="knowledge-merge-keep" v-model="keepSource" aria-label="Keep source" required>
              <option value="" disabled>Choose a document</option>
              <option v-for="name in sources" :key="name" :value="name">{{ name }}</option>
            </select>
          </label>
          <label class="control-field">Remove
            <select id="knowledge-merge-remove" v-model="removeSource" aria-label="Remove source" required>
              <option value="" disabled>Choose a document</option>
              <option v-for="name in sources" :key="name" :value="name" :disabled="name === keepSource">{{ name }}</option>
            </select>
          </label>
          <button class="ghost danger-item" type="submit" :disabled="!keepSource.trim() || !removeSource.trim() || keepSource.trim() === removeSource.trim() || mergeLocked() || mergeConfirming || mergeUnavailable">Merge sources…</button>
          <template v-if="mergeUnavailable || management.notes[MERGE]" #note>
            <p v-if="mergeUnavailable" class="manage-desc" role="status">{{ unavailableText('Knowledge merge') }}</p>
            <p v-if="management.notes[MERGE]" class="manage-note" role="status" aria-label="Knowledge command receipt">{{ management.notes[MERGE] }}</p>
          </template>
        </SettingsRow>
      </form>
    </template>
  </SettingsSection>

  <SettingsSection title="Learned context" aria-label="Learned context" description="Lessons Odin saved from past work. Turn learning on or off in Learning and search above.">
    <template #actions><button class="ghost" :disabled="reads.learned.busy" @click="learned">Refresh learned context</button></template>
    <p v-if="reads.learned.busy" class="manage-desc" role="status">Reading…</p>
    <p v-else-if="reads.learned.unavailable" class="manage-desc" role="status">{{ unavailableText('Learned context') }}</p>
    <p v-else-if="reads.learned.error" class="warn" role="alert">{{ reads.learned.error }}</p>
    <ul v-else-if="reads.learned.loaded" class="manage-list" aria-label="Learned entries">
      <li v-for="entry in learnedEntries" :key="text(entry.key)" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ text(entry.key) }}</code>
          <span v-if="text(entry.category)" class="state-chip">{{ text(entry.category) }}</span>
          <span class="manage-actions">
            <button class="ghost" :aria-label="`Edit learned entry ${text(entry.key)}`" :disabled="learnedUnavailable || Boolean(management.busy[`learned:${text(entry.key)}`])" @click="startEdit(entry)">Edit</button>
            <button class="ghost danger-item" :aria-label="`Delete learned entry ${text(entry.key)}…`" :disabled="learnedUnavailable || learnedConfirming || Boolean(management.busy[`learned:${text(entry.key)}`])" @click="deleteLearned(text(entry.key))">Delete…</button>
          </span>
        </div>
        <p class="manage-desc">{{ text(entry.content) }}</p>
        <form v-if="editing && editing.key === text(entry.key)" class="inline-editor" :aria-label="`Edit learned entry ${editing.key}`" @submit.prevent="updateLearned">
          <SettingsRow label="Content" :control-id="`learned-content-${editing.key}`" full-width><textarea :id="`learned-content-${editing.key}`" v-model="editing.content" rows="4" /></SettingsRow>
          <SettingsRow label="Category" :control-id="`learned-category-${editing.key}`"><input :id="`learned-category-${editing.key}`" v-model="editing.category" /></SettingsRow>
          <div class="settings-editor-actions">
            <button class="ghost" type="submit" :disabled="learnedLock() || learnedUnavailable || (editing.content === editing.original.content && editing.category === editing.original.category)">Save learned entry</button>
            <button class="ghost" type="button" @click="editing = null">Cancel</button>
          </div>
        </form>
        <p v-if="management.notes[`learned:${text(entry.key)}`]" class="manage-note" role="status">{{ management.notes[`learned:${text(entry.key)}`] }}</p>
      </li>
      <li v-if="!learnedEntries.length" class="manage-row manage-desc">Nothing learned yet.</li>
    </ul>
    <p v-else class="manage-desc">Not read yet.</p>
    <p v-if="listNote" class="manage-note" role="status">{{ listNote }}</p>
    <p v-if="learnedUnavailable" class="manage-desc" role="status">{{ unavailableText('Learned context changes') }}</p>
  </SettingsSection>
</template>

<style scoped>
.knowledge-chunks { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.knowledge-pairs { margin: 0; padding-left: 18px; font-size: 13px; }
.raw-record { margin-top: 6px; font-size: 12px; color: var(--muted); }
</style>
