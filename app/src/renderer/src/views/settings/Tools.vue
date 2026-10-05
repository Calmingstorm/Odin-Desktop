<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
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

function editTimeouts(): void {
  defaultTimeout.value = String(management.timeouts?.default_timeout ?? '')
  overrides.value = Object.entries(management.timeouts?.overrides ?? {}).map(([name, seconds]) => ({ name, seconds: String(seconds) }))
}

async function save(): Promise<void> {
  timeoutError.value = ''
  const draft = JSON.stringify([defaultTimeout.value, overrides.value])
  const parsed: Record<string, number> = {}
  for (const row of overrides.value) {
    if (!row.name.trim()) continue
    const seconds = Number(row.seconds)
    if (!Number.isInteger(seconds) || seconds <= 0) {
      timeoutError.value = `${row.name}: a timeout is a whole number of seconds above zero.`
      return
    }
    parsed[row.name.trim()] = seconds
  }
  const fallback = Number(defaultTimeout.value)
  if (!Number.isInteger(fallback) || fallback <= 0) {
    timeoutError.value = 'The default is a whole number of seconds above zero.'
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
      <span v-if="!management.unavailable.tools" class="panel-hint">
        {{ management.tools?.tools.length ?? 0 }} tools, {{ management.tools?.disabled_count ?? 0 }} switched off. A tool that is off
        is not offered to Odin at all.
      </span>
      <input v-if="!management.unavailable.tools" v-model="filter" class="panel-filter" type="search" placeholder="Filter" aria-label="Filter tools" />
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
          </label>
          <code class="manage-name">{{ tool.name }}</code>
          <span v-if="tool.is_core" class="tag">core</span>
          <span :class="['state-chip', tool.state]">{{ STATES[tool.state] }}</span>
          <button class="ghost manage-more" @click="expanded[tool.name] = !expanded[tool.name]">
            {{ expanded[tool.name] ? 'Hide parameters' : 'Parameters' }}
          </button>
        </div>
        <p class="manage-desc">{{ tool.description }}</p>
        <pre v-if="expanded[tool.name]" class="manage-json">{{ JSON.stringify(tool.input_schema, null, 2) }}</pre>
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
    <label class="field-input">Default, in seconds <input v-model="defaultTimeout" type="number" min="1" /></label>
    <div v-for="(row, index) in overrides" :key="index" class="field-input">
      <input v-model="row.name" list="tool-names" placeholder="Tool" aria-label="Tool" />
      <input v-model="row.seconds" type="number" min="1" placeholder="Seconds" aria-label="Seconds" />
      <button class="ghost" @click="overrides.splice(index, 1)">Remove</button>
    </div>
    <datalist id="tool-names">
      <option v-for="tool in management.tools?.tools ?? []" :key="tool.name" :value="tool.name" />
    </datalist>
    <div class="panel-actions">
      <button class="ghost" @click="overrides.push({ name: '', seconds: '' })">Add a tool's own timeout</button>
      <button class="ghost" :disabled="management.busy.timeouts" @click="save">Save timeouts</button>
    </div>
    <p v-if="timeoutError" class="warn">{{ timeoutError }}</p>
    <p v-else-if="management.notes.timeouts" class="manage-note" role="status">{{ management.notes.timeouts }}</p>
    </template>
  </section>
</template>
