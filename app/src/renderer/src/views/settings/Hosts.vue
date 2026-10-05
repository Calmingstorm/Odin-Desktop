<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
  isLocal,
  loadHosts,
  saveHostSettings,
  scan,
  setHostEnabled,
  STEPS,
  testConnection
} from '../../stores/hosts'
import { management } from '../../stores/management'
import { unavailableText } from '../../capability'

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
const shownDefault = computed(() => defaultHost.value ?? hosts.list?.default_host ?? '')
const shownTofu = computed(() => allowTofu.value ?? hosts.list?.tofu_enabled ?? false)
const copied = ref('')

async function saveSettings(): Promise<void> {
  if (await saveHostSettings({ default_host: shownDefault.value, allow_host_tofu: shownTofu.value })) {
    defaultHost.value = null
    allowTofu.value = null
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
    message: `Odin stops using ${host.alias} at once. Work running there is interrupted and the processes it started there are stopped, so what they had done may be unknown.`,
    confirmLabel: 'Force revoke',
    danger: true
  })
  if (confirmed) await forceRevoke(host.alias)
}

function lastTest(host: HostRow): string {
  if (!host.last_test) return 'Not tested since Odin started'
  const at = host.last_test.at ? new Date(host.last_test.at).toLocaleString() : ''
  return `${host.last_test.ok === false ? 'Failed' : 'Passed'}${at ? ` ${at}` : ''}${host.last_test.detail ? `: ${host.last_test.detail}` : ''}`
}
</script>

