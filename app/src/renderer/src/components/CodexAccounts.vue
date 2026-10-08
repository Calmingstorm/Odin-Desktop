<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { CodexAccount, QuotaWindow } from '../../../shared/api'
import { ask } from '../dialog'
import { accountIdentity, activateAccount, beginLogin, labelAccount, loadCodex, removeAccount, retryLogin, settings, stopLogin } from '../stores/settings'
import { isUnavailable, settingsUnavailableText as unavailableText } from '../capability'
import type { Result } from '../../../shared/api'
import { act, management } from '../stores/management'
import OpenRouterAdmin from './OpenRouterAdmin.vue'
import { isUnknownOutcome, onLateReceipt, state } from '../store'
import type { ConfigField, ImageLeaf } from '../../../shared/api'
import { settingsFields } from '../settings-presentation'
import { fromInput, isSecret, toInput } from '../settings-form'
import { clearSecret, saveFields, saveModelSettings, setImageIntent, setSecret } from '../stores/settings'
import SettingEditor from './settings/SettingEditor.vue'
import SettingsRow from './settings/SettingsRow.vue'
import SettingsSection from './settings/SettingsSection.vue'
import SettingsSwitch from './settings/SettingsSwitch.vue'
import ContextUse from './settings/ContextUse.vue'
import { settingsControlId } from '../settings-accessibility'

type ModelRow = { ref: string; name?: string; capability?: string; effort_capabilities?: { values: string[] | null; restrictions_known: boolean; source: string } }
type ProviderStatus = { configured?: boolean; base_url?: string; model?: string; preset?: string; openrouter_recognized?: boolean }
type ModelStatus = { model_catalogue?: Record<string, ModelRow[]>; serving_provider?: string | null; active_provider?: string; codex?: ProviderStatus; ollama?: ProviderStatus; openai_compatible?: ProviderStatus }
const props = defineProps<{ reveal?: string }>()
const modelCatalogue = ref<ModelRow[]>([])
const providerStatus = ref<ModelStatus | null>(null)
const modelReadError = ref('')
let modelRead = 0
const modelId = (path: string): string => settingsControlId('curated', path)
async function loadModels(): Promise<void> {
  const mine = ++modelRead
  modelCatalogue.value = []
  providerStatus.value = null
  const read = (window.odin as unknown as { modelsStatus?: (params: Record<string, never>) => Promise<Result<ModelStatus>> }).modelsStatus
  if (!read) { modelReadError.value = 'Model choices are unavailable. Refresh after updating Odin.'; return }
  const epoch = state.recoveryEpoch, instance = state.app.coreInstanceId
  try {
    const answer = await read({})
    if (mine !== modelRead || epoch !== state.recoveryEpoch || instance !== state.app.coreInstanceId) return
    if (!answer.ok) { modelReadError.value = answer.error.message; return }
    providerStatus.value = answer.result
    modelCatalogue.value = Object.values(answer.result.model_catalogue ?? {}).flat().filter((row) => typeof row.ref === 'string')
    modelReadError.value = ''
  } catch { if (mine === modelRead) modelReadError.value = 'Model choices could not be read. Try again.' }
}
const modelRow = (model: string): ModelRow | undefined => modelCatalogue.value.find((row) => row.ref === model)
const modelEfforts = (model: string): string[] | null => modelRow(model)?.effort_capabilities?.values ?? null
const modelProvider = (model: string): Provider => model.startsWith('compat:') ? 'compat' : model.startsWith('ollama:') ? 'ollama' : 'codex'
const validMainPair = computed(() => {
  const efforts = modelEfforts(String(value('llm_provider.model')))
  return !mainEffort.value || efforts === null || efforts.length === 0 || efforts.includes(String(value(mainEffort.value)))
})
onMounted(loadModels)

