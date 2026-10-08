<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Result } from '../../../shared/api'
import { isUnavailable, settingsUnavailableText as unavailableText } from '../capability'
import { act, management } from '../stores/management'
import { isUnknownOutcome, onLateReceipt } from '../store'
import { loadSettings, settings, settingsCommand } from '../stores/settings'
import { settingsFields } from '../settings-presentation'
import SettingEditor from './settings/SettingEditor.vue'
import SettingsRow from './settings/SettingsRow.vue'

// Optional methods let an older bridge show an explicit capability limit, not break Codex accounts.
type Payload = Record<string, unknown>
type Catalogue = Payload & { recognized: true; models: Payload[]; quick_add: unknown[] }
type Selection = Payload & { model: string; provider_tag: string | null }
type RouterBridge = {
  openrouterCatalogue?: (params: Record<string, never>) => Promise<Result<Catalogue>>
  openrouterEndpoints?: (params: { model: string }) => Promise<Result<Payload>>
  openrouterSelect?: (params: { model: string; provider_tag: string; expected_revision: string }) => Promise<Result<Selection>>
  providersCompatDiagnostic?: (params: Record<string, never>) => Promise<Result<Payload>>
}
const bridge = () => window.odin as unknown as RouterBridge
const catalogue = ref<Catalogue | null>(null)
const endpoints = ref<Payload | null>(null)
const diagnostic = ref<Payload | null>(null)
const selected = ref<Selection | null>(null)
const model = ref('')
const provider = ref('')
const notices = ref({ catalogue: '', endpoints: '', diagnostic: '', select: '' })
const loading = ref({ catalogue: false, endpoints: false, diagnostic: false })
const selectUnavailable = ref(false)
const key = 'openrouter-select'
const validModel = computed(() => /^[^/\s]+\/[^/\s]+$/.test(model.value.trim()))
const models = computed(() => (catalogue.value?.models ?? []).filter((entry) => typeof entry.id === 'string'))
const routing = computed(() => settingsFields('models', 'more-options').filter((entry) => entry.key.startsWith('openai_compatible.openrouter.')).flatMap((entry) => {
  const field = settings.meta?.fields.find((item) => item.path === entry.key)
  return field ? [{ ...entry, field }] : []
}))
const json = (value: unknown): string => JSON.stringify(value, null, 2) ?? 'Not reported'
let alive = true
let catalogueRead = 0
let endpointRead = 0
let diagnosticRead = 0
let pendingSelection: string | undefined
const failure = (result: Result<unknown>, feature: string): string => result.ok ? '' :
  isUnavailable(result.error) ? unavailableText(feature) : result.error.message
const caught = (): Result<never> => ({ ok: false, error: { code: 'bridge_error', message: 'The bridge could not return a result.' } })

async function loadCatalogue(): Promise<void> {
  const mine = ++catalogueRead
  const read = bridge().openrouterCatalogue
  if (!read) {
    catalogue.value = null
    notices.value.catalogue = unavailableText('OpenRouter catalogue')
    return
  }
  loading.value.catalogue = true
  const result = await read({}).catch(caught)
  if (!alive || mine !== catalogueRead) return
  loading.value.catalogue = false
  catalogue.value = result.ok ? result.result : null
  notices.value.catalogue = failure(result, 'OpenRouter catalogue')
}
async function loadEndpoints(): Promise<void> {
  if (!validModel.value) return
  const mine = ++endpointRead
  const read = bridge().openrouterEndpoints
  if (!read) {
    endpoints.value = null
    notices.value.endpoints = unavailableText('OpenRouter endpoints')
    return
  }
  endpoints.value = null
  loading.value.endpoints = true
  const result = await read({ model: model.value.trim() }).catch(caught)
  if (!alive || mine !== endpointRead) return
  loading.value.endpoints = false
  endpoints.value = result.ok ? result.result : null
  notices.value.endpoints = failure(result, 'OpenRouter endpoints')
}
async function loadDiagnostic(): Promise<void> {
  const mine = ++diagnosticRead
  const read = bridge().providersCompatDiagnostic
  if (!read) {
    diagnostic.value = null
    notices.value.diagnostic = unavailableText('Compatibility provider diagnostic')
    return
  }
  loading.value.diagnostic = true
  const result = await read({}).catch(caught)
  if (!alive || mine !== diagnosticRead) return
  loading.value.diagnostic = false
  diagnostic.value = result.ok ? result.result : null
  notices.value.diagnostic = failure(result, 'Compatibility provider diagnostic')
}
async function selectModel(): Promise<void> {
  if (!validModel.value || management.busy[key] || selectUnavailable.value) return
  if (!settings.meta || settings.unknownSave) { notices.value.select = 'Refresh saved settings before saving routing.'; return }
  const select = bridge().openrouterSelect
  if (!select) {
    selectUnavailable.value = true
    notices.value.select = unavailableText('OpenRouter selection')
    return
  }
  const params = { model: model.value.trim(), provider_tag: provider.value.trim(), expected_revision: settings.meta.revision }
  await act(key, async () => {
    const result = await settingsCommand((revision) => select({ ...params, expected_revision: revision }))
    if (!result.ok && isUnknownOutcome(result.error)) pendingSelection = result.error.command_id
    if (!result.ok && isUnavailable(result.error)) {
      selectUnavailable.value = true
      notices.value.select = unavailableText('OpenRouter selection')
    }
    if (!result.ok && result.error.code === 'stale_binding') { await loadSettings(); notices.value.select = 'Settings changed elsewhere. Check, then save routing again.' }
    return result
  }, (answer) => {
    if (alive) selected.value = answer
    return `Saved routing for ${answer.model}; provider ${answer.provider_tag ?? 'automatic'}.`
  }, async () => { await loadSettings(true); await loadCatalogue() })
}
onLateReceipt((receipt) => {
  if (!alive || receipt.id !== pendingSelection) return
  if (!receipt.settled.ok && isUnknownOutcome(receipt.settled.error)) return
  pendingSelection = undefined
  if (!receipt.settled.ok && isUnavailable(receipt.settled.error)) {
    selectUnavailable.value = true
    notices.value.select = unavailableText('OpenRouter selection')
  }
})
watch(model, () => {
  endpointRead += 1
  loading.value.endpoints = false
  endpoints.value = null
  notices.value.endpoints = ''
})
onMounted(loadCatalogue)
onUnmounted(() => { alive = false })
</script>