<template>
  <section class="panel" aria-label="Hosts">
    <header class="panel-head">
      <h3>Hosts</h3>
      <span class="panel-hint">Machines Odin runs commands on, over SSH with its own key. Each host's key is trusted only as you set.</span>
      <button v-if="!hosts.unavailable" class="ghost" @click="beginAdd">Add host</button>
    </header>
    <p v-if="hosts.unavailable" class="capability-unavailable" role="status">{{ unavailableText('Host management') }}</p>
    <template v-else>
    <div class="limits">
      <label class="limit">
        Default host
        <select :value="shownDefault" @change="defaultHost = ($event.target as HTMLSelectElement).value">
          <option value="">None: every command names its host</option>
          <option v-for="host in hosts.list?.hosts ?? []" :key="host.host_id" :value="host.alias">{{ host.alias }}</option>
        </select>
      </label>
      <label class="toggle-inline">
        <input type="checkbox" :checked="shownTofu" @change="allowTofu = ($event.target as HTMLInputElement).checked" />
        Allow trust on first use
      </label>
      <button class="ghost" :disabled="management.busy.hosts" @click="saveSettings">Save</button>
    </div>
    <p v-if="management.notes.hosts" class="manage-note" role="status">{{ management.notes.hosts }}</p>
    <p v-if="hosts.error" class="warn">{{ hosts.error }}</p>
    <ul class="manage-list">
      <li v-for="host in hosts.list?.hosts ?? []" :key="host.host_id" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ host.alias }}</code>
          <span class="manage-count">{{ host.ssh_user }}@{{ host.address }}:{{ host.port }}</span>
          <span class="tag">{{ host.os }}</span>
          <span class="tag">{{ host.trust_state === 'local' ? TRUST.local : (TRUST[host.trust_mode] ?? host.trust_mode) }}</span>
          <span :class="['state-chip', host.targetable ? 'connected' : 'disabled']">{{ host.targetable ? 'Ready' : 'Off' }}</span>
          <span v-if="host.draining" class="state-chip failed">Draining</span>
          <span class="manage-actions">
            <button class="ghost" :aria-label="`Edit host ${host.alias}`" @click="beginEdit(host)">Edit</button>
            <button class="ghost" :aria-label="`${host.enabled ? 'Turn off' : 'Turn on'} host ${host.alias}`" :disabled="management.busy[`host:${host.alias}`]" @click="setHostEnabled(host.alias, !host.enabled)">
              {{ host.enabled ? 'Turn off' : 'Turn on' }}
            </button>
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
  </section>

  <section v-if="hosts.key && !hosts.unavailable" class="panel" aria-label="Odin's key">
    <header class="panel-head">
      <h3>Odin's key</h3>
      <span class="panel-hint">Add it to a host's authorized keys, and Odin can log in there. It never uses passwords.</span>
    </header>
    <pre class="manage-json">{{ hosts.key.public_key }}</pre>
    <div class="panel-actions">
      <button class="ghost" @click="copy('The key', hosts.key.public_key)">Copy the key</button>
      <button class="ghost" @click="copy('The command', hosts.key.authorized_keys_command)">Copy the command that installs it</button>
    </div>
    <p class="manage-desc">Fingerprint {{ hosts.key.fingerprint }}. {{ hosts.key.permissions }}.</p>
    <p v-if="hosts.key.restart_pending" class="field-diff">A new key is saved; Odin uses it from the next start.</p>
    <p v-if="copied" class="manage-note" role="status">{{ copied }}</p>
  </section>

  <section v-if="hosts.enrollment && !hosts.unavailable" class="panel" aria-label="Host enrollment">
    <template v-for="e in [hosts.enrollment]" :key="'enrollment'">
      <header class="panel-head">
        <h3>{{ e.editing ? `Change ${e.form.alias}` : 'Add a host' }}</h3>
        <span class="panel-hint">Step {{ e.step }} of 5: {{ STEPS[e.step - 1] }}</span>
        <button class="ghost" @click="closeEnrollment">Close</button>
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
          <input v-model="e.form.confirm_local" type="checkbox" /> This is this computer: commands run inside Odin itself
        </label>
        <div class="panel-actions">
          <button class="ghost" :disabled="!e.form.alias.trim() || !e.form.address.trim()" @click="goTo(2)">Next</button>
        </div>
      </template>

      <template v-else-if="e.step === 2">
        <p class="manage-desc">Install Odin's key for {{ e.form.ssh_user }}@{{ e.form.address }}, then continue.</p>
        <pre v-if="hosts.key" class="manage-json">{{ hosts.key.authorized_keys_command }}</pre>
        <div class="panel-actions">
          <button v-if="hosts.key" class="ghost" @click="copy('The command', hosts.key.authorized_keys_command)">Copy the command</button>
          <button class="ghost" @click="goTo(1)">Back</button>
          <button class="ghost" @click="goTo(3)">Next</button>
        </div>
        <p v-if="copied" class="manage-note" role="status">{{ copied }}</p>
      </template>

      <template v-else-if="e.step === 3">
        <p v-if="e.form.trust_mode === 'pinned'" class="manage-desc">
          Check the host's key yourself: on the host, run <code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code>, and paste its
          SHA256 fingerprint.
        </p>
        <p v-else-if="e.form.trust_mode === 'ca'" class="manage-desc">
          Paste the SHA256 fingerprint of the CA that signs the host's certificate, checked out of band. Not the host's own key.
        </p>
        <p v-else class="manage-desc">Odin scans the host's key and shows it. Check it, tick to trust it, then scan again.</p>
        <label v-if="e.form.trust_mode !== 'tofu'" class="field-input">Expected fingerprints
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
        <p class="manage-desc">Odin logs in without a password and checks the system, before the host can be used.</p>
        <div class="panel-actions">
          <button class="ghost" @click="goTo(3)">Back</button>
          <button class="ghost" :disabled="e.busy" @click="testConnection">{{ e.busy ? 'Testing…' : 'Test the connection' }}</button>
        </div>
        <p v-if="e.test?.detail" class="manage-desc">{{ e.test.detail }}</p>
      </template>

      <template v-else>
        <p class="manage-desc">The test passed. Activating makes {{ e.form.alias }} live at once.</p>
        <div class="panel-actions">
          <button class="ghost" @click="goTo(3)">Back</button>
          <button class="ghost" :disabled="e.busy || !e.tested || management.busy[hostKey(e)]" @click="activate">
            {{ e.editing ? 'Save and activate' : 'Activate' }}
          </button>
        </div>
        <p v-if="management.notes[hostKey(e)]" class="manage-note" role="status">{{ management.notes[hostKey(e)] }}</p>
      </template>
      <p v-if="e.note" id="host-enrollment-note" :class="e.step === 3 && e.observed.length && !e.token ? 'manage-note' : 'warn'" role="status">{{ e.note }}</p>
    </template>
  </section>
</template>
