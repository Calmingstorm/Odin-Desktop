<script setup lang="ts">
import SettingsSection from './settings/SettingsSection.vue'
import SettingsRow from './settings/SettingsRow.vue'
import { computed, onBeforeUnmount, reactive } from 'vue'
import type { Result } from '../../../shared/api'
import { isUnavailable, settingsUnavailableText as unavailableText } from '../capability'

type ReadKind = 'diffs' | 'failures' | 'stats'
type TailKind = 'audit' | 'logs'
const RETAIN = 200
const reads = reactive(Object.fromEntries(['diffs', 'failures', 'stats'].map((key) => [key, {
  loading: false, loaded: false, error: '', unavailable: false, result: null as unknown
}])) as Record<ReadKind, { loading: boolean; loaded: boolean; error: string; unavailable: boolean; result: unknown }>)
const filters = reactive({ diffs: '', window: 24 })
const tails = reactive(Object.fromEntries(['audit', 'logs'].map((key) => [key, {
  loading: false, loaded: false, error: '', unavailable: false, following: false,
  lines: [] as string[], cursor: undefined as string | undefined, metadata: {} as Record<string, unknown>, discarded: 0
}])) as Record<TailKind, {
  loading: boolean; loaded: boolean; error: string; unavailable: boolean; following: boolean;
  lines: string[]; cursor?: string; metadata: Record<string, unknown>; discarded: number
}>)
const names = { diffs: 'Audit diffs', failures: 'Audit failures', stats: 'Log statistics', audit: 'Audit tail', logs: 'Log tail' }
const descriptions = {
  diffs: 'File changes Odin recorded, newest first. Leave the tool empty for all.',
  failures: 'Tool calls that failed within the window.',
  stats: 'How many entries each log holds, by level.',
  audit: 'The newest lines of the audit record.',
  logs: "The newest lines of Odin's log."
}
const tailBusy = computed(() => tails.audit.loading || tails.logs.loading)
let alive = true
let timer: ReturnType<typeof setTimeout> | undefined
const json = (value: unknown): string => JSON.stringify(value, null, 2)

function stop(): void {
  if (timer !== undefined) clearTimeout(timer)
  timer = undefined
  tails.audit.following = false
  tails.logs.following = false
}
onBeforeUnmount(() => { alive = false; stop() })

async function read(kind: ReadKind): Promise<void> {
  const item = reads[kind]
  if (!alive || item.loading || item.unavailable) return
  item.loading = true
  item.error = ''
  try {
    const tool = filters.diffs.trim()
    const input = { limit: 50, ...(tool ? { tool } : {}) }
    const answer: Result<unknown> = kind === 'diffs' ? await window.odin.auditDiffs(input)
      : kind === 'failures' ? await window.odin.auditFailures({ window: Math.max(1, Math.min(336, Number(filters.window) || 24)) }) : await window.odin.logsStats({})
    if (!alive) return
    if (!answer.ok) {
      item.unavailable = isUnavailable(answer.error)
      item.error = answer.error.message
    } else {
      item.result = answer.result
      item.loaded = true
    }
  } catch (error) {
    if (alive) item.error = error instanceof Error ? error.message : String(error)
  } finally {
    if (alive) item.loading = false
  }
}

/** A single completion-based timer and shared busy gate serialize both named tail reads. */
async function readTail(kind: TailKind, latest = false): Promise<void> {
  const item = tails[kind]
  if (!alive || tailBusy.value || item.unavailable) return
  // A one-shot latest read cannot silently strand the other stream's follow timer.
  if (latest) stop()
  if (timer !== undefined) clearTimeout(timer)
  timer = undefined
  item.loading = true
  item.error = ''
  try {
    const input = { lines: RETAIN, ...(!latest && item.cursor !== undefined ? { cursor: item.cursor } : {}) }
    const answer: Result<unknown> = kind === 'audit' ? await window.odin.auditTail(input) : await window.odin.logsTail(input)
    if (!alive) return
    if (!answer.ok) {
      item.unavailable = isUnavailable(answer.error)
      item.error = answer.error.message
      stop()
      return
    }
    const page = answer.result as Record<string, unknown> | null
    if (!page || !Array.isArray(page.lines) || !page.lines.every((line) => typeof line === 'string') || typeof page.cursor !== 'string') {
      item.error = 'Unrecognized tail result. Follow stopped; nothing was retried.'
      stop()
      return
    }
    const { lines, ...metadata } = page
    item.metadata = metadata
    if (typeof page.availability === 'string' && page.availability !== 'available') {
      item.error = `Source availability: ${page.availability}. No current tail data.`
      stop()
      return
    }
    const reset = latest || page.reset === true
    const combined = [...(reset ? [] : item.lines), ...lines as string[]]
    item.discarded = (reset ? 0 : item.discarded) + Math.max(0, combined.length - RETAIN)
    item.lines = combined.slice(-RETAIN)
    item.cursor = page.cursor
    item.loaded = true
  } catch (error) {
    if (alive) {
      item.error = error instanceof Error ? error.message : String(error)
      stop()
    }
  } finally {
    if (alive) {
      item.loading = false
      if (item.following) timer = setTimeout(() => { void readTail(kind) }, 1000)
    }
  }
}