<template>
  <section class="openrouter-admin" aria-label="OpenRouter models">
    <header class="panel-head">
      <h4>OpenRouter models</h4>
      <button class="ghost" :disabled="loading.catalogue" @click="loadCatalogue">Reload catalogue</button>
    </header>
    <p class="settings-help">Save routing without enabling the provider or changing the main model.</p>
    <p v-if="loading.catalogue" role="status">Reading catalogue.</p>
    <p v-if="notices.catalogue" class="warn" role="status">{{ notices.catalogue }}</p>
    <template v-if="catalogue">
      <p v-if="catalogue.stale" class="settings-help">Showing a saved catalogue; it may be out of date.</p>
      <p v-if="catalogue.refresh_error" class="warn" role="status">Catalogue refresh error: {{ catalogue.refresh_error }}</p>
      <details><summary>Suggested model references</summary><pre>{{ json(catalogue.quick_add) }}</pre></details>
      <details><summary>Measured cache</summary><pre>{{ json(catalogue.measured_cache) }}</pre></details>
      <details>
        <summary>Browse models ({{ models.length }})</summary>
        <ul>
          <li v-for="entry in models" :key="String(entry.id)">
            <button class="ghost" :disabled="management.busy[key]" @click="model = String(entry.id)">{{ entry.id }}</button>
            <span v-if="entry.agent_eligible === false" class="warn">{{ entry.agent_unavailable_reason ?? entry.reason ?? 'Not available for agents' }}</span>
            <details><summary>Model details</summary><pre>{{ json(entry) }}</pre></details>
          </li>
        </ul>
      </details>
    </template>
    <form @submit.prevent="selectModel">
      <SettingsRow label="Model ID" description="Use the author/slug shown in the catalogue." control-id="openrouter-model"><input id="openrouter-model" v-model="model" placeholder="author/slug" :disabled="management.busy[key]" /></SettingsRow>
      <SettingsRow label="Provider pin" description="Leave blank for automatic routing." control-id="openrouter-provider"><input id="openrouter-provider" v-model="provider" :disabled="management.busy[key]" /></SettingsRow>
      <button class="ghost" type="button" :disabled="!validModel || loading.endpoints" @click="loadEndpoints">Read endpoints</button>
      <button type="submit" :disabled="!validModel || management.busy[key] || selectUnavailable || !settings.meta || settings.unknownSave">Save routing</button>
    </form>
    <p v-if="notices.select" class="warn" role="status">{{ notices.select }}</p>
    <p v-if="management.notes[key]" role="status">{{ management.notes[key] }}</p>
    <p v-if="selected" class="settings-help">Saved {{ selected.model }} with {{ selected.provider_tag ?? 'automatic routing' }}.</p>
    <p v-if="loading.endpoints" role="status">Reading endpoints.</p>
    <p v-if="notices.endpoints" class="warn" role="status">{{ notices.endpoints }}</p>
    <details v-if="endpoints" open><summary>Endpoints and effective profile</summary><pre>{{ json(endpoints) }}</pre></details>
    <button class="ghost" :disabled="loading.diagnostic" @click="loadDiagnostic">Read compatibility diagnostic</button>
    <p v-if="loading.diagnostic" role="status">Reading compatibility diagnostic.</p>
    <p v-if="notices.diagnostic" class="warn" role="status">{{ notices.diagnostic }}</p>
    <details v-if="diagnostic" open><summary>Compatibility diagnostic (including unhealthy results)</summary><pre>{{ json(diagnostic) }}</pre></details>
    <details v-if="routing.length"><summary>Routing options</summary><SettingEditor v-for="entry in routing" :key="entry.key" :field="entry.field" :label="entry.label" :help="entry.help" commit="explicit" /></details>
  </section>
</template>

<style scoped>
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
form { display: grid; gap: .5rem; }
</style>
