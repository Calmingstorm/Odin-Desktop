<script setup lang="ts">
import SettingsSection from './settings/SettingsSection.vue'
import SettingsSwitch from './settings/SettingsSwitch.vue'
import SettingsRow from './settings/SettingsRow.vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ConfigMeta, CoreStatus, Result, SettingsChange } from '../../../shared/api'
import { state } from '../store'
import { schedules } from '../stores/schedules'

// A private projection: never retain a secret from settings, or infer acceptance from opt-in.
const meta = ref<ConfigMeta | null>(null)
const ingress = ref<CoreStatus['webhook_ingress']>(undefined)
const enabled = ref(false)
const bind = ref('')
const port = ref('8081')
const selected = ref('')
const source = ref<'generic' | 'github' | 'gitea'>('generic')
const secret = ref('')
const busy = ref(false)
const loading = ref(false)
const stale = ref(true)
const error = ref('')
const notice = ref('')
let generation = 0
let alive = true
let pendingSecret = ''
const rows = computed(() => schedules.list.filter((row) => Boolean(row.trigger)))
const row = computed(() => rows.value.find((item) => item.id === selected.value))
const prefix = computed(() => `webhook.triggers.${selected.value}`)
const field = (path: string) => meta.value?.fields.find((item) => item.path === path)
const available = computed(() => Boolean(meta.value && field('webhook.enabled') && field('webhook.bind_address') && field('webhook.port')))
const secretState = computed(() => {
  const record = field(`${prefix.value}.secret`)
  return !record || record.configured === null ? 'Not reported' : record.configured ? 'Configured (write-only)' : 'Not configured'
})
const statusText = computed(() => {
  const labels = {
    accepting: 'Accepting deliveries', disabled: 'Disabled', closed: 'Closed',
    unconfigured_bind: 'Off: listen address not configured', no_eligible_schedule: 'Off: no eligible schedule',
    not_bound: 'Not bound: listener is not accepting deliveries', unavailable: 'Webhook ingress unavailable'
  }
  return ingress.value ? labels[ingress.value.reason] : 'Webhook ingress status unavailable'
})
const endpoint = computed(() => {
  const address = ingress.value?.address
  if (ingress.value?.reason !== 'accepting' || !address || !row.value) return ''
  const host = address[0].includes(':') ? `[${address[0]}]` : address[0]
  const savedSource = field(`${prefix.value}.source`)?.desired
  return ['generic', 'github', 'gitea'].includes(String(savedSource))
    ? `http://${host}:${address[1]}/webhook/${savedSource}/${encodeURIComponent(row.value.id)}` : ''
})
const selectedWarning = computed(() => {
  if (!row.value) return ''
  const savedSource = field(`${prefix.value}.source`)?.desired
  if (row.value.paused) return 'Selected schedule is paused; it cannot receive deliveries.'
  if (row.value.inert_reason) return 'Selected schedule is inert; it cannot receive deliveries.'
  if (row.value.trigger?.source === 'gitlab') return 'GitLab ingress is unavailable.'
  if (row.value.trigger?.source && row.value.trigger.source !== savedSource) return 'Saved inbound source does not match the selected schedule filter; it cannot receive deliveries.'
  return 'This route does not confirm that this schedule accepts deliveries. It needs its own secret and reporting conversation; another schedule may be using the listener.'
})
const authentication = computed(() => {
  const saved = field(`${prefix.value}.source`)?.desired
  if (saved === 'generic') return 'Generic authentication: send the exact per-trigger secret in X-Webhook-Secret.'
  if (saved === 'github') return 'GitHub authentication: X-Hub-Signature-256 is the HMAC SHA256 hex digest of the raw request body using the per-trigger secret; sha256= prefix is accepted.'
  if (saved === 'gitea') return 'Gitea authentication: X-Gitea-Signature is the HMAC SHA256 hex digest of the raw request body using the per-trigger secret.'
  return ''
})
function chooseSource(): void {
  secret.value = ''
  const saved = field(`${prefix.value}.source`)?.desired ?? row.value?.trigger?.source
  source.value = saved === 'github' || saved === 'gitea' ? saved : 'generic'
}
watch(selected, chooseSource, { flush: 'sync' })
watch(rows, () => {
  if (selected.value && !row.value) selected.value = ''
})
const failure = <T,>(): Result<T> => ({ ok: false, error: { code: 'unavailable', message: 'Odin could not be reached.' } })
async function read<T>(request: () => Promise<Result<T>>): Promise<Result<T>> {
  try { return await request() } catch { return failure<T>() }
}

