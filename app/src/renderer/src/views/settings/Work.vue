<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import type { ScheduleRow, WorkKind } from '../../../../shared/api'
import WorkList from '../../components/WorkList.vue'
import WebhookIngress from '../../components/WebhookIngress.vue'
import OutboundWebhooks from '../../components/OutboundWebhooks.vue'
import { ask } from '../../dialog'
import { ACTIONS, blankForm, buildSave, formFor, REPORT_FORMATS, WEBHOOK_METHODS, type ScheduleForm } from '../../schedule-form'
import { analyzeLocalDateTime } from '../../schedule-time'
import { scheduleRecovery, scheduleRunLabel } from '../../schedule-observations'
import { state } from '../../store'
import { management } from '../../stores/management'
import { settings } from '../../stores/settings'
import { settingsUnavailableText as unavailableText } from '../../capability'
import { checkCron, deleteSchedule, loadHistory, loadSchedules, resetFailures, runNow, saveSchedule, schedules, setPaused } from '../../stores/schedules'
import { loadWork } from '../../stores/work'
import { settingsFields } from '../../settings-presentation'
import SettingEditor from '../../components/settings/SettingEditor.vue'
import SettingsSection from '../../components/settings/SettingsSection.vue'

onMounted(loadSchedules)

/** Running work is listed here too; schedules have their own section above it. */
const RUNNING: WorkKind[] = ['agent', 'task', 'loop', 'process', 'workflow']
/** The tools Odin's scheduler runs as checks; the core says so if that changes. */
const CHECK_TOOLS = ['run_command', 'run_command_multi', 'run_script']
const ZONES: string[] = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? []

const editing = ref<{ form: ScheduleForm; original: ScheduleRow | null } | null>(null)
const scheduleDialog = ref<HTMLDialogElement | null>(null)
watch(() => !!editing.value, async (open) => {
  await nextTick()
  if (open) scheduleDialog.value?.showModal?.()
})
const formError = ref('')
// Validation messages come from buildSave; only mark the field it identifies.
const errorField = computed(() => {
  const fields: Array<[string, string]> = [
    ['Describe', 'description'], ['Choose the conversation', 'channel_id'], ['Enter a cron', 'cron'],
    ['Choose when', 'run_at'], ['That run time', 'run_at'], ["That time doesn't", 'run_at'],
    ['That time happens', 'occurrence'], ['Choose the tool', 'tool_name'], ['The tool input', 'tool_input'],
    ['Steps are', 'steps'], ['Enter the URL', 'webhook_url'], ['Headers are', 'webhook_headers'],
    ['Expected statuses', 'webhook_expected'], ['Retries are', 'max_retries'], ['The wait between', 'retry_backoff_seconds'],
    ['Trigger must', 'trigger_source']
  ]
  return fields.find(([prefix]) => formError.value.startsWith(prefix))?.[1]
})
function fieldError(field: string): Record<string, string | undefined> {
  return { 'aria-invalid': errorField.value === field ? 'true' : undefined, 'aria-describedby': errorField.value === field ? 'schedule-form-error' : undefined }
}
const historyOpen = reactive<Record<string, boolean | undefined>>({})

const counts = computed(() => ({
  total: schedules.list.length,
  paused: schedules.list.filter((s) => s.paused).length,
  failing: schedules.list.filter((s) => (s.consecutive_failures ?? 0) > 0).length
}))
const localTime = computed(() => (editing.value?.form.timing === 'once' ? analyzeLocalDateTime(editing.value.form.run_at) : null))
const more = computed(() => settingsFields('work', 'more-options').flatMap((entry) => {
  const field = settings.meta?.fields.find((field) => field.path === entry.key)
  return field ? [{ ...entry, field }] : []
}))
const formKey = computed(() => (editing.value?.original ? `schedule:${editing.value.original.id}` : 'schedule:new'))

/** Odin's own time zone (Settings → General), which a new schedule starts in. */
const odinZone = computed(() => {
  const zone = settings.meta?.fields.find((field) => field.path === 'timezone')?.desired
  return typeof zone === 'string' ? zone : ''
})

