<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import type { ScheduleRow, WorkKind } from '../../../../shared/api'
import WorkList from '../../components/WorkList.vue'
import { ask } from '../../dialog'
import { ACTIONS, blankForm, buildSave, formFor, REPORT_FORMATS, WEBHOOK_METHODS, type ScheduleForm } from '../../schedule-form'
import { analyzeLocalDateTime } from '../../schedule-time'
import { state } from '../../store'
import { management } from '../../stores/management'
import { checkCron, deleteSchedule, loadHistory, loadSchedules, resetFailures, runNow, saveSchedule, schedules, setPaused } from '../../stores/schedules'

onMounted(loadSchedules)

/** Running work is listed here too; schedules have their own section above it. */
const RUNNING: WorkKind[] = ['agent', 'task', 'loop', 'process', 'workflow']
/** The tools Odin's scheduler runs as checks; the core says so if that changes. */
const CHECK_TOOLS = ['run_command', 'run_command_multi', 'run_script']
const ZONES: string[] = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? []

const editing = ref<{ form: ScheduleForm; original: ScheduleRow | null } | null>(null)
const formError = ref('')
const historyOpen = reactive<Record<string, boolean | undefined>>({})

const counts = computed(() => ({
  total: schedules.list.length,
  paused: schedules.list.filter((s) => s.paused).length,
  failing: schedules.list.filter((s) => (s.consecutive_failures ?? 0) > 0).length
}))
const localTime = computed(() => (editing.value?.form.timing === 'once' ? analyzeLocalDateTime(editing.value.form.run_at) : null))
const formKey = computed(() => (editing.value?.original ? `schedule:${editing.value.original.id}` : 'schedule:new'))

function startNew(): void {
  editing.value = { form: { ...blankForm(), channel_id: state.activeId ?? '' }, original: null }
  formError.value = ''
}

/** Edit a schedule; for one that went inert, straight to choosing a new time. */
function startEdit(row: ScheduleRow): void {
  const form = formFor(row)
  if (row.inert_reason) Object.assign(form, { timing: 'once', run_at: '' })
  editing.value = { form, original: row }
  formError.value = ''
}

async function save(): Promise<void> {
  const current = editing.value
  if (!current) return
  const body = buildSave(current.form, current.original ?? undefined)
  if (typeof body === 'string') {
    formError.value = body
    return
  }
  formError.value = ''
  const sent = JSON.stringify(current.form)
  await saveSchedule(body, (row) => {
    if (editing.value !== current) return // another form is open now: it stays as it is
    // Unchanged since it was sent: done. Changed since: it stays open, now editing what was saved.
    if (JSON.stringify(current.form) === sent) editing.value = null
    else current.original = row
  })
}

let cronTimer: ReturnType<typeof setTimeout> | undefined
watch(
  () => [editing.value?.form.timing, editing.value?.form.cron] as const,
  ([timing, cron]) => {
    clearTimeout(cronTimer)
    if (timing === 'cron') cronTimer = setTimeout(() => void checkCron(cron ?? ''), 400)
  }
)

function conversationTitle(id: string): string | null {
  return state.conversations.find((c) => c.id === id)?.title ?? null
}

function when(row: ScheduleRow): string {
  if (row.cron) return `${row.cron}, ${row.timezone ? `${row.timezone} time` : "the core's time zone"}`
  return row.run_at ? `once, ${new Date(row.run_at).toLocaleString()}` : 'on a trigger'
}

function at(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : ''
}

function reportsTo(row: ScheduleRow): string {
  if (row.action === 'webhook') return `Calls ${String((row.webhook_config ?? {}).url ?? 'a URL')}`
  const title = conversationTitle(row.channel_id)
  return title ? `Reports in ${title}` : 'Reports in a conversation that is gone'
}

async function toggleHistory(row: ScheduleRow): Promise<void> {
  historyOpen[row.id] = !historyOpen[row.id]
  if (historyOpen[row.id]) await loadHistory(row.id)
}

async function remove(row: ScheduleRow): Promise<void> {
  const confirmed = await ask({
    title: 'Delete this schedule?',
    message: `"${row.description}" stops and is removed. Its history goes with it.`,
    confirmLabel: 'Delete',
    danger: true
  })
  if (confirmed) await deleteSchedule(row)
}
</script>

