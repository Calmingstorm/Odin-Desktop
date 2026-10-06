// The schedule form: what it shows for a schedule, and the body it sends. A new schedule sends every field it fills
// in, with the checks Odin's own form makes; a change sends only what changed, since Odin's update changes only the
// fields it is given, and new timing replaces the old (protocol.md, Schedules).
import type { ScheduleAction, ScheduleRow, ScheduleSave } from '../../shared/api'
import { analyzeLocalDateTime, localWallClock, SYSTEM_ZONE, type Zone } from './schedule-time'

export interface ScheduleForm {
  description: string
  action: ScheduleAction
  /** The conversation it reports to. */
  channel_id: string
  /** Inbound webhook matching is independent of the outgoing webhook action. */
  timing: 'cron' | 'once' | 'trigger'
  trigger_source: '' | 'generic' | 'github' | 'gitea' | 'gitlab'
  trigger_event: string
  trigger_repo: string
  cron: string
  /** Empty: the core's own time zone. */
  cron_timezone: string
  /** A datetime-local value: the wall clock on this computer. */
  run_at: string
  /** Which of two real instants, when the clocks go back and a time happens twice. */
  occurrence: number | null
  message: string
  tool_name: string
  /** JSON text */
  tool_input: string
  report_format: string
  /** JSON text */
  steps: string
  webhook_url: string
  webhook_method: string
  /** JSON text */
  webhook_headers: string
  webhook_body: string
  /** Comma-separated HTTP codes */
  webhook_expected: string
  max_retries: string
  retry_backoff_seconds: string
}

export const ACTIONS: Array<{ value: ScheduleAction; label: string; hint: string }> = [
  { value: 'reminder', label: 'Reminder', hint: 'Posts a message in its conversation.' },
  { value: 'check', label: 'Check', hint: 'Runs a command or script and reports what it found.' },
  { value: 'workflow', label: 'Workflow', hint: 'Runs tool steps in order.' },
  { value: 'webhook', label: 'Webhook', hint: 'Calls a URL.' }
]

export const REPORT_FORMATS = [
  { value: '', label: 'Plain text' },
  { value: 'paginated_embed_v1', label: 'Report with pages' }
]

export const WEBHOOK_METHODS = ['POST', 'PUT', 'PATCH', 'GET', 'DELETE']

export function blankForm(): ScheduleForm {
  return {
    description: '',
    action: 'reminder',
    channel_id: '',
    timing: 'cron',
    trigger_source: '',
    trigger_event: '',
    trigger_repo: '',
    cron: '',
    cron_timezone: '',
    run_at: '',
    occurrence: null,
    message: '',
    tool_name: '',
    tool_input: '',
    report_format: '',
    steps: '',
    webhook_url: '',
    webhook_method: 'POST',
    webhook_headers: '',
    webhook_body: '',
    webhook_expected: '',
    max_retries: '',
    retry_backoff_seconds: ''
  }
}

const json = (value: unknown): string => (value === undefined || value === null ? '' : JSON.stringify(value, null, 2))

/** The form for an existing schedule, its run time shown on this computer's clock. */
export function formFor(row: ScheduleRow, zone: Zone = SYSTEM_ZONE): ScheduleForm {
  const config = (row.webhook_config ?? {}) as Record<string, unknown>
  let runAt = ''
  if (row.run_at) {
    const ms = Date.parse(row.run_at)
    runAt = Number.isNaN(ms) ? '' : localWallClock(ms, new Date(ms).getUTCSeconds() !== 0, zone)
  }
  return {
    ...blankForm(),
    description: row.description,
    action: row.action,
    channel_id: row.channel_id ?? '',
    timing: row.cron ? 'cron' : row.trigger && !row.run_at ? 'trigger' : 'once',
    trigger_source: row.trigger?.source ?? '',
    trigger_event: row.trigger?.event ?? '',
    trigger_repo: row.trigger?.repo ?? '',
    cron: row.cron ?? '',
    cron_timezone: row.cron ? (row.timezone ?? '') : '',
    run_at: runAt,
    message: row.message ?? '',
    tool_name: row.tool_name ?? '',
    tool_input: row.tool_input && Object.keys(row.tool_input).length ? json(row.tool_input) : '',
    report_format: row.report_format ?? '',
    steps: json(row.steps),
    webhook_url: String(config.url ?? ''),
    webhook_method: String(config.method ?? 'POST'),
    webhook_headers: json(config.headers),
    webhook_body: config.body === undefined ? '' : String(config.body),
    webhook_expected: Array.isArray(config.expected_status_codes) ? config.expected_status_codes.join(', ') : '',
    max_retries: row.max_retries === undefined ? '' : String(row.max_retries),
    retry_backoff_seconds: row.retry_backoff_seconds === undefined ? '' : String(row.retry_backoff_seconds)
  }
}

