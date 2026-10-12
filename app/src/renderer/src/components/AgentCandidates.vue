<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { ConfigField } from '../../../shared/api'
import { catalogueModelLabel, modelProvider, modelSelectionNote, providerEnabled, type ModelRow } from '../model-picker'

/** One automatic-selection entry, as `agents.auto_model_allowlist` stores it. */
export type Candidate = string | { model: string; reasoning_effort?: string | null; thinking_mode?: string | null }

const props = defineProps<{
  /** The core's model catalogue, every provider. */
  rows: ModelRow[]
  /** What automatic selection uses while no candidates are chosen, from the core. */
  defaults: string[]
  /** The candidates being edited: the draft, else the saved list. Empty means Odin's default. */
  candidates: Candidate[]
  /** Custom descriptions by model; null while the guidance JSON under More options is invalid, undefined when
   *  descriptions aren't a setting here. */
  hints: Record<string, string> | null | undefined
  fields: ConfigField[]
  thinkingModes: string[]
  controlId: (path: string) => string
}>()
const emit = defineEmits<{
  (event: 'update:candidates', value: Candidate[]): void
  /** An empty text means "use Odin's description". */
  (event: 'hint', model: string, text: string): void
}>()

const providerNames = { codex: 'Codex', compat: 'OpenAI-compatible', ollama: 'Ollama' } as const
const modelOf = (item: Candidate): string => typeof item === 'string' ? item : item.model
const usingDefault = computed(() => props.candidates.length === 0)
const chosen = computed(() => usingDefault.value ? props.defaults : props.candidates.map(modelOf))
const rowFor = (model: string): ModelRow | undefined => props.rows.find((row) => row.ref === model)
const compatibleMain = computed(() => props.fields.find((field) => field.path === 'openai_compatible.model')?.desired)
// A compatible endpoint such as OpenRouter can list its whole catalogue. Offer the models set up for it.
function offered(row: ModelRow): boolean {
  if (!providerEnabled(row.ref, props.fields)) return false
  return modelProvider(row.ref) !== 'compat' || row.ref === `compat:${String(compatibleMain.value ?? '')}` || Boolean(row.profile)
}
const list = computed(() => [
  ...chosen.value.map((model) => ({ model, row: rowFor(model), ticked: true })),
  ...props.rows.filter((row) => !chosen.value.includes(row.ref) && offered(row)).map((row) => ({ model: row.ref, row, ticked: false }))
])
// Odin's own reasons a model can't run agents. "Not configured" is only a missing sign-in or setup, not a reason
// to forbid choosing it.
const blocked = (row: ModelRow | undefined): string => {
  const reason = row?.agent_available === false ? row.agent_unavailable_reason ?? '' : ''
  return reason && reason !== 'not configured' && reason !== 'disabled' ? reason : ''
}
const label = (model: string, row: ModelRow | undefined): string => row ? catalogueModelLabel(row) : model
const note = (model: string): string => {
  if (!rowFor(model)) return 'Not in the current model choices. It stays chosen until you untick it.'
  return modelSelectionNote(model, props.rows, props.fields)
}

// Changes made before the parent's update arrives as a prop each build on the one before, never on a stale list.
let pending: Candidate[] | null = null
watch(() => props.candidates, () => { pending = null })
function update(next: Candidate[]): void {
  pending = next
  emit('update:candidates', next)
}
/** The list a change starts from: the latest list, or Odin's default written out. */
function explicit(): Candidate[] {
  const list = pending ?? props.candidates
  return list.length ? list.map((item) => typeof item === 'string' ? item : { ...item }) : [...props.defaults]
}
function toggle(model: string, ticked: boolean): void {
  const next = ticked ? [...explicit(), model] : explicit().filter((item) => modelOf(item) !== model)
  // An empty list means Odin's default, never "no models": the last ticked model can't be unticked.
  if (next.length) update(next)
}
function move(model: string, delta: number): void {
  const next = explicit()
  const from = next.findIndex((item) => modelOf(item) === model)
  const to = from + delta
  if (from < 0 || to < 0 || to >= next.length) return
  ;[next[from], next[to]] = [next[to]!, next[from]!]
  update(next)
}
function choose(model: string, key: 'reasoning_effort' | 'thinking_mode', raw: string): void {
  const next = explicit()
  const index = next.findIndex((item) => modelOf(item) === model)
  if (index < 0) return
  const item = next[index]!
  next[index] = { ...(typeof item === 'string' ? { model: item } : item), [key]: raw || null }
  update(next)
}
const setting = (model: string, key: 'reasoning_effort' | 'thinking_mode'): string => {
  const item = props.candidates.find((entry) => modelOf(entry) === model)
  return item && typeof item !== 'string' ? item[key] ?? '' : ''
}
const efforts = (model: string): string[] | null => rowFor(model)?.effort_capabilities?.values ?? null

