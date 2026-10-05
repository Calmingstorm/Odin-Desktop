<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ask } from '../../dialog'
import { unavailableText } from '../../capability'
import { management } from '../../stores/management'
import { deletePreset, loadPersonality, savePersonality, savePreset, stateStore } from '../../stores/state'

onMounted(loadPersonality)

/** The choice as edited here. Each field follows what Odin has until the user changes it. */
const choice = reactive({ preset: '', custom_name: '', custom_identity: '', custom_voice: '' })
type ChoiceField = keyof typeof choice
const edited = { preset: 0, custom_name: 0, custom_identity: 0, custom_voice: 0 }
const accepted = { ...edited }
function edit(field: ChoiceField): void {
  edited[field] += 1
}
watch(
  () => stateStore.personality,
  (p) => {
    if (!p) return
    const incoming = { preset: p.preset, custom_name: p.custom_name, custom_identity: p.custom_identity, custom_voice: p.custom_voice }
    for (const field of Object.keys(incoming) as ChoiceField[]) {
      if (edited[field] === accepted[field]) choice[field] = incoming[field]
    }
  },
  { immediate: true }
)

const shown = computed(() => (choice.preset === 'custom' ? null : stateStore.personality?.presets[choice.preset]))
const draft = reactive({ name: '', display_name: '', identity: '', voice: '' })
const presetError = ref('')
const presetErrorField = ref<'name' | 'content' | null>(null)
watch(draft, () => {
  presetError.value = ''
  presetErrorField.value = null
})
watch(() => stateStore.unavailable.personality, (unavailable) => {
  if (unavailable) presetError.value = ''
})

async function save(): Promise<void> {
  // The core replaces all four fields, defaulting omitted custom fields to empty strings.
  // A preset switch keeps persisted custom text, not an unsaved hidden custom draft.
  const custom = stateStore.personality
  const change = choice.preset === 'custom' ? { ...choice } : {
    preset: choice.preset,
    custom_name: custom?.custom_name ?? '',
    custom_identity: custom?.custom_identity ?? '',
    custom_voice: custom?.custom_voice ?? ''
  }
  const sent = { ...edited }
  await savePersonality(change, () => {
    // Only successful submitted fields can follow the readback. An edit made during the write or readback,
    // even back to an older value, has a newer generation and stays available for the next Save.
    const fields: ChoiceField[] = change.preset === 'custom' ? ['preset', 'custom_name', 'custom_identity', 'custom_voice'] : ['preset']
    for (const field of fields) accepted[field] = sent[field]
  })
}

async function saveAsPreset(): Promise<void> {
  presetError.value = ''
  presetErrorField.value = null
  if (!draft.name.trim()) {
    presetError.value = 'Name the preset.'
    presetErrorField.value = 'name'
    return
  }
  if (!draft.identity.trim() && !draft.voice.trim()) {
    presetError.value = 'Give it an identity, a voice, or both.'
    presetErrorField.value = 'content'
    return
  }
  const sent = JSON.stringify(draft)
  const saved = await savePreset({ name: draft.name.trim(), display_name: draft.display_name.trim() || undefined, identity: draft.identity, voice: draft.voice })
  // Clear only what was saved: a preset typed meanwhile stays.
  if (saved && JSON.stringify(draft) === sent) Object.assign(draft, { name: '', display_name: '', identity: '', voice: '' })
}

async function remove(name: string): Promise<void> {
  const confirmed = await ask({ title: 'Delete this preset?', message: `${name} is removed. If it's in use, Odin goes back to his own.`, confirmLabel: 'Delete', danger: true })
  if (confirmed) await deletePreset(name)
}
</script>