type Fields = Record<string, unknown>

function parseObject(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text)
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
  } catch {
    return null
  }
}

function wholeNumber(text: string): number | null {
  const n = Number(text)
  return text.trim() !== '' && Number.isInteger(n) && n >= 0 ? n : null
}

/** Every field the form sets, checked as Odin's form checks them, or what is wrong. */
function fieldsOf(form: ScheduleForm, zone: Zone): Fields | string {
  const fields: Fields = {}
  if (!form.description.trim()) return 'Describe the schedule.'
  fields.description = form.description.trim()
  if (form.action !== 'webhook' && !form.channel_id) return 'Choose the conversation it reports to.'
  fields.channel_id = form.channel_id

  if (form.timing === 'cron') {
    if (!form.cron.trim()) return 'Enter a cron expression, or choose a one-time run.'
    fields.cron = form.cron.trim()
    if (form.cron_timezone.trim()) fields.cron_timezone = form.cron_timezone.trim()
  } else if (form.timing === 'once') {
    // The field is this computer's wall clock. Odin takes an explicit instant, so a time the clocks skip is refused
    // and a time that happens twice is an explicit choice.
    const time = analyzeLocalDateTime(form.run_at, zone)
    if (time.state === 'empty') return 'Choose when it runs.'
    if (time.state === 'invalid') return 'That run time is not a valid date.'
    if (time.state === 'nonexistent') return "That time doesn't exist here: the clocks skip it."
    if (time.state === 'ambiguous') {
      const chosen = form.occurrence === null ? undefined : time.options[form.occurrence]
      if (!chosen) return 'That time happens twice here: choose which one.'
      fields.run_at = chosen.iso
    } else {
      fields.run_at = time.iso
    }
  } else if (form.timing === 'trigger') {
    if (!form.trigger_source && !form.trigger_event && !form.trigger_repo) return 'Trigger must have at least one condition: source, event or repository.'
    // Keep unspecified matching unspecified. Null/absent are equivalent to the scheduler.
    fields.trigger = {
      ...(form.trigger_source ? { source: form.trigger_source } : {}),
      ...(form.trigger_event ? { event: form.trigger_event } : {}),
      ...(form.trigger_repo ? { repo: form.trigger_repo } : {})
    }
  }

  if (form.action === 'reminder' && form.message.trim()) fields.message = form.message.trim()
  if (form.action === 'check') {
    if (!form.tool_name.trim()) return 'Choose the tool the check runs.'
    fields.tool_name = form.tool_name.trim()
    if (form.tool_input.trim()) {
      const input = parseObject(form.tool_input)
      if (!input) return 'The tool input is a JSON object.'
      fields.tool_input = input
    }
    if (form.report_format) fields.report_format = form.report_format
  }
  if (form.action === 'workflow') {
    let steps: unknown
    try {
      steps = JSON.parse(form.steps)
    } catch {
      steps = null
    }
    const valid =
      Array.isArray(steps) &&
      steps.length > 0 &&
      steps.every((step) => {
        if (!step || typeof step !== 'object' || Array.isArray(step)) return false
        const s = step as Record<string, unknown>
        return (
          typeof s.tool_name === 'string' &&
          s.tool_name.trim() !== '' &&
          !!s.tool_input &&
          typeof s.tool_input === 'object' &&
          !Array.isArray(s.tool_input) &&
          (s.condition == null || typeof s.condition === 'string') &&
          (s.on_failure == null || s.on_failure === 'abort' || s.on_failure === 'continue')
        )
      })
    if (!valid) return 'Steps are a JSON list of {tool_name, tool_input}, each with an optional condition and on_failure (abort or continue).'
    fields.steps = steps
  }
  if (form.action === 'webhook') {
    if (!form.webhook_url.trim()) return 'Enter the URL it calls.'
    const config: Record<string, unknown> = { url: form.webhook_url.trim(), method: form.webhook_method }
    if (form.webhook_headers.trim()) {
      const headers = parseObject(form.webhook_headers)
      if (!headers) return 'Headers are a JSON object.'
      config.headers = headers
    }
    if (form.webhook_body) config.body = form.webhook_body
    if (form.webhook_expected.trim()) {
      const codes = form.webhook_expected.split(',').map((v) => Number(v.trim()))
      if (codes.some((code) => !Number.isInteger(code) || code < 100 || code > 599)) return 'Expected statuses are HTTP codes, separated by commas.'
      config.expected_status_codes = codes
    }
    fields.webhook_config = config
  }
  if (form.max_retries.trim()) {
    const n = wholeNumber(form.max_retries)
    if (n === null) return 'Retries are a whole number, 0 or more.'
    fields.max_retries = n
  }
  if (form.retry_backoff_seconds.trim()) {
    const n = wholeNumber(form.retry_backoff_seconds)
    if (n === null || n < 1) return 'The wait between retries is a whole number of seconds, at least 1.'
    fields.retry_backoff_seconds = n
  }
  return fields
}

