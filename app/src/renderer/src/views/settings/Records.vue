<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import ObservabilityDetails from '../../components/ObservabilityDetails.vue'
import TrajectoryDetails from '../../components/TrajectoryDetails.vue'
import RecordDetails from '../../components/RecordDetails.vue'
import SettingsSection from '../../components/settings/SettingsSection.vue'
import SettingsRow from '../../components/settings/SettingsRow.vue'
import { settingsUnavailableText as unavailableText } from '../../capability'
import { basis, count, percent } from '../../format'
import { state } from '../../store'
import { management } from '../../stores/management'
import { auditVerificationNote, computerGeneration, computerReadiness, computerReleaseUncertain, computerSession, legacyComputer, loadAudit, loadComputer, loadHealth, loadRecords, loadTurns, loadUsage, logLevel, logMessage, reasonText, records, searchLogs, verifyAudit } from '../../stores/records'

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
const session = computed(() => computerSession(records.computer))
const readiness = computed(() => computerReadiness(records.computer))
const legacy = computed(() => legacyComputer(records.computer))
const computerKey = computed(() => `computer:${session.value?.session_id ?? ''}`)
const fullyVerified = computed(() => {
  const check = records.verify
  return check?.valid === true && check.availability !== 'not_enabled' &&
    typeof check.verified === 'number' && check.verified > 0 &&
    check.verified === check.total && !check.unsigned_prefix
})

</script>

