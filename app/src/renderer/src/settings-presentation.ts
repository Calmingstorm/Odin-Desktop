// Presentation only: no values, validation, enums, write routes or implicit schema leftovers.
import type { ConfigField } from '../../shared/api'
export interface PresentedField { path: string; label: string; help: string; category: string }
export const GENERAL_TIMEZONE: PresentedField = { path: 'timezone', label: 'Time zone', help: 'Use an IANA time zone, such as America/New_York, for schedules and dates.', category: 'General' }
const category = (name: string, entries: readonly (readonly [string, string, string])[]): PresentedField[] => entries.map(([path, label, help]) => ({ path, label, help, category: name }))
/** Reviewed allowlist. Six nested model-profile facts share their one container editor. */
export const ADVANCED_FIELDS: readonly PresentedField[] = [
  ...category('Models and context', [
    ['openai_codex.context_budget_overrides', 'Codex context budgets', 'Correct usable context budgets for individual models.'],
    ['ollama.max_tokens', 'Local model response limit', 'Limit local-model response length.'],
    ['openai_compatible.max_tokens', 'Compatible provider response limit', 'Limit response length for this provider.'],
    ['openai_compatible.reasoning_dialect', 'Reasoning protocol', 'Choose the format understood by the provider.'],
    ['openai_compatible.glm_clear_thinking', 'Clear previous thinking', 'Control GLM thinking-message compatibility.'],
    ['openai_compatible.model_profiles', 'Custom model profiles', 'Correct context and reasoning capabilities in one profile transaction.'],
    ['sessions.max_history', 'Conversation history limit', 'Limit the messages retained in context.'],
    ['sessions.max_age_hours', 'Conversation context age', 'Limit the age of messages included in context.'],
    ['sessions.token_budget', 'Conversation token budget', 'Limit tokens used for history.'],
    ['sessions.context_token_budget', 'Context token budget', 'Set the conversation context budget.'],
    ['sessions.context_budget_overrides', 'Conversation model budgets', 'Correct context budgets for specific models.']
  ]),
  ...category('Tool execution', [
    ['tools.tool_output_max_chars', 'Tool output limit', 'Limit output included in a response.'],
    ['tools.command_shell', 'Command shell', 'Choose the shell used for local commands.'],
    ['tools.bulkhead.ssh_max_concurrent', 'Concurrent SSH commands', 'Limit simultaneous remote commands.'],
    ['tools.bulkhead.subprocess_max_concurrent', 'Concurrent local commands', 'Limit simultaneous local commands.'],
    ['tools.bulkhead.browser_max_concurrent', 'Concurrent browser tasks', 'Limit simultaneous browser work.'],
    ['tools.bulkhead.ssh_max_queued', 'Queued SSH commands', 'Limit waiting remote commands.'],
    ['tools.bulkhead.subprocess_max_queued', 'Queued local commands', 'Limit waiting local commands.'],
    ['tools.bulkhead.browser_max_queued', 'Queued browser tasks', 'Limit waiting browser work.'],
    ['tools.max_tool_iterations_chat', 'Chat tool iterations', 'Bound tool steps in a chat turn.'],
    ['tools.max_tool_iterations_loop', 'Loop tool iterations', 'Bound tool steps in a loop turn.'],
    ['email.max_body_chars', 'Email body limit', 'Limit the email text read at once.'],
    ['email.max_results', 'Email result limit', 'Limit messages returned by a search.'],
    ['email.max_attachment_bytes', 'Email attachment size', 'Limit email attachment bytes.'],
    ['browser.max_wait_timeout_seconds', 'Browser wait limit', 'Limit how long browser actions wait.'],
    ['browser.viewport_width', 'Browser viewport width', 'Set the isolated browser viewport width.'],
    ['browser.viewport_height', 'Browser viewport height', 'Set the isolated browser viewport height.'],
    ['image.openai.max_image_bytes', 'Generated image size limit', 'Bound bytes accepted for generated images.']
  ]),
  ...category('Hosts and access', [
    ['tools.governor.host_overrides', 'Per-host command safety', 'Override command safety policy for specific hosts.']
  ]),
  ...category('Work and recovery', [
    ['agents.max_nesting_depth', 'Agent nesting depth', 'Limit how deeply agents create children.'],
    ['agents.max_children_per_agent', 'Children per agent', 'Limit children created by one agent.'],
    ['agents.max_iterations', 'Agent iteration limit', 'Bound ordinary agent iterations.'],
    ['agents.scheduled_max_iterations', 'Scheduled agent iterations', 'Bound iterations for scheduled agents.'],
    ['agents.hard_max_iterations', 'Hard agent iteration ceiling', 'Set the absolute iteration ceiling.'],
    ['agents.max_lifetime_seconds', 'Agent lifetime limit', 'Bound how long an agent can run.'],
    ['learning.loop_reflection_cooldown_hours', 'Reflection cooldown', 'Control the interval between loop reflections.'],
    ['learning.loop_reflection_max_per_hour', 'Reflections per hour', 'Limit loop reflections in an hour.'],
    ['turn_state.resume_ttl_hours', 'Preserved work resume window', 'Limit how long work can be resumed.']
  ]),
  ...category('Data and retention', [
    ['turn_state.payload_retention_days', 'Preserved payload retention', 'Control retained work payload history.'],
    ['turn_state.ledger_retention_days', 'Work ledger retention', 'Control retained work ledger history.'],
    ['logging.level', 'Log detail', 'Choose the level of diagnostic logging.'],
    ['learning.max_entries', 'Learned context entries', 'Limit learned context entries.'],
    ['learning.consolidation_target', 'Learning consolidation target', 'Set the target size after consolidation.'],
    ['learning.injection_token_budget', 'Learned context token budget', 'Limit learned context added to a turn.'],
    ['attachments.inline_text_max_bytes', 'Inline attachment size', 'Limit attachment text included inline.'],
    ['attachments.preview_max_chars', 'Attachment preview length', 'Limit ordinary attachment previews.'],
    ['attachments.large_preview_chars', 'Large attachment preview length', 'Limit previews of large attachments.'],
    ['attachments.archive_max_bytes', 'Archive size limit', 'Bound accepted archive bytes.'],
    ['attachments.archive_max_files', 'Archive file count', 'Bound the number of archived files.'],
    ['attachments.archive_extract_max_bytes', 'Archive extraction size', 'Bound total extracted bytes.'],
    ['attachments.archive_preview_total_chars', 'Archive preview budget', 'Limit total archive preview text.'],
    ['attachments.image_max_bytes', 'Image attachment size', 'Bound image attachment bytes.'],
    ['attachments.pdf_max_bytes', 'PDF attachment size', 'Bound PDF attachment bytes.'],
    ['attachments.archive_preview_file_max_bytes', 'Archive file preview size', 'Bound preview bytes for one archived file.'],
    ['attachments.retention_hours', 'Attachment retention', 'Choose how long attachments are retained.']
  ])
]
export const ADVANCED_CATEGORIES = ['Models and context', 'Tool execution', 'Hosts and access', 'Work and recovery', 'Data and retention'] as const
export const curatedPaths = new Set([GENERAL_TIMEZONE.path, ...ADVANCED_FIELDS.map((entry) => entry.path)])
export function isCuratedPath(path: string): boolean { return [...curatedPaths].some((parent) => path === parent || path.startsWith(`${parent}.`)) }
export function presentationFor(path: string): PresentedField | undefined { return path === 'timezone' ? GENERAL_TIMEZONE : ADVANCED_FIELDS.find((entry) => path === entry.path || path.startsWith(`${entry.path}.`)) }
export function advancedMatches(entry: PresentedField, search: string): boolean {
  return search.trim().toLowerCase().split(/\s+/).every((word) => `${entry.label} ${entry.help} ${entry.category}`.toLowerCase().includes(word))
}
export function restartFields(fields: readonly ConfigField[]): ConfigField[] { return fields.filter((field) => field.pending_restart || field.apply_state === 'pending_restart') }