<template>
  <section class="panel" aria-label="Schedules">
    <header class="panel-head">
      <h3>Schedules</h3>
      <span class="panel-hint">{{ counts.total }} schedule{{ counts.total === 1 ? '' : 's' }}, {{ counts.paused }} paused, {{ counts.failing }} failing.</span>
      <button class="ghost" @click="startNew">New schedule</button>
    </header>
    <p v-if="management.error" class="warn">{{ management.error }}</p>
    <p v-else-if="schedules.loaded && !schedules.list.length" class="manage-desc">No schedules yet.</p>
    <ul class="manage-list">
      <li v-for="row in schedules.list" :key="row.id" class="manage-row">
        <div class="manage-line">
          <strong class="schedule-title">{{ row.description }}</strong>
          <span class="tag">{{ ACTIONS.find((a) => a.value === row.action)?.label ?? row.action }}</span>
          <span v-if="row.inert_reason" class="state-chip failed">Inert</span>
          <span v-else-if="row.paused" class="state-chip disabled">Paused</span>
          <span v-else class="state-chip connected">Active</span>
          <span v-if="(row.consecutive_failures ?? 0) > 0" class="state-chip failed">Failing ×{{ row.consecutive_failures }}</span>
          <span v-if="row.retry_at" class="state-chip">Retrying</span>
          <span class="manage-actions">
            <button v-if="!row.inert_reason" class="ghost" :disabled="management.busy[`schedule:${row.id}`]" @click="setPaused(row, !row.paused)">
              {{ row.paused ? 'Resume' : 'Pause' }}
            </button>
            <button class="ghost" :disabled="Boolean(row.inert_reason) || management.busy[`schedule:${row.id}`]" @click="runNow(row)">Run now</button>
            <button v-if="(row.consecutive_failures ?? 0) > 0" class="ghost" @click="resetFailures(row)">Reset failures</button>
            <button class="ghost" @click="startEdit(row)">Edit</button>
            <button class="ghost" @click="toggleHistory(row)">{{ historyOpen[row.id] ? 'Hide runs' : 'Runs' }}</button>
            <button class="ghost danger-item" @click="remove(row)">Delete…</button>
          </span>
        </div>
        <p class="manage-desc">
          {{ when(row) }}<template v-if="row.next_run">. Next: {{ at(row.next_run) }}</template
          ><template v-if="row.last_run">. Last ran {{ at(row.last_run) }}{{ row.last_error ? ', and failed' : '' }}</template>. {{ reportsTo(row) }}.
        </p>
        <div v-if="row.inert_reason" class="warn">
          {{ row.inert_reason }}
          <button class="ghost" @click="startEdit(row)">Set a new time</button>
        </div>
        <p v-if="row.last_error" class="warn">{{ row.last_error }}</p>
        <table v-if="historyOpen[row.id]" class="runs">
          <tbody>
            <tr v-for="(run, index) in schedules.history[row.id] ?? []" :key="index">
              <td>{{ at(run.timestamp) }}</td>
              <td :class="run.status === 'success' ? 'ok' : 'bad'">{{ run.status === 'success' ? 'Succeeded' : 'Failed' }}</td>
              <td>{{ (run.duration_ms / 1000).toFixed(1) }} s</td>
              <td>{{ run.error ?? '' }}</td>
            </tr>
            <tr v-if="!(schedules.history[row.id] ?? []).length"><td>No runs yet.</td></tr>
          </tbody>
        </table>
        <p v-if="management.notes[`schedule:${row.id}`]" class="manage-note" role="status">{{ management.notes[`schedule:${row.id}`] }}</p>
      </li>
    </ul>
  </section>

  <section v-if="editing" class="panel" aria-label="Schedule form">
    <template v-for="f in [editing.form]" :key="'form'">
      <header class="panel-head">
        <h3>{{ editing.original ? `Edit "${editing.original.description}"` : 'New schedule' }}</h3>
        <span v-if="editing.original" class="panel-hint">Only what you change is sent.</span>
        <button class="ghost" @click="editing = null">Close</button>
      </header>
      <label class="field-input">Description <input v-model="f.description" maxlength="500" /></label>
      <label v-if="!editing.original" class="field-input">
        It
        <select v-model="f.action">
          <option v-for="a in ACTIONS" :key="a.value" :value="a.value">{{ a.label }}: {{ a.hint }}</option>
        </select>
      </label>
      <label class="field-input">
        Reports in
        <select v-model="f.channel_id">
          <option v-if="f.action === 'webhook'" value="">No conversation</option>
          <option v-for="c in state.conversations" :key="c.id" :value="c.id">{{ c.title }}</option>
        </select>
      </label>
      <div class="field-input">
        <label class="toggle-inline"><input v-model="f.timing" type="radio" value="cron" /> On a schedule</label>
        <label class="toggle-inline"><input v-model="f.timing" type="radio" value="once" /> Once</label>
        <label v-if="editing.original?.trigger" class="toggle-inline">
          <input v-model="f.timing" type="radio" value="trigger" /> On its trigger, as it is
        </label>
      </div>
      <p v-if="f.timing === 'trigger'" class="manage-desc">It runs when its trigger fires. Choose a schedule or a time to replace that.</p>
      <template v-if="f.timing === 'cron'">
        <label class="field-input">Cron <input v-model="f.cron" placeholder="0 9 * * 1-5" spellcheck="false" /></label>
        <label class="field-input">Time zone <input v-model="f.cron_timezone" list="zones" placeholder="The core's time zone" /></label>
        <datalist id="zones"><option v-for="z in ZONES" :key="z" :value="z" /></datalist>
        <p v-if="schedules.cron?.error && schedules.cron.expression === f.cron" class="warn">{{ schedules.cron.error }}</p>
        <p v-else-if="schedules.cron?.next_runs.length && schedules.cron.expression === f.cron" class="manage-desc">
          Next: {{ schedules.cron.next_runs.slice(0, 3).map((r) => at(r)).join(', ') }}
        </p>
      </template>
      <template v-else-if="f.timing === 'once'">
        <label class="field-input">At, on this computer's clock <input v-model="f.run_at" type="datetime-local" step="1" /></label>
        <p v-if="localTime?.state === 'nonexistent'" class="warn">That time doesn't exist here: the clocks skip it.</p>
        <label v-else-if="localTime?.state === 'ambiguous'" class="field-input">
          That time happens twice here. Which one?
          <select :value="f.occurrence ?? ''" @change="f.occurrence = Number(($event.target as HTMLSelectElement).value)">
            <option value="" disabled>Choose</option>
            <option v-for="(o, i) in localTime.options" :key="o.iso" :value="i">{{ o.offset }}: {{ new Date(o.ms).toLocaleString() }}</option>
          </select>
        </label>
      </template>

      <label v-if="f.action === 'reminder'" class="field-input">Message <textarea v-model="f.message" rows="3" placeholder="The description, if left empty" /></label>
      <template v-if="f.action === 'check'">
        <label class="field-input">Tool <input v-model="f.tool_name" list="check-tools" placeholder="run_command" /></label>
        <datalist id="check-tools"><option v-for="t in CHECK_TOOLS" :key="t" :value="t" /></datalist>
        <label class="field-input">Its input, as JSON <textarea v-model="f.tool_input" rows="4" spellcheck="false" placeholder='{"host": "localhost", "command": "uptime"}' /></label>
        <label class="field-input">
          Report as
          <select v-model="f.report_format">
            <option v-for="r in REPORT_FORMATS" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
        </label>
      </template>
      <label v-if="f.action === 'workflow'" class="field-input">
        Steps, as JSON
        <textarea v-model="f.steps" rows="6" spellcheck="false" placeholder='[{"tool_name": "run_command", "tool_input": {"command": "uptime"}, "on_failure": "abort"}]' />
      </label>
      <template v-if="f.action === 'webhook'">
        <label class="field-input">URL <input v-model="f.webhook_url" type="url" placeholder="https://…" /></label>
        <label class="field-input">
          Method
          <select v-model="f.webhook_method"><option v-for="m in WEBHOOK_METHODS" :key="m" :value="m">{{ m }}</option></select>
        </label>
        <label class="field-input">Headers, as JSON <input v-model="f.webhook_headers" spellcheck="false" placeholder='{"Content-Type": "application/json"}' /></label>
        <label class="field-input">Body <textarea v-model="f.webhook_body" rows="3" spellcheck="false" /></label>
        <label class="field-input">Expected statuses <input v-model="f.webhook_expected" placeholder="200, 204" /></label>
      </template>
      <div class="field-input">
        <label class="limit">Retries <input v-model="f.max_retries" type="number" min="0" placeholder="0" /></label>
        <label class="limit">seconds between <input v-model="f.retry_backoff_seconds" type="number" min="0" placeholder="60" /></label>
      </div>
      <div class="panel-actions">
        <button class="ghost" :disabled="management.busy[formKey]" @click="save">{{ editing.original ? 'Save' : 'Create' }}</button>
      </div>
      <p v-if="formError" class="warn">{{ formError }}</p>
      <p v-else-if="management.notes[formKey]" class="manage-note" role="status">{{ management.notes[formKey] }}</p>
    </template>
  </section>

  <section class="panel" aria-label="Running work">
    <header class="panel-head">
      <h3>Running now</h3>
      <span class="panel-hint">Agents, tasks, loops, processes and workflows, with the controls Odin offers for each.</span>
    </header>
    <WorkList :kinds="RUNNING" empty-text="Nothing is running." />
  </section>
</template>
