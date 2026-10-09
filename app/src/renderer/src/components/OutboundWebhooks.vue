<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { OutboundWebhookDelivery, OutboundWebhookSave, OutboundWebhookStatus, OutboundWebhookTarget, Result } from '../../../shared/api'
import { ask } from '../dialog'
import { state } from '../store'
import { act, management } from '../stores/management'
import { loadSettings, settings, settingsCommand } from '../stores/settings'
import SettingsSection from './settings/SettingsSection.vue'
import SettingsRow from './settings/SettingsRow.vue'
import SettingsSwitch from './settings/SettingsSwitch.vue'

const KEY = 'outbound-webhooks'
const EVENTS = ['tool_execution', 'alert', 'schedule', 'agent', 'loop', 'health', 'web_action', 'custom']
const snapshot = ref<OutboundWebhookStatus | null>(null)
const loading = ref(false)
const stale = ref(true)
const error = ref('')
const unavailable = ref(false)
const revision = ref('')
type Intent = 'keep' | 'replace' | 'remove'
type Draft = { original: OutboundWebhookTarget | null; name: string; url: string; urlIntent: Intent; secret: string; secretIntent: Intent; events: string[]; enabled: boolean; scrub: boolean; tls: boolean; revision: string }
const draft = ref<Draft | null>(null)
const confirming = ref(false)
const editorDialog = ref<HTMLDialogElement | null>(null)
let opener: HTMLElement | null = null
// Native modality contains focus. Suspend it for the shared confirmation,
// otherwise its browser top layer hides that confirmation behind the editor.
watch(() => Boolean(draft.value) && !confirming.value, async (open) => {
  if (!open) editorDialog.value?.close?.()
  await nextTick()
  if (open) editorDialog.value?.showModal?.()
  if (!draft.value && opener?.isConnected) { opener.focus(); opener = null }
})
let generation = 0
let alive = true
const busy = computed(() => Boolean(management.busy[KEY]))
const unavailableForWrite = computed(() => busy.value || loading.value || stale.value || settings.unavailable || settings.unknownSave)
const locked = computed(() => confirming.value || unavailableForWrite.value)
// Display is not a replacement endpoint: query and fragment may hold credentials.
function publicUrl(value: string): string {
  try { const url = new URL(value); url.username = ''; url.password = ''; url.search = ''; url.hash = ''; return url.toString() } catch { return '' }
}
function privateUrl(value: string): boolean {
  try { const url = new URL(value); return Boolean(url.username || url.password || url.search || url.hash) } catch { return false }
}
function cancel(): void { if (busy.value || confirming.value) return; if (draft.value) { draft.value.secret = ''; draft.value.url = '' }; draft.value = null; error.value = '' }
watch(() => draft.value?.urlIntent, () => { if (draft.value) draft.value.url = '' })
watch(() => draft.value?.secretIntent, () => { if (draft.value) draft.value.secret = '' })
function edit(row: OutboundWebhookTarget | null = null): void {
  if (locked.value) return
  cancel()
  opener = typeof HTMLElement !== 'undefined' && document.activeElement instanceof HTMLElement ? document.activeElement : null
  draft.value = { original: row, name: row?.name ?? '', url: '', urlIntent: row ? 'keep' : 'replace', secret: '', secretIntent: 'keep', events: row?.events.includes('all') ? [] : [...(row?.events ?? [])], enabled: row?.enabled ?? true, scrub: row?.scrub_secrets ?? true, tls: row?.verify_ssl ?? true, revision: revision.value }
}
watch(() => [state.recoveryEpoch, state.app.coreInstanceId], () => {
  generation += 1; stale.value = true; snapshot.value = null; loading.value = false
  if (draft.value) { draft.value.secret = ''; draft.value.url = '' }
  error.value = 'Odin changed. Refresh and inspect before submitting again.'
})
onBeforeUnmount(() => { alive = false; generation += 1; if (draft.value) { draft.value.secret = ''; draft.value.url = '' } })
async function refresh(): Promise<void> {
  if (busy.value || confirming.value) return
  cancel()
  await readProjection(true)
}
async function readProjection(explicit = false): Promise<void> {
  const mine = ++generation
  loading.value = true; stale.value = true; snapshot.value = null
  try {
    if (typeof window.odin.outboundWebhooksList !== 'function') { unavailable.value = true; error.value = ''; return }
    if (explicit || (!settings.meta && !settings.unavailable)) await loadSettings(explicit)
    const result = await window.odin.outboundWebhooksList({})
    if (!alive || mine !== generation) return
    unavailable.value = !result.ok && result.error.code === 'capability_unavailable'
    if (unavailable.value) { error.value = ''; return }
    if (!result.ok || !settings.meta || settings.unavailable || settings.error) {
      error.value = 'Outbound webhooks unavailable. Refresh before changing targets.'
      return
    }
    snapshot.value = result.result; revision.value = settings.meta.revision; stale.value = false; error.value = ''; unavailable.value = false
  } catch { if (alive && mine === generation) error.value = 'Outbound webhooks unavailable. Refresh before changing targets.' }
  finally { if (alive && mine === generation) loading.value = false }
}
const staleResult = <T,>(): Result<T> => ({ ok: false, error: { code: 'stale_binding', message: 'Settings changed. Refresh, inspect, then submit again.' } })
async function save(): Promise<void> {
  const current = draft.value
  if (!current || locked.value) return
  const reviewed = JSON.stringify(current)
  const body: OutboundWebhookSave = { expected_revision: current.revision, ...(current.original ? { id: current.original.id } : {}), name: current.name, events: [...current.events], enabled: current.enabled, scrub_secrets: current.scrub, verify_ssl: current.tls }
  if (!current.original || current.urlIntent === 'replace') {
    try { const url = new URL(current.url); if (!['http:', 'https:'].includes(url.protocol) || current.url.includes('[REDACTED]')) throw new Error() } catch { error.value = 'Enter a complete HTTP or HTTPS endpoint URL. Masked URLs cannot be saved.'; return }
    body.url = current.url
  } else if (current.urlIntent === 'remove') body.url = publicUrl(current.original.url)
  if (current.secretIntent === 'replace') { if (!current.secret) { error.value = 'Enter a signing key to replace it.'; return }; body.secret = current.secret }
  if (current.secretIntent === 'remove') body.secret = ''
  confirming.value = true
  try {
    if (!body.verify_ssl && current.original?.verify_ssl !== false && !await ask({ title: 'Disable TLS verification?', message: 'This target will no longer verify the endpoint certificate. This weakens delivery security.', confirmLabel: 'Disable verification', danger: true })) return
    if (!body.scrub_secrets && current.original?.scrub_secrets !== false && !await ask({ title: 'Disable target secret scrubbing?', message: 'This target permits unsanitized event payloads. Global scrubbing may still apply.', confirmLabel: 'Disable scrubbing', danger: true })) return
    if (current.original && (current.urlIntent === 'remove' || current.secretIntent === 'remove') && !await ask({ title: 'Remove outbound credentials?', message: 'Remove endpoint userinfo, query and fragment, and/or the selected signing key? Removing the signing key makes this target unsigned. The stripped endpoint may no longer accept delivery.', confirmLabel: 'Remove credentials', danger: true })) return
  } finally { confirming.value = false }
  if (draft.value !== current || unavailableForWrite.value || JSON.stringify(current) !== reviewed) { error.value = 'Draft changed during confirmation. Inspect it before saving.'; return }
  // Erase submitted credentials immediately. No masked value ever becomes a replacement.
  current.secret = ''; current.url = ''; error.value = ''
  const mine = generation
  await act(KEY, () => settingsCommand((latest) => latest === current.revision ? window.odin.outboundWebhooksSave(body) : Promise.resolve(staleResult())), () => {
    if (alive && mine === generation && draft.value === current) draft.value = null
    return 'Target saved. Delivery readiness is not implied.'
  }, async () => { if (alive && mine === generation && draft.value !== current) await readProjection() })
  if (!alive || mine !== generation) return
  if (draft.value === current) { stale.value = true; error.value = 'Save not confirmed. Refresh and inspect before another submission.' }
}
async function remove(row: OutboundWebhookTarget): Promise<void> {
  if (locked.value) return
  const baseline = revision.value; const mine = generation
  confirming.value = true
  try { if (!await ask({ title: 'Delete outbound webhook?', message: `Remove “${row.name}” and its owned signing key and private endpoint credentials?`, confirmLabel: 'Delete target', danger: true })) return }
  finally { confirming.value = false }
  if (locked.value || mine !== generation) return
  let deleted = false
  const saved = await act(KEY, () => settingsCommand((latest) => latest === baseline ? window.odin.outboundWebhooksDelete({ id: row.id, expected_revision: baseline }) : Promise.resolve(staleResult())), () => { deleted = true; return 'Target and owned credentials deleted.' }, async () => { if (deleted && alive && mine === generation) { cancel(); await readProjection() } })
  if (!alive || mine !== generation) return
  if (!saved) stale.value = true
}
async function test(row: OutboundWebhookTarget): Promise<void> {
  if (locked.value) return
  const mine = generation; const baseline = revision.value
  confirming.value = true
  try { if (!await ask({ title: 'Send outbound test?', message: `Send an actual test event to “${row.name}”? This performs an external request.`, confirmLabel: 'Send test' })) return }
  finally { confirming.value = false }
  if (locked.value || mine !== generation) return
  const settled = await act(KEY, () => settingsCommand(async (latest) => {
    if (latest !== baseline) return staleResult<OutboundWebhookDelivery>()
    const meta = await window.odin.settingsSchema()
    if (!meta.ok || meta.result.revision !== baseline || mine !== generation) return staleResult<OutboundWebhookDelivery>()
    return window.odin.outboundWebhooksTest({ id: row.id, expected_revision: baseline })
  }), (delivery) => {
    if (!alive || mine !== generation) return 'Test settled after the displayed core changed. Refresh and inspect.'
    if (!delivery || typeof delivery.success !== 'boolean' || typeof delivery.status_code !== 'number' || typeof delivery.latency_ms !== 'number' || typeof delivery.attempt !== 'number') return 'Test receipt did not report a measured delivery. Refresh and inspect; it is not sent again.'
    return delivery.success ? `Test delivered: HTTP ${delivery.status_code}, ${delivery.latency_ms} ms, attempt ${delivery.attempt}.` : `Test failed: HTTP ${delivery.status_code}, attempt ${delivery.attempt}.`
  }, async () => { if (alive && mine === generation) await readProjection() })
  if (alive && mine === generation && !settled) stale.value = true
}
onMounted(() => readProjection())
</script>

