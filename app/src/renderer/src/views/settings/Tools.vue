<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import type { BuiltinTool } from '../../../../shared/api'
import { loadTools, management, saveTimeouts, setToolEnabled } from '../../stores/management'
import { settingsUnavailableText as unavailableText } from '../../capability'
import { browser, loadBrowserStatus } from '../../stores/browser'
import SettingEditor from '../../components/settings/SettingEditor.vue'
import SecretControl from '../../components/settings/SecretControl.vue'
import { isSecret } from '../../settings-form'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import SettingsRow from '../../components/settings/SettingsRow.vue'
import SettingsSwitch from '../../components/settings/SettingsSwitch.vue'
import { settingsFields } from '../../settings-presentation'
import { settings } from '../../stores/settings'
import { ask } from '../../dialog'
import { computerReadiness, computerReleaseUncertain, computerSession, isDesktopComputer, legacyComputer, loadComputer, reasonText, reconcileComputer, records } from '../../stores/records'

const filter = ref('')
const browserSetup = ref(false)
const emailSetup = ref(false)
const props = defineProps<{ reveal?: string }>()
watch(() => props.reveal, (reveal) => {
  const path = reveal?.split(':')[0] ?? ''
  if (path.startsWith('browser.') && path !== 'browser.enabled') browserSetup.value = true
  if (path.startsWith('email.') && path !== 'email.enabled') emailSetup.value = true
}, { immediate: true })
const primary = computed(() => settingsFields('tools').map((entry) => ({ ...entry, field: settings.meta?.fields.find((field) => field.path === entry.key) })).filter((entry) => entry.field))
const more = computed(() => settingsFields('tools', 'more-options').map((entry) => ({ ...entry, field: settings.meta?.fields.find((field) => field.path === entry.key) })).filter((entry) => entry.field))
const availability = computed(() => primary.value.filter((entry) => entry.key === 'tools.enabled'))
const browserFields = computed(() => primary.value.filter((entry) => entry.key === 'browser.enabled'))
const emailFields = computed(() => primary.value.filter((entry) => entry.key === 'email.enabled'))
const emailAccount = computed(() => primary.value.filter((entry) => entry.key.startsWith('email.') && entry.key !== 'email.enabled'))
const computerFields = computed(() => primary.value.filter((entry) => entry.key === 'computer.enabled'))
const browserMore = computed(() => more.value.filter((entry) => entry.key.startsWith('browser.')))
const emailMore = computed(() => more.value.filter((entry) => entry.key.startsWith('email.')))
const toolMore = computed(() => more.value.filter((entry) => entry.key.startsWith('tools.') && !['tools.command_timeout_seconds', 'tools.tool_timeouts'].includes(entry.key)))
const session = computed(() => computerSession(records.computer))
const readiness = computed(() => computerReadiness(records.computer))
const legacy = computed(() => legacyComputer(records.computer))
const computerKey = computed(() => `computer:${session.value?.session_id ?? ''}`)
async function reconcile(): Promise<void> {
  const status = records.computer
  if (!status) return
  if (isDesktopComputer(status)) { await reconcileComputer(status); return }
  const confirmed = await ask({ title: 'Release this session?', message: 'Odin could not confirm that it let go of the mouse and keyboard. Check the computer first. Releasing this session only records that you checked; input release still remains unverified. Do not resume computer use until cleanup is verified.', confirmLabel: 'Release', danger: true })
  if (confirmed) await reconcileComputer(status)
}
const expanded = reactive<Record<string, boolean | undefined>>({})
const STATES: Record<BuiltinTool['state'], string> = {
  available: 'Available',
  disabled: 'Off',
  global_disabled: 'Tools are off',
  unavailable: 'Not configured here'
}

const tools = computed(() => {
  const words = filter.value.trim().toLowerCase()
  return (management.tools?.tools ?? []).filter((t) => !words || `${t.name} ${t.description}`.toLowerCase().includes(words))
})

// Timeouts: the default, and one line per tool that has its own.
const defaultTimeout = ref<string>('')
const overrides = ref<Array<{ name: string; seconds: string }>>([])
const timeoutError = ref('')
const timeoutErrorField = ref<'default' | number | null>(null)
watch([defaultTimeout, overrides], () => {
  timeoutError.value = ''
  timeoutErrorField.value = null
}, { deep: true })