const TIMING = ['cron', 'cron_timezone', 'run_at', 'trigger']

/** What clears a field Odin keeps when it is emptied: no message, no tool input, a plain text report. */
const CLEARED: Fields = { message: '', tool_input: {}, report_format: '' }
/** Odin keeps these once set: an update can change them but not unset them. */
const KEPT: Record<string, string> = {
  max_retries: 'Odin keeps the number of retries once set: enter 0 for none.',
  retry_backoff_seconds: 'Odin keeps the wait between retries once set: enter at least 1 second. Set Retries to 0 to disable retries.'
}

/**
 * The body to send, or what is wrong with the form. With `original`, only what changed goes: Odin's update leaves
 * out what it isn't given, and new timing replaces the old.
 */
export function buildSave(form: ScheduleForm, original?: ScheduleRow, zone: Zone = SYSTEM_ZONE): ScheduleSave | string {
  const after = fieldsOf(form, zone)
  if (typeof after === 'string') return after
  if (!original) return { action: form.action, ...after } as ScheduleSave
  const beforeFields = fieldsOf(formFor(original, zone), zone)
  const before: Fields = typeof beforeFields === 'string' ? {} : beforeFields
  const same = (key: string): boolean => JSON.stringify(after[key]) === JSON.stringify(before[key])
  const change: Fields = { id: original.id }
  if (TIMING.some((key) => !same(key))) {
    for (const key of TIMING) if (after[key] !== undefined) change[key] = after[key]
  }
  for (const key of Object.keys(after)) {
    if (!TIMING.includes(key) && !same(key)) change[key] = after[key]
  }
  // A field emptied in the form is sent as its clear value, since an update leaves out what it isn't given.
  for (const key of Object.keys(before)) {
    if (TIMING.includes(key) || key in after) continue
    if (key in KEPT) return KEPT[key]!
    if (key in CLEARED) change[key] = CLEARED[key]
  }
  if (Object.keys(change).length === 1) return 'Nothing changed.'
  return change as ScheduleSave
}
