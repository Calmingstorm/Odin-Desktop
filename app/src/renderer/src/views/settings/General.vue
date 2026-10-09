<script setup lang="ts">
import { computed, ref, onMounted, reactive } from 'vue'
import type { Appearance, NotificationChange, DesktopInfo, DisplayPictureTarget } from '../../../../shared/api'
import ReleaseNotice from '../../components/ReleaseNotice.vue'
import { state } from '../../store'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import SettingsRow from '../../components/settings/SettingsRow.vue'
import SettingsSwitch from '../../components/settings/SettingsSwitch.vue'
import OdinImport from '../../components/settings/OdinImport.vue'
import AvatarPicker from '../../components/AvatarPicker.vue'
import { displayProfile, loadDisplayProfile, saveDisplayName } from '../../stores/display-profile'
import { settings } from '../../stores/settings'
import { status, linkLabel } from '../../stores/status'
import { GENERAL_TIMEZONE } from '../../settings-presentation'
import { FieldDrafts, editableHere } from '../../settings-form'
import { saveField, resetField } from '../../stores/settings'

const desktop = ref<DesktopInfo | null>(null)
const support = reactive({ info: '', folder: '', diagnostics: '' })
const timezone = computed(() => settings.meta?.fields.find((field) => field.path === 'timezone'))
const zoneSearch = ref('')
const zoneForm = new FieldDrafts({ save: saveField, reset: resetField, latest: (path) => settings.meta?.fields.find((field) => field.path === path) })
const systemZone = (() => {
  try { const zone = Intl.DateTimeFormat().resolvedOptions().timeZone; new Intl.DateTimeFormat('en', { timeZone: zone }); return zone }
  catch { return '' }
})()
const zoneNames = (() => { try { return Intl.supportedValuesOf('timeZone') } catch { return [] } })()
const zoneValue = computed(() => timezone.value ? String(zoneForm.current(timezone.value)) : '')
const zoneOptions = computed(() => [...new Set([systemZone, zoneValue.value, 'UTC', ...zoneNames].filter(Boolean))]
  .filter((zone) => zone === systemZone || zone === zoneValue.value || zone.toLowerCase().includes(zoneSearch.value.trim().toLowerCase())))
const zoneEditable = computed(() => Boolean(timezone.value && editableHere(timezone.value)))
const zoneStatus = computed(() => settings.fields.timezone)
async function pickZone(value: string): Promise<void> {
  if (!timezone.value || !zoneEditable.value || !zoneOptions.value.includes(value)) return
  zoneForm.edit(timezone.value, value)
  await zoneForm.save(timezone.value)
}
const core = computed(() => status.epoch === state.recoveryEpoch && state.app.link === 'ready' && status.core?.core_instance_id === state.app.coreInstanceId ? status.core : null)
async function readInfo(): Promise<void> {
  try { const result = await window.odin.getDesktopInfo(); desktop.value = result.ok ? result.result : null; support.info = result.ok ? '' : result.error.message }
  catch { support.info = 'Desktop build information is unavailable.' }
}
async function folder(): Promise<void> {
  try { const result = await window.odin.openSettingsFolder(); support.folder = result.ok ? 'Opened the settings folder.' : result.error.message }
  catch { support.folder = 'The settings folder could not be opened.' }
}
async function diagnostics(): Promise<void> {
  const text = JSON.stringify({ desktop: desktop.value, connection: linkLabel(state.app.link), engineBuild: core.value?.version ?? null, enginePhase: core.value?.phase ?? null }, null, 2)
  try { const result = await window.odin.copyText(text); support.diagnostics = result.ok ? 'Copied redacted diagnostics.' : result.error.message }
  catch { support.diagnostics = 'Diagnostics could not be copied.' }
}
onMounted(readInfo)

