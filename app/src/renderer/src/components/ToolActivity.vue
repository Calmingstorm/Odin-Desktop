<script setup lang="ts">
import { reactive, ref, useId } from 'vue'
import type { ToolDetail } from '../../../shared/api'
import type { ToolEntry } from '../store'
import { appendPage, type OutputView } from '../tool-output'
import FileCard from './FileCard.vue'

const props = defineProps<{ entries: ToolEntry[]; requestId?: string; live?: boolean }>()
const open = ref(Boolean(props.live))
const uid = useId()
const notice = ref('')

/** Retained output arrives in pages of this many characters. */
const OUTPUT_PAGE = 32_768

interface Expanded {
  loading: boolean
  error: string
  detail: ToolDetail | null
  output: OutputView & { loading: boolean; error: string }
}


/** Details of the tool calls the user opened, by invocation id. Fetched on demand; nothing is ever run again. */
const expanded = reactive<Record<string, Expanded | undefined>>({})

function mark(entry: ToolEntry): string {
  if (entry.outcome === 'success') return '✓'
  if (entry.outcome === 'failure') return '✕'
  if (entry.outcome === 'unknown') return '?'
  return '…'
}

async function toggle(entry: ToolEntry): Promise<void> {
  const id = entry.invocation_id
  if (expanded[id]) {
    delete expanded[id]
    return
  }
  if (!props.requestId) return
  expanded[id] = { loading: true, error: '', detail: null, output: { text: '', files: [], next: null, loading: false, error: '', eof: false } }
  const pending = expanded[id]
  const result = await window.odin.toolDetail({ request_id: props.requestId, invocation_id: id })
  const current = expanded[id]
  if (!current || current !== pending) return
  current.loading = false
  if (result.ok) current.detail = result.result
  else current.error = result.error.message
  notice.value = result.ok ? `Details loaded for ${entry.tool}.` : `Couldn't load details for ${entry.tool}.`
}

async function more(id: string, tool: string): Promise<void> {
  const current = expanded[id]
  const cursor = current?.output.next ?? current?.detail?.output.cursor
  if (!current || !cursor || current.output.loading || current.output.eof) return
  current.output.loading = true
  const result = await window.odin.toolOutput({ cursor, limit: OUTPUT_PAGE })
  if (expanded[id] !== current) return
  current.output.loading = false
  if (!result.ok) {
    current.output.error = result.error.code === 'expired' ? 'Odin no longer keeps this output.' : result.error.message
    notice.value = `Couldn't load output for ${tool}.`
    return
  }
  current.output.error = ''
  appendPage(current.output, tool, result.result)
  notice.value = current.output.eof ? `All output loaded for ${tool}.` : `Output page loaded for ${tool}.`
}

function json(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? String(value)
}

function until(iso: string): string {
  return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div v-if="entries.length" class="tools">
    <p class="tool-announcement" role="status" aria-atomic="true">{{ notice }}</p>
    <button class="tools-toggle" :aria-expanded="open" :aria-controls="`${uid}-calls`" :aria-label="`${entries.length} tool call${entries.length === 1 ? '' : 's'}: Tool activity`" @click="open = !open">
      {{ entries.length }} tool call{{ entries.length === 1 ? '' : 's' }} <span aria-hidden="true">{{ open ? '▾' : '▸' }}</span>
    </button>
    <ul v-if="open" :id="`${uid}-calls`" class="tool-list">
      <li v-for="e in entries" :key="e.invocation_id" :class="['tool', e.outcome ?? 'running']">
        <button
          class="tool-row"
          :aria-expanded="Boolean(expanded[e.invocation_id])"
          :aria-controls="`${uid}-${e.invocation_id}`"
          :disabled="!requestId"
          :title="requestId ? 'Show arguments and output' : undefined"
          @click="toggle(e)"
        >
          <span class="mark" aria-hidden="true">{{ mark(e) }}</span>
          <span class="sr-only">{{ e.outcome ?? 'running' }}. Show arguments and output. </span>
          <code class="name">{{ e.tool }}</code>
          <span v-if="e.target" class="target">{{ e.target }}</span>
          <span v-if="e.summary && e.summary.trim() !== e.tool" class="summary">{{ e.summary }}</span>
          <span v-if="e.exit_code !== undefined" class="exit">exit {{ e.exit_code }}</span>
          <span v-if="e.duration_ms !== undefined" class="dur">{{ (e.duration_ms / 1000).toFixed(1) }}s</span>
        </button>
        <div v-if="expanded[e.invocation_id]" :id="`${uid}-${e.invocation_id}`" class="tool-detail">
          <template v-for="x in [expanded[e.invocation_id]!]" :key="e.invocation_id">
            <p v-if="x.loading" class="tool-note">Loading…</p>
            <p v-else-if="x.error" class="warn">{{ x.error }}</p>
            <template v-else-if="x.detail">
              <h2>Arguments <span class="tool-note">secrets hidden</span></h2>
              <pre tabindex="0" role="region" :aria-label="`Arguments for ${e.tool}`">{{ json(x.detail.arguments) }}</pre>
              <template v-for="(preview, index) in x.detail.previews" :key="index">
                <h2>
                  {{ preview.label }}
                  <span v-if="preview.truncated" class="tool-note">preview, cut short</span>
                </h2>
                <pre tabindex="0" role="region" :aria-label="`${preview.label} for ${e.tool}`">{{ preview.text }}</pre>
              </template>
              <div v-if="x.detail.output.cursor" class="tool-output">
                <h2 v-if="x.output.text || x.output.files.length">Full output</h2>
                <pre v-if="x.output.text" tabindex="0" role="region" :aria-label="`Retained output for ${e.tool}`">{{ x.output.text }}</pre>
                <FileCard v-for="f in x.output.files" :key="f.ref" :artifact="f" />
                <div class="tool-output-line">
                  <button class="ghost" :aria-label="`${x.output.loading ? 'Loading…' : x.output.eof ? 'All output loaded' : x.output.text || x.output.files.length ? 'Load more' : 'Show full output'} for ${e.tool}`" :aria-disabled="x.output.loading || x.output.eof" @click="!x.output.eof && more(e.invocation_id, e.tool)">
                    {{ x.output.loading ? 'Loading…' : x.output.eof ? 'All output loaded' : x.output.text || x.output.files.length ? 'Load more' : 'Show full output' }}
                  </button>
                  <span v-if="x.detail.output.expires_at" class="tool-note">Kept until {{ until(x.detail.output.expires_at) }}</span>
                </div>
                <p v-if="x.output.error" class="warn">{{ x.output.error }}</p>
              </div>
            </template>
          </template>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.tools { position: relative; }
.tool-announcement { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
button:focus-visible { outline: 2px solid var(--accent, #91baff); outline-offset: 3px; }
button[aria-disabled="true"] { opacity: .65; }
</style>