function startNew(): void {
  // A cron without a zone runs on UTC; a new one starts in Odin's zone, as Odin's own schedules do.
  editing.value = { form: { ...blankForm(), channel_id: state.activeId ?? '', cron_timezone: odinZone.value }, original: null }
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
  const sent = { ...current.form }
  await saveSchedule(body, (row) => {
    if (editing.value !== current) return // another form is open now: it stays as it is
    // Unchanged since it was sent: done. Changed since: it stays open, now editing what was saved.
    if (JSON.stringify(current.form) === JSON.stringify(sent)) editing.value = null
    else {
      const saved = formFor(row)
      for (const key of Object.keys(saved) as Array<keyof ScheduleForm>) {
        if (current.form[key] === sent[key]) Object.assign(current.form, { [key]: saved[key] })
      }
      current.original = row
    }
  })
}

let cronTimer: ReturnType<typeof setTimeout> | undefined
watch(
  () => [editing.value?.form.timing, editing.value?.form.cron, editing.value?.form.cron_timezone] as const,
  ([timing, cron, zone]) => {
    clearTimeout(cronTimer)
    if (timing === 'cron') cronTimer = setTimeout(() => void checkCron(cron ?? '', zone ?? ''), 400)
  }
)
/** The preview belongs to the form only while both its cron and its zone are the form's. */
const cronPreview = computed(() => {
  const form = editing.value?.form
  const preview = schedules.cron
  return form && preview && preview.expression === form.cron && preview.timezone === form.cron_timezone.trim() ? preview : null
})
/** Which field the preview's refusal is about: the zone, or the cron itself. */
const previewErrorField = computed(() => (!cronPreview.value?.error ? '' : cronPreview.value.error.startsWith('Unknown time zone') ? 'cron_timezone' : 'cron'))

function conversationTitle(id: string): string | null {
  return state.conversations.find((c) => c.id === id)?.title ?? null
}

