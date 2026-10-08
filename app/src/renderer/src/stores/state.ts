// The State and Personality sections: what Odin remembers and knows, and who he is, in the shapes of Odin's
// /api/personality, /api/memory and /api/knowledge routes, plus named lists and reloading context.
import { reactive } from 'vue'
import type { KnowledgeHit, KnowledgeIngest, KnowledgeSource, KnowledgeVersion, MemoryIndex, NamedList, Personality, PersonalitySet, Result } from '../../../shared/api'
import { isUnavailable, settingsResultMessage as resultMessage } from '../capability'
import { act, management } from './management'
import { activePersonality } from '../assistant-name'

type StateResource = 'personality' | 'memory' | 'lists' | 'knowledge' | 'context'
const features: Record<StateResource, string> = { personality: 'Personality', memory: 'Memory', lists: 'Named list management', knowledge: 'Knowledge', context: 'Context reload' }

export const stateStore = reactive({
  personality: null as Personality | null,
  memory: null as MemoryIndex | null,
  /** The scopes opened, with their entries. */
  memoryEntries: {} as Record<string, Record<string, unknown> | undefined>,
  lists: [] as NamedList[],
  listItems: {} as Record<string, unknown[] | undefined>,
  knowledge: [] as KnowledgeSource[],
  hits: null as KnowledgeHit[] | null,
  versions: {} as Record<string, KnowledgeVersion[] | undefined>,
  reload: '',
  unavailable: {} as Partial<Record<StateResource, boolean>>,
  errors: {} as Partial<Record<StateResource, string>>
})

// Refused reads invalidate returned details too, including reads already in flight. They never release an action
// lock or discard a local draft: an unanswered write remains unanswered even when reads aren't served.
const epochs: Record<StateResource, number> = { personality: 0, memory: 0, lists: 0, knowledge: 0, context: 0 }
const asked = { memory: 0, lists: 0, knowledge: 0 }

function answered<T>(resource: StateResource, result: Result<T>): result is { ok: true; result: T } {
  stateStore.errors[resource] = resultMessage(result, features[resource])
  if (result.ok) {
    stateStore.unavailable[resource] = false
    return true
  }
  if (!isUnavailable(result.error)) return false
  stateStore.unavailable[resource] = true
  epochs[resource] += 1
  if (resource === 'personality') stateStore.personality = activePersonality.value = null
  if (resource === 'memory') {
    stateStore.memory = null
    stateStore.memoryEntries = {}
  }
  if (resource === 'lists') {
    stateStore.lists = []
    stateStore.listItems = {}
  }
  if (resource === 'knowledge') {
    stateStore.knowledge = []
    stateStore.hits = null
    stateStore.versions = {}
    latestSearch += 1
  }
  if (resource === 'context') stateStore.reload = ''
  const prefixes = resource === 'personality' ? ['personality', 'preset'] : resource === 'lists' ? ['list'] : [resource]
  for (const key of Object.keys(management.notes)) {
    if (prefixes.some((prefix) => key === prefix || key.startsWith(`${prefix}:`)) && !management.busy[key]) delete management.notes[key]
  }
  if (resource === 'knowledge') delete management.notes.search
  return false
}

/** Keep command codes/dispositions intact for act's unknown-outcome handling; only refusal wording changes. */
async function command<T>(resource: StateResource, run: () => Promise<Result<T>>): Promise<Result<T>> {
  const result = await run()
  if (!result.ok && isUnavailable(result.error)) {
    answered(resource, result)
    return { ...result, error: { ...result.error, message: resultMessage(result, features[resource]) } }
  }
  return result
}

// ---- Personality ------------------------------------------------------------------------------------------------------

let personalityAsked = 0

export async function loadPersonality(): Promise<void> {
  const mine = ++personalityAsked
  const epoch = epochs.personality
  const result = await window.odin.personalityGet({})
  if (mine !== personalityAsked || epoch !== epochs.personality) return
  if (answered('personality', result)) stateStore.personality = activePersonality.value = result.result
}

