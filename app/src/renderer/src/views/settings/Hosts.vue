<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { HostRow } from '../../../../shared/api'
import { ask } from '../../dialog'
import {
  activate,
  beginAdd,
  beginEdit,
  closeEnrollment,
  deleteHost,
  forceRevoke,
  goTo,
  hostKey,
  hosts,
  importLegacy,
  isLocal,
  loadHosts,
  saveHostSettings,
  scan,
  setHostEnabled,
  STEPS,
  testConnection
} from '../../stores/hosts'
import { management } from '../../stores/management'
import { settingsUnavailableText as unavailableText } from '../../capability'
import { settingsFields } from '../../settings-presentation'
import { saveField, settings } from '../../stores/settings'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import SettingsRow from '../../components/settings/SettingsRow.vue'
import SettingsSwitch from '../../components/settings/SettingsSwitch.vue'
import type { ConfigField } from '../../../../shared/api'
import { editableHere } from '../../settings-form'
import { state } from '../../store'

onMounted(loadHosts)

const TRUST: Record<string, string> = {
  pinned: 'Pinned key',
  ca: 'Host CA',
  tofu: 'Trusted on first use',
  legacy: 'Legacy known_hosts',
  local: 'This computer'
}

// The host settings as edited here; null means unchanged from what Odin has.
const defaultHost = ref<string | null>(null)
const allowTofu = ref<boolean | null>(null)
const shownDefault = computed(() => defaultHost.value ?? hosts.list?.configured_default_host ?? hosts.list?.default_host ?? '')
const shownTofu = computed(() => allowTofu.value ?? hosts.list?.tofu_enabled ?? false)
const copied = ref('')
const policyNote = ref('')
const enrollmentDialog = ref<HTMLDialogElement | null>(null)
watch(() => !!hosts.enrollment, async (open) => {
  await nextTick()
  if (open) enrollmentDialog.value?.showModal?.()
})
const policies = computed(() => settingsFields('hosts', 'more-options').flatMap((entry) => {
  const field = settings.meta?.fields.find((field) => field.path === entry.key)
  return field ? [{ ...entry, field }] : []
}))

async function changePolicy(field: ConfigField, value: boolean): Promise<void> {
  if (!editableHere(field) || field.type !== 'boolean' || field.sensitivity !== 'public') return
  const revision = settings.meta?.revision
  const epoch = state.recoveryEpoch
  const instance = state.app.coreInstanceId
  const widens = field.path === 'tools.governor.owner_can_override' ? value : !value
  policyNote.value = ''
  if (widens && !(await ask({ title: 'Allow more command access?', message: 'This weakens command safeguards. Only continue if you trust the people and tools using Odin.', confirmLabel: 'Allow change', danger: true }))) return
  if (revision !== settings.meta?.revision || epoch !== state.recoveryEpoch || instance !== state.app.coreInstanceId || settings.meta?.fields.find((entry) => entry.path === field.path) !== field) {
    policyNote.value = 'Settings changed while you were confirming. Check them, then try again.'
    return
  }
  await saveField(field, value)
}

async function saveSettings(): Promise<void> {
  const change = {
    ...(defaultHost.value === null ? {} : { default_host: defaultHost.value }),
    ...(allowTofu.value === null ? {} : { allow_host_tofu: allowTofu.value })
  }
  if (!Object.keys(change).length) return
  const revision = settings.meta?.revision
  const snapshot = hosts.list
  const epoch = state.recoveryEpoch
  const instance = state.app.coreInstanceId
  if (change.allow_host_tofu === true && !hosts.list?.tofu_enabled) {
    if (!(await ask({ title: 'Allow trust on first use?', message: 'New hosts can be trusted without a previously pinned key. You will still need to review the scanned key.', confirmLabel: 'Allow', danger: true }))) return
    if (revision !== settings.meta?.revision || snapshot !== hosts.list || epoch !== state.recoveryEpoch || instance !== state.app.coreInstanceId) { policyNote.value = 'Hosts changed while you were confirming. Check them, then save again.'; return }
  }
  if (await saveHostSettings(change)) {
    if (defaultHost.value === change.default_host) defaultHost.value = null
    if (allowTofu.value === change.allow_host_tofu) allowTofu.value = null
  }
}