function when(row: ScheduleRow): string {
  if (row.cron) return `${row.cron}, ${row.timezone ? `${row.timezone} time` : 'UTC'}`
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
  <SettingsSection title="Schedules" aria-label="Schedules">
    <header class="panel-head">
      <span v-if="!schedules.unavailable" class="panel-hint">{{ counts.total }} schedule{{ counts.total === 1 ? '' : 's' }}, {{ counts.paused }} paused, {{ counts.failing }} failing.</span>
      <button class="ghost" aria-label="Refresh schedules" @click="loadSchedules">Refresh</button>
      <button v-if="!schedules.unavailable" class="ghost" @click="startNew">New schedule</button>
    </header>
    <p v-if="schedules.unavailable" class="capability-unavailable" role="status">{{ unavailableText('Scheduling') }}</p>
    <p v-else-if="management.error" class="warn">{{ management.error }}</p>
    <p v-else-if="schedules.loaded && !schedules.list.length" class="manage-desc">No schedules yet. Create one for reminders or recurring work.</p>
    <ul class="manage-list">
      <li v-for="row in schedules.list" :key="row.id" class="manage-row">
        <div class="manage-line">
          <strong class="schedule-title">{{ row.description }}</strong>
          <span class="tag">{{ ACTIONS.find((a) => a.value === row.action)?.label ?? row.action }}</span>
          <span v-if="row.inert_reason" class="state-chip failed">Inert</span>
          <span v-else-if="row.recovery_required" class="state-chip failed">Recovery required</span>
          <span v-else-if="row.paused" class="state-chip disabled">Paused</span>
          <span v-else class="state-chip connected">Active</span>
          <span v-if="(row.consecutive_failures ?? 0) > 0" class="state-chip failed">Failing ×{{ row.consecutive_failures }}</span>
          <span v-if="row.retry_at" class="state-chip">Retrying</span>
          <span class="manage-actions">
            <button v-if="!row.inert_reason" class="ghost" :aria-label="`${row.paused ? 'Resume' : 'Pause'} schedule ${row.description}`" :disabled="management.busy[`schedule:${row.id}`]" @click="setPaused(row, !row.paused)">
              {{ row.paused ? 'Resume' : 'Pause' }}
            </button>
            <button class="ghost" :aria-label="`Run now schedule ${row.description}`" :disabled="Boolean(row.inert_reason) || management.busy[`schedule:${row.id}`]" @click="runNow(row)">Run now</button>
            <button v-if="(row.consecutive_failures ?? 0) > 0" class="ghost" :aria-label="`Reset failures for schedule ${row.description}`" @click="resetFailures(row)">Reset failures</button>
            <button class="ghost" :aria-label="`Edit schedule ${row.description}`" @click="startEdit(row)">Edit</button>
            <button class="ghost" :aria-label="`${historyOpen[row.id] ? 'Hide runs' : 'Runs'} for schedule ${row.description}`" :aria-expanded="Boolean(historyOpen[row.id])" :aria-controls="`schedule-runs-${row.id}`" @click="toggleHistory(row)">{{ historyOpen[row.id] ? 'Hide runs' : 'Runs' }}</button>
            <button class="ghost danger-item" :aria-label="`Delete schedule ${row.description}…`" @click="remove(row)">Delete…</button>
          </span>
        </div>
        <p class="manage-desc">
          {{ when(row) }}<template v-if="row.next_run">. Next: {{ at(row.next_run) }}</template
          ><template v-if="row.last_run">. Last ran {{ at(row.last_run) }}{{ row.last_error ? ', and failed' : '' }}</template>. {{ reportsTo(row) }}.
        </p>
        <div v-if="row.inert_reason" class="warn">
          {{ row.inert_reason }}
          <button class="ghost" :aria-label="`Set a new time for schedule ${row.description}`" @click="startEdit(row)">Set a new time</button>
        </div>
        <div v-if="scheduleRecovery(row).length" class="schedule-recovery" role="status">
          <p v-for="line in scheduleRecovery(row)" :key="line" class="manage-desc">{{ line }}</p>
        </div>
        <p v-if="row.last_error" class="warn">{{ row.last_error }}</p>
        <table v-if="historyOpen[row.id]" :id="`schedule-runs-${row.id}`" :aria-label="`Runs for schedule ${row.description}`" class="runs">
          <tbody>
            <tr v-for="(run, index) in schedules.history[row.id] ?? []" :key="index">
              <td>{{ at(run.timestamp) }}</td>
              <td :class="run.status === 'success' ? 'ok' : run.status === 'failure' ? 'bad' : ''">{{ scheduleRunLabel(run) }}</td>
              <td>{{ (run.duration_ms / 1000).toFixed(1) }} s</td>
              <td>{{ run.error ?? '' }}</td>
            </tr>
            <tr v-if="!(schedules.history[row.id] ?? []).length"><td>No runs yet.</td></tr>
          </tbody>
        </table>
        <p v-if="management.notes[`schedule:${row.id}`]" class="manage-note" role="status">{{ management.notes[`schedule:${row.id}`] }}</p>
      </li>
    </ul>
  </SettingsSection>

  <dialog v-if="editing && !schedules.unavailable" ref="scheduleDialog" class="schedule-editor-dialog" :aria-label="editing.original ? `Edit schedule ${editing.original.description}` : 'New schedule'" @cancel.prevent="editing = null">
  <SettingsSection :title="editing.original ? `Edit ${editing.original.description}` : 'New schedule'" aria-label="Schedule form" :aria-describedby="formError ? 'schedule-form-error' : undefined">
    <template v-for="f in [editing.form]" :key="'form'">
      <header class="panel-head">
        <button class="ghost" @click="editing = null">Cancel</button>
      </header>
      <label class="field-input">Description <input v-model="f.description" v-bind="fieldError('description')" maxlength="500" /></label>
      <label v-if="!editing.original" class="field-input">
        It
        <select v-model="f.action" :disabled="management.busy[formKey]">
          <option v-for="a in ACTIONS" :key="a.value" :value="a.value">{{ a.label }}: {{ a.hint }}</option>
        </select>
      </label>
      <label class="field-input">
        Reports in
        <select v-model="f.channel_id" v-bind="fieldError('channel_id')">
          <option v-if="f.action === 'webhook'" value="">No conversation</option>
          <option v-for="c in state.conversations" :key="c.id" :value="c.id">{{ c.title }}</option>
        </select>
      </label>
      <div class="field-input">
        <label class="toggle-inline"><input v-model="f.timing" type="radio" value="cron" /> On a schedule</label>
        <label class="toggle-inline"><input v-model="f.timing" type="radio" value="once" /> Once</label>
        <label class="toggle-inline">
          <input v-model="f.timing" type="radio" value="trigger" data-testid="schedule-timing-trigger" /> On a webhook trigger
        </label>
      </div>
      <template v-if="f.timing === 'trigger'">
        <p class="manage-desc">All filters must match. After saving, set up its incoming source and secret below; outgoing webhooks are separate.</p>
        <label class="field-input">Trigger source
          <select v-model="f.trigger_source" v-bind="fieldError('trigger_source')" data-testid="schedule-trigger-source">
            <option value="">Unspecified (any matching source)</option>
            <option value="generic">Generic</option><option value="github">GitHub</option><option value="gitea">Gitea</option>
            <option value="gitlab">GitLab (scheduler supported; ingress unavailable)</option>
          </select>
        </label>
        <label class="field-input">Trigger event <input v-model="f.trigger_event" data-testid="schedule-trigger-event" placeholder="Any event when empty" /></label>
        <label class="field-input">Repository filter <input v-model="f.trigger_repo" data-testid="schedule-trigger-repo" placeholder="Case-insensitive substring; any when empty" /></label>
      </template>
      <template v-if="f.timing === 'cron'">
        <label class="field-input">Cron <input v-model="f.cron" :aria-invalid="errorField === 'cron' || previewErrorField === 'cron' ? 'true' : undefined" :aria-describedby="errorField === 'cron' ? 'schedule-form-error' : previewErrorField === 'cron' ? 'schedule-cron-error' : undefined" placeholder="0 9 * * 1-5" spellcheck="false" /></label>
        <label class="field-input">Time zone <input v-model="f.cron_timezone" list="zones" placeholder="UTC" :aria-invalid="previewErrorField === 'cron_timezone' ? 'true' : undefined" :aria-describedby="previewErrorField === 'cron_timezone' ? 'schedule-cron-error' : undefined" /></label>
        <datalist id="zones"><option v-for="z in ZONES" :key="z" :value="z" /></datalist>
        <p v-if="cronPreview?.error" id="schedule-cron-error" class="warn" role="status">{{ cronPreview.error }}</p>
        <p v-else-if="cronPreview?.next_runs.length" class="manage-desc">
          Next: {{ cronPreview.next_runs.slice(0, 3).map((r) => at(r)).join(', ') }}
        </p>
      </template>
      <template v-else-if="f.timing === 'once'">
        <label class="field-input">At, on this computer's clock <input v-model="f.run_at" :aria-invalid="errorField === 'run_at' || localTime?.state === 'nonexistent' ? 'true' : undefined" :aria-describedby="errorField === 'run_at' ? 'schedule-form-error' : localTime?.state === 'nonexistent' ? 'schedule-time-error' : undefined" type="datetime-local" step="1" /></label>
        <p v-if="localTime?.state === 'nonexistent'" id="schedule-time-error" class="warn" role="status">That time doesn't exist here: the clocks skip it.</p>
        <label v-else-if="localTime?.state === 'ambiguous'" class="field-input">
          That time happens twice here. Which one?
          <select :value="f.occurrence ?? ''" v-bind="fieldError('occurrence')" @change="f.occurrence = Number(($event.target as HTMLSelectElement).value)">
            <option value="" disabled>Choose</option>
            <option v-for="(o, i) in localTime.options" :key="o.iso" :value="i">{{ o.offset }}: {{ new Date(o.ms).toLocaleString() }}</option>
          </select>
        </label>
      </template>

      <label v-if="f.action === 'reminder'" class="field-input">Message <textarea v-model="f.message" rows="3" placeholder="The description, if left empty" /></label>
      <template v-if="f.action === 'check'">
        <label class="field-input">Tool <input v-model="f.tool_name" v-bind="fieldError('tool_name')" list="check-tools" placeholder="run_command" /></label>
        <datalist id="check-tools"><option v-for="t in CHECK_TOOLS" :key="t" :value="t" /></datalist>
        <label class="field-input">Its input, as JSON <textarea v-model="f.tool_input" v-bind="fieldError('tool_input')" rows="4" spellcheck="false" placeholder='{"host": "localhost", "command": "uptime"}' /></label>
        <label class="field-input">
          Report as
          <select v-model="f.report_format">
            <option v-for="r in REPORT_FORMATS" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
        </label>
      </template>
      <label v-if="f.action === 'workflow'" class="field-input">
        Steps, as JSON
        <textarea v-model="f.steps" v-bind="fieldError('steps')" rows="6" spellcheck="false" placeholder='[{"tool_name": "run_command", "tool_input": {"command": "uptime"}, "on_failure": "abort"}]' />
      </label>
      <template v-if="f.action === 'webhook'">
        <label class="field-input">URL <input v-model="f.webhook_url" v-bind="fieldError('webhook_url')" type="url" placeholder="https://…" /></label>
        <label class="field-input">
          Method
          <select v-model="f.webhook_method"><option v-for="m in WEBHOOK_METHODS" :key="m" :value="m">{{ m }}</option></select>
        </label>
        <label class="field-input">Headers, as JSON <input v-model="f.webhook_headers" v-bind="fieldError('webhook_headers')" spellcheck="false" placeholder='{"Content-Type": "application/json"}' /></label>
        <label class="field-input">Body <textarea v-model="f.webhook_body" rows="3" spellcheck="false" /></label>
        <label class="field-input">Expected statuses <input v-model="f.webhook_expected" v-bind="fieldError('webhook_expected')" placeholder="200, 204" /></label>
      </template>
      <div class="field-input">
        <label class="limit">Retries <input :value="f.max_retries" v-bind="fieldError('max_retries')" @input="f.max_retries = ($event.target as HTMLInputElement).value" type="number" min="0" placeholder="0" /></label>
        <label class="limit">seconds between <input :value="f.retry_backoff_seconds" v-bind="fieldError('retry_backoff_seconds')" @input="f.retry_backoff_seconds = ($event.target as HTMLInputElement).value" type="number" min="1" placeholder="60" /></label>
      </div>
      <div class="panel-actions">
        <button class="ghost" :disabled="management.busy[formKey]" @click="save">{{ editing.original ? 'Save' : 'Create' }}</button>
      </div>
      <p v-if="formError" id="schedule-form-error" class="warn" role="alert">{{ formError }}</p>
      <p v-else-if="management.notes[formKey]" class="manage-note" role="status">{{ management.notes[formKey] }}</p>
    </template>
  </SettingsSection>

  </dialog>
  <WebhookIngress v-if="!schedules.unavailable && !settings.unavailable" />
  <SettingsSection v-else title="Incoming webhooks" aria-label="Webhook ingress"><p class="capability-unavailable" role="status">Incoming webhook setup is unavailable.</p></SettingsSection>

  <OutboundWebhooks />

  <SettingsSection title="Running now" aria-label="Running work">
    <header class="panel-head">
      <button class="ghost" aria-label="Refresh running work" @click="loadWork">Refresh</button>
    </header>
    <WorkList :kinds="RUNNING" empty-text="Nothing is running." :unavailable-message="unavailableText('Work (agents, tasks, loops, processes, workflows and schedules)')" />
  </SettingsSection>

  <details v-if="more.length" class="settings-more-options">
    <summary>More options</summary>
    <SettingsSection title="Learning and recovery">
      <SettingEditor v-for="entry in more" :key="entry.key" :field="entry.field" :label="entry.label" :help="entry.help" />
    </SettingsSection>
  </details>
</template>

<style scoped>
.schedule-editor-dialog { width: min(760px, calc(100vw - 48px)); max-height: calc(100vh - 48px); overflow: auto; padding: 0 20px; border: 1px solid var(--border); border-radius: 12px; color: var(--text); background: var(--bg); }
.schedule-editor-dialog::backdrop { background: rgb(0 0 0 / 55%); }
</style>
