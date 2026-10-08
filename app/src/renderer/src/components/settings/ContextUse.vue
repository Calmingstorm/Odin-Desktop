<script setup lang="ts">
import { computed } from 'vue'
import type { ConfigField } from '../../../../shared/api'
import { editableHere, FieldDrafts, isSecret } from '../../settings-form'
import { settingsControlId } from '../../settings-accessibility'
import { resetField, saveField, settings } from '../../stores/settings'
import SettingsRow from './SettingsRow.vue'

const props = defineProps<{ field: ConfigField }>()
const field = computed(() => settings.meta?.fields.find((item) => item.path === props.field.path) ?? props.field)
const form = new FieldDrafts({ save: saveField, reset: resetField, latest: (path) => settings.meta?.fields.find((item) => item.path === path) })
const id = computed(() => settingsControlId('curated', field.value.path))
const editable = computed(() => !isSecret(field.value) && ['integer', 'number'].includes(field.value.type) && editableHere(field.value))
const dirty = computed(() => form.changed(field.value))
const busy = computed(() => settings.fields[field.value.path]?.status === 'saving')
const error = computed(() => form.errors[field.value.path] || (settings.fields[field.value.path]?.status === 'error' ? settings.fields[field.value.path]?.message : ''))
const range = computed(() => {
  const { minimum, maximum } = field.value.constraints
  if (minimum !== undefined && maximum !== undefined) return `${minimum}% to ${maximum}%`
  if (minimum !== undefined) return `At least ${minimum}%`
  if (maximum !== undefined) return `At most ${maximum}%`
  return 'Valid range unavailable'
})
function edit(raw: string): void { if (editable.value) form.edit(field.value, raw) }
async function save(): Promise<void> { if (editable.value) await form.save(field.value) }
function enter(event: KeyboardEvent): void { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); void save() } }
function blur(event: FocusEvent): void { if (!(event.relatedTarget as HTMLElement | null)?.dataset?.settingsDraftAction) void save() }
</script>

<template>
  <SettingsRow label="Context use" :description="`Share of model context used for conversations. ${range}.`" :control-id="id">
    <span class="context-percent">
      <input :id="id" type="number" :value="form.current(field)" :min="field.constraints.minimum" :max="field.constraints.maximum" :step="field.type === 'integer' ? 1 : 'any'" :disabled="!editable" :aria-describedby="`${id}-description`" :aria-invalid="Boolean(error) || undefined" @input="edit(($event.target as HTMLInputElement).value)" @keydown="enter" @blur="blur" />
      <span aria-hidden="true">%</span>
    </span>
    <template #note>
      <div v-if="dirty" class="settings-editor-actions context-actions">
        <span>Unsaved changes</span>
        <button type="button" data-settings-draft-action="save" :disabled="busy || !editable" @click="save">Save</button>
        <button type="button" data-settings-draft-action="cancel" class="ghost" @click="form.cancel(field.path)">Cancel</button>
      </div>
      <p v-if="error" role="status" class="warn">{{ error }}</p>
      <p v-else-if="busy" role="status">Saving…</p>
      <p v-else-if="settings.fields[field.path]?.status === 'saved'" role="status">Saved.</p>
      <p v-if="!editable" class="settings-help">Editing is unavailable for this setting.</p>
      <p v-if="['invalid', 'drift'].includes(field.apply_state)" class="warn">{{ field.apply_state === 'invalid' ? 'This saved value is invalid. Correct it and save again.' : 'The running value differs from the saved value.' }}</p>
    </template>
  </SettingsRow>
</template>

<style scoped>
.context-percent { display: flex; align-items: center; gap: .5rem; }
.context-percent input { width: 7rem; min-width: 0; }
.context-actions { justify-content: flex-end; }
</style>