<template>
  <SettingsSection title="Outgoing webhooks" aria-label="Outgoing webhooks" description="Push events to external targets. This is separate from incoming schedule triggers.">
    <template #actions>
      <button class="ghost" :disabled="busy || loading || confirming" @click="refresh">Refresh outgoing webhooks</button>
      <button class="ghost" :disabled="locked" @click="edit()">Add outbound webhook</button>
    </template>
    <p v-if="loading" role="status">Loading outgoing targets…</p>
    <p v-else-if="unavailable" role="status">Outgoing webhooks are unavailable.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="stale && !loading" class="warn">Refresh and inspect targets before changing them. Nothing is automatically replayed.</p>
    <p v-if="management.notes[KEY]" role="status">{{ management.notes[KEY] }}</p>
    <p v-if="snapshot" class="manage-desc">{{ snapshot.enabled_count }} of {{ snapshot.webhook_count }} targets enabled.</p>
    <p v-if="snapshot && !snapshot.webhooks.length" class="manage-desc">No outbound targets configured.</p>
    <ul v-if="snapshot" class="manage-list">
      <li v-for="row in snapshot.webhooks" :key="row.id" class="manage-row">
        <div class="manage-line"><strong>{{ row.name }}</strong><span :class="['state-chip', row.enabled ? 'connected' : 'disabled']">{{ row.enabled ? 'Enabled' : 'Disabled' }}</span>
          <span class="manage-actions">
            <button class="ghost" :aria-label="`Edit outbound webhook ${row.name}`" :disabled="locked" @click="edit(row)">Edit</button>
            <button class="ghost" :aria-label="`Test outbound webhook ${row.name}`" :disabled="locked" @click="test(row)">Test…</button>
            <button class="ghost danger-item" :aria-label="`Delete outbound webhook ${row.name}`" :disabled="locked" @click="remove(row)">Delete…</button>
          </span>
        </div>
        <p class="manage-desc">{{ publicUrl(row.url) }} · {{ privateUrl(row.url) ? 'Private endpoint configured (write-only)' : 'Public endpoint' }} · Signing key: {{ row.has_secret ? 'Configured (write-only)' : 'Not configured' }}</p>
        <p class="manage-desc">Events: {{ row.events.length ? row.events.join(', ') : 'All' }} · Secret scrubbing: {{ row.scrub_secrets ? 'On' : 'Off' }} · TLS verification: {{ row.verify_ssl ? 'On' : 'Off' }}</p>
      </li>
      <li v-for="row in snapshot.skipped_webhooks" :key="`skipped:${row.id}`" class="manage-row warn">Target {{ row.id }} unavailable: {{ row.reason }}</li>
    </ul>
    <dialog v-if="draft" ref="editorDialog" class="settings-form-dialog" :aria-label="draft.original ? 'Edit outbound target' : 'Add outbound target'" @cancel.prevent="cancel">
    <form class="settings-form" aria-label="Outbound webhook editor" @submit.prevent="save">
      <h3>{{ draft.original ? 'Edit outbound target' : 'Add outbound target' }}</h3>
      <p v-if="error" role="alert">{{ error }}</p>
      <fieldset :disabled="locked">
        <label>Name <input v-model="draft.name" data-testid="outbound-name" :maxlength="draft.original ? 128 : 100" /></label>
        <label>Endpoint action <select v-model="draft.urlIntent" data-testid="outbound-url-intent">
          <option v-if="draft.original" value="keep">Keep current endpoint unchanged</option><option value="replace">Replace endpoint</option><option v-if="draft.original" value="remove">Strip endpoint userinfo, query and fragment</option>
        </select></label>
        <label v-if="draft.urlIntent === 'replace'">Endpoint URL (write-only) <input v-model="draft.url" type="password" autocomplete="new-password" maxlength="2048" data-testid="outbound-url" /></label>
        <label>Signing key action <select v-model="draft.secretIntent" data-testid="outbound-secret-intent"><option value="keep">Keep signing key</option><option value="replace">Replace signing key</option><option value="remove">Remove signing key</option></select></label>
        <label v-if="draft.secretIntent === 'replace'">Signing key (write-only) <input v-model="draft.secret" type="password" autocomplete="new-password" maxlength="256" data-testid="outbound-secret" /></label>
        <SettingsRow label="Enable this target" control-id="outbound-enabled"><SettingsSwitch id="outbound-enabled" label="Enable this outbound target" :checked="draft.enabled" :disabled="locked" data-testid="outbound-enabled" @change="draft.enabled = $event" /></SettingsRow>
        <SettingsRow label="Scrub secrets for this target" control-id="outbound-scrub"><SettingsSwitch id="outbound-scrub" label="Scrub secrets for this outbound target" :checked="draft.scrub" :disabled="locked" data-testid="outbound-scrub" @change="draft.scrub = $event" /></SettingsRow>
        <SettingsRow label="Verify TLS certificates for this target" control-id="outbound-tls"><SettingsSwitch id="outbound-tls" label="Verify TLS certificates for this outbound target" :checked="draft.tls" :disabled="locked" data-testid="outbound-tls" @change="draft.tls = $event" /></SettingsRow>
        <fieldset><legend>Event subscriptions (none selected means all)</legend><div class="settings-form-options"><label v-for="event in EVENTS" :key="event" class="toggle-inline"><input v-model="draft.events" type="checkbox" :value="event" /> {{ event }}</label></div></fieldset>
      </fieldset>
      <p>Refresh replaces this draft. Credentials are never read back. Save is explicit; Cancel writes nothing.</p>
      <div class="settings-form-actions">
        <button type="button" class="ghost" aria-label="Cancel outbound edit" :disabled="busy || confirming" @click="cancel">Cancel</button>
        <button type="button" class="primary" :aria-label="draft.original ? 'Save outbound webhook' : 'Add target (outbound webhook)'" :disabled="locked" @click="save">{{ draft.original ? 'Save' : 'Add target' }}</button>
      </div>
    </form>
    </dialog>
  </SettingsSection>
</template>