export async function savePersonality(change: PersonalitySet, onSaved?: () => void): Promise<boolean> {
  if (stateStore.unavailable.personality) return false
  return act('personality', () => command('personality', () => window.odin.personalitySet(change)), () => {
    onSaved?.()
    return 'Saved. New requests use it.'
  }, loadPersonality)
}

export async function savePreset(preset: { name: string; display_name?: string; identity?: string; voice?: string }): Promise<boolean> {
  if (stateStore.unavailable.personality) return false
  return act('preset', () => command('personality', () => window.odin.personalityPresetsSave(preset)), (r) => `Saved as ${r.name}.`, loadPersonality)
}

export async function deletePreset(name: string): Promise<boolean> {
  if (stateStore.unavailable.personality) return false
  return act(`preset:${name}`, () => command('personality', () => window.odin.personalityPresetsDelete({ name })), () => 'Deleted.', loadPersonality)
}

// ---- Memory and lists ------------------------------------------------------------------------------------------------

export async function loadMemory(): Promise<void> {
  const memoryAsked = ++asked.memory
  const listsAsked = ++asked.lists
  const memoryEpoch = epochs.memory
  const listsEpoch = epochs.lists
  await Promise.all([
    window.odin.memoryList({}).then(async (result) => {
      if (memoryAsked !== asked.memory || memoryEpoch !== epochs.memory) return
      if (!answered('memory', result)) return
      stateStore.memory = result.result
      await Promise.all(Object.keys(stateStore.memoryEntries).map(openScope))
    }),
    window.odin.listsList({}).then((result) => {
      if (listsAsked !== asked.lists || listsEpoch !== epochs.lists) return
      if (answered('lists', result)) stateStore.lists = result.result.items
    })
  ])
}

const scopesAsked: Record<string, number> = {}

export async function openScope(scope: string): Promise<void> {
  if (stateStore.unavailable.memory) return
  const mine = scopesAsked[scope] = (scopesAsked[scope] ?? 0) + 1
  const epoch = epochs.memory
  const result = await window.odin.memoryGet({ scope })
  if (epoch !== epochs.memory || mine !== scopesAsked[scope]) return
  if (answered('memory', result)) stateStore.memoryEntries[scope] = result.result.entries ?? {}
  else delete stateStore.memoryEntries[scope]
}

export function closeScope(scope: string): void {
  scopesAsked[scope] = (scopesAsked[scope] ?? 0) + 1
  delete stateStore.memoryEntries[scope]
}

export async function setMemory(scope: string, key: string, value: unknown): Promise<boolean> {
  if (stateStore.unavailable.memory) return false
  return act(`memory:${scope}`, () => command('memory', () => window.odin.memorySet({ scope, key, value })), () => `Saved ${key}.`, loadMemory)
}

export async function deleteMemory(scope: string, keys: string[]): Promise<boolean> {
  if (stateStore.unavailable.memory) return false
  if (keys.length === 1) return act(`memory:${scope}`, () => command('memory', () => window.odin.memoryDelete({ scope, key: keys[0]! })), () => 'Deleted.', loadMemory)
  return act(
    `memory:${scope}`,
    () => command('memory', () => window.odin.memoryBulkDelete({ entries: keys.map((key) => ({ scope, key })) })),
    (r) => `Deleted ${r.count}.`,
    loadMemory
  )
}

const listsAsked: Record<string, number> = {}

export async function openList(name: string): Promise<void> {
  if (stateStore.unavailable.lists) return
  const mine = listsAsked[name] = (listsAsked[name] ?? 0) + 1
  const epoch = epochs.lists
  const result = await window.odin.listsGet({ name })
  if (epoch !== epochs.lists || mine !== listsAsked[name]) return
  if (answered('lists', result)) stateStore.listItems[name] = result.result.items
}

export async function deleteList(name: string): Promise<boolean> {
  if (stateStore.unavailable.lists) return false
  delete stateStore.listItems[name]
  return act(`list:${name}`, () => command('lists', () => window.odin.listsDelete({ name })), () => 'Deleted.', loadMemory)
}