// Your name and picture in chat. Odin calls you by the name; the picture is display only.
const userTarget: DisplayPictureTarget = { target: 'user' }
const nameDraft = ref<string | null>(null)
const nameValue = computed(() => nameDraft.value ?? displayProfile.name)
const nameState = reactive({ busy: false, error: '', note: '' })
function editName(event: Event): void {
  nameDraft.value = (event.target as HTMLInputElement).value
  nameState.note = ''
}
async function saveName(): Promise<void> {
  if (nameState.busy || nameDraft.value === null) return
  const sent = nameDraft.value
  nameState.busy = true
  nameState.error = ''
  nameState.note = ''
  try {
    const failure = await saveDisplayName(sent)
    if (failure) nameState.error = failure
    else {
      nameState.note = 'Saved.'
      if (nameDraft.value === sent) nameDraft.value = null
    }
  } finally {
    nameState.busy = false
  }
}
onMounted(() => void loadDisplayProfile())

const THEMES: Array<{ value: Appearance; label: string }> = [
  { value: 'system', label: 'System' },
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' }
]

// The app's own settings, kept by the app rather than the core: startup and desktop notifications (D13).
const notifications = computed(() => state.notifications)
const preferenceState = reactive<Record<string, string>>({})
let preferenceTail: Promise<unknown> = Promise.resolve()
let preferenceFence = 0
async function localPreference(key: string, action: () => Promise<{ ok: boolean; result?: unknown; error?: { message: string } }>, adopt: (value: unknown) => void): Promise<boolean> {
  const fence = preferenceFence
  preferenceState[key] = 'Saving…'
  const operation = preferenceTail.then(async () => {
    if (fence !== preferenceFence) { preferenceState[key] = 'An earlier save did not complete. Check, then submit again.'; return false }
    try {
      const result = await action()
      if (result.ok) { adopt(result.result); preferenceState[key] = 'Saved.'; return true }
      else { preferenceFence += 1; preferenceState[key] = result.error?.message ?? 'The preference could not be saved.'; return false }
    } catch { preferenceFence += 1; preferenceState[key] = 'The save outcome could not be confirmed. Check before submitting again.'; return false }
  })
  preferenceTail = operation.then(() => undefined, () => undefined)
  return await operation
}
function appearance(value: Appearance): void { void localPreference('theme', () => window.odin.setAppearance(value), (result) => { state.appearance = (result as { appearance: Appearance }).appearance }) }
function autostart(enabled: boolean): void { void localPreference('autostart', () => window.odin.setAutostart(enabled), (result) => { state.autostart = (result as { autostart: boolean }).autostart }) }

async function change(update: NotificationChange): Promise<boolean> {
  return await localPreference('notifications', () => window.odin.setNotifications(update), (result) => { state.notifications = (result as { notifications: NonNullable<typeof state.notifications> }).notifications })
}

const quietDraft = reactive<{ start?: string; end?: string }>({})
const quietSaving = reactive({ start: false, end: false })
const quietOwed: { start?: string; end?: string } = {}
function cancelQuiet(key: 'start' | 'end'): void { quietDraft[key] = undefined; delete quietOwed[key] }
const quietValue = (key: 'start' | 'end'): string => quietDraft[key] ?? notifications.value?.quietHours[key] ?? ''
function quietBlur(key: 'start' | 'end', event: FocusEvent): void {
  if (!(event.relatedTarget as HTMLElement | null)?.dataset?.settingsDraftAction) void quiet(key)
}
async function quiet(key: 'start' | 'end'): Promise<void> {
  const sent = quietDraft[key]
  if (sent === undefined) return
  if (quietSaving[key]) { quietOwed[key] = sent; return }
  if (sent === notifications.value?.quietHours[key]) return
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(sent)) { preferenceState.notifications = 'Enter a time in HH:MM format.'; return }
  quietSaving[key] = true
  let succeeded = false
  try {
    succeeded = await change({ quietHours: { [key]: sent } })
    if (succeeded && quietDraft[key] === sent) quietDraft[key] = undefined
  } finally { quietSaving[key] = false }
  const next = quietOwed[key]
  delete quietOwed[key]
  if (succeeded && next !== undefined && next !== notifications.value?.quietHours[key]) {
    const newer = quietDraft[key]
    quietDraft[key] = next
    const saving = quiet(key)
    if (newer !== next) quietDraft[key] = newer
    await saving
  }
}
</script>