const primary = computed(() => settingsFields('models', 'primary'))
const more = computed(() => settingsFields('models', 'more-options'))
const field = (path: string): ConfigField | undefined => settings.meta?.fields.find((item) => item.path === path)
const entry = (path: string) => [...primary.value, ...more.value].find((item) => item.key === path)
const label = (path: string): string => entry(path)?.label ?? 'Setting'
const help = (path: string): string => entry(path)?.help ?? ''
const providerNames = { codex: 'Codex', ollama: 'Ollama', compat: 'OpenAI-compatible' } as const
type Provider = keyof typeof providerNames
const providerPaths: Record<Provider, string[]> = {
  codex: ['openai_codex.enabled'],
  ollama: ['ollama.enabled', 'ollama.base_url', 'ollama.model', 'ollama.api_key'],
  compat: ['openai_compatible.enabled', 'openai_compatible.preset', 'openai_compatible.base_url', 'openai_compatible.model', 'openai_compatible.reasoning_effort', 'openai_compatible.context_utilization', 'openai_compatible.api_key']
}
const providers = Object.keys(providerNames) as Provider[]
const expanded = reactive<Record<Provider, boolean>>({ codex: false, ollama: false, compat: false })
watch(() => props.reveal, (path) => {
  if (path?.startsWith('ollama.')) expanded.ollama = true
  if (path?.startsWith('openai_compatible.')) expanded.compat = true
  if (path?.startsWith('openai_codex.')) expanded.codex = true
}, { immediate: true })
const drafts = reactive<Record<string, string | boolean>>({})
const secretDrafts = reactive<Record<string, string>>({})
const errors = reactive<Record<string, string>>({})
const busy = reactive<Record<string, boolean>>({})
const notes = reactive<Record<string, string>>({})
const value = (path: string): string | boolean => drafts[path] ?? (field(path) ? toInput(field(path)!) : '')
const dirty = (paths: string[]): boolean => paths.some((path) => field(path) && drafts[path] !== undefined && value(path) !== toInput(field(path)!))
const edit = (path: string, raw: string | boolean): void => { drafts[path] = raw; errors[path] = ''; notes[path] = '' }
function cancel(paths: string[]): void { for (const path of paths) { delete drafts[path]; delete errors[path] } }
function present(paths: string[]): ConfigField[] { return paths.flatMap((path) => entry(path) && field(path) ? [field(path)!] : []) }
function providerFields(provider: Provider): ConfigField[] { return present(providerPaths[provider].slice(1)).filter((item) => item.path !== mainEffort.value && item.path !== 'openai_compatible.context_utilization') }
// The core owns provider identity. An unsaved model choice must not redirect context edits.
const activeProvider = computed(() => providerStatus.value?.serving_provider ?? field('llm_provider.active_provider')?.effective ?? providerStatus.value?.active_provider)
const activeContext = computed(() => activeProvider.value === 'codex' ? field('openai_codex.context_utilization') : activeProvider.value === 'compat' ? field('openai_compatible.context_utilization') : undefined)
function providerSummary(provider: Provider): string {
  if (provider === 'codex') {
    if (settings.codex.stale || settings.codex.error) return 'Account status unavailable'
    if (!settings.codex.status) return settings.codex.unavailable ? 'Account status unavailable' : 'Loading accounts…'
    const accounts = settings.codex.status.accounts
    if (!accounts.length) return 'Not set up'
    const signedIn = accounts.filter((account) => !account.error && !account.expired).length
    return `${signedIn ? 'Signed in' : 'Sign-in needed'} · ${accounts.length} ${accounts.length === 1 ? 'account' : 'accounts'}`
  }
  const status = providerStatus.value?.[provider === 'compat' ? 'openai_compatible' : 'ollama']
  if (!status) return 'Provider status unavailable'
  if (!status.model || !status.base_url) return 'Not set up'
  if (provider === 'compat' && status.openrouter_recognized) return `OpenRouter · ${status.model}`
  // A constructed provider client is not evidence of a successful connection probe.
  return `${status.configured ? 'Configured' : 'Setup saved'} · ${status.base_url}`
}
function stateNote(item: ConfigField): string {
  if (item.apply_state === 'invalid') return 'This saved value is invalid. Correct it and save again.'
  if (item.apply_state === 'drift') return 'The running value differs from the saved value.'
  if (item.apply_state === 'unknown') return 'The running value is not known.'
  return ''
}
async function groupSave(key: string, paths: string[], enable?: boolean): Promise<void> {
  if (busy[key]) return
  const changes: { field: ConfigField; value: unknown }[] = []
  for (const item of present(paths).filter((item) => !isSecret(item) && !(key === 'compat' && item.path === mainEffort.value))) {
    const raw = enable !== undefined && item.type === 'boolean' && item.path.endsWith('.enabled') ? enable : value(item.path)
    if (raw === toInput(item)) continue
    const parsed = fromInput(item, raw)
    if (!parsed.ok) { errors[item.path] = parsed.error; return }
    changes.push({ field: item, value: parsed.value })
  }
  if (!changes.length) return
  busy[key] = true; notes[key] = ''
  const snapshot = Object.fromEntries(paths.map((path) => [path, value(path)]))
  try {
    if (await saveFields(changes)) {
      for (const { field: item } of changes) if (value(item.path) === snapshot[item.path]) delete drafts[item.path]
      notes[key] = 'Saved.'
      if (providers.includes(key as Provider)) void loadModels()
    }
  } finally { busy[key] = false }
}
async function toggleProvider(provider: Provider, enabled: boolean): Promise<void> {
  const path = providerPaths[provider][0]!
  if (!enabled && field('llm_provider.model')?.desired && modelProvider(String(field('llm_provider.model')?.desired)) === provider) {
    const confirmed = await ask({ title: `Disable ${providerNames[provider]}?`, message: 'This provider handles your main model. Main chat will be unavailable until you choose an enabled provider. Your saved setup is kept.', confirmLabel: 'Disable', danger: true })
    if (!confirmed) return
  }
  await groupSave(provider, [path], enabled)
}
async function storeKey(item: ConfigField): Promise<void> {
  const snapshot = secretDrafts[item.path]
  if (!snapshot || busy[item.path] || !keyAvailable(item)) return
  busy[item.path] = true
  try { await setSecret(item, snapshot) }
  finally {
    if (secretDrafts[item.path] === snapshot) delete secretDrafts[item.path]
    busy[item.path] = false
  }
}
async function removeKey(item: ConfigField): Promise<void> {
  if (busy[item.path] || !keyAvailable(item)) return
  if (!await ask({ title: 'Remove this API key?', message: 'Requests requiring this key will stop working.', confirmLabel: 'Remove', danger: true })) return
  busy[item.path] = true
  try { await clearSecret(item) } finally { busy[item.path] = false }
}
const mainPaths = ['llm_provider.model', 'openai_codex.reasoning_effort', 'openai_compatible.reasoning_effort']
const keyAvailable = (item: ConfigField): boolean => item.sensitivity === 'sensitive' && item.secret_route === 'secrets.set'
const mainProvider = computed(() => modelProvider(String(value('llm_provider.model'))))
const mainEffort = computed(() => modelEfforts(String(value('llm_provider.model')))?.length === 0 ? '' : mainProvider.value === 'codex' ? 'openai_codex.reasoning_effort' : mainProvider.value === 'compat' ? 'openai_compatible.reasoning_effort' : '')
async function saveMain(): Promise<void> {
  if (busy.main || !field('llm_provider.model') || !validMainPair.value) return
  const model = String(value('llm_provider.model')).trim()
  if (!model) { errors['llm_provider.model'] = 'Enter a model.'; return }
  const params: Record<string, unknown> = { model }
  if (mainEffort.value && field(mainEffort.value)) params.reasoning_effort = value(mainEffort.value)
  const snapshot = Object.fromEntries(mainPaths.map((path) => [path, value(path)]))
  busy.main = true; notes.main = ''
  try { if (await saveModelSettings('models.main.set', params)) { for (const path of mainPaths) if (value(path) === snapshot[path]) delete drafts[path]; notes.main = 'Saved.'; void loadModels() } }
  finally { busy.main = false }
}
const agentPaths = ['agents.model', 'agents.auto_model_allowlist', 'agents.thinking_mode', 'agents.model_selection_hints']
const agentMode = computed(() => value('agents.model') === 'auto' ? 'auto' : value('agents.model') === '' || value('agents.model') === 'main' ? 'main' : 'fixed')
function chooseAgent(mode: string): void { edit('agents.model', mode === 'main' ? '' : mode === 'auto' ? 'auto' : String(field('agents.model')?.desired ?? '').replace(/^auto$/, '') || String(field('llm_provider.model')?.desired ?? '')) }
type Candidate = string | { model: string; reasoning_effort?: string | null; thinking_mode?: string | null }
const allowlistDraft = ref<Candidate[] | null>(null)
const candidates = computed<Candidate[]>(() => allowlistDraft.value ?? (Array.isArray(field('agents.auto_model_allowlist')?.desired) ? field('agents.auto_model_allowlist')!.desired as Candidate[] : []))
const candidateModel = (item: Candidate): string => typeof item === 'string' ? item : item.model
function updateCandidate(index: number, key: 'model' | 'reasoning_effort' | 'thinking_mode', raw: string): void {
  const next = candidates.value.map((item) => typeof item === 'string' ? item : { ...item })
  const item = next[index]!
  next[index] = key === 'model' && typeof item === 'string' ? raw : { ...(typeof item === 'string' ? { model: item } : item), [key]: raw || null }
  allowlistDraft.value = next
}
function reorder(index: number, delta: number): void { const next = [...candidates.value]; const to = index + delta; if (to < 0 || to >= next.length) return; [next[index], next[to]] = [next[to]!, next[index]!]; allowlistDraft.value = next }
async function saveAgents(): Promise<void> {
  if (busy.agents) return
  const params: Record<string, unknown> = { model: value('agents.model') || null }
  if (allowlistDraft.value) {
    if (candidates.value.some((item) => !candidateModel(item).trim())) { errors.agents = 'Enter a model for every automatic candidate.'; return }
    if (candidates.value.some((item) => typeof item !== 'string' && item.reasoning_effort && item.reasoning_effort !== 'auto' && modelEfforts(item.model)?.includes(item.reasoning_effort) !== true)) { errors.agents = 'Choose supported reasoning efforts for every automatic candidate.'; return }
    params.auto_model_allowlist = candidates.value
  }
  for (const path of agentPaths.slice(2)) if (Object.hasOwn(drafts, path) && field(path)) { const parsed = fromInput(field(path)!, value(path)); if (!parsed.ok) { errors[path] = parsed.error; return }; params[path.split('.').pop()!] = parsed.value }
  const snapshot = JSON.stringify({ model: value('agents.model'), candidates: candidates.value, drafts: agentPaths.map((path) => value(path)) })
  busy.agents = true; notes.agents = ''
  try { if (await saveModelSettings('models.agents.set', params)) { if (snapshot === JSON.stringify({ model: value('agents.model'), candidates: candidates.value, drafts: agentPaths.map((path) => value(path)) })) { cancel(agentPaths); allowlistDraft.value = null }; notes.agents = 'Saved.' } }
  finally { busy.agents = false }
}
const independentAgentPaths = ['agents.max_concurrent_agents']
const agentEffortModels = computed(() => (agentMode.value === 'auto' ? candidates.value.map(candidateModel) : [agentMode.value === 'main' ? String(value('llm_provider.model')) : String(value('agents.model'))]).filter((model) => modelProvider(model) === 'codex'))
const agentEfforts = computed(() => {
  if (!agentEffortModels.value.length || agentEffortModels.value.some((model) => modelEfforts(model) === null)) return null
  return modelEfforts(agentEffortModels.value[0]!)!.filter((effort) => agentEffortModels.value.every((model) => modelEfforts(model)!.includes(effort)))
})
const agentDirty = computed(() => dirty(agentPaths) || (allowlistDraft.value !== null && JSON.stringify(allowlistDraft.value) !== JSON.stringify(field('agents.auto_model_allowlist')?.desired ?? [])))
async function pickAgentEffort(effort: string): Promise<void> {
  const item = field('openai_codex.agent_reasoning_effort')
  if (!item || (effort !== '' && effort !== 'auto' && agentEfforts.value?.includes(effort) !== true)) return
  await saveFields([{ field: item, value: effort || null }])
}
const extraPaths = computed(() => more.value.filter((item) => !item.key.startsWith('openai_compatible.openrouter.') && !agentPaths.includes(item.key) && !item.key.startsWith('openai_codex.auxiliary.') && !item.key.startsWith('image.openai.')).map((item) => item.key))
const imagePaths = ['image.openai.enabled', 'image.openai.outer_model', 'image.openai.image_model']

