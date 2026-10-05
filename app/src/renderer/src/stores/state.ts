// The State and Personality sections: what Odin remembers and knows, and who he is, in the shapes of Odin's
// /api/personality, /api/memory and /api/knowledge routes, plus named lists and reloading context.
import { reactive } from 'vue'
import type { KnowledgeHit, KnowledgeIngest, KnowledgeSource, KnowledgeVersion, MemoryIndex, NamedList, Personality, PersonalitySet } from '../../../shared/api'
import { act, failure, management } from './management'

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
  reload: ''
})

// ---- Personality ------------------------------------------------------------------------------------------------------

export async function loadPersonality(): Promise<void> {
  const result = await window.odin.personalityGet({})
  management.error = failure(result)
  if (result.ok) stateStore.personality = result.result
}

export async function savePersonality(change: PersonalitySet): Promise<boolean> {
  return act('personality', () => window.odin.personalitySet(change), () => 'Saved. New requests use it.', loadPersonality)
}

export async function savePreset(preset: { name: string; display_name?: string; identity?: string; voice?: string }): Promise<boolean> {
  return act('preset', () => window.odin.personalityPresetsSave(preset), (r) => `Saved as ${r.name}.`, loadPersonality)
}

export async function deletePreset(name: string): Promise<boolean> {
  return act(`preset:${name}`, () => window.odin.personalityPresetsDelete({ name }), () => 'Deleted.', loadPersonality)
}

// ---- Memory and lists ------------------------------------------------------------------------------------------------

export async function loadMemory(): Promise<void> {
  const [memory, lists] = await Promise.all([window.odin.memoryList({}), window.odin.listsList({})])
  management.error = !memory.ok ? memory.error.message : !lists.ok ? lists.error.message : ''
  if (memory.ok) stateStore.memory = memory.result
  if (lists.ok) stateStore.lists = lists.result.items
  for (const scope of Object.keys(stateStore.memoryEntries)) await openScope(scope)
}

export async function openScope(scope: string): Promise<void> {
  const result = await window.odin.memoryGet({ scope })
  if (result.ok) stateStore.memoryEntries[scope] = result.result.entries ?? {}
  else delete stateStore.memoryEntries[scope]
}

export function closeScope(scope: string): void {
  delete stateStore.memoryEntries[scope]
}

export async function setMemory(scope: string, key: string, value: unknown): Promise<boolean> {
  return act(`memory:${scope}`, () => window.odin.memorySet({ scope, key, value }), () => `Saved ${key}.`, loadMemory)
}

export async function deleteMemory(scope: string, keys: string[]): Promise<boolean> {
  if (keys.length === 1) return act(`memory:${scope}`, () => window.odin.memoryDelete({ scope, key: keys[0]! }), () => 'Deleted.', loadMemory)
  return act(
    `memory:${scope}`,
    () => window.odin.memoryBulkDelete({ entries: keys.map((key) => ({ scope, key })) }),
    (r) => `Deleted ${r.count}.`,
    loadMemory
  )
}

export async function openList(name: string): Promise<void> {
  const result = await window.odin.listsGet({ name })
  if (result.ok) stateStore.listItems[name] = result.result.items
}

export async function deleteList(name: string): Promise<boolean> {
  delete stateStore.listItems[name]
  return act(`list:${name}`, () => window.odin.listsDelete({ name }), () => 'Deleted.', loadMemory)
}

/** Odin's /reload: the context files again, and what is in context now. */
export async function reloadContext(): Promise<void> {
  stateStore.reload = 'Reloading…'
  const result = await window.odin.reload('context')
  stateStore.reload = result.ok ? result.result.summary || 'Reloaded.' : result.error.message
}

// ---- Knowledge ---------------------------------------------------------------------------------------------------------

export async function loadKnowledge(): Promise<void> {
  const result = await window.odin.knowledgeList({})
  management.error = failure(result)
  if (result.ok) stateStore.knowledge = result.result
}

/** What an ingest did, in words: stored, unchanged, or why not. */
export function ingestNote(answer: KnowledgeIngest): string {
  if (answer.outcome === 'created') return `Stored as ${answer.chunks ?? 0} chunks.`
  if (answer.outcome === 'unchanged') return 'Already stored, unchanged.'
  return answer.message ?? answer.status
}

export async function ingest(source: string, content: string): Promise<boolean> {
  let stored = false
  const ok = await act(
    'knowledge',
    () => window.odin.knowledgeIngest({ source, content }),
    (answer) => {
      stored = answer.outcome === 'created' || answer.outcome === 'unchanged'
      return ingestNote(answer)
    },
    loadKnowledge
  )
  return ok && stored
}

export async function reingest(source: string): Promise<void> {
  await act(`knowledge:${source}`, () => window.odin.knowledgeReingest({ source }), ingestNote, loadKnowledge)
}

export async function deleteSource(source: string): Promise<void> {
  delete stateStore.versions[source]
  await act(`knowledge:${source}`, () => window.odin.knowledgeDelete({ source }), (r) => `Deleted, ${r.chunks_removed} chunks.`, loadKnowledge)
}

export async function loadVersions(source: string): Promise<void> {
  const result = await window.odin.knowledgeVersions({ source })
  if (result.ok) stateStore.versions[source] = result.result
}

export async function restoreVersion(source: string, version: number): Promise<void> {
  await act(
    `knowledge:${source}`,
    () => window.odin.knowledgeRestore({ source, version }),
    (r) => `Restored version ${r.version}: ${r.chunks} chunks.`,
    async () => {
      await loadKnowledge()
      await loadVersions(source)
    }
  )
}

let latestSearch = 0

export async function searchKnowledge(q: string): Promise<void> {
  const mine = ++latestSearch
  if (!q.trim()) {
    stateStore.hits = null
    return
  }
  const result = await window.odin.knowledgeSearch({ q: q.trim(), limit: 20 })
  if (mine !== latestSearch) return
  stateStore.hits = result.ok ? result.result : []
  management.notes.search = result.ok ? '' : result.error.message
}
