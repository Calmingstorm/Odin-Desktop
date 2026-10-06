<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ask } from '../../dialog'
import { unavailableText } from '../../capability'
import { management } from '../../stores/management'
import KnowledgeDetails from '../../components/KnowledgeDetails.vue'
import {
  closeScope,
  deleteList,
  deleteMemory,
  deleteSource,
  ingest,
  loadKnowledge,
  loadMemory,
  loadVersions,
  openList,
  openScope,
  reingest,
  reloadContext,
  restoreVersion,
  searchKnowledge,
  setMemory,
  stateStore
} from '../../stores/state'

onMounted(() => void Promise.all([loadMemory(), loadKnowledge()]))

const scopeName = (scope: string): string => scope === 'global' ? 'Everywhere' : scope.startsWith('user_') ? 'Yours' : scope
const show = (value: unknown): string => (typeof value === 'string' ? value : JSON.stringify(value))
const listItem = (value: unknown): string => {
  if (value && typeof value === 'object' && 'name' in value && typeof value.name === 'string') {
    return `${'done' in value && value.done ? 'Done: ' : ''}${value.name}`
  }
  return show(value)
}
const changedAt = (value: string): string => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString() : 'unknown'

// Memory: a new or edited entry per scope, and the keys picked for deleting.
const drafts = reactive<Record<string, { key: string; value: string } | undefined>>({})
const picked = reactive<Record<string, string[] | undefined>>({})

async function toggleScope(scope: string): Promise<void> {
  if (stateStore.memoryEntries[scope]) {
    closeScope(scope)
    return
  }
  picked[scope] = []
  await openScope(scope)
}

function toggleList(name: string): void {
  if (stateStore.listItems[name]) stateStore.listItems[name] = undefined
  else void openList(name)
}

function toggleVersions(source: string): void {
  if (stateStore.versions[source]) stateStore.versions[source] = undefined
  else void loadVersions(source)
}

function editEntry(scope: string, key = '', value: unknown = ''): void {
  drafts[scope] = { key, value: show(value) }
}

async function saveEntry(scope: string): Promise<void> {
  const draft = drafts[scope]
  if (!draft?.key.trim()) return
  const sent = JSON.stringify(draft)
  const saved = await setMemory(scope, draft.key.trim(), draft.value)
  // Close only the editor that was saved, and only if nothing in it changed since.
  if (saved && drafts[scope] === draft && JSON.stringify(draft) === sent) drafts[scope] = undefined
}

async function removePicked(scope: string): Promise<void> {
  const keys = picked[scope] ?? []
  if (!keys.length) return
  const confirmed = await ask({ title: `Delete ${keys.length} ${keys.length === 1 ? 'entry' : 'entries'}?`, message: `Odin stops remembering ${keys.join(', ')}.`, confirmLabel: 'Delete', danger: true })
  // Unpick only what was deleted: keys picked meanwhile stay picked.
  if (confirmed && (await deleteMemory(scope, keys))) picked[scope] = (picked[scope] ?? []).filter((key) => !keys.includes(key))
}

async function removeList(name: string): Promise<void> {
  const confirmed = await ask({ title: 'Delete this list?', message: `${name} and everything on it is removed.`, confirmLabel: 'Delete', danger: true })
  if (confirmed) await deleteList(name)
}

// Knowledge: a new source, and the search.
const source = ref('')
const content = ref('')
const query = ref('')

async function readFile(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  content.value = await file.text()
  if (!source.value.trim()) source.value = file.name
}

async function add(): Promise<void> {
  const sent = { source: source.value.trim(), content: content.value }
  if (!sent.source || sent.source.length > 100 || !sent.content.trim() || sent.content.trim().length > 500000) return
  // Clear only what was stored: a document typed meanwhile stays.
  if ((await ingest(sent.source, sent.content)) && source.value.trim() === sent.source && content.value === sent.content) {
    source.value = ''
    content.value = ''
  }
}

async function removeSource(name: string): Promise<void> {
  const confirmed = await ask({ title: 'Delete this source?', message: `${name} is removed from Odin's knowledge, with all its chunks.`, confirmLabel: 'Delete', danger: true })
  if (confirmed) await deleteSource(name)
}
</script>