async function copy(what: string, text: string): Promise<void> {
  const result = await window.odin.copyText(text)
  copied.value = result.ok ? `${what} copied.` : result.error.message
}

async function remove(host: HostRow): Promise<void> {
  const confirmed = await ask({
    title: 'Delete this host?',
    message: `${host.alias} is removed from Odin's hosts. If anything still names it, nothing is deleted and you see what.`,
    confirmLabel: 'Delete',
    danger: true
  })
  if (confirmed) await deleteHost(host.alias)
}

async function revoke(host: HostRow): Promise<void> {
  const confirmed = await ask({
    title: 'Force revoke this host?',
    message: `Revoke existing uses of ${host.alias}. Odin attempts to stop the processes it started there; their outcomes may be unknown. This does not turn off the host for future work.`,
    confirmLabel: 'Force revoke',
    danger: true
  })
  if (confirmed) await forceRevoke(host.alias)
}

function lastTest(host: HostRow): string {
  if (!host.last_test) return 'Not tested since Odin started'
  const at = typeof host.last_test.checked_at === 'number' ? new Date(host.last_test.checked_at * 1000).toLocaleString() : ''
  return `${host.last_test.ok === false ? 'Failed' : 'Passed'}${at ? ` ${at}` : ''}${host.last_test.detail ? `: ${host.last_test.detail}` : ''}`
}
</script>

