<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { ToolDetail } from '../../../shared/api'
import type { ToolEntry } from '../store'

const props = defineProps<{ entries: ToolEntry[]; requestId?: string; live?: boolean }>()
const open = ref(Boolean(props.live))

/** Retained output arrives in pages of this many characters. */
const OUTPUT_PAGE = 32_768

interface Expanded {
  loading: boolean
  error: string
  detail: ToolDetail | null
  output: { text: string; next: string | null; loading: boolean; error: string; eof: boolean }
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
  expanded[id] = { loading: true, error: '', detail: null, output: { text: '', next: null, loading: false, error: '', eof: false } }
  const result = await window.odin.toolDetail({ request_id: props.requestId, invocation_id: id })
  const current = expanded[id]
  if (!current) return
  current.loading = false
  if (result.ok) current.detail = result.result
  else current.error = result.error.message
}

async function more(id: string): Promise<void> {
  const current = expanded[id]
  const cursor = current?.output.next ?? current?.detail?.output.cursor
  if (!current || !cursor || current.output.loading) return
  current.output.loading = true
  const result = await window.odin.toolOutput({ cursor, limit: OUTPUT_PAGE })
  current.output.loading = false
  if (!result.ok) {
    current.output.error = result.error.code === 'expired' ? 'Odin no longer keeps this output.' : result.error.message
    return
  }
  current.output.error = ''
  current.output.text += result.result.text
  current.output.next = result.result.next_cursor ?? null
  current.output.eof = result.result.eof
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
    <button class="tools-toggle" :aria-expanded="open" @click="open = !open">
      {{ entries.length }} tool call{{ entries.length === 1 ? '' : 's' }} {{ open ? '▾' : '▸' }}
    </button>
    <ul v-if="open" class="tool-list">
      <li v-for="e in entries" :key="e.invocation_id" :class="['tool', e.outcome ?? 'running']">
        <button
          class="tool-row"
          :aria-expanded="Boolean(expanded[e.invocation_id])"
          :disabled="!requestId"
          :title="requestId ? 'Show arguments and output' : undefined"
          @click="toggle(e)"
        >
          <span class="mark" :title="e.outcome ?? 'running'">{{ mark(e) }}</span>
          <code class="name">{{ e.tool }}</code>
          <span v-if="e.target" class="target">{{ e.target }}</span>
          <span class="summary">{{ e.summary }}</span>
          <span v-if="e.exit_code !== undefined" class="exit">exit {{ e.exit_code }}</span>
          <span v-if="e.duration_ms !== undefined" class="dur">{{ (e.duration_ms / 1000).toFixed(1) }}s</span>
        </button>
        <div v-if="expanded[e.invocation_id]" class="tool-detail">
          <template v-for="x in [expanded[e.invocation_id]!]" :key="e.invocation_id">
            <p v-if="x.loading" class="tool-note">Loading…</p>
            <p v-else-if="x.error" class="warn">{{ x.error }}</p>
            <template v-else-if="x.detail">
              <h4>Arguments <span class="tool-note">secrets hidden</span></h4>
              <pre>{{ json(x.detail.arguments) }}</pre>
              <template v-for="(preview, index) in x.detail.previews" :key="index">
                <h4>
                  {{ preview.label }}
                  <span v-if="preview.truncated" class="tool-note">preview, cut short</span>
                </h4>
                <pre>{{ preview.text }}</pre>
              </template>
              <div v-if="x.detail.output.cursor" class="tool-output">
                <h4 v-if="x.output.text">Full output</h4>
                <pre v-if="x.output.text">{{ x.output.text }}</pre>
                <div class="tool-output-line">
                  <button v-if="!x.output.eof" class="ghost" :disabled="x.output.loading" @click="more(e.invocation_id)">
                    {{ x.output.text ? 'Load more' : 'Show full output' }}
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
