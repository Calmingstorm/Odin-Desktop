<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ask } from '../../dialog'
import { unavailableText } from '../../capability'
import { basis, count, percent } from '../../format'
import { state } from '../../store'
import { management } from '../../stores/management'
import { auditVerificationNote, loadAudit, loadComputer, loadHealth, loadRecords, loadTurns, loadUsage, logLevel, logMessage, reasonText, reconcileComputer, records, searchLogs, verifyAudit } from '../../stores/records'

onMounted(loadRecords)

const PERIODS = { '24h': 'the last 24 hours', '7d': 'the last 7 days', '30d': 'the last 30 days', all: 'all time' } as const
const period = ref<keyof typeof PERIODS>('7d')
const audit = reactive({ q: '', tool: '', error_only: false })
const logs = reactive<{ q: string; level: 'error' | 'info' | 'all' }>({ q: '', level: 'all' })

const at = (value: string | number | null | undefined): string => value == null || value === '' ? '' : new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString()
const conversationTitle = (id: string): string => state.conversations.find((c) => c.id === id)?.title ?? id
/** The period the usage shown covers: the answer's own, which lags the choice until its read lands. */
const usagePeriod = computed(() => {
  const shown = records.usage?.period
  return shown && shown in PERIODS ? PERIODS[shown as keyof typeof PERIODS] : shown
})
const computerKey = computed(() => `computer:${records.computer?.session_id ?? ''}`)
const fullyVerified = computed(() => {
  const check = records.verify
  return check?.valid === true && check.availability !== 'not_enabled' &&
    typeof check.verified === 'number' && check.verified > 0 &&
    check.verified === check.total && !check.unsigned_prefix
})

async function reconcile(): Promise<void> {
  const status = records.computer
  if (!status) return
  const confirmed = await ask({
    title: 'Release this session?',
    message: `Odin couldn't verify that session ${status.session_id} let go of the mouse and keyboard. Check the computer first. Releasing it records that you checked; Odin still treats the cleanup as unverified.`,
    confirmLabel: 'Release',
    danger: true
  })
  if (confirmed) await reconcileComputer(status)
}
</script>