onMounted(loadCodex)
const copyStatus = ref('')
const refreshUnavailable = ref(false)
const refreshKey = 'codex-refresh'
let alive = true
let pendingRefresh: string | undefined
onUnmounted(() => { alive = false })
onLateReceipt((receipt) => {
  if (!alive || receipt.id !== pendingRefresh) return
  if (!receipt.settled.ok && isUnknownOutcome(receipt.settled.error)) return
  pendingRefresh = undefined
  if (!receipt.settled.ok && isUnavailable(receipt.settled.error)) refreshUnavailable.value = true
})
type RefreshBridge = { codexRefresh?: (params: { index: number }) => Promise<Result<{ status: 'refreshed'; email: string; expired: false }>> }

async function refreshAccount(account: CodexAccount): Promise<void> {
  if (settings.codex.busy || settings.codex.stale || management.busy[refreshKey] || refreshUnavailable.value) return
  const identity = accountIdentity(account)
  const now = settings.codex.status?.accounts.find((entry) => entry.index === account.index)
  if (!now || accountIdentity(now) !== identity) return
  const refresh = (window.odin as unknown as RefreshBridge).codexRefresh
  if (!refresh) { refreshUnavailable.value = true; return }
  settings.codex.busy = true
  settings.codex.stale = true
  await act(refreshKey, async () => {
    const result = await refresh({ index: account.index }).catch((): Result<never> => ({
      ok: false, error: { code: 'bridge_error', message: 'The bridge could not return a result.' }
    }))
    if (!result.ok && isUnknownOutcome(result.error)) pendingRefresh = result.error.command_id
    if (!result.ok && isUnavailable(result.error)) refreshUnavailable.value = true
    return result
  }, (answer) => `Sign-in refreshed for ${answer.email}.`, async () => {
    try { settings.codex.stale = !await loadCodex() }
    finally { settings.codex.busy = false }
  })
}
const loginAnnouncement = computed(() => {
  const login = settings.codex.login
  if (!login) return ''
  if (login.status === 'waiting') return 'Waiting for sign-in approval in the browser.'
  if (login.status === 'stopped') return 'Stopped waiting. This app is no longer checking or finishing that login. Add an account to start again.'
  return login.message ?? (login.status === 'done' ? 'Account added.' : `Sign-in ${login.status}.`)
})
watch(() => settings.codex.login?.code, () => { copyStatus.value = '' })
async function copyCode(): Promise<void> {
  const login = settings.codex.login
  if (!login || login.status !== 'waiting') return
  const result = await window.odin.copyText(login.code)
  copyStatus.value = result.ok ? 'Sign-in code copied.' : 'Could not copy the sign-in code.'
}
const accountName = (account: CodexAccount): string => account.label || account.email || `Account ${account.index + 1}`