<template>
  <section class="panel" aria-label="Memory">
    <header class="panel-head">
      <h3>Memory</h3>
      <span class="panel-hint">What Odin remembers. All of it goes into every request, as in Odin.</span>
    </header>
    <p v-if="stateStore.unavailable.memory" class="manage-desc" role="status">{{ unavailableText('Memory') }}</p>
    <template v-else>
    <p v-if="stateStore.errors.memory" class="warn">{{ stateStore.errors.memory }}</p>
    <ul class="manage-list">
      <li v-for="(info, scope) in stateStore.memory ?? {}" :key="scope" class="manage-row">
        <div class="manage-line">
          <strong>{{ scopeName(String(scope)) }}</strong>
          <span class="manage-count">{{ info.count }} {{ info.count === 1 ? 'entry' : 'entries' }}</span>
          <span class="manage-actions">
            <button class="ghost" :aria-label="`${stateStore.memoryEntries[scope] ? 'Close' : 'Open'} ${scopeName(String(scope))} memory`" :aria-expanded="Boolean(stateStore.memoryEntries[scope])" :aria-controls="`memory-entries-${scope}`" @click="toggleScope(String(scope))">
              {{ stateStore.memoryEntries[scope] ? 'Close' : 'Open' }}
            </button>
            <button class="ghost" :aria-label="`Add ${scopeName(String(scope))} memory entry`" @click="editEntry(scope)">Add</button>
          </span>
        </div>
        <table v-if="stateStore.memoryEntries[scope]" :id="`memory-entries-${scope}`" :aria-label="`${scopeName(String(scope))} memory entries`" class="runs memory">
          <tbody>
            <tr v-for="(value, key) in stateStore.memoryEntries[scope]" :key="key">
              <td><label><input v-model="picked[scope]" type="checkbox" :value="key" :aria-label="`Pick ${key} in ${scopeName(String(scope))} memory`" /> Pick</label></td>
              <td><code>{{ key }}</code></td>
              <td class="memory-value">{{ show(value) }}</td>
              <td><button class="ghost" :aria-label="`Edit ${key} in ${scopeName(String(scope))} memory`" @click="editEntry(scope, String(key), value)">Edit</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="(picked[scope] ?? []).length" class="panel-actions">
          <button class="ghost danger-item" :aria-label="`Delete ${picked[scope]!.length} picked in ${scopeName(String(scope))} memory…`" @click="removePicked(scope)">Delete {{ picked[scope]!.length }} picked…</button>
        </div>
        <div v-if="drafts[scope]" class="field-input">
          <label class="field-input">Key <input v-model="drafts[scope]!.key" placeholder="Key" :aria-label="`Key in ${scopeName(String(scope))} memory`" /></label>
          <label class="field-input">Value <input v-model="drafts[scope]!.value" placeholder="What to remember" :aria-label="`Value in ${scopeName(String(scope))} memory`" @keydown.enter="saveEntry(scope)" /></label>
          <button class="ghost" :aria-label="`Save ${scopeName(String(scope))} memory entry`" @click="saveEntry(scope)">Save</button>
          <button class="ghost" :aria-label="`Cancel ${scopeName(String(scope))} memory edit`" @click="drafts[scope] = undefined">Cancel</button>
        </div>
        <p v-if="management.notes[`memory:${scope}`]" class="manage-note" role="status">{{ management.notes[`memory:${scope}`] }}</p>
      </li>
    </ul>
    </template>
  </section>

  <section class="panel" aria-label="Named lists">
    <header class="panel-head">
      <h3>Named lists</h3>
      <span class="panel-hint">Lists Odin keeps for you, like a shopping list.</span>
    </header>
    <p v-if="stateStore.unavailable.lists" class="manage-desc" role="status">{{ unavailableText('Named list management') }}</p>
    <template v-else>
    <p v-if="stateStore.errors.lists" class="warn">{{ stateStore.errors.lists }}</p>
    <ul class="manage-list">
      <li v-for="list in stateStore.lists" :key="list.name" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ list.name }}</code>
          <span class="manage-count">{{ list.count }} items, changed {{ changedAt(list.updated_at) }}</span>
          <span class="manage-actions">
            <button class="ghost" :aria-label="`${stateStore.listItems[list.name] ? 'Close' : 'Open'} list ${list.name}`" :aria-expanded="Boolean(stateStore.listItems[list.name])" :aria-controls="`named-list-${encodeURIComponent(list.name)}`" @click="toggleList(list.name)">
              {{ stateStore.listItems[list.name] ? 'Close' : 'Open' }}
            </button>
            <button class="ghost danger-item" :aria-label="`Delete list ${list.name}…`" @click="removeList(list.name)">Delete…</button>
          </span>
        </div>
        <ul v-if="stateStore.listItems[list.name]" :id="`named-list-${encodeURIComponent(list.name)}`" class="refs">
          <li v-for="(item, i) in stateStore.listItems[list.name]" :key="i">{{ listItem(item) }}</li>
        </ul>
      </li>
    </ul>
    <p v-if="!stateStore.lists.length" class="manage-desc">No lists.</p>
    </template>
  </section>

  <section class="panel" aria-label="Knowledge">
    <header class="panel-head">
      <h3>Knowledge</h3>
      <span class="panel-hint">Documents Odin can search. Each source keeps its versions.</span>
    </header>
    <p v-if="stateStore.unavailable.knowledge" class="manage-desc" role="status">{{ unavailableText('Knowledge') }}</p>
    <template v-else>
    <p v-if="stateStore.errors.knowledge" class="warn">{{ stateStore.errors.knowledge }}</p>
    <label class="field-input">Search <input v-model="query" type="search" placeholder="Words to find" @input="searchKnowledge(query)" /></label>
    <ul v-if="stateStore.hits" class="manage-list">
      <li v-for="hit in stateStore.hits" :key="hit.chunk_id" class="manage-row">
        <div class="manage-line"><code class="manage-name">{{ hit.source }}</code><span class="manage-count">score {{ hit.score }}</span></div>
        <p class="manage-desc">{{ hit.content }}</p>
      </li>
      <li v-if="!stateStore.hits.length" class="manage-desc">Nothing found.</li>
    </ul>
    <ul class="manage-list">
      <li v-for="item in stateStore.knowledge" :key="item.source" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ item.source }}</code>
          <span class="manage-count">{{ item.chunks }} chunks, {{ new Date(item.ingested_at).toLocaleString() }}</span>
          <span class="manage-actions">
            <button class="ghost" :aria-label="`${stateStore.versions[item.source] ? 'Hide versions' : 'Versions'} for ${item.source}`" :aria-expanded="Boolean(stateStore.versions[item.source])" :aria-controls="`knowledge-versions-${encodeURIComponent(item.source)}`" @click="toggleVersions(item.source)">
              {{ stateStore.versions[item.source] ? 'Hide versions' : 'Versions' }}
            </button>
            <button class="ghost" :aria-label="`Re-ingest ${item.source}`" :disabled="management.busy[`knowledge:${item.source}`]" @click="reingest(item.source)">Re-ingest</button>
            <button class="ghost danger-item" :aria-label="`Delete source ${item.source}…`" @click="removeSource(item.source)">Delete…</button>
          </span>
        </div>
        <p v-if="item.preview" class="manage-desc">{{ item.preview }}</p>
        <table v-if="stateStore.versions[item.source]" :id="`knowledge-versions-${encodeURIComponent(item.source)}`" :aria-label="`Versions for ${item.source}`" class="runs">
          <tbody>
            <tr v-for="v in stateStore.versions[item.source]" :key="v.id">
              <td>v{{ v.version }}</td>
              <td>{{ v.action }}</td>
              <td>{{ new Date(v.created_at).toLocaleString() }}</td>
              <td>{{ v.diff_summary }}</td>
              <td><button class="ghost" :aria-label="`Restore ${item.source} version ${v.version}`" :disabled="v.action === 'delete' || management.busy[`knowledge:${item.source}`]" @click="restoreVersion(item.source, v.version)">Restore</button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="management.notes[`knowledge:${item.source}`]" class="manage-note" role="status">{{ management.notes[`knowledge:${item.source}`] }}</p>
      </li>
    </ul>
    <h4 class="sub-head">Add a document</h4>
    <label class="field-input">Source <input v-model="source" maxlength="100" placeholder="runbook.md" /></label>
    <label class="field-input">Text <textarea v-model="content" rows="5" maxlength="500000" /></label>
    <div class="panel-actions">
      <label class="ghost file-pick">Load a text file <input type="file" accept=".txt,.md,.markdown,.json,.yml,.yaml,.csv,.log,text/*" @change="readFile" /></label>
      <button class="ghost" :disabled="!source.trim() || source.trim().length > 100 || !content.trim() || content.trim().length > 500000 || management.busy.knowledge" @click="add">Add</button>
    </div>
    <p v-if="management.notes.knowledge" class="manage-note" role="status">{{ management.notes.knowledge }}</p>
    </template>
  </section>

  <KnowledgeDetails />

  <section class="panel" aria-label="Context">
    <header class="panel-head">
      <h3>Context</h3>
      <span class="panel-hint">Reload the context files, and see what is in context now.</span>
      <button v-if="!stateStore.unavailable.context" class="ghost" @click="reloadContext">Reload context</button>
    </header>
    <pre v-if="stateStore.reload" class="manage-json">{{ stateStore.reload }}</pre>
  </section>
</template>