function editTimeouts(): void {
  defaultTimeout.value = String(management.timeouts?.default_timeout ?? '')
  overrides.value = Object.entries(management.timeouts?.overrides ?? {}).map(([name, seconds]) => ({ name, seconds: String(seconds) }))
}

async function save(): Promise<void> {
  timeoutError.value = ''
  const draft = JSON.stringify([defaultTimeout.value, overrides.value])
  timeoutErrorField.value = null
  const parsed: Record<string, number> = {}
  for (const [index, row] of overrides.value.entries()) {
    if (!row.name.trim()) continue
    const seconds = Number(row.seconds)
    if (!Number.isInteger(seconds) || seconds <= 0) {
      timeoutError.value = `${row.name}: a timeout is a whole number of seconds above zero.`
      timeoutErrorField.value = index
      return
    }
    parsed[row.name.trim()] = seconds
  }
  const fallback = Number(defaultTimeout.value)
  if (!Number.isInteger(fallback) || fallback <= 0) {
    timeoutError.value = 'The default is a whole number of seconds above zero.'
    timeoutErrorField.value = 'default'
    return
  }
  if (await saveTimeouts({ default_timeout: fallback, overrides: parsed }) && JSON.stringify([defaultTimeout.value, overrides.value]) === draft) editTimeouts()
}

onMounted(async () => {
  await Promise.all([loadTools(), loadBrowserStatus(), loadComputer()])
  editTimeouts()
})
</script>

