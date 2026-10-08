<script setup lang="ts">
import { computed, onBeforeUnmount } from 'vue'
import type { ConfigField } from '../../../../shared/api'
import { ask } from '../../dialog'
import { settingsControlId } from '../../settings-accessibility'
import { editableHere, isSecret, SecretDrafts } from '../../settings-form'
import { clearSecret, setSecret, settings } from '../../stores/settings'
import { state as appState } from '../../store'
import SettingsRow from './SettingsRow.vue'

const props = defineProps<{ field: ConfigField; label: string; help?: string }>()
const field = computed(() => settings.meta?.fields.find((item) => item.path === props.field.path) ?? props.field)
const id = computed(() => settingsControlId('curated', field.value.path))
const state = computed(() => settings.fields[field.value.path])
const epoch = appState.recoveryEpoch
const instance = appState.app.coreInstanceId
const routeAvailable = computed(() => field.value.sensitivity === 'sensitive' && field.value.secret_route === 'secrets.set')
const blocked = computed(() => !routeAvailable.value || !editableHere(field.value) || !isSecret(field.value) || settings.unknownSave || epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId)
const secrets = new SecretDrafts(async (path, value) => {
  const latest = settings.meta?.fields.find((item) => item.path === path)
  return latest && !blocked.value ? setSecret(latest, value) : false
})
const configured = computed(() => field.value.configured === null ? 'Saved password status is unavailable.' : field.value.configured ? 'Password stored.' : 'No password stored.')
const saving = (): boolean => settings.fields[field.value.path]?.status === 'saving'
onBeforeUnmount(() => { secrets.values[field.value.path] = undefined })
async function remove(): Promise<void> {
  if (blocked.value || saving()) return
  const shown = field.value
  if (await ask({ title: `Remove ${props.label.toLowerCase()}?`, message: 'The stored password will be removed. Enter a new password to connect again.', confirmLabel: 'Remove', danger: true })) {
    if (!blocked.value && !saving() && field.value === shown) await clearSecret(field.value)
  }
}
</script>

<template>
  <SettingsRow :label="label" :description="help" :control-id="id" full-width>
    <input :id="id" :value="blocked ? '' : secrets.values[field.path] ?? ''" type="password" autocomplete="new-password" placeholder="New password" :disabled="blocked" :aria-describedby="`${id}-status`" :aria-invalid="state?.status === 'error' || undefined" @input="secrets.values[field.path] = ($event.target as HTMLInputElement).value" />
    <button type="button" class="ghost" :aria-label="`${field.configured ? 'Replace' : 'Store'} ${label.toLowerCase()}`" :disabled="blocked || state?.status === 'saving' || !secrets.values[field.path]" @click="secrets.save(field.path)">{{ field.configured ? 'Replace' : 'Store' }}</button>
    <button v-if="field.configured" type="button" class="ghost danger-item" :aria-label="`Remove ${label.toLowerCase()}…`" :disabled="blocked || state?.status === 'saving'" @click="remove">Remove…</button>
    <button v-if="secrets.values[field.path]" type="button" class="ghost" :aria-label="`Cancel ${label.toLowerCase()} draft`" @click="secrets.values[field.path] = undefined">Cancel</button>
    <template #note>
      <p :id="`${id}-status`" class="settings-editor-note">{{ configured }}</p>
      <p v-if="state?.status === 'error'" role="status" class="settings-editor-error">{{ state.message }}</p>
      <p v-else-if="state?.status === 'saving'" role="status">Saving…</p>
      <p v-else-if="state?.status === 'saved'" role="status">Saved</p>
    </template>
  </SettingsRow>
</template>