<template>
  <section v-if="stateStore.unavailable.personality" class="panel" aria-label="Personality">
    <h3>Who Odin is</h3>
    <p class="manage-desc" role="status">{{ unavailableText('Personality') }}</p>
  </section>
  <p v-else-if="!stateStore.personality && stateStore.errors.personality" class="warn">{{ stateStore.errors.personality }}</p>
  <section v-if="stateStore.personality" class="panel" aria-label="Personality">
    <header class="panel-head">
      <h3>Who Odin is</h3>
      <span class="panel-hint">A preset sets his identity and voice. New requests use the one saved here.</span>
    </header>
    <label class="field-input">
      Preset
      <select v-model="choice.preset" @change="edit('preset')">
        <option v-for="key in stateStore.personality.builtin_presets" :key="key" :value="key">{{ stateStore.personality.presets[key]?.name ?? key }}</option>
        <option v-for="key in stateStore.personality.user_presets" :key="key" :value="key">{{ stateStore.personality.presets[key]?.name ?? key }} (yours)</option>
        <option value="custom">Custom</option>
      </select>
    </label>
    <template v-if="shown">
      <p class="manage-desc"><strong>Identity.</strong> {{ shown.identity }}</p>
      <p class="manage-desc"><strong>Voice.</strong> {{ shown.voice }}</p>
    </template>
    <template v-else>
      <label class="field-input">Name <input v-model="choice.custom_name" @input="edit('custom_name')" maxlength="200" /></label>
      <label class="field-input">Identity <textarea v-model="choice.custom_identity" @input="edit('custom_identity')" rows="4" /></label>
      <label class="field-input">Voice <textarea v-model="choice.custom_voice" @input="edit('custom_voice')" rows="4" /></label>
    </template>
    <div class="panel-actions">
      <button class="ghost" aria-label="Save personality" :disabled="management.busy.personality" @click="save">Save</button>
    </div>
    <p v-if="management.notes.personality" class="manage-note" role="status">{{ management.notes.personality }}</p>
    <p v-if="stateStore.errors.personality" class="warn">{{ stateStore.errors.personality }}</p>
  </section>

  <section v-if="stateStore.personality" class="panel" aria-label="Your presets">
    <header class="panel-head">
      <h3>Your presets</h3>
      <span class="panel-hint">Built-in presets can't be changed or deleted.</span>
    </header>
    <ul class="manage-list">
      <li v-for="key in stateStore.personality.user_presets" :key="key" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ key }}</code>
          <span class="manage-count">{{ stateStore.personality.presets[key]?.name }}</span>
          <span class="manage-actions"><button class="ghost danger-item" :aria-label="`Delete preset ${key}…`" @click="remove(key)">Delete…</button></span>
        </div>
        <p v-if="management.notes[`preset:${key}`]" class="manage-note" role="status">{{ management.notes[`preset:${key}`] }}</p>
      </li>
    </ul>
    <p v-if="!stateStore.personality.user_presets.length" class="manage-desc">None yet.</p>
    <h4 class="sub-head">Save a preset</h4>
    <label class="field-input">Name <input v-model="draft.name" maxlength="64" placeholder="night_shift" :aria-invalid="presetErrorField === 'name' || undefined" :aria-describedby="presetErrorField === 'name' ? 'preset-validation-error' : undefined" /></label>
    <label class="field-input">Shown as <input v-model="draft.display_name" maxlength="200" placeholder="Night shift" /></label>
    <label class="field-input">Identity <textarea v-model="draft.identity" rows="3" :aria-invalid="presetErrorField === 'content' || undefined" :aria-describedby="presetErrorField === 'content' ? 'preset-validation-error' : undefined" /></label>
    <label class="field-input">Voice <textarea v-model="draft.voice" rows="3" :aria-invalid="presetErrorField === 'content' || undefined" :aria-describedby="presetErrorField === 'content' ? 'preset-validation-error' : undefined" /></label>
    <div class="panel-actions"><button class="ghost" :disabled="management.busy.preset" @click="saveAsPreset">Save preset</button></div>
    <p v-if="presetError" id="preset-validation-error" class="warn" role="alert">{{ presetError }}</p>
    <p v-else-if="management.notes.preset" class="manage-note" role="status">{{ management.notes.preset }}</p>
  </section>
</template>