<template>
  <ObservabilityDetails />
  <TrajectoryDetails />
  <RecordDetails />
  <SettingsSection title="Health" aria-label="Health">
    <p v-if="records.unavailable.health" class="manage-desc" role="status">{{ unavailableText('Health') }}</p>
    <template v-else>
    <SettingsRow label="Service status">
      <span v-if="records.health" class="panel-hint">
        {{ records.health.overall }}: {{ records.health.healthy_count }} healthy, {{ records.health.degraded_count }} degraded,
        {{ records.health.down_count }} down, {{ records.health.unconfigured_count }} not set up. Checked {{ at(records.health.checked_at) }}.
      </span>
      <button class="ghost" @click="loadHealth">Check again</button>
    </SettingsRow>
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
    </template>
  </SettingsSection>

  <SettingsSection title="Usage" aria-label="Usage">
    <p v-if="records.unavailable.usage" class="manage-desc" role="status">{{ unavailableText('Usage') }}</p>
    <template v-else>
    <SettingsRow label="Reported usage">
      <label class="limit">Period <select v-model="period" :aria-describedby="records.errors.usage ? 'records-usage-error' : undefined" @change="loadUsage(period)">
        <option value="24h">Last 24 hours</option>
        <option value="7d">Last 7 days</option>
        <option value="30d">Last 30 days</option>
        <option value="all">All time</option>
      </select></label>
    </SettingsRow>
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
    </template>
  </SettingsSection>

  <SettingsSection title="Audit" aria-label="Audit">
    <p v-if="records.unavailable.audit" class="manage-desc" role="status">{{ unavailableText('Audit') }}</p>
    <template v-else>
    <SettingsRow label="Tool call record" description="Tool calls, with their input (secrets removed) and result.">
      <button v-if="!records.unavailable.verify" class="ghost" @click="verifyAudit">Verify the record</button>
    </SettingsRow>
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
    </template>
  </SettingsSection>

  <SettingsSection title="Logs" aria-label="Logs">
    <p v-if="records.unavailable.logs" class="manage-desc" role="status">{{ unavailableText('Log search') }}</p>
    <template v-else>
    <SettingsRow label="Find log entries">
      <label class="limit">Level <select v-model="logs.level" :aria-describedby="records.errors.logs ? 'records-logs-error' : undefined" @change="searchLogs(logs)">
        <option value="all">Everything</option>
        <option value="info">Information</option>
        <option value="error">Errors</option>
      </select></label>
      <label class="limit">Search the logs <input v-model="logs.q" type="search" class="panel-filter" placeholder="Search" :aria-describedby="records.errors.logs ? 'records-logs-error' : undefined" @keydown.enter="searchLogs(logs)" /></label>
    </SettingsRow>
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
    </template>
  </SettingsSection>

  <SettingsSection title="Preserved work" aria-label="Turn state">
    <p v-if="records.unavailable.turns" class="manage-desc" role="status">{{ unavailableText('Preserved work') }}</p>
    <template v-else>
    <SettingsRow label="Saved requests" description="Requests kept so they can resume, including any that need your attention.">
      <button class="ghost" aria-label="Refresh preserved work" @click="loadTurns">Refresh</button>
    </SettingsRow>
    <p v-if="records.errors.turns" class="warn">Couldn't read preserved work: {{ records.errors.turns }}{{ records.turns ? ' Showing the last read.' : '' }}</p>
    <p v-if="records.turns && records.turns.availability !== 'available'" class="manage-desc">
      {{ records.turns.availability === 'not_enabled' ? 'Preserving work is off.' : 'Preserved work is unavailable right now.' }}
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
    </template>
  </SettingsSection>

  <SettingsSection title="Computer use report" aria-label="Computer use">
    <p v-if="records.unavailable.computer" class="manage-desc" role="status">{{ unavailableText('Computer use') }}</p>
    <template v-else>
    <SettingsRow label="Session report" description="Read-only status. Manage computer use and check recovery in Tools.">
      <span v-if="legacy" class="panel-hint">{{ legacy.enabled ? 'On' : 'Off' }}: {{ legacy.state }}.</span>
      <button class="ghost" aria-label="Refresh computer use" @click="loadComputer">Refresh</button>
      <button class="ghost" @click="state.settingsSection = 'tools'">Go to Tools</button>
    </SettingsRow>
    <p v-if="records.errors.computer" class="warn">Couldn't read computer use: {{ records.errors.computer }}{{ records.computer ? ' Showing the last read.' : '' }}</p>
    <template v-if="readiness">
      <p class="manage-desc">Management: {{ readiness.management_available ? 'available' : 'unavailable' }}.</p>
      <p v-if="readiness.foreground_available" role="status">Desktop input is available on X11. Each request still needs consent and a verified target. Odin must also accept the request before sending input.</p>
      <p v-else class="capability-unavailable" role="status">Desktop input is unavailable. Input route: {{ readiness.dispatch }}. Reason: {{ reasonText(readiness.reason) }}.</p>
      <p v-if="!session" class="manage-desc">No computer-use session is reported. This does not confirm that mouse and keyboard input was released.</p>
      <p v-else class="manage-desc">Checking recovery in Tools only reviews the recorded session. It does not start a session, send input, or confirm that you checked the computer.</p>
    </template>
    <template v-if="session?.session_id">
      <div class="manage-line">
        <code class="manage-name">{{ session.session_id }}</code>
        <span class="manage-count">generation {{ records.computer ? computerGeneration(records.computer) : '' }}</span>
        <span :class="['state-chip', session.state === 'quarantined' ? 'failed' : 'disabled']">{{ session.state }}</span>
      </div>
      <p v-if="session.recovery" :class="session.recovery.complete ? 'manage-desc' : 'warn'">
        Recovery: {{ session.recovery.status.replace(/_/g, ' ') }}, because {{ reasonText(session.recovery.reason) }}.
        {{ session.recovery.complete ? 'Recovery is recorded as complete; this does not confirm input is safe to resume.' : 'Recovery is incomplete. Do not resume desktop input.' }}
      </p>
      <p v-if="computerReleaseUncertain(session)" class="warn">Input release remains unverified.</p>
      <p v-if="management.notes[computerKey]" class="manage-note" role="status">{{ management.notes[computerKey] }}</p>
    </template>
    </template>
  </SettingsSection>
</template>