<template>
  <SettingsSection title="Hosts" aria-label="Hosts">
    <header class="panel-head">
      <button v-if="!hosts.unavailable" class="ghost" @click="beginAdd">Add host</button>
    </header>
    <p v-if="hosts.unavailable" class="capability-unavailable" role="status">{{ unavailableText('Host management') }}</p>
    <template v-else>
    <SettingsRow label="Default host" description="Use this machine when a command does not name one." control-id="hosts-default">
        <select id="hosts-default" :value="shownDefault" @change="defaultHost = ($event.target as HTMLSelectElement).value">
          <option value="">None: every command names its host</option>
          <option v-for="host in hosts.list?.hosts ?? []" :key="host.host_id" :value="host.alias">{{ host.alias }}</option>
        </select>
    </SettingsRow>
    <div v-if="defaultHost !== null" class="panel-actions">
      <button class="ghost" :disabled="management.busy.hosts" @click="saveSettings">Save</button>
      <button class="ghost" @click="defaultHost = null; allowTofu = null">Cancel</button>
    </div>
    <p v-if="management.notes.hosts" class="manage-note" role="status">{{ management.notes.hosts }}</p>
    <p v-if="hosts.error" class="warn">{{ hosts.error }}</p>
    <p v-if="!hosts.list" class="manage-desc" role="status">Loading hosts…</p>
    <p v-else-if="!hosts.list.hosts.length" class="manage-desc">No hosts yet. Add a host to connect another machine.</p>
    <ul class="manage-list">
      <li v-for="host in hosts.list?.hosts ?? []" :key="host.host_id" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ host.alias }}</code>
          <span class="manage-count">{{ host.ssh_user }}@{{ host.address }}:{{ host.port }}</span>
          <span class="tag">{{ host.os }}</span>
          <span class="tag">{{ host.trust_state === 'local' ? TRUST.local : (TRUST[host.trust_mode] ?? host.trust_mode) }}</span>
          <span :class="['state-chip', host.targetable ? 'connected' : 'disabled']">{{ host.targetable ? 'Ready' : host.enabled ? 'Not ready' : 'Off' }}</span>
          <span v-if="host.draining" class="state-chip failed">Draining</span>
          <span class="manage-actions">
            <button v-if="host.trust_mode === 'legacy' && !isLocal(host.address)" type="button" class="ghost" :aria-label="`Enroll trusted key for host ${host.alias}`" :disabled="management.busy[`host:${host.alias}`]" @click="importLegacy(host)">Enroll trusted key</button>
            <button class="ghost" :aria-label="`Edit host ${host.alias}`" @click="beginEdit(host)">Edit</button>
            <label class="toggle-inline">Available
              <SettingsSwitch :id="`host-enabled-${encodeURIComponent(host.alias)}`" :label="`${host.enabled ? 'Turn off' : 'Turn on'} host ${host.alias}`" :checked="host.enabled" :disabled="management.busy[`host:${host.alias}`]" @change="setHostEnabled(host.alias, $event)" />
            </label>
            <button v-if="host.draining" class="ghost danger-item" :aria-label="`Force revoke host ${host.alias}…`" @click="revoke(host)">Force revoke…</button>
            <button class="ghost danger-item" :aria-label="`Delete host ${host.alias}…`" @click="remove(host)">Delete…</button>
          </span>
        </div>
        <p v-if="host.description" class="manage-desc">{{ host.description }}</p>
        <p class="manage-desc">{{ host.trust_state === 'local' ? '' : `Trust: ${host.trust_state}. ` }}{{ lastTest(host) }}.</p>
        <p v-if="host.diagnostic" class="warn">{{ host.diagnostic }}</p>
        <div v-if="hosts.references[host.alias]?.length" class="warn">
          Not deleted: these still name {{ host.alias }}.
          <ul class="refs">
            <li v-for="reference in hosts.references[host.alias]" :key="`${reference.kind}:${reference.location}`">{{ reference.kind }}: {{ reference.location }}</li>
          </ul>
        </div>
        <p v-if="management.notes[`host:${host.alias}`]" class="manage-note" role="status">{{ management.notes[`host:${host.alias}`] }}</p>
      </li>
    </ul>
    </template>
  </SettingsSection>

  <SettingsSection v-if="hosts.key && !hosts.unavailable" title="Odin's key" aria-label="Odin's key">
    <p class="manage-desc">Install this public key on a host to allow password-free SSH access.</p>
    <pre class="manage-json">{{ hosts.key.public_key }}</pre>
    <div class="panel-actions">
      <button class="ghost" @click="copy('The key', hosts.key.public_key)">Copy the key</button>
      <button class="ghost" @click="copy('The command', hosts.key.authorized_keys_command)">Copy the command that installs it</button>
    </div>
    <p class="manage-desc">Fingerprint {{ hosts.key.fingerprint }}. {{ hosts.key.permissions }}.</p>
    <p v-if="hosts.key.restart_pending" class="field-diff">A new key is saved; Odin uses it from the next start.</p>
    <p v-if="copied" class="manage-note" role="status">{{ copied }}</p>
  </SettingsSection>

  <dialog v-if="hosts.enrollment && !hosts.unavailable" ref="enrollmentDialog" class="host-editor-dialog" :aria-label="hosts.enrollment.editing ? `Edit host ${hosts.enrollment.form.alias}` : 'Add host'" @cancel.prevent="closeEnrollment">
  <SettingsSection :title="hosts.enrollment.editing ? `Change ${hosts.enrollment.form.alias}` : 'Add a host'" aria-label="Host enrollment">
    <template v-for="e in [hosts.enrollment]" :key="'enrollment'">
      <header class="panel-head">
        <span class="panel-hint">Step {{ e.step }} of 5: {{ STEPS[e.step - 1] }}</span>
        <button class="ghost" @click="closeEnrollment">Cancel</button>
      </header>
      <ol class="steps">
        <li v-for="(name, index) in STEPS" :key="name" :aria-current="e.step === index + 1 ? 'step' : undefined" :class="{ current: e.step === index + 1, done: e.step > index + 1 }">{{ name }}</li>
      </ol>

      <template v-if="e.step === 1">
        <label class="field-input">Alias <input v-model="e.form.alias" :disabled="e.editing" placeholder="build-box" /></label>
        <label class="field-input">Address <input v-model="e.form.address" placeholder="192.168.1.20 or host.lan" /></label>
        <label class="field-input">Port <input v-model.number="e.form.port" type="number" min="1" max="65535" /></label>
        <label class="field-input">SSH user <input v-model="e.form.ssh_user" /></label>
        <label class="field-input">
          System
          <select v-model="e.form.os">
            <option value="linux">Linux</option>
            <option value="macos">macOS</option>
          </select>
        </label>
        <label class="field-input">Description <input v-model="e.form.description" maxlength="200" placeholder="What the machine is" /></label>
        <label class="field-input">
          Trust its key by
          <select v-model="e.form.trust_mode">
            <option value="pinned">Pinning its fingerprint</option>
            <option value="ca">Its signing CA</option>
            <option value="tofu" :disabled="!hosts.list?.tofu_enabled">Trusting it on first use</option>
          </select>
        </label>
        <label v-if="isLocal(e.form.address)" class="toggle-inline">
          <input v-model="e.form.confirm_local" type="checkbox" /> Allow commands on this computer
        </label>
        <div class="panel-actions">
          <button class="ghost" :disabled="!e.form.alias.trim() || !e.form.address.trim()" @click="goTo(2)">Next</button>
        </div>
      </template>

      <template v-else-if="e.step === 2">
        <p v-if="isLocal(e.form.address)" class="manage-desc">Local commands do not need an SSH key.</p>
        <p v-else class="manage-desc">Install Odin's key for {{ e.form.ssh_user }}@{{ e.form.address }}, then continue.</p>
        <pre v-if="hosts.key && !isLocal(e.form.address)" class="manage-json">{{ hosts.key.authorized_keys_command }}</pre>
        <div class="panel-actions">
          <button v-if="hosts.key && !isLocal(e.form.address)" class="ghost" @click="copy('The command', hosts.key.authorized_keys_command)">Copy the command</button>
          <button class="ghost" @click="goTo(1)">Back</button>
          <button class="ghost" @click="goTo(3)">Next</button>
        </div>
        <p v-if="copied" class="manage-note" role="status">{{ copied }}</p>
      </template>

      <template v-else-if="e.step === 3">
        <p v-if="isLocal(e.form.address)" class="manage-desc">Confirm this computer's details. There is no remote host key to compare.</p>
        <p v-else-if="e.form.trust_mode === 'pinned'" class="manage-desc">
          Check the host's key yourself: on the host, run <code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code>, and paste its
          SHA256 fingerprint.
        </p>
        <p v-else-if="e.form.trust_mode === 'ca'" class="manage-desc">
          Paste the SHA256 fingerprint of the CA that signs the host's certificate, checked out of band. Not the host's own key.
        </p>
        <p v-else class="manage-desc">Odin scans the host's key and shows it. Check it, tick to trust it, then scan again.</p>
        <label v-if="!isLocal(e.form.address) && e.form.trust_mode !== 'tofu'" class="field-input">Expected fingerprints
        <textarea
          v-model="e.expected"
          class="field-input"
          rows="3"
          spellcheck="false"
          placeholder="SHA256:…"
          :aria-describedby="e.note ? 'host-enrollment-note' : undefined"
          :aria-invalid="e.note.includes('is not a fingerprint') ? 'true' : undefined"
        />
        </label>
        <p v-if="e.observed.length" class="manage-desc">Scanned: <code v-for="f in e.observed" :key="f" class="fingerprint">{{ f }}</code></p>
        <label v-if="e.form.trust_mode === 'tofu' && e.observed.length" class="toggle-inline">
          <input v-model="e.form.confirm_tofu" type="checkbox" /> Trust exactly this key
        </label>
        <div class="panel-actions">
          <button class="ghost" @click="goTo(2)">Back</button>
          <button class="ghost" :disabled="e.busy" @click="scan">{{ e.busy ? 'Scanning…' : 'Scan and compare' }}</button>
        </div>
      </template>

      <template v-else-if="e.step === 4">
        <p v-if="e.observed.length" class="manage-desc">Candidate key: <code v-for="f in e.observed" :key="f" class="fingerprint">{{ f }}</code></p>
        <p class="manage-desc">{{ isLocal(e.form.address) ? 'Odin checks the local system without SSH.' : 'Odin logs in without a password and checks the system, before the host can be used.' }}</p>
        <div class="panel-actions">
          <button class="ghost" @click="goTo(3)">Back</button>
          <button class="ghost" :disabled="e.busy" @click="testConnection">{{ e.busy ? 'Testing…' : 'Test the connection' }}</button>
        </div>
        <p v-if="e.test?.detail" class="manage-desc">{{ e.test.detail }}</p>
      </template>

      <template v-else>
        <p class="manage-desc">The test passed. {{ e.form.enabled ? `Saving makes ${e.form.alias} available for new work if its trust is ready.` : 'Saving keeps this host switched off.' }}</p>
        <div class="panel-actions">
          <button class="ghost" @click="goTo(3)">Back</button>
          <button class="ghost" :disabled="e.busy || !e.tested || management.busy[hostKey(e)]" @click="activate">
            {{ !e.form.enabled ? 'Save, keeping off' : e.editing ? 'Save and activate' : 'Activate' }}
          </button>
        </div>
        <p v-if="management.notes[hostKey(e)]" class="manage-note" role="status">{{ management.notes[hostKey(e)] }}</p>
      </template>
      <p v-if="e.note" id="host-enrollment-note" :class="e.step === 3 && e.observed.length && !e.token ? 'manage-note' : 'warn'" role="status">{{ e.note }}</p>
    </template>
  </SettingsSection>

  </dialog>
  <details v-if="!hosts.unavailable" class="settings-more-options">
    <summary>More options</summary>
    <SettingsSection title="Trust and command access">
      <SettingsRow label="Allow trust on first use" description="Review a host's key without pinning it in advance." control-id="hosts-tofu">
        <SettingsSwitch id="hosts-tofu" label="Allow trust on first use" :checked="shownTofu" :disabled="management.busy.hosts" described-by="hosts-tofu-description" @change="allowTofu = $event" />
        <template #note><div v-if="allowTofu !== null" class="panel-actions">
          <button class="ghost" :disabled="management.busy.hosts" @click="saveSettings">Save trust policy</button>
          <button class="ghost" @click="allowTofu = null">Cancel trust changes</button>
        </div></template>
      </SettingsRow>
      <SettingsRow v-for="entry in policies" :key="entry.key" :label="entry.label" :description="entry.help" :control-id="`hosts-policy-${entry.key}`">
        <input :id="`hosts-policy-${entry.key}`" type="checkbox" role="switch" class="settings-switch" :aria-label="entry.label" :aria-describedby="`hosts-policy-${entry.key}-description`" :aria-invalid="entry.field.apply_state === 'invalid' || undefined" :checked="entry.field.desired === true" :disabled="settings.fields[entry.key]?.status === 'saving' || !editableHere(entry.field) || entry.field.sensitivity !== 'public' || entry.field.type !== 'boolean'" @change="changePolicy(entry.field, ($event.target as HTMLInputElement).checked); ($event.target as HTMLInputElement).checked = entry.field.desired === true" />
        <template #note>
          <p v-if="entry.field.apply_state === 'invalid'" class="warn">This value is invalid. Choose a value and save again.</p>
          <p v-if="entry.field.apply_state === 'drift'" class="warn">The running value differs from the saved value.</p>
          <p v-if="entry.field.apply_state === 'unknown'" class="warn">The running value is unknown. Refresh before relying on it.</p>
          <p v-if="settings.fields[entry.key]" class="manage-note" role="status">{{ settings.fields[entry.key]?.message ?? (settings.fields[entry.key]?.status === 'saving' ? 'Saving…' : 'Saved') }}</p>
        </template>
      </SettingsRow>
      <p v-if="policyNote" class="warn" role="status">{{ policyNote }}</p>
    </SettingsSection>
  </details>
</template>

<style scoped>
.host-editor-dialog { width: min(760px, calc(100vw - 48px)); max-height: calc(100vh - 48px); overflow: auto; padding: 0 20px; border: 1px solid var(--border); border-radius: 12px; color: var(--text); background: var(--bg); }
.host-editor-dialog::backdrop { background: rgb(0 0 0 / 55%); }
</style>