function follow(kind: TailKind): void {
  if (tailBusy.value || tails[kind].unavailable) return
  stop()
  tails[kind].following = true
  void readTail(kind)
}
</script>

<template>
  <SettingsSection title="Records extras" aria-label="Records extras" description="Shows up to 200 recent lines; Follow reads one log at a time.">
    <section v-for="kind in (['diffs', 'failures', 'stats'] as const)" :key="kind" :aria-label="names[kind]">
      <SettingsRow :label="names[kind]" :description="descriptions[kind]">
        <p v-if="reads[kind].unavailable" class="manage-desc" role="status">{{ unavailableText(names[kind]) }}</p>
        <template v-else>
          <label v-if="kind === 'diffs'" class="control-field">Tool
            <input v-model="filters.diffs" placeholder="Any tool" @keydown.enter="read(kind)" />
          </label>
          <template v-if="kind === 'failures'">
            <label class="control-field narrow">Window, in hours
              <input v-model.number="filters.window" type="number" min="1" max="336" @keydown.enter="read(kind)" />
            </label>
          </template>
          <button class="ghost" :disabled="reads[kind].loading" @click="read(kind)">Read {{ names[kind].toLowerCase() }}</button>
        </template>
        <template #note>
          <template v-if="!reads[kind].unavailable">
            <p class="manage-desc" role="status">{{ reads[kind].loading ? 'Reading…' : reads[kind].loaded ? 'Last successful read shown below.' : 'Not read yet.' }}</p>
            <p v-if="reads[kind].error" class="warn" role="alert">Couldn't read: {{ reads[kind].error }} No automatic retry.</p>
          </template>
          <pre v-if="reads[kind].loaded" class="manage-json">{{ json(reads[kind].result) }}</pre>
        </template>
      </SettingsRow>
    </section>
    <section v-for="kind in (['audit', 'logs'] as const)" :key="kind" :aria-label="names[kind]">
      <SettingsRow :label="names[kind]" :description="descriptions[kind]">
        <p v-if="tails[kind].unavailable" class="manage-desc" role="status">{{ unavailableText(names[kind]) }} Follow stopped.</p>
        <template v-else>
          <button class="ghost" :disabled="tailBusy" @click="readTail(kind, true)">Read latest {{ names[kind].toLowerCase() }}</button>
          <button class="ghost" :disabled="tailBusy || tails[kind].following" :aria-pressed="tails[kind].following" @click="follow(kind)">Follow {{ names[kind].toLowerCase() }}</button>
          <button class="ghost" :disabled="!tails[kind].following" @click="stop">Stop {{ names[kind].toLowerCase() }}</button>
        </template>
        <template #note>
          <p class="manage-desc" role="status">{{ tails[kind].following ? 'Following.' : 'Follow stopped.' }} {{ tails[kind].loading ? 'Reading…' : tails[kind].loaded ? `${tails[kind].lines.length} retained lines.` : 'Not read yet.' }}</p>
          <p v-if="tails[kind].error && !tails[kind].unavailable" class="warn" role="alert">Couldn't read: {{ tails[kind].error }} Follow stopped. No automatic retry.</p>
          <template v-if="tails[kind].loaded">
            <p v-if="tails[kind].discarded" class="manage-desc">{{ tails[kind].discarded }} older lines are no longer shown here. File resets and truncation are listed below.</p>
            <pre class="manage-json" :aria-label="`${names[kind]} retained lines`">{{ tails[kind].lines.join('\n') }}</pre>
          </template>
          <details v-if="Object.keys(tails[kind].metadata).length"><summary>{{ names[kind] }} file details</summary><pre class="manage-json">{{ json(tails[kind].metadata) }}</pre></details>
        </template>
      </SettingsRow>
    </section>
  </SettingsSection>
</template>
