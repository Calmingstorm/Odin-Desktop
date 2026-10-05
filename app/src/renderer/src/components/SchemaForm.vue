<script setup lang="ts">
import { reactive } from 'vue'
import type { ConfigField } from '../../../shared/api'
import { dedicatedMethod, differenceNote, effectText, FieldDrafts, imageLeafOf, isSecret, STATE_LABELS } from '../settings-form'
import { clearSecret, resetField, saveField, setImageIntent, setSecret, settings } from '../stores/settings'

defineProps<{ fields: ConfigField[] }>()

/** What the user changed, per field, until it is saved: one save per field at a time, never clearing newer typing. */
const form = new FieldDrafts()
const errors = form.errors
const secrets = reactive<Record<string, string | undefined>>({})

const current = (field: ConfigField): string | boolean => form.current(field)
const edit = (field: ConfigField, value: string | boolean): void => form.edit(field, value)
const save = (field: ConfigField): Promise<void> => form.save(field, saveField)

/** Toggles and choices save at once; typed values save on Enter or when the field loses focus. */
async function pick(field: ConfigField, value: string | boolean): Promise<void> {
  edit(field, value)
  await save(field)
}

async function saveSecret(field: ConfigField): Promise<void> {
  const value = secrets[field.path]
  if (!value) return
  if (await setSecret(field, value)) secrets[field.path] = undefined
}

async function reset(field: ConfigField): Promise<void> {
  if (await resetField(field)) form.clear(field)
}

const inputId = (field: ConfigField): string => `field-${field.path.replace(/\W/g, '-')}`
</script>

<template>
  <div class="schema-form">
    <div v-for="field in fields" :key="field.path" :class="['field', field.apply_state]">
      <div class="field-head">
        <label :for="inputId(field)" class="field-label">{{ field.label }}</label>
        <code class="field-path">{{ field.path }}</code>
        <span :class="['apply-state', field.apply_state]">{{ STATE_LABELS[field.apply_state] }}</span>
      </div>
      <p v-if="field.description" class="field-desc">{{ field.description }}</p>

      <div v-if="isSecret(field)" class="field-input secret">
        <span class="secret-state">{{ field.desired ? 'Set' : 'Not set' }}</span>
        <input
          :id="inputId(field)"
          :value="secrets[field.path] ?? ''"
          type="password"
          autocomplete="off"
          placeholder="New value"
          @input="secrets[field.path] = ($event.target as HTMLInputElement).value"
          @keydown.enter="saveSecret(field)"
        />
        <button class="ghost" :disabled="!secrets[field.path]" @click="saveSecret(field)">Save</button>
        <button v-if="field.desired" class="ghost" @click="clearSecret(field)">Clear</button>
      </div>
      <label v-else-if="field.type === 'boolean'" class="field-input toggle">
        <input
          :id="inputId(field)"
          type="checkbox"
          :checked="current(field) === true"
          @change="pick(field, ($event.target as HTMLInputElement).checked)"
        />
        {{ current(field) === true ? 'On' : 'Off' }}
      </label>
      <select
        v-else-if="field.enum"
        :id="inputId(field)"
        class="field-input"
        :value="current(field)"
        @change="pick(field, ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="option in field.enum" :key="option" :value="option">{{ option }}</option>
      </select>
      <textarea
        v-else-if="field.type === 'array' || field.type === 'object'"
        :id="inputId(field)"
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
        class="field-input"
        :type="field.type === 'integer' || field.type === 'number' ? 'number' : 'text'"
        :min="field.constraints.minimum"
        :max="field.constraints.maximum"
        :value="String(current(field))"
        @input="edit(field, ($event.target as HTMLInputElement).value)"
        @keydown.enter="save(field)"
        @blur="save(field)"
      />

      <p class="field-effect">{{ effectText(field) }}</p>
      <template v-for="leaf in [imageLeafOf(field)]" :key="`intent-${field.path}`">
        <div v-if="leaf && settings.meta?.image_models?.[leaf]" class="field-intent">
          <span v-if="settings.meta.image_models[leaf].status === 'follow'">
            Follows Odin's default ({{ settings.meta.image_models[leaf].default }}), and changes when that does.
          </span>
          <span v-else>Pinned to {{ settings.meta.image_models[leaf].effective }}.</span>
          <button
            class="ghost"
            :disabled="settings.fields[field.path]?.status === 'saving'"
            @click="setImageIntent(leaf, settings.meta.image_models[leaf].status === 'follow' ? 'pin' : 'follow')"
          >
            {{ settings.meta.image_models[leaf].status === 'follow' ? 'Pin this value' : "Follow Odin's default" }}
          </button>
        </div>
      </template>
      <p v-if="differenceNote(field)" class="field-diff">{{ differenceNote(field) }}</p>
      <p v-if="errors[field.path]" class="warn">{{ errors[field.path] }}</p>
      <p v-else-if="settings.fields[field.path]?.status === 'error'" class="warn">{{ settings.fields[field.path]?.message }}</p>
      <p v-else-if="settings.fields[field.path]?.status === 'saved'" class="field-saved">Saved.</p>
      <button v-if="!isSecret(field) && !dedicatedMethod(field) && field.configured" class="ghost field-reset" @click="reset(field)">
        Reset to default
      </button>
    </div>
  </div>
</template>
