<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Result } from '../../../shared/api'
import { catalogueRows, modelEffortPath, modelOptions, modelSelectionNote, providerEnabled, type ModelRow, type ModelStatus } from '../model-picker'
import { state } from '../store'
import { loadSettings, saveModelSettings, settings } from '../stores/settings'

defineProps<{ model: { main: string; effort: string; provider: string } }>()
const wrapper = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const modelControl = ref<HTMLSelectElement | null>(null)
const open = ref(false), loading = ref(false), busy = ref(false)
const error = ref(''), selected = ref(''), effort = ref('')
const rows = ref<ModelRow[]>([])
let generation = 0
const fields = computed(() => settings.meta?.fields ?? [])
const options = computed(() => modelOptions(rows.value, fields.value, selected.value))
const selectionNote = computed(() => modelSelectionNote(selected.value, rows.value, fields.value))
const effortPath = computed(() => modelEffortPath(selected.value, rows.value))
const efforts = computed(() => rows.value.find((row) => row.ref === selected.value)?.effort_capabilities?.values ?? null)
const valid = computed(() => !!selected.value && providerEnabled(selected.value, fields.value) && options.value.some((row) => row.ref === selected.value && !row.disabled) && (!effortPath.value || efforts.value?.includes(effort.value) === true))
function close(restore = true): void {
  generation += 1
  open.value = false
  if (restore) trigger.value?.focus?.()
}
async function show(): Promise<void> {
  if (open.value) { close(); return }
  const mine = ++generation, epoch = state.recoveryEpoch, instance = state.app.coreInstanceId
  open.value = true; loading.value = true; error.value = ''; rows.value = []; selected.value = ''; effort.value = ''
  try {
    const read = (window.odin as unknown as { modelsStatus?: (params: Record<string, never>) => Promise<Result<ModelStatus>> }).modelsStatus
    if (!read) { error.value = 'Model choices are unavailable. Update Odin, then try again.'; return }
    const [answer] = await Promise.all([read({}), loadSettings(true)])
    if (mine !== generation || epoch !== state.recoveryEpoch || instance !== state.app.coreInstanceId) return
    if (!answer.ok) { error.value = answer.error.message; return }
    if (settings.error || settings.unavailable || !settings.meta) { error.value = settings.error || 'Saved model settings are unavailable.'; return }
    rows.value = catalogueRows(answer.result)
    selected.value = String(fields.value.find((item) => item.path === 'llm_provider.model')?.desired ?? '')
    effort.value = String(fields.value.find((item) => item.path === effortPath.value)?.desired ?? '')
    loading.value = false
    await nextTick()
    if (mine === generation) modelControl.value?.focus?.()
  } catch { if (mine === generation) error.value = 'Model choices could not be read. Close and try again.' }
  finally { if (mine === generation) loading.value = false }
}
function chooseModel(value: string): void {
  selected.value = value
  // Preserve a valid draft effort; otherwise show the saved value for the new provider,
  // never silently replace it with the first effort offered by the catalogue.
  if (!efforts.value?.includes(effort.value)) effort.value = String(fields.value.find((item) => item.path === effortPath.value)?.desired ?? '')
  error.value = ''
}
async function save(): Promise<void> {
  if (loading.value || busy.value || !valid.value) return
  const mine = generation
  const params: Record<string, unknown> = { model: selected.value }
  if (effortPath.value) params.reasoning_effort = effort.value
  busy.value = true; error.value = ''
  try {
    const saved = await saveModelSettings('models.main.set', params)
    if (mine !== generation) return
    if (saved) close()
    else error.value = (settings.unknownSave ? settings.notice : '') || settings.fields['llm_provider.model']?.message || settings.notice || 'The model change could not be saved. Check and try again.'
  } finally { busy.value = false }
}
function outside(event: PointerEvent): void {
  if (open.value && !wrapper.value?.contains?.(event.target as Node)) close(false)
}
function key(event: KeyboardEvent): void {
  if (open.value && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
}
onMounted(() => { globalThis.document?.addEventListener?.('pointerdown', outside); globalThis.document?.addEventListener?.('keydown', key) })
onUnmounted(() => { generation += 1; globalThis.document?.removeEventListener?.('pointerdown', outside); globalThis.document?.removeEventListener?.('keydown', key) })
watch(() => [state.recoveryEpoch, state.app.coreInstanceId, state.app.link], () => { if (open.value) close() })
</script>

<template>
  <div ref="wrapper" class="header-model-switcher">
    <button ref="trigger" class="status-item chat-model" :aria-label="`Change main model and reasoning effort: ${model.main} · ${model.effort}`" aria-haspopup="dialog" :aria-expanded="open" aria-controls="header-model-dialog" :title="`Model and effort, served by ${model.provider}. Change the main model.`" @click="show">{{ model.main }} · {{ model.effort }}</button>
    <div v-if="open" id="header-model-dialog" class="header-model-popover" role="dialog" aria-label="Main model and reasoning effort" :aria-busy="loading || busy">
      <h3>Main model</h3>
      <p v-if="loading" role="status">Loading model choices…</p>
      <template v-else-if="rows.length">
        <label for="header-model">Model</label>
        <select id="header-model" ref="modelControl" :value="selected" :disabled="busy" @change="chooseModel(($event.target as HTMLSelectElement).value)"><option v-for="row in options" :key="row.ref" :value="row.ref" :disabled="row.disabled">{{ row.label }}</option></select>
        <p v-if="selectionNote" class="settings-help">{{ selectionNote }}</p>
        <template v-if="effortPath">
          <label for="header-effort">Reasoning effort</label>
          <select id="header-effort" :value="effort" :disabled="busy || !efforts?.length" @change="effort = ($event.target as HTMLSelectElement).value">
            <option v-if="!efforts?.includes(effort)" :value="effort" disabled>{{ effort || 'Choose an effort' }} (choose a supported effort)</option>
            <option v-for="choice in efforts ?? []" :key="choice" :value="choice">{{ choice }}</option>
          </select>
          <p v-if="efforts === null" class="settings-help">Supported effort choices are not known for this model.</p>
        </template>
      </template>
      <p v-else-if="!error" role="status">Model choices are unavailable.</p>
      <p v-if="error" role="alert" class="warn">{{ error }}</p>
      <div class="header-model-actions"><button class="primary" :disabled="loading || busy || !valid" @click="save">{{ busy ? 'Saving…' : 'Save' }}</button><button class="ghost" @click="close()">Cancel</button></div>
    </div>
  </div>
</template>

<style scoped>
.header-model-switcher { position: relative; min-width: 0; }
.header-model-popover { position: absolute; top: calc(100% + 8px); right: 0; z-index: 20; width: min(330px, calc(100vw - 36px)); max-height: calc(100vh - 110px); overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 16px; border: 1px solid var(--line); border-radius: var(--radius-lg); background: var(--panel); color: var(--fg); box-shadow: 0 12px 36px #0004; text-align: left; }
.header-model-popover h3, .header-model-popover p { margin: 0; }
.header-model-popover h3 { font-size: 14px; }
.header-model-popover label { font-size: 12px; color: var(--muted); }
.header-model-popover select { width: 100%; min-width: 0; padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--panel); color: var(--fg); }
.header-model-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
</style>
