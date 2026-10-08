<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ConfigField } from '../../../../shared/api'
import { fromInput, toInput } from '../../settings-form'
import { settingsControlId } from '../../settings-accessibility'

// Shape selection is presentation. Values, constraints, choices and writes stay metadata-backed.
const props = defineProps<{ field: ConfigField; value: string; fields: ConfigField[]; dirty: boolean; kind: 'budgets' | 'profiles' | 'host-policy' }>()
const emit = defineEmits<{ input: [value: string]; invalid: [message: string] }>()
const newKey = ref('')
const localErrors = ref<Record<string, string>>({})
const draftValue = ref(props.value)
watch(() => props.value, (value) => { draftValue.value = value })
watch(() => props.dirty, (dirty) => { if (!dirty) { localErrors.value = {}; emit('invalid', '') } })
const labels: Record<string, string> = {
  total_window_tokens: 'Total context tokens', max_output_tokens: 'Response reservation tokens',
  selection_hint: 'Selection guidance', supports_thinking_mode: 'Supports thinking',
  supports_reasoning: 'Supports reasoning', supported_efforts: 'Supported reasoning levels'
}
const entries = computed<Record<string, unknown>>(() => {
  try { const value = JSON.parse(draftValue.value); return value && typeof value === 'object' && !Array.isArray(value) ? value : {} }
  catch { return {} }
})
const members = computed(() => Object.entries(labels).flatMap(([name, label]) => {
  const facts = props.field.record_members?.find((member) => member.path === `${props.field.path}.${name}` && member.sensitivity === 'public')
  // The parent supplies write authority; member facts supply editing shape only.
  const metadata = facts ? { ...props.field, ...facts, desired: facts.default } : props.fields.find((field) => field.path.startsWith(`${props.field.path}.`) && field.path.endsWith(`.${name}`) && field.sensitivity === 'public')
  return metadata ? [{ name, label, metadata }] : []
}))
function id(key: string, member = 'value'): string { return settingsControlId('curated-record', `${props.field.path}.${key}.${member}`) }
function publish(value: Record<string, unknown>): void { draftValue.value = JSON.stringify(value, null, 2); emit('input', draftValue.value) }
function report(): void { emit('invalid', Object.values(localErrors.value).find(Boolean) ?? '') }
function change(key: string, raw: string | boolean, member?: { name: string; metadata: ConfigField }): void {
  const errorKey = `${key}.${member?.name ?? 'value'}`
  let value: unknown = raw
  if (member) {
    const parsed = fromInput(member.metadata, raw)
    localErrors.value[errorKey] = parsed.ok ? '' : parsed.error
    value = parsed.ok ? parsed.value : raw
  } else if (props.kind === 'budgets') {
    // Model-specific map bounds are validated by the save owner, not copied here.
    value = typeof raw === 'string' && raw.trim() && Number.isFinite(Number(raw)) ? Number(raw) : raw
    localErrors.value[errorKey] = typeof value === 'number' && Number.isInteger(value) ? '' : 'Enter a whole number.'
  }
  const copy = { ...entries.value }
  copy[key] = member ? { ...(copy[key] as object ?? {}), [member.name]: value } : value
  publish(copy)
  report()
}
function add(): void {
  const key = newKey.value.trim()
  if (!key || Object.hasOwn(entries.value, key) || ['__proto__', 'constructor', 'prototype'].includes(key)) {
    emit('invalid', 'Enter a new, unique name.')
    return
  }
  publish({ ...entries.value, [key]: props.kind === 'profiles' ? {} : '' })
  newKey.value = ''
  if (props.kind === 'budgets') localErrors.value[`${key}.value`] = 'Enter a whole number.'
  if (props.kind === 'profiles') {
    for (const member of members.value) {
      if (!member.metadata.nullable && ['integer', 'number'].includes(member.metadata.type)) localErrors.value[`${key}.${member.name}`] = 'Enter a number.'
    }
  }
  report()
}
function remove(key: string): void {
  const copy = { ...entries.value }; delete copy[key]; publish(copy)
  for (const name of Object.keys(localErrors.value)) if (name.startsWith(`${key}.`)) delete localErrors.value[name]
  report()
}
function memberValue(value: unknown, name: string): unknown { return value && typeof value === 'object' ? (value as Record<string, unknown>)[name] : undefined }
function memberInput(value: unknown, metadata: ConfigField): string | boolean { return toInput({ ...metadata, desired: value }) }
</script>

