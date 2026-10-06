<script setup lang="ts">
import type { ConfigField } from '../../../shared/api'
import { settingsControlId } from '../settings-accessibility'
import {
  dedicatedMethod,
  differenceNote,
  editableHere,
  effectText,
  FieldDrafts,
  imageLeafOf,
  isSecret,
  SecretDrafts,
  STATE_LABELS
} from '../settings-form'
import { clearSecret, resetField, saveField, setImageIntent, setSecret, settings } from '../stores/settings'

defineProps<{ fields: ConfigField[] }>()

/** What the user changed, per field, until it is saved: one write per field at a time, never clearing newer typing. */
const form = new FieldDrafts({
  save: saveField,
  reset: resetField,
  latest: (path) => settings.meta?.fields.find((f) => f.path === path)
})
const errors = form.errors
const secrets = new SecretDrafts((path, value) => {
  const field = settings.meta?.fields.find((f) => f.path === path)
  return field ? setSecret(field, value) : Promise.resolve(false)
})

const current = (field: ConfigField): string | boolean => form.current(field)
const edit = (field: ConfigField, value: string | boolean): void => form.edit(field, value)
const save = (field: ConfigField): Promise<void> => form.save(field)
const reset = (field: ConfigField): Promise<void> => form.reset(field)
const saving = (field: ConfigField): boolean => settings.fields[field.path]?.status === 'saving'

/** Toggles and choices save at once; typed values save on Enter or when the field loses focus. */
async function pick(field: ConfigField, value: string | boolean): Promise<void> {
  edit(field, value)
  await save(field)
}

const inputId = (field: ConfigField): string => settingsControlId('field', field.path)
const fieldError = (field: ConfigField): string | undefined =>
  errors[field.path] || (settings.fields[field.path]?.status === 'error' ? settings.fields[field.path]?.message : undefined)
const invalid = (field: ConfigField): boolean => Boolean(fieldError(field)) || field.apply_state === 'invalid'
const describedBy = (field: ConfigField): string => [
  field.description ? `${inputId(field)}-description` : '',
  `${inputId(field)}-state`,
  `${inputId(field)}-effect`,
  fieldError(field) ? `${inputId(field)}-error` : ''
].filter(Boolean).join(' ')
</script>

