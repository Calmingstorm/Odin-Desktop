<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ConfigField } from '../../../../shared/api'
import { settingsControlId } from '../../settings-accessibility'
import { editableHere, FieldDrafts, fromInput, isSecret } from '../../settings-form'
import { ask } from '../../dialog'
import { resetField, saveField, settings } from '../../stores/settings'
import SettingsRow from './SettingsRow.vue'
import SettingsSwitch from './SettingsSwitch.vue'
import StructuredSetting from './StructuredSetting.vue'

const props = defineProps<{ field: ConfigField; label: string; help?: string; editor?: 'short' | 'long'; commit?: 'automatic' | 'explicit' }>()
const structuredError = ref('')
const structuredKind = computed(() => props.field.path === 'openai_compatible.model_profiles' ? 'profiles'
  : props.field.path === 'tools.governor.host_overrides' ? 'host-policy'
  : ['openai_codex.context_budget_overrides', 'sessions.context_budget_overrides'].includes(props.field.path) ? 'budgets' : undefined)
const form = new FieldDrafts({
  save: saveField,
  reset: resetField,
  latest: (path) => settings.meta?.fields.find((field) => field.path === path)
})
const field = computed(() => settings.meta?.fields.find((field) => field.path === props.field.path) ?? props.field)
const controlId = computed(() => settingsControlId('curated', field.value.path))
const secret = computed(() => isSecret(field.value))
const supported = computed(() => ['string', 'integer', 'number', 'boolean', 'array', 'object'].includes(field.value.type)
  && ['applied', 'pending_restart', 'dormant', 'invalid', 'drift', 'unknown'].includes(field.value.apply_state))
const editable = computed(() => !secret.value && supported.value && editableHere(field.value))
const long = computed(() => props.editor === 'long' || field.value.type === 'array' || field.value.type === 'object')
const current = computed(() => form.current(field.value))
const dirty = computed(() => editable.value && form.changed(field.value))
const state = computed(() => settings.fields[field.value.path])
const saving = computed(() => state.value?.status === 'saving')
const error = computed(() => structuredError.value || form.errors[field.value.path]
  || (state.value?.status === 'error' ? state.value.message || 'The change could not be saved. Try again.' : ''))
const invalid = computed(() => Boolean(error.value) || field.value.apply_state === 'invalid')
const note = computed(() => {
  if (secret.value) return 'Secret editing is unavailable here. Use the dedicated secret controls.'
  if (!supported.value) return 'Editing is unavailable for this setting. Refresh settings to check for support.'
  if (!editable.value) return 'Read-only here. Use this setting’s dedicated controls.'
  if (field.value.apply_state === 'invalid') return 'This value is invalid. Correct it and save again.'
  if (field.value.apply_state === 'drift') return 'The running value differs from the saved value. Check the value before making another change.'
  if (field.value.apply_state === 'unknown') return 'The running value is unknown. Check the connection before relying on this setting.'
  if (field.value.apply_state === 'pending_restart') return 'The saved change needs Odin to restart.'
  return ''
})
const describedBy = computed(() => [
  props.help ? `${controlId.value}-description` : '',
  note.value ? `${controlId.value}-note` : '',
  error.value ? `${controlId.value}-error` : ''
].filter(Boolean).join(' ') || undefined)

function edit(value: string | boolean): void {
  if (editable.value) form.edit(field.value, value)
}
async function save(): Promise<void> {
  if (!editable.value || structuredError.value) return
  const parsed = fromInput(field.value, current.value)
  if (!parsed.ok) { await form.save(field.value); return }
  const addsEntries = (value: unknown, saved: unknown): boolean => Array.isArray(value) && value.some((entry) => !Array.isArray(saved) || !saved.includes(entry))
  const expands = (structuredKind.value === 'host-policy' && dirty.value)
    || (field.value.path === 'email.tls_verify' && field.value.desired !== false && parsed.value === false)
    || (['browser.allow_private_targets', 'email.allowed_attachment_dirs', 'tools.skill_allowed_urls'].includes(field.value.path) && addsEntries(parsed.value, field.value.desired))
  if (expands) {
    const revision = settings.meta?.revision
    const authority = field.value
    const draft = current.value
    const confirmed = await ask({ title: 'Change access policy?', message: structuredKind.value === 'host-policy'
      ? 'Changing per-host command safety can allow commands that were blocked.'
      : field.value.path === 'email.tls_verify' ? 'Mail connections will no longer verify server certificates.'
      : 'These changes allow access to additional destinations or folders.', confirmLabel: 'Save access changes', danger: true })
    if (!confirmed) return
    if (settings.meta?.revision !== revision || field.value !== authority) {
      structuredError.value = 'Settings changed. Refresh and check before saving again.'
      return
    }
    if (current.value !== draft) return
  }
  await form.save(field.value)
}
async function pick(value: string | boolean): Promise<void> {
  if (!editable.value) return
  edit(value)
  if (props.commit !== 'explicit') await save()
}
function cancel(): void {
  form.cancel(field.value.path)
  structuredError.value = ''
}
function enter(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.isComposing || long.value || props.commit === 'explicit') return
  event.preventDefault()
  void save()
}
function blur(event: FocusEvent): void {
  // Cancel and explicit Save own their intent. Leaving the input for either must not start a hidden write.
  if ((event.relatedTarget as HTMLElement | null)?.dataset?.settingsDraftAction) return
  if (!long.value && props.commit !== 'explicit') void save()
}
</script>