<template>
  <section v-if="records.unavailable.health" class="panel" aria-label="Health">
    <h3>Health</h3><p class="manage-desc" role="status">{{ unavailableText('Health') }}</p>
  </section>
  <section v-else class="panel" aria-label="Health">
    <header class="panel-head">
      <h3>Health</h3>
      <span v-if="records.health" class="panel-hint">
        {{ records.health.overall }}: {{ records.health.healthy_count }} healthy, {{ records.health.degraded_count }} degraded,
        {{ records.health.down_count }} down, {{ records.health.unconfigured_count }} not set up. Checked {{ at(records.health.checked_at) }}.
      </span>
      <button class="ghost" @click="loadHealth">Check again</button>
    </header>
    <p v-if="records.errors.health" class="warn">Couldn't check: {{ records.errors.health }}{{ records.health ? ' Showing the last check.' : '' }}</p>
    <ul class="manage-list">
      <li v-for="c in records.health?.components ?? []" :key="c.name" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ c.name }}</code>
          <span :class="['state-chip', c.status === 'ok' || c.status === 'healthy' ? 'connected' : c.status === 'unconfigured' || c.status === 'unavailable' ? 'disabled' : 'failed']">{{ c.status }}</span>
          <span class="manage-count">{{ c.detail }}</span>
        </div>
      </li>
    </ul>
  </section>

  <section v-if="records.unavailable.usage" class="panel" aria-label="Usage">
    <h3>Usage</h3><p class="manage-desc" role="status">{{ unavailableText('Usage') }}</p>
  </section>
  <section v-else class="panel" aria-label="Usage">
    <header class="panel-head">
      <h3>Usage</h3>
      <label class="limit">Period <select v-model="period" :aria-describedby="records.errors.usage ? 'records-usage-error' : undefined" @change="loadUsage(period)">
        <option value="24h">Last 24 hours</option>
        <option value="7d">Last 7 days</option>
        <option value="30d">Last 30 days</option>
        <option value="all">All time</option>
      </select></label>
    </header>
    <p v-if="records.errors.usage" id="records-usage-error" class="warn" role="status">Couldn't read usage: {{ records.errors.usage }}{{ records.usage ? ' Showing the last read.' : '' }}</p>
    <template v-if="records.usage">
      <p class="manage-desc" :title="basis(records.usage.tokens)">
        {{ count(records.usage.tokens) }} tokens in {{ usagePeriod }} ({{ basis(records.usage.tokens) }}).
      </p>
      <p v-for="q in records.usage.quota" :key="`${q.account}:${q.window}`" class="manage-desc">
        {{ q.account }}, {{ q.window }} limit:
        {{ q.used_percent.kind === 'unknown' ? 'use not reported' : `${percent(q.used_percent)} used` }}{{ q.resets_at ? `, resets ${at(q.resets_at)}` : '' }}.
      </p>
      <pre v-if="records.usage.summary" class="manage-json">{{ records.usage.summary }}</pre>
    </template>
  </section>

  <section v-if="records.unavailable.audit" class="panel" aria-label="Audit">
    <h3>Audit</h3><p class="manage-desc" role="status">{{ unavailableText('Audit') }}</p>
  </section>
  <section v-else class="panel" aria-label="Audit">
    <header class="panel-head">
      <h3>Audit</h3>
      <span class="panel-hint">Every tool call, with its input (secrets scrubbed) and result.</span>
      <button v-if="!records.unavailable.verify" class="ghost" @click="verifyAudit">Verify the record</button>
    </header>
    <p v-if="records.unavailable.verify" class="manage-desc" role="status">{{ unavailableText('Audit verification') }}</p>
    <p v-else-if="records.errors.verify" class="warn">Couldn't check the record: {{ records.errors.verify }}. It is neither verified nor known to be broken.</p>
    <p v-else-if="records.verify" :class="fullyVerified ? 'field-saved' : 'warn'">
      {{ auditVerificationNote(records.verify) }}
    </p>
    <div class="limits">
      <label class="limit">Search the audit <input v-model="audit.q" type="search" class="panel-filter" placeholder="Search" :aria-describedby="records.errors.audit ? 'records-audit-error' : undefined" @keydown.enter="loadAudit(audit)" /></label>
      <label class="limit">Tool <input v-model="audit.tool" class="panel-filter" placeholder="Tool" :aria-describedby="records.errors.audit ? 'records-audit-error' : undefined" @keydown.enter="loadAudit(audit)" /></label>
      <label class="toggle-inline"><input v-model="audit.error_only" type="checkbox" /> Errors only</label>
      <button class="ghost" @click="loadAudit(audit)">Show</button>
    </div>
    <p v-if="records.errors.audit" id="records-audit-error" class="warn" role="status">Couldn't read the audit: {{ records.errors.audit }}{{ records.loaded.audit ? ' Showing the last read.' : '' }}</p>
    <table class="runs audit">
      <tbody>
        <tr v-for="(e, i) in records.audit" :key="i">
          <td>{{ at(e.timestamp) }}</td>
          <td>
            <code>{{ e.tool_name }}</code>
            <details v-if="e.tool_input && Object.keys(e.tool_input).length" class="audit-input">
              <summary :aria-label="`Input for ${e.tool_name} at ${at(e.timestamp)}`">Input</summary>
              <pre class="manage-json">{{ JSON.stringify(e.tool_input, null, 2) }}</pre>
            </details>
          </td>
          <td>{{ e.host ?? '' }}</td>
          <td :class="e.error ? 'bad' : ''">{{ e.error ?? e.result_summary ?? e.detail ?? '' }}</td>
          <td>{{ e.execution_time_ms !== undefined ? `${e.execution_time_ms} ms` : '' }}</td>
        </tr>
        <tr v-if="records.loaded.audit && !records.audit.length"><td>Nothing recorded.</td></tr>
      </tbody>
    </table>
  </section>

  <section v-if="records.unavailable.logs" class="panel" aria-label="Logs">
    <h3>Logs</h3><p class="manage-desc" role="status">{{ unavailableText('Log search') }}</p>
  </section>
  <section v-else class="panel" aria-label="Logs">
    <header class="panel-head">
      <h3>Logs</h3>
      <label class="limit">Level <select v-model="logs.level" :aria-describedby="records.errors.logs ? 'records-logs-error' : undefined" @change="searchLogs(logs)">
        <option value="all">Everything</option>
        <option value="info">Information</option>
        <option value="error">Errors</option>
      </select></label>
      <label class="limit">Search the logs <input v-model="logs.q" type="search" class="panel-filter" placeholder="Search" :aria-describedby="records.errors.logs ? 'records-logs-error' : undefined" @keydown.enter="searchLogs(logs)" /></label>
    </header>
    <p v-if="records.errors.logs" id="records-logs-error" class="warn" role="status">Couldn't search the logs: {{ records.errors.logs }}{{ records.loaded.logs ? ' Showing the last search.' : '' }}</p>
    <table class="runs">
      <tbody>
        <tr v-for="(e, i) in records.logs" :key="i">
          <td>{{ at(e.timestamp) }}</td>
          <td :class="logLevel(e) === 'ERROR' ? 'bad' : ''">{{ logLevel(e) }}</td>
          <td><code>{{ e.tool_name }}</code> {{ logMessage(e) }}</td>
        </tr>
        <tr v-if="records.loaded.logs && !records.logs.length"><td>No entries.</td></tr>
      </tbody>
    </table>
  </section>

  <section v-if="records.unavailable.turns" class="panel" aria-label="Turn state">
    <h3>Preserved work</h3><p class="manage-desc" role="status">{{ unavailableText('Preserved work') }}</p>
  </section>
  <section v-else class="panel" aria-label="Turn state">
    <header class="panel-head">
      <h3>Preserved work</h3>
      <span class="panel-hint">Requests Odin kept so they can resume, and any that need your attention.</span>
      <button class="ghost" aria-label="Refresh preserved work" @click="loadTurns">Refresh</button>
    </header>
    <p v-if="records.errors.turns" class="warn">Couldn't read preserved work: {{ records.errors.turns }}{{ records.turns ? ' Showing the last read.' : '' }}</p>
    <p v-if="records.turns && records.turns.availability !== 'available'" class="manage-desc">
      {{ records.turns.availability === 'not_enabled' ? 'Turn state is off.' : 'Turn state is unavailable right now.' }}
    </p>
    <ul v-else class="manage-list">
      <li v-for="t in records.turns?.data.turns ?? []" :key="`${t.source}:${t.channel_id}:${t.message_id}:${t.turn_generation}`" class="manage-row">
        <div class="manage-line">
          <span :class="['state-chip', t.requires_attention ? 'failed' : 'disabled']">{{ t.status.toLowerCase() }}</span>
          <span class="manage-count">{{ t.source }}, in {{ conversationTitle(t.channel_id) }}, request {{ t.message_id }}, generation {{ t.turn_generation }}</span>
          <span v-if="t.requires_attention" class="state-chip failed">Needs attention</span>
          <span v-if="t.manual_resolution_operations" class="state-chip failed">{{ t.manual_resolution_operations }} need manual resolution</span>
          <span v-if="t.outcome_unknown_operations" class="manage-count">{{ t.outcome_unknown_operations }} historical unknown (diagnostic only)</span>
        </div>
        <p class="manage-desc">Started {{ at(t.created_at) }}{{ t.has_checkpoint ? '. Progress is kept.' : '.' }}</p>
      </li>
      <li v-if="records.turns && !(records.turns.data.turns ?? []).length" class="manage-desc">Nothing preserved.</li>
    </ul>
  </section>

  <section v-if="records.unavailable.computer" class="panel" aria-label="Computer use">
    <h3>Computer use</h3><p class="manage-desc" role="status">{{ unavailableText('Computer use') }}</p>
  </section>
  <section v-else class="panel" aria-label="Computer use">
    <header class="panel-head">
      <h3>Computer use</h3>
      <span v-if="records.computer" class="panel-hint">{{ records.computer.enabled ? 'On' : 'Off' }}: {{ records.computer.state }}.</span>
      <button class="ghost" aria-label="Refresh computer use" @click="loadComputer">Refresh</button>
    </header>
    <p v-if="records.errors.computer" class="warn">Couldn't read computer use: {{ records.errors.computer }}{{ records.computer ? ' Showing the last read.' : '' }}</p>
    <template v-if="records.computer?.session_id">
      <div class="manage-line">
        <code class="manage-name">{{ records.computer.session_id }}</code>
        <span class="manage-count">generation {{ records.computer.session_generation ?? records.computer.generation }}</span>
        <span :class="['state-chip', records.computer.state === 'quarantined' ? 'failed' : 'connected']">{{ records.computer.state }}</span>
        <span v-if="records.computer.state === 'quarantined'" class="manage-actions">
          <button class="ghost danger-item" :aria-label="`Release session ${records.computer.session_id}…`" :disabled="management.busy[computerKey]" @click="reconcile">Release…</button>
        </span>
      </div>
      <p v-if="records.computer.recovery" :class="records.computer.recovery.complete ? 'manage-desc' : 'warn'">
        Recovery: {{ records.computer.recovery.status.replace(/_/g, ' ') }}, because {{ reasonText(records.computer.recovery.reason) }}.
        {{ records.computer.recovery.complete ? 'Complete.' : 'Not complete: the cleanup is unverified.' }}
      </p>
      <p v-if="management.notes[computerKey]" class="manage-note" role="status">{{ management.notes[computerKey] }}</p>
    </template>
  </section>
</template>