<template>
  <div class="settings-structured">
    <p v-if="!Object.keys(entries).length" class="settings-help">No entries yet. Add a name below.</p>
    <fieldset v-for="(value, key) in entries" :key="key">
      <legend>{{ key }}</legend>
      <template v-if="kind === 'profiles'">
        <div v-for="member in members" :key="member.name" class="settings-record-member">
          <label :for="id(key, member.name)">{{ member.label }}</label>
          <input v-if="member.metadata.type === 'boolean'" :id="id(key, member.name)" type="checkbox" :checked="memberValue(value, member.name) === true" @change="change(key, ($event.target as HTMLInputElement).checked, member)">
          <select v-else-if="member.metadata.enum" :id="id(key, member.name)" :value="memberInput(memberValue(value, member.name), member.metadata)" @change="change(key, ($event.target as HTMLSelectElement).value, member)">
            <option v-if="member.metadata.nullable" value="">Not specified</option>
            <option v-for="option in member.metadata.enum" :key="option" :value="option">{{ option }}</option>
          </select>
          <textarea v-else-if="member.metadata.type === 'array'" :id="id(key, member.name)" :value="String(memberInput(memberValue(value, member.name), member.metadata))" rows="2" @input="change(key, ($event.target as HTMLTextAreaElement).value, member)" />
          <input v-else :id="id(key, member.name)" :type="['integer', 'number'].includes(member.metadata.type) ? 'number' : 'text'" :min="member.metadata.constraints.minimum" :max="member.metadata.constraints.maximum" :value="memberInput(memberValue(value, member.name), member.metadata)" @input="change(key, ($event.target as HTMLInputElement).value, member)">
          <p v-if="localErrors[`${key}.${member.name}`]" role="status">{{ localErrors[`${key}.${member.name}`] }}</p>
        </div>
        <p v-if="!members.length" class="settings-help">Details are unavailable. Refresh settings before editing a profile.</p>
      </template>
      <template v-else>
        <label :for="id(key)">{{ kind === 'budgets' ? 'Context tokens' : 'Command safety policy' }}</label>
        <input :id="id(key)" :type="kind === 'budgets' ? 'number' : 'text'" :step="kind === 'budgets' ? 1 : undefined" :value="value" @input="change(key, ($event.target as HTMLInputElement).value)">
        <p v-if="localErrors[`${key}.value`]" role="status">{{ localErrors[`${key}.value`] }}</p>
      </template>
      <button type="button" data-settings-draft-action="edit" :aria-label="`Remove ${key}`" @click="remove(key)">Remove entry</button>
    </fieldset>
    <label :for="id('new')">{{ kind === 'host-policy' ? 'Host name' : 'Model name' }}</label>
    <input :id="id('new')" v-model="newKey" type="text">
    <button type="button" data-settings-draft-action="edit" :disabled="kind === 'profiles' && !members.length" @click="add">Add entry</button>
  </div>
</template>

<style scoped>
.settings-structured { width: 100%; }
fieldset { border: 1px solid var(--line); border-radius: 6px; margin: 0 0 12px; padding: 12px; }
legend { overflow-wrap: anywhere; }
.settings-record-member { display: grid; grid-template-columns: minmax(150px, 1fr) minmax(120px, 1fr); gap: 8px; align-items: center; margin-bottom: 10px; }
input, select, textarea { max-width: 100%; }
button { background: var(--bg); color: var(--fg); border: 1px solid var(--line); border-radius: 7px; padding: 8px 10px; }
@media (max-width: 700px) { .settings-record-member { grid-template-columns: 1fr; } }
</style>