<template>
  <div class="schema-form">
    <div v-for="field in fields" :key="field.path" :class="['field', field.apply_state]">
      <div class="field-head">
        <label v-if="editableHere(field)" :for="inputId(field)" class="field-label">{{ field.label }}</label>
        <span v-else class="field-label">{{ field.label }}</span>
        <code class="field-path">{{ field.path }}</code>
        <span :id="`${inputId(field)}-state`" :class="['apply-state', field.apply_state]">{{ STATE_LABELS[field.apply_state] }}</span>
      </div>
      <p v-if="field.description" :id="`${inputId(field)}-description`" class="field-desc">{{ field.description }}</p>

      <div v-if="!editableHere(field)" class="field-input readonly">
        <code class="field-value">{{ JSON.stringify(field.desired) }}</code>
        <span class="field-desc">{{ field.path === 'llm_provider.active_provider' ? 'Selected by the main model reference.' : 'Changed with the controls above.' }}</span>
      </div>
      <div v-else-if="isSecret(field)" class="field-input secret">
        <span class="secret-state">{{ field.configured === null ? 'Keyring unavailable; saved value unknown' : field.configured ? 'Set' : 'Not set' }}</span>
        <input
          :id="inputId(field)"
          :aria-describedby="describedBy(field)"
          :aria-invalid="invalid(field)"
          :value="secrets.values[field.path] ?? ''"
          type="password"
          autocomplete="off"
          placeholder="New value"
          @input="secrets.values[field.path] = ($event.target as HTMLInputElement).value"
          @keydown.enter="secrets.save(field.path)"
        />
        <button class="ghost" :aria-label="`Save ${field.label}`" :disabled="!secrets.values[field.path]" @click="secrets.save(field.path)">Save</button>
        <button v-if="field.desired" class="ghost" :aria-label="`Clear ${field.label}`" @click="clearSecret(field)">Clear</button>
      </div>
      <div v-else-if="field.type === 'boolean'" class="field-input toggle">
        <input
          :id="inputId(field)"
          :aria-describedby="describedBy(field)"
          :aria-invalid="invalid(field)"
          type="checkbox"
          :checked="current(field) === true"
          @change="pick(field, ($event.target as HTMLInputElement).checked)"
        />
        {{ current(field) === true ? 'On' : 'Off' }}
      </div>
      <select
        v-else-if="field.enum"
        :id="inputId(field)"
        :aria-describedby="describedBy(field)"
        :aria-invalid="invalid(field)"
        class="field-input"
        :value="current(field)"
        @change="pick(field, ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="option in field.enum" :key="option" :value="option">{{ option }}</option>
      </select>
      <textarea
        v-else-if="field.type === 'array' || field.type === 'object'"
        :id="inputId(field)"
        :aria-describedby="describedBy(field)"
        :aria-invalid="invalid(field)"
        class="field-input"
        rows="4"
        spellcheck="false"
        :value="String(current(field))"
        @input="edit(field, ($event.target as HTMLTextAreaElement).value)"
        @blur="save(field)"
      />
      <input
        v-else
        :id="inputId(field)"
        :aria-describedby="describedBy(field)"
        :aria-invalid="invalid(field)"
        class="field-input"
        :type="field.type === 'integer' || field.type === 'number' ? 'number' : 'text'"
        :min="field.constraints.minimum"
        :max="field.constraints.maximum"
        :value="String(current(field))"
        @input="edit(field, ($event.target as HTMLInputElement).value)"
        @keydown.enter="save(field)"
        @blur="save(field)"
      />

      <p :id="`${inputId(field)}-effect`" class="field-effect">{{ effectText(field) }}</p>
      <template v-for="leaf in [imageLeafOf(field)]" :key="`intent-${field.path}`">
        <div v-if="leaf && settings.meta?.image_models?.[leaf]" class="field-intent">
          <span v-if="settings.meta.image_models[leaf].status === 'follow'">
            Follows Odin's default ({{ settings.meta.image_models[leaf].default }}), and changes when that does.
          </span>
          <span v-else>Pinned to {{ settings.meta.image_models[leaf].effective }}.</span>
          <button
            class="ghost"
            :aria-label="settings.meta.image_models[leaf].status === 'follow' ? `Pin this value: ${field.label}` : `Follow Odin's default for ${field.label}`"
            :disabled="settings.fields[field.path]?.status === 'saving'"
            @click="setImageIntent(leaf, settings.meta.image_models[leaf].status === 'follow' ? 'pin' : 'follow')"
          >
            {{ settings.meta.image_models[leaf].status === 'follow' ? 'Pin this value' : "Follow Odin's default" }}
          </button>
        </div>
      </template>
      <p v-if="differenceNote(field)" class="field-diff">{{ differenceNote(field) }}</p>
      <p v-if="fieldError(field)" :id="`${inputId(field)}-error`" class="warn" role="status">{{ fieldError(field) }}</p>
      <p v-else-if="saving(field)" class="field-saved" role="status">Saving {{ field.label }}.</p>
      <p v-else-if="settings.fields[field.path]?.status === 'saved'" class="field-saved" role="status">Saved {{ field.label }}.</p>
      <button
        v-if="editableHere(field) && !isSecret(field) && !dedicatedMethod(field) && field.configured"
        class="ghost field-reset"
        :aria-label="`Reset to default: ${field.label}`"
        :disabled="saving(field)"
        @click="reset(field)"
      >
        Reset to default
      </button>
    </div>
  </div>
</template>
