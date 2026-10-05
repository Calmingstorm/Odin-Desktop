<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import type { ComputerSession } from '../../../../shared/api'
import { ask } from '../../dialog'
import { basis, count, percent } from '../../format'
import { state } from '../../store'
import { management } from '../../stores/management'
import { loadAudit, loadComputer, loadHealth, loadRecords, loadTurns, loadUsage, reconcileComputer, records, searchLogs, verifyAudit } from '../../stores/records'

onMounted(loadRecords)

const period = ref<'24h' | '7d' | '30d' | 'all'>('7d')
const audit = reactive({ q: '', tool: '', error_only: false })
const logs = reactive<{ q: string; level: 'error' | 'info' | 'all' }>({ q: '', level: 'all' })

const at = (iso: string | null | undefined): string => (iso ? new Date(iso).toLocaleString() : '')
const conversationTitle = (id: string): string => state.conversations.find((c) => c.id === id)?.title ?? 'a conversation that is gone'

async function reconcile(session: ComputerSession): Promise<void> {
  const confirmed = await ask({
    title: 'Release this session?',
    message: `Odin couldn't verify that session ${session.session_id} let go of the mouse and keyboard. Check the computer first. Releasing it acknowledges that the cleanup is unverified.`,
    confirmLabel: 'Release',
    danger: true
  })
  if (confirmed) await reconcileComputer(session)
}
</script>