const builtin = (model: string): string => rowFor(model)?.builtin_hint ?? ''
const custom = (model: string): string | undefined => props.hints?.[model] || undefined
const editing = reactive<Record<string, boolean>>({})
/** Editing starts from Odin's description; text back to it, or cleared, stores no custom description. */
function describe(model: string, text: string): void {
  if (!props.hints) return
  const own = text.trim()
  emit('hint', model, !own || own === builtin(model).trim() ? '' : text)
}
function useBuiltin(model: string): void {
  emit('hint', model, '')
  editing[model] = false
}
const id = (model: string, part: string): string => props.controlId(`agents.auto_model_allowlist.${model}.${part}`)
</script>

<template>
  <div :id="controlId('agents.auto_model_allowlist')" tabindex="-1" class="agent-candidates" data-testid="agent-candidates">
    <h4>Models Odin can choose from</h4>
    <p class="settings-help">For each agent, Odin picks one of the ticked models. Models nearer the top are preferred. A model's description tells Odin what it's good for.</p>
    <p class="candidates-state" data-testid="agent-candidates-state">
      <template v-if="usingDefault">Using Odin's default: {{ defaults.length === 1 ? 'one model' : `${defaults.length} models` }}. Untick a model to choose your own.</template>
      <template v-else>{{ chosen.length }} of {{ list.length }} models ticked.</template>
    </p>
    <p v-if="hints === null" class="settings-help">Descriptions can't be edited here until the selection guidance under More options is valid JSON.</p>
    <ul class="candidate-list" aria-label="Models Odin can choose from">
      <li v-for="(item, index) in list" :key="item.model" :class="['candidate', { ticked: item.ticked }]" :data-model="item.model">
        <div class="candidate-head">
          <input :id="id(item.model, 'chosen')" type="checkbox" :checked="item.ticked"
            :disabled="item.ticked ? chosen.length === 1 : Boolean(blocked(item.row))"
            @change="toggle(item.model, ($event.target as HTMLInputElement).checked)" />
          <label :for="id(item.model, 'chosen')"><span v-if="item.ticked" class="candidate-rank">{{ index + 1 }}.</span> {{ label(item.model, item.row) }}</label>
          <span class="candidate-provider">{{ providerNames[modelProvider(item.model)] }}</span>
          <span v-if="item.ticked" class="candidate-order">
            <button class="ghost" :aria-label="`Move ${item.model} up`" :disabled="index === 0" @click="move(item.model, -1)">Move up</button>
            <button class="ghost" :aria-label="`Move ${item.model} down`" :disabled="index === chosen.length - 1" @click="move(item.model, 1)">Move down</button>
          </span>
        </div>
        <p v-if="blocked(item.row)" class="settings-help">Can't run agents: {{ blocked(item.row) }}</p>
        <p v-if="item.ticked && note(item.model)" class="settings-help">{{ note(item.model) }}</p>
        <p v-if="item.ticked && chosen.length === 1" class="settings-help">At least one model stays ticked.</p>
        <p class="candidate-description" :data-testid="`candidate-description-${item.model}`">
          <template v-if="custom(item.model)">{{ custom(item.model) }} <span class="candidate-source">Your description</span></template>
          <template v-else-if="builtin(item.model)">{{ builtin(item.model) }}</template>
          <template v-else>Odin has no description for this model.<template v-if="item.ticked"> Add one so Odin knows which tasks suit it.</template></template>
        </p>
        <div v-if="item.ticked" class="candidate-options">
          <span>
            <label :for="id(item.model, 'reasoning_effort')">Reasoning effort</label>
            <select :id="id(item.model, 'reasoning_effort')" :value="setting(item.model, 'reasoning_effort')" @change="choose(item.model, 'reasoning_effort', ($event.target as HTMLSelectElement).value)">
              <option v-if="setting(item.model, 'reasoning_effort') && setting(item.model, 'reasoning_effort') !== 'auto' && !efforts(item.model)?.includes(setting(item.model, 'reasoning_effort'))" :value="setting(item.model, 'reasoning_effort')" disabled>{{ setting(item.model, 'reasoning_effort') }} (not supported)</option>
              <option value="">Same as agent reasoning effort</option><option value="auto">Automatic</option>
              <option v-for="effort in efforts(item.model) ?? []" :key="effort" :value="effort">{{ effort }}</option>
            </select>
          </span>
          <span v-if="item.row?.capability === 'thinking'">
            <label :for="id(item.model, 'thinking_mode')">Thinking mode</label>
            <select :id="id(item.model, 'thinking_mode')" :value="setting(item.model, 'thinking_mode')" @change="choose(item.model, 'thinking_mode', ($event.target as HTMLSelectElement).value)">
              <option value="">Same as agents</option><option v-for="mode in thinkingModes" :key="mode" :value="mode">{{ mode }}</option>
            </select>
          </span>
          <span v-if="hints !== undefined" class="candidate-description-actions">
            <button class="ghost" :aria-label="`${editing[item.model] ? 'Close' : 'Edit'} the description of ${item.model}`" :aria-expanded="Boolean(editing[item.model])" :aria-controls="id(item.model, 'description')" @click="editing[item.model] = !editing[item.model]">{{ editing[item.model] ? 'Close description' : 'Edit description' }}</button>
            <button v-if="custom(item.model) && builtin(item.model)" class="ghost" :disabled="!hints" :aria-label="`Use Odin's description for ${item.model}`" @click="useBuiltin(item.model)">Use Odin's description</button>
          </span>
        </div>
        <template v-if="item.ticked && hints !== undefined && editing[item.model]">
          <label :for="id(item.model, 'description')" class="sr-only">Description for {{ item.model }}</label>
          <textarea :id="id(item.model, 'description')" rows="3" :disabled="!hints" :value="custom(item.model) ?? builtin(item.model)" placeholder="Which tasks suit this model" @input="describe(item.model, ($event.target as HTMLTextAreaElement).value)" />
        </template>
      </li>
    </ul>
    <button v-if="!usingDefault" class="ghost" data-testid="agent-candidates-reset" @click="update([])">Use Odin's default</button>
  </div>
</template>

<style scoped>
.agent-candidates { padding: 1rem; }
.agent-candidates h4 { margin-top: 0; }
.candidates-state { font-weight: 600; }
.candidate-list { list-style: none; margin: 0; padding: 0; }
.candidate { padding: .75rem 0; border-bottom: 1px solid var(--border); display: grid; gap: .4rem; }
.candidate:not(.ticked) { opacity: .8; }
.candidate-head { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.candidate-head label { font-weight: 600; overflow-wrap: anywhere; }
.candidate-rank { font-variant-numeric: tabular-nums; }
.candidate-provider { font-size: 12px; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 0 .5rem; }
.candidate-order { margin-left: auto; display: flex; gap: .25rem; }
.candidate-description { margin: 0; color: var(--muted); overflow-wrap: anywhere; }
.candidate-source { font-size: 12px; font-style: italic; }
.candidate-options { display: flex; flex-wrap: wrap; gap: .5rem 1rem; align-items: center; }
.candidate-options > span { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
.candidate-description-actions { margin-left: auto; }
.candidate textarea { width: 100%; min-width: 0; }
@media (max-width: 760px) { .candidate-order, .candidate-description-actions { margin-left: 0; } }
</style>