async function openVerification(): Promise<void> {
  const result = await window.odin.codexOpenVerification()
  if (!result.ok) settings.codex.error = result.error.message
}

function windowName(minutes: number): string {
  if (minutes >= 10080) return 'weekly'
  if (minutes >= 1440) return `${Math.round(minutes / 1440)}-day`
  return `${Math.round(minutes / 60)}-hour`
}

function resets(window: QuotaWindow): string {
  if (!window.resets_at) return ''
  return `, resets ${new Date(window.resets_at * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}`
}

/** Odin's quota as reported by the account's own replies: percent used, never a guess. */
function quota(account: CodexAccount): string {
  const windows = [account.quota?.primary, account.quota?.secondary].filter((w): w is QuotaWindow => Boolean(w))
  if (!windows.length) return 'Quota not reported yet'
  return windows.map((w) => `${Math.round(w.used_percent)}% of the ${windowName(w.window_minutes)} limit used${resets(w)}`).join('; ')
}

async function rename(account: CodexAccount): Promise<void> {
  const label = await ask({
    title: 'Label this account',
    message: '',
    confirmLabel: 'Save',
    input: { value: account.label ?? '', label: 'Label', maxLength: 80 }
  })
  if (typeof label === 'string') await labelAccount(account, label.trim())
}

async function remove(account: CodexAccount): Promise<void> {
  const confirmed = await ask({
    title: 'Remove this account?',
    message: `Odin stops using ${account.email ?? 'this account'}. You can sign in with it again later.`,
    confirmLabel: 'Remove',
    danger: true
  })
  if (confirmed) await removeAccount(account)
}
</script>