/** Odin's /reload: the context files again, and what is in context now. */
export async function reloadContext(): Promise<void> {
  stateStore.reload = 'Reloading…'
  const result = await window.odin.reload('context')
  if (answered('context', result)) stateStore.reload = result.result.summary || 'Reloaded.'
  else stateStore.reload = stateStore.errors.context ?? ''
}

// ---- Knowledge ---------------------------------------------------------------------------------------------------------

export async function loadKnowledge(): Promise<void> {
  const mine = ++asked.knowledge
  const epoch = epochs.knowledge
  const result = await window.odin.knowledgeList({})
  if (mine !== asked.knowledge || epoch !== epochs.knowledge) return
  if (answered('knowledge', result)) stateStore.knowledge = result.result
}

/** What an ingest did, in words: stored, unchanged, or why not. */
function storedIngest(answer: KnowledgeIngest): boolean {
  // Fresh durable success uses the pinned route's {source, chunks}, not the fixture's outcome tag.
  return answer.outcome === 'created' || answer.outcome === 'unchanged' ||
    (answer.outcome === undefined && typeof answer.chunks === 'number' && answer.chunks > 0)
}

export function ingestNote(answer: KnowledgeIngest): string {
  if (answer.outcome === 'unchanged') return 'Already stored, unchanged.'
  if (storedIngest(answer)) return `Stored as ${answer.chunks ?? 0} chunks.`
  return answer.message ?? answer.status ?? 'No durable storage result was reported.'
}

export async function ingest(source: string, content: string): Promise<boolean> {
  if (stateStore.unavailable.knowledge) return false
  let stored = false
  const ok = await act(
    'knowledge',
    () => command('knowledge', () => window.odin.knowledgeIngest({ source, content })),
    (answer) => {
      stored = storedIngest(answer)
      return ingestNote(answer)
    },
    loadKnowledge
  )
  return ok && stored
}

export async function reingest(source: string): Promise<void> {
  if (stateStore.unavailable.knowledge) return
  await act(`knowledge:${source}`, () => command('knowledge', () => window.odin.knowledgeReingest({ source })), ingestNote, loadKnowledge)
}

export async function deleteSource(source: string): Promise<void> {
  if (stateStore.unavailable.knowledge) return
  delete stateStore.versions[source]
  await act(`knowledge:${source}`, () => command('knowledge', () => window.odin.knowledgeDelete({ source })), (r) => `Deleted, ${r.chunks_removed} chunks.`, loadKnowledge)
}

const versionsAsked: Record<string, number> = {}

export async function loadVersions(source: string): Promise<void> {
  if (stateStore.unavailable.knowledge) return
  const mine = versionsAsked[source] = (versionsAsked[source] ?? 0) + 1
  const epoch = epochs.knowledge
  const result = await window.odin.knowledgeVersions({ source })
  if (epoch !== epochs.knowledge || mine !== versionsAsked[source]) return
  if (answered('knowledge', result)) stateStore.versions[source] = result.result
}

export async function restoreVersion(source: string, version: number): Promise<void> {
  if (stateStore.unavailable.knowledge) return
  await act(
    `knowledge:${source}`,
    () => command('knowledge', () => window.odin.knowledgeRestore({ source, version })),
    (r) => `Restored version ${r.version}: ${r.chunks} chunks.`,
    async () => {
      await loadKnowledge()
      await loadVersions(source)
    }
  )
}

let latestSearch = 0

export async function searchKnowledge(q: string): Promise<void> {
  if (stateStore.unavailable.knowledge) return
  const mine = ++latestSearch
  const epoch = epochs.knowledge
  if (!q.trim()) {
    stateStore.hits = null
    return
  }
  const result = await window.odin.knowledgeSearch({ q: q.trim(), limit: 20 })
  if (mine !== latestSearch || epoch !== epochs.knowledge) return
  if (answered('knowledge', result)) stateStore.hits = result.result
  else if (!stateStore.unavailable.knowledge) stateStore.hits = []
  management.notes.search = resultMessage(result, 'Knowledge')
}