<template>
  <SettingsRow
    class="setting-editor"
    :label="label"
    :description="help"
    :control-id="secret ? undefined : controlId"
    :full-width="long"
  >
    <span v-if="secret" class="settings-editor-readonly">Secret support unavailable</span>
    <output v-else-if="!editable" :id="controlId" :aria-describedby="describedBy" class="settings-editor-readonly">{{ supported ? String(current) : 'Support unavailable' }}</output>
    <StructuredSetting
      v-else-if="structuredKind"
      :id="controlId"
      tabindex="-1"
      :field="field"
      :dirty="dirty"
      :value="String(current)"
      :fields="settings.meta?.fields ?? []"
      :kind="structuredKind"
      @input="edit"
      @invalid="structuredError = $event"
    />
    <SettingsSwitch
      v-else-if="field.type === 'boolean'"
      :id="controlId"
      :label="label"
      :checked="current === true"
      :described-by="describedBy"
      :invalid="invalid"
      @change="pick"
    />
    <select
      v-else-if="field.enum"
      :id="controlId"
      :value="current"
      :aria-describedby="describedBy"
      :aria-invalid="invalid || undefined"
      @change="pick(($event.target as HTMLSelectElement).value)"
    >
      <option v-if="!field.enum.includes(String(current))" :value="current" disabled>Choose a supported value</option>
      <option v-for="option in field.enum" :key="option" :value="option">{{ option }}</option>
    </select>
    <textarea
      v-else-if="long"
      :id="controlId"
      :value="String(current)"
      :aria-describedby="describedBy"
      :aria-invalid="invalid || undefined"
      :minlength="field.constraints.min_length"
      :maxlength="field.constraints.max_length"
      rows="5"
      @input="edit(($event.target as HTMLTextAreaElement).value)"
    />
    <input
      v-else
      :id="controlId"
      :value="String(current)"
      :type="field.type === 'integer' || field.type === 'number' ? 'number' : 'text'"
      :min="field.constraints.minimum"
      :max="field.constraints.maximum"
      :step="field.type === 'integer' ? 1 : field.type === 'number' ? 'any' : undefined"
      :minlength="field.constraints.min_length"
      :maxlength="field.constraints.max_length"
      :aria-describedby="describedBy"
      :aria-invalid="invalid || undefined"
      @input="edit(($event.target as HTMLInputElement).value)"
      @keydown="enter"
      @blur="blur"
    />
    <template #note>
      <p v-if="note" :id="`${controlId}-note`" class="settings-editor-note">{{ note }}</p>
      <div v-if="dirty" class="settings-editor-actions">
        <span class="settings-editor-dirty">Unsaved changes</span>
        <button type="button" data-settings-draft-action="save" :aria-label="`Save ${label}`" @click="save">Save</button>
        <button type="button" data-settings-draft-action="cancel" :aria-label="`Cancel changes to ${label}`" @click="cancel">Cancel</button>
      </div>
      <p v-if="error" :id="`${controlId}-error`" role="status" class="settings-editor-error">{{ error }}</p>
      <p v-else-if="saving" role="status" class="settings-editor-status">Saving…</p>
      <p v-else-if="state?.status === 'saved' && !dirty" role="status" class="settings-editor-status">Saved</p>
    </template>
  </SettingsRow>
</template>