async function refresh(): Promise<void> {
  if (busy.value) return
  notice.value = 'Refreshing replaces unsaved listener and source drafts with saved settings and discards the secret draft.'
  secret.value = ''
  await refreshProjection()
}
async function refreshProjection(): Promise<void> {
  const mine = ++generation
  loading.value = true
  stale.value = true
  // Old acceptance evidence is not current acceptance evidence.
  ingress.value = undefined
  const [settings, status] = await Promise.all([
    read(() => window.odin.settingsSchema()), read(() => window.odin.status())
  ])
  if (!alive || mine !== generation) return
  loading.value = false
  meta.value = settings.ok ? settings.result : null
  ingress.value = status.ok ? status.result.webhook_ingress : undefined
  stale.value = !settings.ok || !status.ok
  error.value = !settings.ok ? 'Webhook settings unavailable. Refresh before changing setup.'
    : !status.ok ? 'Ingress status could not be refreshed. Acceptance is unknown.' : ''
  if (settings.ok) {
    enabled.value = field('webhook.enabled')?.desired === true
    bind.value = String(field('webhook.bind_address')?.desired ?? '')
    port.value = String(field('webhook.port')?.desired ?? 8081)
    chooseSource()
  }
}

async function writeSettings(changes: SettingsChange[]): Promise<boolean> {
  if (!meta.value) return false
  const mine = generation
  const result = await read(() => window.odin.settingsSet({ expected_revision: meta.value!.revision, changes }))
  if (!alive || mine !== generation) return false
  if (!result.ok) {
    stale.value = true
    error.value = result.error.code === 'stale_binding'
      ? 'Settings changed elsewhere. Refresh, review the new setup, then submit again. Nothing was retried.'
      : 'Settings were not confirmed saved. Refresh before retrying.'
    return false
  }
  return true
}
async function saveListener(): Promise<void> {
  if (busy.value || loading.value || stale.value || !available.value) return
  busy.value = true
  ingress.value = undefined
  error.value = ''; notice.value = ''
  try {
    // Core validates explicit numeric/nonwildcard LAN, tailnet, link-local and loopback addresses.
    // No renderer address policy narrower than D17.
    const number = Number(port.value)
    if (!String(port.value).trim() || !Number.isInteger(number) || number < 0 || number > 65535) {
      error.value = 'Listen port must be a whole number from 0 to 65535.'
      return
    }
    const saved = await writeSettings([
      { path: 'webhook.enabled', value: enabled.value }, { path: 'webhook.bind_address', value: bind.value },
      { path: 'webhook.port', value: number }
    ])
    if (saved && alive) {
      notice.value = 'Listener settings saved. Only the measured ingress status below establishes acceptance.'
      await refreshProjection()
    }
  } finally { busy.value = false }
}
async function saveTrigger(): Promise<void> {
  if (busy.value || loading.value || stale.value || !available.value || !row.value || row.value.trigger?.source === 'gitlab') return
  if (!secret.value) { error.value = 'Enter a new per-trigger secret.'; return }
  const id = row.value.id
  const path = `webhook.triggers.${id}`
  const chosen = source.value
  const mine = generation
  pendingSecret = secret.value
  secret.value = '' // Clear immediately, including failed source writes and pending submissions.
  busy.value = true
  ingress.value = undefined
  error.value = ''; notice.value = ''
  try {
    const saved = await writeSettings([{ path: `${path}.source`, value: chosen }])
    if (!saved || !alive || mine !== generation) return
    // Unmount or a changed schedule stops the second stage. Never bind a secret to a new selection.
    if (selected.value !== id || !row.value) {
      notice.value = 'Source saved, but secret was not submitted because the selected schedule changed.'
      await refreshProjection()
      return
    }
    const submission = read(() => window.odin.secretsSet({ path: `${path}.secret`, value: pendingSecret }))
    pendingSecret = ''
    const result = await submission
    if (!alive || mine !== generation) return
    notice.value = result.ok ? 'Source and secret saved. Check the status to confirm deliveries are accepted.'
      : 'Partial setup: source saved, but secret storage was not confirmed. The previous secret, if any, may still be in use. Refresh before retrying.'
    await refreshProjection()
  } finally { pendingSecret = ''; busy.value = false }
}
async function clearTriggerSecret(): Promise<void> {
  if (busy.value || loading.value || stale.value || !available.value || !row.value) return
  secret.value = ''
  const path = `${prefix.value}.secret`
  const mine = generation
  busy.value = true
  ingress.value = undefined
  error.value = ''; notice.value = ''
  try {
    const result = await read(() => window.odin.secretsClear({ path }))
    if (!alive || mine !== generation) return
    notice.value = result.ok ? 'Per-trigger secret cleared. This trigger cannot receive authenticated deliveries without a secret.'
      : 'Secret clearing was not confirmed. The previous secret may still be in use. Refresh before retrying.'
    await refreshProjection()
  } finally { busy.value = false }
}
watch(() => [state.recoveryEpoch, state.app.coreInstanceId, state.app.link], () => {
  generation += 1; meta.value = null; ingress.value = undefined; stale.value = true
  secret.value = ''; pendingSecret = ''; loading.value = false
  error.value = 'Core connection changed. Refresh to obtain current ingress state.'
}, { flush: 'sync' })
// The first load has no drafts to discard, so it reads without the explicit Refresh notice.
onMounted(refreshProjection)
onBeforeUnmount(() => { alive = false; generation += 1; secret.value = ''; pendingSecret = ''; meta.value = null; ingress.value = undefined })
</script>