<template>
  <ReleaseNotice />
  <SettingsSection title="Your profile">
    <SettingsRow label="Your name" description="Shown on your messages instead of “You”, and what Odin calls you." control-id="display-name">
      <input id="display-name" :value="nameValue" maxlength="40" placeholder="You" autocomplete="off" @input="editName" @keydown.enter.prevent="saveName" />
      <button class="ghost" aria-label="Save your name" :aria-disabled="nameState.busy || nameDraft === null" @click="saveName">Save</button>
      <template #note><p v-if="nameState.error" class="warn" role="alert">{{ nameState.error }}</p><p v-else-if="nameState.note" role="status">{{ nameState.note }}</p></template>
    </SettingsRow>
    <SettingsRow label="Your picture" description="Shown beside your messages.">
      <AvatarPicker :target="userTarget" :picture="displayProfile.user" label="your picture" />
    </SettingsRow>
  </SettingsSection>
  <SettingsSection title="Time">
    <SettingsRow v-if="timezone" :label="GENERAL_TIMEZONE.label" description="Used for schedules and dates." control-id="settings-curated-timezone">
      <div class="settings-timezone" role="group" aria-label="Time zone selection">
      <input aria-label="Find a time zone" placeholder="Search time zones" type="search" :value="zoneSearch" :disabled="!zoneEditable" @input="zoneSearch = ($event.target as HTMLInputElement).value" />
      <select id="settings-curated-timezone" :value="zoneValue" :disabled="!zoneEditable" @change="pickZone(($event.target as HTMLSelectElement).value)">
        <option v-for="zone in zoneOptions" :key="zone" :value="zone">{{ zone === systemZone ? `System: ${zone}` : zone }}</option>
      </select>
      </div>
      <template #note>
        <div v-if="zoneForm.changed(timezone)" class="settings-editor-actions">
          <span>Unsaved changes</span>
          <button type="button" :disabled="zoneStatus?.status === 'saving'" @click="pickZone(zoneValue)">Save time zone</button>
          <button type="button" @click="zoneForm.cancel('timezone')">Cancel time zone change</button>
        </div>
        <p v-if="zoneForm.errors.timezone || zoneStatus?.status === 'error'" role="status">{{ zoneForm.errors.timezone || zoneStatus?.message }}</p>
        <p v-else-if="zoneStatus?.status === 'saving'" role="status">Saving…</p>
        <p v-else-if="zoneStatus?.status === 'saved' && !zoneForm.changed(timezone)" role="status">Saved</p>
        <p v-if="!zoneEditable" role="status">Time zone cannot be changed right now.</p>
        <p v-if="timezone.apply_state === 'invalid'" role="status">Choose a valid time zone and save again.</p>
        <p v-else-if="timezone.apply_state === 'drift'" role="status">The saved and running time zones differ. Refresh before changing it.</p>
        <p v-else-if="timezone.pending_restart" role="status">The saved time zone needs Odin to restart.</p>
      </template>
    </SettingsRow>
    <p v-else role="status">{{ settings.unavailable ? 'Time zone is unavailable.' : settings.error ? 'Time zone could not be read.' : 'Loading time zone.' }}</p>
  </SettingsSection>
  <SettingsSection title="Appearance">
    <SettingsRow label="Theme">
      <div class="settings-segmented" role="group" aria-label="Theme">
        <button v-for="theme in THEMES" :key="theme.value" type="button" :aria-pressed="state.appearance === theme.value" @click="appearance(theme.value)">{{ theme.label }}</button>
      </div>
      <template v-if="preferenceState.theme" #note><p role="status">{{ preferenceState.theme }}</p></template>
    </SettingsRow>
  </SettingsSection>
  <SettingsSection title="Startup and notifications">
    <SettingsRow label="Start Odin when you log in" description="Closing the window keeps Odin running in the tray. Exit stops it." control-id="start-at-login">
      <SettingsSwitch id="start-at-login" label="Start Odin when you log in" data-testid="start-at-login" :checked="state.autostart" @change="autostart" />
    </SettingsRow>
    <template v-if="notifications">
      <SettingsRow label="Desktop notifications" control-id="notifications-enabled"><SettingsSwitch id="notifications-enabled" label="Desktop notifications" :checked="notifications.enabled" @change="(enabled) => change({ enabled })" /></SettingsRow>
      <SettingsRow label="Show message previews in notifications" description="Include message text; turn off to keep notification content private." control-id="notification-previews"><SettingsSwitch id="notification-previews" label="Show message previews in notifications" data-testid="notification-previews" :checked="notifications.previews" :disabled="!notifications.enabled" @change="(previews) => change({ previews })" /></SettingsRow>
      <SettingsRow label="Quiet hours" control-id="quiet-hours-enabled">
        <SettingsSwitch
          id="quiet-hours-enabled"
          label="Quiet hours"
          :checked="notifications.quietHours.enabled"
          data-testid="notification-quiet-hours"
          :disabled="!notifications.enabled"
          @change="(enabled) => change({ quietHours: { enabled } })"
        />
      </SettingsRow>
      <SettingsRow v-for="key in (['start', 'end'] as const)" :key="key" :label="`Quiet hours ${key}`" :control-id="`quiet-hours-${key}`">
        <input :id="`quiet-hours-${key}`" type="time" :value="quietValue(key)" :disabled="!notifications.enabled || !notifications.quietHours.enabled" @input="quietDraft[key] = ($event.target as HTMLInputElement).value" @change="quietDraft[key] = ($event.target as HTMLInputElement).value" @keydown.enter="quiet(key)" @blur="quietBlur(key, $event)" />
        <template #note><div v-if="quietDraft[key] !== undefined && quietDraft[key] !== notifications.quietHours[key]" class="settings-editor-actions"><button class="ghost" data-settings-draft-action="save" :disabled="quietSaving[key]" @click="quiet(key)">Save</button><button class="ghost" data-settings-draft-action="cancel" @mousedown.prevent @click="cancelQuiet(key)">Cancel</button></div></template>
      </SettingsRow>
      <p v-if="preferenceState.notifications" role="status">{{ preferenceState.notifications }}</p>
      <p class="panel-hint">Muted conversations: {{ notifications.muted.length }}. Mute or unmute one from its ⋯ menu.</p>
    </template>
  </SettingsSection>
  <p v-if="preferenceState.autostart" role="status">{{ preferenceState.autostart }}</p>
  <SettingsSection title="About">
    <SettingsRow label="Desktop release"><span>{{ desktop?.appVersion ?? state.app.appVersion ?? 'Unavailable' }}</span></SettingsRow>
    <SettingsRow label="Engine build"><span>{{ core?.version ?? 'Unavailable' }}</span></SettingsRow>
    <SettingsRow label="Runtime"><span v-if="desktop">Electron {{ desktop.electronVersion }} · Chromium {{ desktop.chromiumVersion }} · Node {{ desktop.nodeVersion }}</span><span v-else>Unavailable</span></SettingsRow>
    <SettingsRow label="Build and licence"><span v-if="desktop">{{ desktop.packaged ? 'Packaged build' : 'Source build' }} · {{ desktop.platform }} / {{ desktop.architecture }} · {{ desktop.license }}</span><span v-else>Unavailable</span></SettingsRow>
    <SettingsRow label="Diagnostics" description="Versions and connection only. No credentials, account details or configuration."><button class="ghost" @click="diagnostics">Copy diagnostics</button><template #note><p v-if="support.diagnostics" role="status">{{ support.diagnostics }}</p></template></SettingsRow>
    <p v-if="support.info" class="warn" role="status">{{ support.info }} <button class="ghost" @click="readInfo">Read build information again</button></p>
  </SettingsSection>
  <SettingsSection title="Support and advanced">
    <SettingsRow label="Settings folder" description="Exit before editing, then reopen Odin; manage credentials in the app and leave app-managed files unchanged."><button class="ghost" @click="folder">Open settings folder</button><template #note><p v-if="support.folder" role="status">{{ support.folder }}</p></template></SettingsRow>
    <SettingsRow label="Import from Odin" description="Bring memory, skills, MCP servers, personality, hosts and settings over from an Odin install."><OdinImport /></SettingsRow>
    <SettingsRow label="Advanced settings" description="Search compatibility, execution limits and retention policies."><button class="ghost" @click="state.settingsSection = 'advanced'">Advanced settings</button></SettingsRow>
  </SettingsSection>
</template>