<template>
  <SettingsSection v-if="availability.length" title="Availability">
    <SettingEditor v-for="entry in availability" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" />
  </SettingsSection>
  <SettingsSection title="Browser" aria-label="Browser runtime">
    <SettingEditor v-for="entry in browserFields" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" />
    <SettingsRow label="Browser setup" description="Odin launches its own browser unless you supply an existing browser address.">
      <button class="ghost" aria-label="Configure browser" :aria-expanded="browserSetup" aria-controls="browser-setup" @click="browserSetup = !browserSetup">Configure</button>
      <button class="ghost" aria-label="Refresh status for browser" :disabled="browser.busy" @click="loadBrowserStatus">Refresh status</button>
    </SettingsRow>
    <p v-if="browser.error" class="warn" role="status">Couldn't read browser status: {{ browser.error }}{{ browser.status ? ' Showing the last read.' : '' }}</p>
    <template v-if="browser.status">
      <p class="settings-help">{{ browser.status.state }}. {{ browser.status.ready ? 'Ready for browser requests.' : 'Not ready.' }}</p>
      <p v-if="browser.status.reason" class="manage-desc">Reason: {{ browser.status.reason }}</p>
      <p class="manage-desc" role="status">{{ browser.status.ready ? 'Refresh only checks status; it does not open the browser.' : browser.status.retry_available ? 'The next browser request can check availability again; this does not mean the browser is ready. Refresh does not open it.' : 'No next-use retry is reported. Refresh only checks status. Open Configure to review setup.' }}</p>
    </template>
    <p v-else-if="browser.loaded" class="capability-unavailable" role="status">Browser status is not available here.</p>
    <p v-else-if="!browser.error" class="manage-desc" role="status">Browser status has not been read.</p>
    <div v-if="browserSetup" id="browser-setup">
      <SettingEditor v-for="entry in browserMore" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" commit="explicit" />
      <p v-if="!browserMore.length" role="status">Browser setup settings are not available. Refresh saved settings to try again.</p>
    </div>
  </SettingsSection>

  <SettingsSection title="Email">
    <SettingEditor v-for="entry in emailFields" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" />
    <SettingsRow label="Mail account" description="Set up incoming and outgoing mail while email tools are off.">
      <button class="ghost" aria-label="Configure email" :aria-expanded="emailSetup" aria-controls="email-setup" @click="emailSetup = !emailSetup">Configure</button>
    </SettingsRow>
    <div v-if="emailSetup" id="email-setup">
      <template v-for="entry in emailAccount" :key="entry.key">
        <SecretControl v-if="isSecret(entry.field!)" :field="entry.field!" :label="entry.label" :help="entry.help" />
        <SettingEditor v-else :field="entry.field!" :label="entry.label" :help="entry.help" commit="explicit" />
      </template>
      <p v-if="!emailAccount.length" role="status">Email setup settings are not available. Refresh saved settings to try again.</p>
      <details><summary>More options</summary><SettingEditor v-for="entry in emailMore" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" commit="explicit" /></details>
    </div>
  </SettingsSection>

  <SettingsSection title="Computer use" aria-label="Computer use">
    <SettingEditor v-for="entry in computerFields" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" />
    <SettingsRow label="Desktop availability" description="Turning this on is not consent to control your desktop."><button class="ghost" aria-label="Refresh computer use" @click="loadComputer">Refresh</button></SettingsRow>
    <p v-if="records.unavailable.computer" role="status">{{ unavailableText('Computer use') }}</p>
    <p v-if="records.errors.computer" class="warn">Couldn't read computer use: {{ records.errors.computer }}{{ records.computer ? ' Showing the last read.' : '' }}</p>
    <template v-if="readiness">
      <p v-if="readiness.foreground_available" role="status">Foreground computer use is available on X11. Each request still needs consent and a verified target.</p>
      <p v-else class="capability-unavailable" role="status">Desktop input is unavailable: {{ reasonText(readiness.reason) }}.</p>
      <p class="manage-desc">X11 requires your current signed-in desktop. Wayland input is not supported here; switching this on does not change that.</p>
      <p v-if="!session" class="manage-desc">No session is reported. This does not confirm that mouse and keyboard input was released.</p>
      <p v-else class="manage-desc">Check recovery only reviews the recorded session. It does not start a session or send input.</p>
    </template>
    <p v-if="legacy" class="manage-desc">{{ legacy.enabled ? 'On' : 'Off' }}: {{ legacy.state }}.</p>
    <template v-if="session?.session_id">
      <SettingsRow label="Computer-use session" :description="session.state === 'quarantined' ? 'Odin lost track of a computer-use session. Check recovery before using computer use again.' : `Session state: ${session.state}`">
        <button v-if="session.state === 'quarantined' && readiness" class="ghost" :aria-label="`Check recovery for session ${session.session_id}`" :disabled="management.busy[computerKey] || !readiness.management_available" @click="reconcile">Check recovery</button>
        <button v-else-if="session.state === 'quarantined'" class="ghost danger-item" :aria-label="`Release session ${session.session_id}…`" :disabled="management.busy[computerKey]" @click="reconcile">Release…</button>
      </SettingsRow>
      <details class="computer-session-details"><summary>Session details</summary><p class="manage-desc">Session: {{ session.session_id }} · State: {{ session.state }}</p></details>
      <p v-if="session.recovery" :class="session.recovery.complete ? 'manage-desc' : 'warn'">Recovery: {{ session.recovery.status.replace(/_/g, ' ') }}, because {{ reasonText(session.recovery.reason) }}. {{ session.recovery.complete ? 'Recovery is recorded as complete; this does not grant desktop input.' : 'Recovery is incomplete. Do not resume desktop input.' }}</p>
      <p v-if="computerReleaseUncertain(session)" class="warn">Input release remains unverified.</p>
      <p v-if="management.notes[computerKey]" class="manage-note" role="status">{{ management.notes[computerKey] }}</p>
    </template>
  </SettingsSection>

  <SettingsSection title="Built-in tools" aria-label="Built-in tools">
    <SettingsRow label="Find a tool" control-id="tool-filter">
      <span v-if="!management.unavailable.tools && management.tools" class="panel-hint">
        {{ management.tools.tools.length }} tools, {{ management.tools.disabled_count }} switched off. Permissions still apply.
      </span>
      <label v-if="!management.unavailable.tools" class="sr-only" for="tool-filter">Filter tools</label><input v-if="!management.unavailable.tools" id="tool-filter" v-model="filter" class="panel-filter" type="search" placeholder="Filter" />
    </SettingsRow>
    <p v-if="management.unavailable.tools" class="capability-unavailable" role="status">{{ unavailableText('Tool management') }}</p>
    <p v-else-if="management.errors.tools" class="warn">{{ management.errors.tools }}</p>
    <ul v-if="!management.unavailable.tools" class="manage-list">
      <li v-for="tool in tools" :key="tool.name" :class="['manage-row', tool.state]">
        <div class="manage-line">
          <SettingsSwitch
              :id="`tool-enable-${encodeURIComponent(tool.name)}`"
              :label="`${tool.name} on or off`"
              :checked="tool.enabled"
              :disabled="management.busy[`tool:${tool.name}`]"
              @change="setToolEnabled(tool.name, $event)"
            />
          <label :for="`tool-enable-${encodeURIComponent(tool.name)}`" class="manage-name">{{ tool.name }}</label>
          <span :class="['state-chip', tool.state]">{{ STATES[tool.state] }}</span>
          <button class="ghost manage-more" :aria-label="`${expanded[tool.name] ? 'Hide parameters' : 'Parameters'} for ${tool.name}`" :aria-expanded="!!expanded[tool.name]" :aria-controls="`tool-parameters-${encodeURIComponent(tool.name)}`" @click="expanded[tool.name] = !expanded[tool.name]">
            {{ expanded[tool.name] ? 'Hide parameters' : 'Parameters' }}
          </button>
        </div>
        <p class="manage-desc">{{ tool.description }}</p>
        <p v-if="tool.cost || tool.risk" class="panel-hint"><template v-if="tool.cost">Cost: {{ tool.cost }}.</template> <template v-if="tool.risk">Risk: {{ tool.risk }}.</template></p>
        <div :id="`tool-parameters-${encodeURIComponent(tool.name)}`"><pre v-if="expanded[tool.name]" class="manage-json">{{ JSON.stringify(tool.input_schema, null, 2) }}</pre></div>
        <p v-if="management.notes[`tool:${tool.name}`]" class="manage-note" role="status">{{ management.notes[`tool:${tool.name}`] }}</p>
      </li>
    </ul>
    <p v-if="management.tools && !tools.length && !management.unavailable.tools" role="status">No matching tools. <button class="ghost" @click="filter = ''">Clear filter</button></p>
  </SettingsSection>

  <details class="settings-more"><summary>More options</summary>
    <SettingsSection title="Tool progress">
      <SettingEditor v-for="entry in toolMore" :key="entry.key" :field="entry.field!" :label="entry.label" :help="entry.help" />
    </SettingsSection>
  <SettingsSection title="Timeouts" aria-label="Tool timeouts">
    <SettingsRow label="Tool deadlines" description="Changes apply to new calls; running calls keep their deadlines." />
    <p v-if="management.unavailable.timeouts" class="capability-unavailable" role="status">{{ unavailableText('Tool timeout management') }}</p>
    <p v-else-if="management.errors.timeouts" class="warn">{{ management.errors.timeouts }}</p>
    <template v-if="!management.unavailable.timeouts">
    <label class="field-input">Default, in seconds <input v-model="defaultTimeout" type="number" min="1" :aria-invalid="timeoutErrorField === 'default' || undefined" :aria-describedby="timeoutErrorField === 'default' ? 'tool-timeout-error' : undefined" /></label>
    <div v-for="(row, index) in overrides" :key="index" class="field-input">
      <label>Tool {{ index + 1 }} <input v-model="row.name" list="tool-names" placeholder="Tool" /></label>
      <label>Seconds for tool {{ index + 1 }} <input v-model="row.seconds" type="number" min="1" placeholder="Seconds" :aria-invalid="timeoutErrorField === index || undefined" :aria-describedby="timeoutErrorField === index ? 'tool-timeout-error' : undefined" /></label>
      <button class="ghost" :aria-label="`Remove timeout for ${row.name || `tool ${index + 1}`}`" @click="overrides.splice(index, 1)">Remove</button>
    </div>
    <datalist id="tool-names">
      <option v-for="tool in management.tools?.tools ?? []" :key="tool.name" :value="tool.name" />
    </datalist>
    <div class="panel-actions">
      <button class="ghost" @click="overrides.push({ name: '', seconds: '' })">Add a tool's own timeout</button>
      <button class="ghost" :disabled="management.busy.timeouts" @click="save">Save timeouts</button>
      <button class="ghost" aria-label="Cancel timeout changes" @click="editTimeouts">Cancel</button>
    </div>
    <p v-if="timeoutError" id="tool-timeout-error" class="warn" role="alert">{{ timeoutError }}</p>
    <p v-else-if="management.notes.timeouts" class="manage-note" role="status">{{ management.notes.timeouts }}</p>
    </template>
  </SettingsSection>
  </details>
</template>