<template>
  <SettingsSection title="Incoming webhooks" aria-label="Webhook ingress" data-testid="webhook-ingress" :aria-busy="busy || loading"
    description="Let a service such as GitHub start a webhook-triggered schedule. Off until you turn it on.">
    <template #actions>
      <button class="ghost" aria-label="Refresh webhook ingress" aria-describedby="ingress-refresh-help" :disabled="busy" @click="refresh">Refresh</button>
    </template>
    <SettingsRow label="Listener" description="Whether Odin is accepting deliveries now.">
      <template #note>
        <p role="status" aria-atomic="true" data-testid="webhook-ingress-status" class="manage-desc">{{ statusText }}<template v-if="ingress">. Eligible schedules: {{ ingress.eligible_schedules }}. Unknown deliveries: {{ ingress.unknown_deliveries }}.</template></p>
        <p v-if="ingress?.address" class="manage-desc">Actual listen address: {{ ingress.address[0] }}:{{ ingress.address[1] }}</p>
        <p v-if="error" id="ingress-error" class="warn" role="alert">{{ error }}</p>
        <p v-if="notice" class="manage-desc" role="status">{{ notice }}</p>
        <p v-if="meta?.status?.keyring_error" class="warn" role="status">Secret storage is unavailable. Keyring error: {{ meta.status.keyring_error }}. Stored-secret presence and eligibility may be unknown.</p>
        <p v-if="!available && !loading" class="manage-desc" role="status">Webhook settings are unavailable. No setup can be changed here.</p>
        <p id="ingress-refresh-help" class="sr-only">Refresh replaces unsaved listener and source drafts with saved settings and discards any secret draft.</p>
      </template>
    </SettingsRow>
    <template v-if="available">
      <fieldset class="settings-fieldset" :disabled="busy || loading || stale">
        <legend class="sr-only">Inbound listener setup</legend>
        <SettingsRow label="Accept incoming webhooks" description="The listener starts once an unpaused webhook schedule has a conversation and its own secret. On does not mean accepting." control-id="webhook-ingress-enabled">
          <SettingsSwitch id="webhook-ingress-enabled" label="Accept incoming webhooks" :checked="enabled" data-testid="webhook-ingress-enabled" @change="enabled = $event" />
        </SettingsRow>
        <SettingsRow label="Listen address" description="A numeric LAN, tailnet or loopback address, not a wildcard or hostname." control-id="webhook-ingress-bind">
          <input id="webhook-ingress-bind" v-model="bind" data-testid="webhook-ingress-bind" :aria-describedby="error ? 'ingress-error ingress-bind-help' : 'ingress-bind-help'" spellcheck="false" />
          <span id="ingress-bind-help" class="sr-only">Use a numeric LAN, tailnet or loopback address, not a wildcard or hostname.</span>
        </SettingsRow>
        <SettingsRow label="Listen port" control-id="webhook-ingress-port">
          <input id="webhook-ingress-port" v-model="port" class="narrow" type="number" min="0" max="65535" data-testid="webhook-ingress-port" :aria-describedby="error ? 'ingress-error' : undefined" />
        </SettingsRow>
        <div class="panel-actions"><button class="ghost" :disabled="busy || loading || stale" @click="saveListener">Save listener setup</button></div>
      </fieldset>
      <fieldset class="settings-fieldset" :disabled="busy || loading || stale">
        <legend class="sr-only">Per-trigger delivery setup</legend>
        <SettingsRow label="Webhook schedule" description="The saved webhook schedule a delivery starts." control-id="webhook-ingress-schedule">
          <select id="webhook-ingress-schedule" v-model="selected" data-testid="webhook-ingress-schedule"><option value="">Choose a saved trigger schedule</option><option v-for="item in rows" :key="item.id" :value="item.id">{{ item.description }}{{ item.paused ? ' (paused)' : '' }}</option></select>
          <template #note>
            <p v-if="!rows.length" class="manage-desc">Save a schedule with webhook timing before configuring its secret.</p>
            <template v-if="row">
              <p v-if="row.trigger?.source === 'gitlab'" class="manage-desc" role="status">GitLab scheduler matching is supported, but GitLab ingress is unavailable. This panel cannot configure GitLab deliveries.</p>
              <p v-if="row.paused" class="manage-desc" role="status">This schedule is paused and cannot accept deliveries.</p>
              <p v-if="!row.channel_id" class="manage-desc" role="status">This schedule needs a valid reporting conversation to be eligible.</p>
              <p class="manage-desc" role="status">Secret: {{ secretState }}</p>
            </template>
          </template>
        </SettingsRow>
        <template v-if="row">
          <template v-if="row.trigger?.source !== 'gitlab'">
            <SettingsRow label="Delivery source" description="The service that sends this schedule's webhooks." control-id="webhook-ingress-source">
              <select id="webhook-ingress-source" v-model="source" data-testid="webhook-ingress-source"><option value="generic">Generic</option><option value="github">GitHub</option><option value="gitea">Gitea</option></select>
              <template #note>
                <p v-if="row.trigger?.source && row.trigger.source !== source" class="manage-desc" role="status">The inbound source differs from this schedule's source filter. It will not be eligible until those match.</p>
              </template>
            </SettingsRow>
            <SettingsRow label="New secret" description="Write-only: a stored secret is never shown again. Saving clears this field, even on failure." control-id="webhook-ingress-secret">
              <input id="webhook-ingress-secret" v-model="secret" type="password" autocomplete="new-password" spellcheck="false" data-testid="webhook-ingress-secret" aria-describedby="ingress-secret-help" />
              <span id="ingress-secret-help" class="sr-only">Write-only. Stored secrets are never filled or read back. Submission clears this draft, even on failure. Source is saved first, then the secret separately.</span>
            </SettingsRow>
          </template>
          <div class="panel-actions">
            <button v-if="row.trigger?.source !== 'gitlab'" class="ghost" :disabled="busy || loading || stale || !secret" @click="saveTrigger">Save trigger source and secret</button>
            <button class="ghost" :disabled="busy || loading || stale" @click="clearTriggerSecret">Clear per-trigger secret</button>
          </div>
          <div class="card-block">
            <p role="status" class="manage-desc" data-testid="webhook-ingress-selected-status">{{ selectedWarning }}</p>
            <p v-if="endpoint" class="manage-desc" data-testid="webhook-ingress-endpoint">Delivery route URL (not selected-schedule eligibility proof): {{ endpoint }}</p>
            <p v-if="authentication" class="manage-desc">{{ authentication }}</p>
          </div>
        </template>
      </fieldset>
    </template>
  </SettingsSection>
</template>
