<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import type { BuiltinTool } from '../../../../shared/api'
import { loadTools, management, saveTimeouts, setToolEnabled } from '../../stores/management'
import { unavailableText } from '../../capability'

const filter = ref('')
const expanded = reactive<Record<string, boolean | undefined>>({})
const STATES: Record<BuiltinTool['state'], string> = {
  available: 'Available',
  disabled: 'Off',
  global_disabled: 'Tools are off',
  unavailable: 'Hidden: not configured here'
}

const tools = computed(() => {
  const words = filter.value.trim().toLowerCase()
  return (management.tools?.tools ?? []).filter((t) => !words || `${t.name} ${t.description}`.toLowerCase().includes(words))
})

// Timeouts: the default, and one line per tool that has its own.
const defaultTimeout = ref<string>('')
const overrides = ref<Array<{ name: string; seconds: string }>>([])
const timeoutError = ref('')
const timeoutErrorField = ref<'default' | number | null>(null)
watch([defaultTimeout, overrides], () => {
  timeoutError.value = ''
  timeoutErrorField.value = null
}, { deep: true })

function editTimeouts(): void {
  defaultTimeout.value = String(management.timeouts?.default_timeout ?? '')
  overrides.value = Object.entries(management.timeouts?.overrides ?? {}).map(([name, seconds]) => ({ name, seconds: String(seconds) }))
}

async function save(): Promise<void> {
  timeoutError.value = ''
  const draft = JSON.stringify([defaultTimeout.value, overrides.value])
  timeoutErrorField.value = null
  const parsed: Record<string, number> = {}
  for (const [index, row] of overrides.value.entries()) {
    if (!row.name.trim()) continue
    const seconds = Number(row.seconds)
    if (!Number.isInteger(seconds) || seconds <= 0) {
      timeoutError.value = `${row.name}: a timeout is a whole number of seconds above zero.`
      timeoutErrorField.value = index
      return
    }
    parsed[row.name.trim()] = seconds
  }
  const fallback = Number(defaultTimeout.value)
  if (!Number.isInteger(fallback) || fallback <= 0) {
    timeoutError.value = 'The default is a whole number of seconds above zero.'
    timeoutErrorField.value = 'default'
    return
  }
  if (await saveTimeouts({ default_timeout: fallback, overrides: parsed }) && JSON.stringify([defaultTimeout.value, overrides.value]) === draft) editTimeouts()
}

onMounted(async () => {
  await loadTools()
  editTimeouts()
})
</script>

<template>
  <section class="panel" aria-label="Built-in tools">
    <header class="panel-head">
      <h3>Built-in tools</h3>
      <span v-if="!management.unavailable.tools && management.tools" class="panel-hint">
        {{ management.tools.tools.length }} tools, {{ management.tools.disabled_count }} switched off. A tool that is off
        is not offered to Odin at all.
      </span>
      <label v-if="!management.unavailable.tools">Filter tools <input v-model="filter" class="panel-filter" type="search" placeholder="Filter" /></label>
    </header>
    <p v-if="management.unavailable.tools" class="capability-unavailable" role="status">{{ unavailableText('Tool management') }}</p>
    <p v-else-if="management.errors.tools" class="warn">{{ management.errors.tools }}</p>
    <ul v-if="!management.unavailable.tools" class="manage-list">
      <li v-for="tool in tools" :key="tool.name" :class="['manage-row', tool.state]">
        <div class="manage-line">
          <label class="toggle-inline">
            <input
              type="checkbox"
              :checked="tool.enabled"
              :disabled="management.busy[`tool:${tool.name}`]"
              :aria-label="`${tool.name} on or off`"
              @change="setToolEnabled(tool.name, ($event.target as HTMLInputElement).checked)"
            />
            <code class="manage-name">{{ tool.name }}</code>
          </label>
          <span v-if="tool.is_core" class="tag">core</span>
          <span :class="['state-chip', tool.state]">{{ STATES[tool.state] }}</span>
          <button class="ghost manage-more" :aria-label="`${expanded[tool.name] ? 'Hide parameters' : 'Parameters'} for ${tool.name}`" :aria-expanded="!!expanded[tool.name]" :aria-controls="`tool-parameters-${encodeURIComponent(tool.name)}`" @click="expanded[tool.name] = !expanded[tool.name]">
            {{ expanded[tool.name] ? 'Hide parameters' : 'Parameters' }}
          </button>
        </div>
        <p class="manage-desc">{{ tool.description }}</p>
        <p class="panel-hint">Cost: {{ tool.cost ?? 'not reported' }}. Risk: {{ tool.risk ?? 'not reported' }}.</p>
        <div :id="`tool-parameters-${encodeURIComponent(tool.name)}`"><pre v-if="expanded[tool.name]" class="manage-json">{{ JSON.stringify(tool.input_schema, null, 2) }}</pre></div>
        <p v-if="management.notes[`tool:${tool.name}`]" class="manage-note" role="status">{{ management.notes[`tool:${tool.name}`] }}</p>
      </li>
    </ul>
  </section>

  <section class="panel" aria-label="Tool timeouts">
    <header class="panel-head">
      <h3>Timeouts</h3>
      <span class="panel-hint">How long a call may run. A change applies to new calls; calls already running keep theirs.</span>
    </header>
    <p v-if="management.unavailable.timeouts" class="capability-unavailable" role="status">{{ unavailableText('Tool timeout management') }}</p>
    <p v-else-if="management.errors.timeouts" class="warn">{{ management.errors.timeouts }}</p>
    <template v-if="!management.unavailable.timeouts">
    <label class="field-input">Default, in seconds <input v-model="defaultTimeout" type="number" min="1" :aria-invalid="timeoutErrorField === 'default' || undefined" :aria-describedby="timeoutErrorField === 'default' ? 'tool-timeout-error' : undefined" /></label>
    <div v-for="(row, index) in overrides" :key="index" class="field-input">
      <label>Tool {{ index + 1 }} <input v-model="row.name" list="tool-names" placeholder="Tool" /></label>
      <label>Seconds for tool {{ index + 1 }} <input v-model="row.seconds" type="number" min="1" placeholder="Seconds" :aria-invalid="timeoutErrorField === index || undefined" :aria-describedby="timeoutErrorField === index ? 'tool-timeout-error' : undefined" /></label>
      <button class="ghost" :aria-label="`Remove timeout for ${row.name || `tool ${index + 1}`}`" @click="overrides.splice(index, 1)">Remove</button>
    </div>
    <datalist id="tool-names">
      <option v-for="tool in management.tools?.tools ?? []" :key="tool.name" :value="tool.name" />
    </datalist>
    <div class="panel-actions">
      <button class="ghost" @click="overrides.push({ name: '', seconds: '' })">Add a tool's own timeout</button>
      <button class="ghost" :disabled="management.busy.timeouts" @click="save">Save timeouts</button>
    </div>
    <p v-if="timeoutError" id="tool-timeout-error" class="warn" role="alert">{{ timeoutError }}</p>
    <p v-else-if="management.notes.timeouts" class="manage-note" role="status">{{ management.notes.timeouts }}</p>
    </template>
  </section>
</template>