<template>
  <SettingsSection v-if="field('llm_provider.model')" title="Main model">
    <SettingsRow label="Model" description="Choose the model used for main chat." :control-id="modelId('llm_provider.model')">
      <select :id="modelId('llm_provider.model')" :value="value('llm_provider.model')" @change="edit('llm_provider.model', ($event.target as HTMLSelectElement).value)">
        <option v-if="!modelRow(String(value('llm_provider.model')))" :value="value('llm_provider.model')" disabled>{{ value('llm_provider.model') }} (choices unavailable)</option>
        <option v-for="row in modelCatalogue" :key="row.ref" :value="row.ref">{{ row.name ?? row.ref }} · {{ row.ref }}</option>
      </select>
      <button class="ghost model-refresh" @click="loadModels">Refresh model choices</button>
    </SettingsRow>
    <SettingsRow v-if="mainEffort && field(mainEffort)" label="Reasoning effort" description="Choose how much reasoning the model uses." :control-id="modelId(mainEffort)">
      <select :id="modelId(mainEffort)" :value="value(mainEffort)" :disabled="!modelEfforts(String(value('llm_provider.model')))?.length" @change="edit(mainEffort, ($event.target as HTMLSelectElement).value)">
        <option v-if="!modelEfforts(String(value('llm_provider.model')))?.includes(String(value(mainEffort)))" :value="value(mainEffort)" disabled>{{ value(mainEffort) }} (choose a supported effort)</option>
        <option v-for="effort in modelEfforts(String(value('llm_provider.model'))) ?? []" :key="effort" :value="effort">{{ effort }}</option>
      </select>
      <template #note><p v-if="modelEfforts(String(value('llm_provider.model'))) === null" class="settings-help">Supported effort choices are not known for this model.</p><p v-else-if="!validMainPair" class="warn">Choose an effort supported by this model. The saved effort is not changed automatically.</p></template>
    </SettingsRow>
    <p v-if="modelReadError" role="status" class="warn">{{ modelReadError }}</p>
    <p v-if="busy.main" role="status">Saving…</p><p v-else-if="notes.main" role="status">{{ notes.main }}</p>
    <p v-for="item in present(mainPaths)" :key="item.path" class="warn" role="status">{{ errors[item.path] || (settings.fields[item.path]?.status === 'error' ? settings.fields[item.path]?.message : '') || stateNote(item) }}</p>
    <div v-if="dirty(mainPaths)" id="main-model-actions" class="settings-editor-actions model-actions" data-testid="main-model-actions">
      <span>Unsaved changes</span>
      <button :disabled="busy.main || !validMainPair" @click="saveMain">Save</button>
      <button class="ghost" @click="cancel(mainPaths)">Cancel</button>
    </div>
  </SettingsSection>
  <SettingsSection title="Context">
    <ContextUse v-if="activeContext" :key="activeContext.path" :field="activeContext" />
    <p v-else class="settings-help context-unavailable">{{ activeProvider === 'ollama' ? 'Ollama context limits are under More options.' : 'Context use is unavailable until the active provider is known.' }}</p>
  </SettingsSection>
  <SettingsSection v-if="field('agents.model')" title="Agents">
    <SettingsRow label="Agent model" description="Agents can follow main chat or use a separate model." :control-id="modelId(agentMode === 'fixed' ? 'agents.model.mode' : 'agents.model')">
      <select :id="modelId(agentMode === 'fixed' ? 'agents.model.mode' : 'agents.model')" :value="agentMode" @change="chooseAgent(($event.target as HTMLSelectElement).value)">
        <option value="main">Same as main</option><option value="auto">Choose automatically</option><option value="fixed">Choose a model</option>
      </select>
    </SettingsRow>
    <SettingsRow v-if="agentMode === 'fixed'" label="Chosen model" :control-id="modelId('agents.model')">
      <select :id="modelId('agents.model')" :value="value('agents.model')" @change="edit('agents.model', ($event.target as HTMLSelectElement).value)"><option v-if="!modelRow(String(value('agents.model')))" :value="value('agents.model')" disabled>{{ value('agents.model') }} (choices unavailable)</option><option v-for="row in modelCatalogue" :key="row.ref" :value="row.ref">{{ row.name ?? row.ref }} · {{ row.ref }}</option></select>
    </SettingsRow>
    <div v-if="agentMode === 'auto' && field('agents.auto_model_allowlist')" :id="modelId('agents.auto_model_allowlist')" tabindex="-1" class="model-candidates">
      <h4>Automatic candidates</h4>
      <p class="settings-help">Order sets preference. Per-model effort and thinking choices must be compatible with that model.</p>
      <p v-if="!candidates.length">No candidates. Add a model for automatic selection.</p>
      <div v-for="(candidate, index) in candidates" :key="index" class="model-candidate">
        <label :for="modelId(`agents.auto_model_allowlist.${index}.model`)">Model {{ index + 1 }}</label>
        <select :id="modelId(`agents.auto_model_allowlist.${index}.model`)" :value="candidateModel(candidate)" @change="updateCandidate(index, 'model', ($event.target as HTMLSelectElement).value)"><option v-if="!modelRow(candidateModel(candidate))" :value="candidateModel(candidate)" disabled>{{ candidateModel(candidate) || 'Choose a model' }}</option><option v-for="row in modelCatalogue" :key="row.ref" :value="row.ref">{{ row.ref }}</option></select>
        <label :for="modelId(`agents.auto_model_allowlist.${index}.reasoning_effort`)">Reasoning effort {{ index + 1 }}</label>
        <select :id="modelId(`agents.auto_model_allowlist.${index}.reasoning_effort`)" :value="typeof candidate === 'string' ? '' : candidate.reasoning_effort ?? ''" @change="updateCandidate(index, 'reasoning_effort', ($event.target as HTMLSelectElement).value)">
          <option v-if="typeof candidate !== 'string' && candidate.reasoning_effort && candidate.reasoning_effort !== 'auto' && !modelEfforts(candidateModel(candidate))?.includes(candidate.reasoning_effort)" :value="candidate.reasoning_effort" disabled>{{ candidate.reasoning_effort }} (not supported)</option>
          <option value="">Use agent policy</option><option value="auto">Choose automatically</option>
          <option v-for="effort in modelEfforts(candidateModel(candidate)) ?? []" :key="effort" :value="effort">{{ effort }}</option>
        </select>
        <label :for="modelId(`agents.auto_model_allowlist.${index}.thinking_mode`)">Thinking mode {{ index + 1 }}</label>
        <select :id="modelId(`agents.auto_model_allowlist.${index}.thinking_mode`)" :disabled="modelProvider(candidateModel(candidate)) === 'codex'" :value="typeof candidate === 'string' ? '' : candidate.thinking_mode ?? ''" @change="updateCandidate(index, 'thinking_mode', ($event.target as HTMLSelectElement).value)">
          <option value="">Use agent policy</option><option v-for="mode in field('agents.thinking_mode')?.enum ?? []" :key="mode" :value="mode">{{ mode }}</option>
        </select>
        <div class="settings-actions">
          <button class="ghost" :aria-label="`Move model ${index + 1} up`" :disabled="index === 0" @click="reorder(index, -1)">Move up</button>
          <button class="ghost" :aria-label="`Move model ${index + 1} down`" :disabled="index === candidates.length - 1" @click="reorder(index, 1)">Move down</button>
          <button class="ghost" :aria-label="`Remove model ${index + 1}`" @click="allowlistDraft = candidates.filter((_, at) => at !== index)">Remove</button>
        </div>
      </div>
      <button class="ghost" @click="allowlistDraft = [...candidates, '']">Add automatic candidate</button>
    </div>
    <p v-if="errors.agents" role="status" class="warn">{{ errors.agents }}</p>
    <p v-if="busy.agents" role="status">Saving…</p><p v-else-if="notes.agents" role="status">{{ notes.agents }}</p>
    <p v-for="item in present(agentPaths)" :key="item.path" class="warn" role="status">{{ settings.fields[item.path]?.status === 'error' ? settings.fields[item.path]?.message : stateNote(item) }}</p>
    <SettingsRow v-if="field('openai_codex.agent_reasoning_effort')" label="Agent reasoning effort" description="Automatic lets Odin choose the effort for each task." :control-id="modelId('openai_codex.agent_reasoning_effort')">
      <select :id="modelId('openai_codex.agent_reasoning_effort')" :value="String(field('openai_codex.agent_reasoning_effort')?.desired ?? '')" @change="pickAgentEffort(($event.target as HTMLSelectElement).value)">
        <option value="">Same as main</option><option value="auto">Automatic</option>
        <option v-if="field('openai_codex.agent_reasoning_effort')?.desired && field('openai_codex.agent_reasoning_effort')?.desired !== 'auto' && !agentEfforts?.includes(String(field('openai_codex.agent_reasoning_effort')?.desired))" :value="String(field('openai_codex.agent_reasoning_effort')?.desired)" disabled>{{ field('openai_codex.agent_reasoning_effort')?.desired }} (not supported by these models)</option>
        <option v-for="effort in agentEfforts ?? []" :key="effort" :value="effort">{{ effort }}</option>
      </select>
      <template #note><p v-if="agentEfforts === null" class="settings-help">Fixed effort choices are unavailable until model capabilities are known.</p><p v-if="settings.fields['openai_codex.agent_reasoning_effort']?.status === 'error'" class="warn" role="status">{{ settings.fields['openai_codex.agent_reasoning_effort']?.message }}</p></template>
    </SettingsRow>
    <SettingEditor v-for="item in present(independentAgentPaths)" :key="item.path" :field="item" :label="label(item.path)" :help="help(item.path)" />
    <div v-if="agentDirty" id="agent-model-actions" class="model-actions settings-editor-actions" data-testid="agent-model-actions">
      <span>Unsaved changes</span>
      <button :disabled="busy.agents" @click="saveAgents">Save</button>
      <button class="ghost" @click="cancel(agentPaths); allowlistDraft = null">Cancel</button>
    </div>
  </SettingsSection>
  <SettingsSection title="Accounts and quota">
    <template #actions>
      <button v-if="!settings.codex.unavailable" data-testid="codex-add-account" class="ghost" :disabled="settings.codex.busy || settings.codex.beginning || settings.codex.login?.status === 'waiting'" @click="beginLogin">Add account</button>
    </template>
  <section class="codex-accounts" aria-label="Codex accounts">
    <p v-if="settings.codex.unavailable" class="capability-unavailable" role="status">{{ unavailableText('Codex accounts') }}</p>
    <template v-else>
      <div v-if="settings.codex.login" class="login">
      <p role="status" aria-atomic="true">{{ loginAnnouncement }}</p>
      <template v-if="settings.codex.login.status === 'waiting'">
        <p>
          Open <button class="ghost" data-testid="codex-open-verification" aria-describedby="codex-login-browser" @click="openVerification">{{ settings.codex.login.url }}</button>
          and enter the sign-in code. Odin adds the account once you approve it.
        </p>
        <p id="codex-login-browser" class="panel-hint">Opens in your browser. The sign-in code is temporary; your stored credentials are never shown here.</p>
        <p>Sign-in code: <code class="login-code">{{ settings.codex.login.code }}</code></p>
        <button class="ghost" @click="copyCode">Copy sign-in code</button>
        <p v-if="copyStatus" role="status">{{ copyStatus }}</p>
        <button class="ghost" data-testid="codex-cancel-login" @click="stopLogin">Stop waiting</button>
      </template>
      <button v-if="settings.codex.login.status === 'failed'" class="ghost" data-testid="codex-retry-login" @click="retryLogin">Retry login</button>
      </div>
      <p v-if="settings.codex.error" class="warn" role="status">{{ settings.codex.error }} <button class="ghost" @click="loadCodex">Retry accounts</button></p>
      <p v-if="settings.codex.busy" role="status">Updating Codex accounts.</p>
      <p v-if="refreshUnavailable" class="capability-unavailable" role="status">{{ unavailableText('Codex sign-in refresh') }}</p>
      <p v-if="management.notes[refreshKey]" role="status">{{ management.notes[refreshKey] }}</p>
      <p v-if="settings.codex.stale && !settings.codex.busy" class="warn">
        The list couldn't be refreshed after your last change, so it may be out of date.
        <button class="ghost" @click="loadCodex">Refresh</button>
      </p>
      <p v-else-if="settings.codex.status && !settings.codex.status.accounts.length" class="panel-hint">No accounts. Add an account to use Codex.</p>
      <p v-if="!settings.codex.status && !settings.codex.error && !settings.codex.unavailable" role="status">Loading accounts…</p>
      <ul class="accounts">
        <li v-for="account in settings.codex.status?.accounts ?? []" :key="account.index" :class="['account', { current: account.is_current }]">
            <div class="account-details">
              <strong>{{ accountName(account) }}</strong>
              <div class="account-meta">{{ account.email }}<template v-if="account.plan_type"> · {{ account.plan_type }}</template></div>
              <div class="account-meta">{{ quota(account) }}</div>
              <p v-if="account.error" class="warn">Account {{ account.index + 1 }}: {{ account.error }}</p>
              <p v-if="settings.codex.notes[accountIdentity(account)]" class="account-note" role="status">{{ settings.codex.notes[accountIdentity(account)] }}</p>
            </div>
            <div class="account-controls">
              <div class="account-status">
              <span v-if="account.is_current" class="in-use">In use</span>
              <span v-if="account.limit_reached" class="warn">Limit reached</span>
              <span v-if="account.quota_check_failed" class="warn">Quota check failed</span>
              <span v-if="account.expired" class="warn">Sign-in expired</span>
            </div>
            <div class="account-actions">
              <button v-if="!account.is_current && !account.error" class="ghost" :aria-label="`Use this account: ${accountName(account)}`" :disabled="settings.codex.busy || settings.codex.stale" @click="activateAccount(account)">
                Use this account
              </button>
              <button class="ghost" :aria-label="`Refresh sign-in: ${accountName(account)}`" :disabled="settings.codex.busy || settings.codex.stale || management.busy[refreshKey] || refreshUnavailable" @click="refreshAccount(account)">Refresh sign-in</button>
              <button v-if="!account.error" class="ghost" :aria-label="`Rename ${accountName(account)}`" :disabled="settings.codex.busy || settings.codex.stale" @click="rename(account)">Rename</button>
              <button class="ghost danger-item" :aria-label="`Remove ${accountName(account)}`" :disabled="settings.codex.busy || settings.codex.stale" @click="remove(account)">Remove…</button>
            </div>
            </div>
        </li>
      </ul>
    </template>
  </section>
  </SettingsSection>
  <SettingsSection v-if="providers.some((provider) => field(providerPaths[provider][0]!))" title="Providers">
    <template v-for="provider in providers" :key="provider">
      <SettingsRow v-if="field(providerPaths[provider][0]!)" :label="providerNames[provider]" :description="providerSummary(provider)">
        <SettingsSwitch :id="modelId(providerPaths[provider][0]!)" :label="`Enable ${providerNames[provider]}`" :checked="field(providerPaths[provider][0]!)?.desired === true" :disabled="busy[provider]" @change="toggleProvider(provider, $event)" />
        <button class="ghost" :data-testid="`configure-${provider}`" :aria-label="`Configure ${providerNames[provider]}`" :aria-expanded="expanded[provider]" :aria-controls="`provider-${provider}-setup`" @click="expanded[provider] = !expanded[provider]">Configure</button>
      </SettingsRow>
      <section v-if="expanded[provider]" :id="`provider-${provider}-setup`" class="provider-setup" :aria-label="`${providerNames[provider]} setup`">
        <h4>{{ providerNames[provider] }} setup</h4>
        <p v-if="provider === 'codex'" class="settings-help">Use Add account above to sign in. Account setup is kept when Codex is disabled.</p>
        <SettingsRow v-for="item in providerFields(provider)" :key="item.path" :label="label(item.path)" :description="help(item.path)" :control-id="modelId(item.path)" :full-width="isSecret(item) || item.path.endsWith('base_url')">
          <template v-if="isSecret(item)">
            <span>{{ item.configured === null ? 'Saved key status unavailable' : item.configured ? 'Key stored' : 'No key stored' }}</span>
            <input :id="modelId(item.path)" :value="secretDrafts[item.path] ?? ''" :disabled="!keyAvailable(item)" type="password" autocomplete="new-password" placeholder="New API key" @input="secretDrafts[item.path] = ($event.target as HTMLInputElement).value" />
            <button :disabled="!keyAvailable(item) || !secretDrafts[item.path] || busy[item.path]" :aria-label="`${item.configured ? 'Replace' : 'Store'} ${providerNames[provider]} API key`" @click="storeKey(item)">{{ item.configured ? 'Replace key' : 'Store key' }}</button>
            <button v-if="item.configured" class="ghost" :disabled="!keyAvailable(item) || busy[item.path]" :aria-label="`Remove ${providerNames[provider]} API key`" @click="removeKey(item)">Remove key</button>
          </template>
          <select v-else-if="item.enum" :id="modelId(item.path)" :value="value(item.path)" @change="edit(item.path, ($event.target as HTMLSelectElement).value)"><option v-for="option in item.enum" :key="option" :value="option">{{ option }}</option></select>
          <input v-else :id="modelId(item.path)" :value="value(item.path)" @input="edit(item.path, ($event.target as HTMLInputElement).value)" />
          <template #note><p v-if="errors[item.path] || settings.fields[item.path]?.status === 'error' || stateNote(item)" class="warn" role="status">{{ errors[item.path] || settings.fields[item.path]?.message || stateNote(item) }}</p></template>
        </SettingsRow>
        <ContextUse v-if="provider === 'compat' && field('openai_compatible.context_utilization') && activeContext?.path !== 'openai_compatible.context_utilization'" :field="field('openai_compatible.context_utilization')!" />
        <ContextUse v-if="provider === 'codex' && field('openai_codex.context_utilization') && activeContext?.path !== 'openai_codex.context_utilization'" :field="field('openai_codex.context_utilization')!" />
        <div v-if="provider !== 'codex'" class="settings-editor-actions model-actions">
          <span v-if="dirty(providerPaths[provider])">Unsaved changes</span>
          <button :disabled="!dirty(providerPaths[provider]) || busy[provider]" @click="groupSave(provider, providerPaths[provider])">Save {{ providerNames[provider] }} setup</button>
          <button class="ghost" @click="cancel(providerPaths[provider])">Cancel {{ providerNames[provider] }} changes</button>
        </div>
        <p v-if="busy[provider]" role="status">Saving…</p><p v-else-if="notes[provider]" role="status">{{ notes[provider] }}</p>
        <OpenRouterAdmin v-if="provider === 'compat'" />
      </section>
    </template>
  </SettingsSection>
  <details class="settings-more-options">
    <summary>More options</summary>
    <SettingsSection title="Model policies">
      <SettingEditor v-for="item in present(extraPaths)" :key="item.path" :field="item" :label="label(item.path)" :help="help(item.path)" :commit="item.path === 'openai_compatible.reasoning_content_feedback_policy' ? 'explicit' : 'automatic'" />
      <SettingsRow v-for="item in present(agentPaths.slice(2))" :key="item.path" :label="label(item.path)" :description="help(item.path)" :control-id="modelId(item.path)" :full-width="item.type === 'object'">
        <select v-if="item.enum" :id="modelId(item.path)" :value="value(item.path)" @change="edit(item.path, ($event.target as HTMLSelectElement).value)"><option value="">Follow model default</option><option v-for="option in item.enum" :key="option" :value="option">{{ option }}</option></select>
        <textarea v-else :id="modelId(item.path)" rows="4" :value="String(value(item.path))" @input="edit(item.path, ($event.target as HTMLTextAreaElement).value)" />
        <template #note><p v-if="errors[item.path]" class="warn" role="status">{{ errors[item.path] }}</p></template>
      </SettingsRow>
      <button v-if="dirty(agentPaths.slice(2))" @click="saveAgents">Save agent options</button>
      <button v-if="dirty(agentPaths.slice(2))" class="ghost" @click="cancel(agentPaths.slice(2))">Cancel agent options</button>
    </SettingsSection>
    <SettingsSection v-if="field('openai_codex.auxiliary.model')" title="Auxiliary model">
      <SettingsRow label="Model" description="Use a separate model for background work." :control-id="modelId('openai_codex.auxiliary.model')"><input :id="modelId('openai_codex.auxiliary.model')" :value="value('openai_codex.auxiliary.model')" @input="edit('openai_codex.auxiliary.model', ($event.target as HTMLInputElement).value)" /></SettingsRow>
      <SettingsRow v-if="field('openai_codex.auxiliary.enabled')" label="Enable auxiliary model" :control-id="modelId('openai_codex.auxiliary.enabled')"><SettingsSwitch :id="modelId('openai_codex.auxiliary.enabled')" label="Enable auxiliary model" :checked="value('openai_codex.auxiliary.enabled') === true" @change="edit('openai_codex.auxiliary.enabled', $event)" /></SettingsRow>
      <div class="settings-editor-actions model-actions"><button :disabled="!dirty(['openai_codex.auxiliary.model', 'openai_codex.auxiliary.enabled']) || busy.auxiliary" @click="groupSave('auxiliary', ['openai_codex.auxiliary.model', 'openai_codex.auxiliary.enabled'])">Save auxiliary model</button><button class="ghost" @click="cancel(['openai_codex.auxiliary.model', 'openai_codex.auxiliary.enabled'])">Cancel auxiliary changes</button></div>
    </SettingsSection>
    <SettingsSection v-if="present(imagePaths).length" title="Images">
      <SettingEditor v-for="item in present(imagePaths)" :key="item.path" :field="item" :label="label(item.path)" :help="help(item.path)" commit="explicit" />
      <SettingsRow v-for="leaf in (['outer_model', 'image_model'] as ImageLeaf[])" :key="leaf" v-show="settings.meta?.image_models?.[leaf]" :label="leaf === 'outer_model' ? 'Image host model policy' : 'Image model policy'">
        <template v-if="settings.meta?.image_models?.[leaf]">
          <span>{{ settings.meta.image_models[leaf].status === 'follow' ? `Following default: ${settings.meta.image_models[leaf].default}` : `Pinned: ${settings.meta.image_models[leaf].effective}` }}</span>
          <button class="ghost" :disabled="settings.fields[`image.openai.${leaf}`]?.status === 'saving'" @click="setImageIntent(leaf, settings.meta!.image_models![leaf].status === 'follow' ? 'pin' : 'follow')">{{ settings.meta.image_models[leaf].status === 'follow' ? 'Pin current value' : 'Follow default' }}</button>
        </template>
      </SettingsRow>
    </SettingsSection>
  </details>
</template>

<style scoped>
.codex-accounts, .provider-setup, .model-candidates { padding: 1rem; }
.provider-setup { border-bottom: 1px solid var(--border); }
.model-actions { padding: .75rem 1rem; flex-wrap: wrap; justify-content: flex-end; }
.model-refresh { font-size: 12px; }
.context-unavailable { padding: 1rem; margin: 0; }
.model-candidate { display: grid; gap: .5rem; padding: .75rem 0; border-bottom: 1px solid var(--border); }
.model-candidate input, .model-candidate select { width: 100%; min-width: 0; }
.model-candidates h4, .provider-setup h4 { margin-top: 0; }
.account { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
.account-details { flex: 1 1 45%; min-width: 0; }
.account-controls { flex: 1 1 50%; min-width: 0; text-align: right; }
.account-status, .account-actions { display: flex; justify-content: flex-end; gap: .5rem; flex-wrap: wrap; }
.account-actions { margin-top: .5rem; }
.account-meta { overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .account { flex-direction: column; align-items: stretch; }
  .account-controls { text-align: left; }
  .account-status, .account-actions { justify-content: flex-start; }
}
</style>