<template>
  <section class="panel" aria-label="Health">
    <header class="panel-head">
      <h3>Health</h3>
      <span v-if="records.health" class="panel-hint">
        {{ records.health.overall }}: {{ records.health.healthy_count }} healthy, {{ records.health.degraded_count }} degraded,
        {{ records.health.down_count }} down, {{ records.health.unconfigured_count }} not set up. Checked {{ at(records.health.checked_at) }}.
      </span>
      <button class="ghost" @click="loadHealth">Check again</button>
    </header>
    <ul class="manage-list">
      <li v-for="c in records.health?.components ?? []" :key="c.name" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ c.name }}</code>
          <span :class="['state-chip', c.status === 'healthy' ? 'connected' : c.status === 'unconfigured' ? 'disabled' : 'failed']">{{ c.status }}</span>
          <span class="manage-count">{{ c.detail }}</span>
        </div>
      </li>
    </ul>
  </section>

  <section class="panel" aria-label="Usage">
    <header class="panel-head">
      <h3>Usage</h3>
      <select v-model="period" aria-label="Period" @change="loadUsage(period)">
        <option value="24h">Last 24 hours</option>
        <option value="7d">Last 7 days</option>
        <option value="30d">Last 30 days</option>
        <option value="all">All time</option>
      </select>
    </header>
    <template v-if="records.usage">
      <p class="manage-desc" :title="basis(records.usage.tokens)">{{ count(records.usage.tokens) }} tokens ({{ basis(records.usage.tokens) }}).</p>
      <p v-for="q in records.usage.quota" :key="`${q.account}:${q.window}`" class="manage-desc">
        {{ q.account }}, {{ q.window }} limit:
        {{ q.used_percent.kind === 'unknown' ? 'use not reported' : `${percent(q.used_percent)} used` }}{{ q.resets_at ? `, resets ${at(q.resets_at)}` : '' }}.
      </p>
      <pre v-if="records.usage.summary" class="manage-json">{{ records.usage.summary }}</pre>
    </template>
  </section>

  <section class="panel" aria-label="Audit">
    <header class="panel-head">
      <h3>Audit</h3>
      <span class="panel-hint">Every tool call, with its input (secrets scrubbed) and result.</span>
      <button class="ghost" @click="verifyAudit">Verify the record</button>
    </header>
    <p v-if="records.verify" :class="records.verify.valid ? 'field-saved' : 'warn'">
      {{ records.verify.valid ? `Intact: ${records.verify.verified ?? records.verify.total} entries verified.` : `Not intact: ${records.verify.reason ?? 'the chain is broken'}.` }}
    </p>
    <div class="limits">
      <input v-model="audit.q" type="search" class="panel-filter" placeholder="Search" aria-label="Search the audit" @keydown.enter="loadAudit(audit)" />
      <input v-model="audit.tool" class="panel-filter" placeholder="Tool" aria-label="Tool" @keydown.enter="loadAudit(audit)" />
      <label class="toggle-inline"><input v-model="audit.error_only" type="checkbox" /> Errors only</label>
      <button class="ghost" @click="loadAudit(audit)">Show</button>
    </div>
    <p v-if="management.error" class="warn">{{ management.error }}</p>
    <table class="runs audit">
      <tbody>
        <tr v-for="(e, i) in records.audit" :key="i">
          <td>{{ at(e.timestamp) }}</td>
          <td><code>{{ e.tool_name }}</code></td>
          <td>{{ e.host ?? '' }}</td>
          <td :class="e.error ? 'bad' : ''">{{ e.error ?? e.result_summary ?? e.detail ?? '' }}</td>
          <td>{{ e.execution_time_ms !== undefined ? `${e.execution_time_ms} ms` : '' }}</td>
        </tr>
        <tr v-if="!records.audit.length"><td>Nothing recorded.</td></tr>
      </tbody>
    </table>
  </section>

  <section class="panel" aria-label="Logs">
    <header class="panel-head">
      <h3>Logs</h3>
      <select v-model="logs.level" aria-label="Level" @change="searchLogs(logs)">
        <option value="all">Everything</option>
        <option value="info">Information</option>
        <option value="error">Errors</option>
      </select>
      <input v-model="logs.q" type="search" class="panel-filter" placeholder="Search" aria-label="Search the logs" @keydown.enter="searchLogs(logs)" />
    </header>
    <table class="runs">
      <tbody>
        <tr v-for="(e, i) in records.logs" :key="i">
          <td>{{ at(e.timestamp) }}</td>
          <td :class="e.level === 'ERROR' ? 'bad' : ''">{{ e.level }}</td>
          <td>{{ e.message }}</td>
        </tr>
        <tr v-if="!records.logs.length"><td>No entries.</td></tr>
      </tbody>
    </table>
  </section>

  <section class="panel" aria-label="Turn state">
    <header class="panel-head">
      <h3>Preserved work</h3>
      <span class="panel-hint">Requests Odin kept so they can resume, and any that need your attention.</span>
      <button class="ghost" @click="loadTurns">Refresh</button>
    </header>
    <p v-if="records.turns && records.turns.availability !== 'available'" class="manage-desc">
      {{ records.turns.availability === 'not_enabled' ? 'Turn state is off.' : 'Turn state is unavailable right now.' }}
    </p>
    <ul v-else class="manage-list">
      <li v-for="t in records.turns?.data.turns ?? []" :key="`${t.request_id}:${t.turn_generation}`" class="manage-row">
        <div class="manage-line">
          <span :class="['state-chip', t.attention ? 'failed' : 'disabled']">{{ t.status.toLowerCase() }}</span>
          <span class="manage-count">In {{ conversationTitle(t.conversation_id) }}, generation {{ t.turn_generation }}</span>
          <span v-if="t.outcome_unknown_operations" class="state-chip failed">{{ t.outcome_unknown_operations }} unknown</span>
        </div>
        <p class="manage-desc">Started {{ at(t.created_at) }}{{ t.has_checkpoint ? '. Progress is kept.' : '.' }}</p>
      </li>
      <li v-if="!(records.turns?.data.turns ?? []).length" class="manage-desc">Nothing preserved.</li>
    </ul>
  </section>

  <section class="panel" aria-label="Computer use">
    <header class="panel-head">
      <h3>Computer use</h3>
      <span v-if="records.computer" class="panel-hint">{{ records.computer.enabled ? 'On' : 'Off' }}: {{ records.computer.state }}.</span>
      <button class="ghost" @click="loadComputer">Refresh</button>
    </header>
    <p v-if="records.computer?.reason" class="warn">{{ records.computer.reason }}</p>
    <ul class="manage-list">
      <li v-for="s in records.computer?.sessions ?? []" :key="s.session_id" class="manage-row">
        <div class="manage-line">
          <code class="manage-name">{{ s.session_id }}</code>
          <span class="manage-count">{{ s.target }}, generation {{ s.generation }}, since {{ at(s.started_at) }}</span>
          <span :class="['state-chip', s.quarantined ? 'failed' : 'connected']">{{ s.state }}</span>
          <span v-if="s.quarantined" class="manage-actions"><button class="ghost danger-item" @click="reconcile(s)">Release…</button></span>
        </div>
        <p v-if="management.notes[`computer:${s.session_id}`]" class="manage-note" role="status">{{ management.notes[`computer:${s.session_id}`] }}</p>
      </li>
    </ul>
  </section>
</template>
