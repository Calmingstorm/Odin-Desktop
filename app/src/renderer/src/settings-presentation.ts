// Presentation only: no values, validation, enums, write routes or implicit schema leftovers.
import type { ConfigField } from '../../shared/api'
export interface PresentedField { path: string; label: string; help: string; category: string }
export const GENERAL_TIMEZONE: PresentedField = { path: 'timezone', label: 'Time zone', help: 'Choose the time zone used for schedules and dates.', category: 'General' }
const category = (name: string, entries: readonly (readonly [string, string, string])[]): PresentedField[] => entries.map(([path, label, help]) => ({ path, label, help, category: name }))
/** Reviewed allowlist. Six nested model-profile facts share their one container editor. */
export const ADVANCED_FIELDS: readonly PresentedField[] = [
  ...category('Models and context', [
    ['openai_codex.context_budget_overrides', 'Codex context budgets', 'Correct usable context budgets for individual models.'],
    ['ollama.max_tokens', 'Local model response limit', 'Limit local-model response length.'],
    ['openai_compatible.max_tokens', 'Compatible provider response limit', 'Limit response length for this provider.'],
    ['openai_compatible.reasoning_dialect', 'Reasoning protocol', 'Choose the format understood by the provider.'],
    ['openai_compatible.glm_clear_thinking', 'Clear previous thinking', 'Control GLM thinking-message compatibility.'],
    ['openai_compatible.model_profiles', 'Custom model profiles', 'Set context limits and reasoning support for your custom models.'],
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
export type SettingsPlacement = 'primary' | 'more-options' | 'more'
export type SettingsField = PresentedField & { key: string }
// Explicit presentation allowlists. Managed records are deliberately absent: their existing dialogs
// own hosts, MCP servers, built-in tools, incoming webhooks and outgoing integrations.
const PAGE_FIELDS: Record<string, { primary: PresentedField[]; 'more-options': PresentedField[] }> = {
  general: { primary: [GENERAL_TIMEZONE], 'more-options': [] },
  models: {
    primary: category('Models and providers', [
      ['llm_provider.model', 'Main model', 'Choose the model used for chat.'],
      ['llm_provider.active_provider', 'Chat provider', 'The selected main model determines the provider.'],
      ['openai_codex.enabled', 'Codex', 'Enable this provider without losing saved accounts.'],
      ['openai_codex.reasoning_effort', 'Reasoning effort', 'Balance response speed and depth of reasoning.'],
      ['openai_codex.context_utilization', 'Context', 'Choose how much model context conversations can use.'],
      ['openai_codex.agent_reasoning_effort', 'Agent reasoning effort', 'Choose how deeply agents reason.'],
      ['agents.model', 'Agent model', 'Use the main model, automatic selection or a chosen model.'],
      ['agents.auto_model_allowlist', 'Automatic candidates', 'Choose the models automatic selection can use.'],
      ['agents.max_concurrent_agents', 'Concurrent agents', 'Limit agents working at the same time in one conversation.'],
      ['ollama.enabled', 'Ollama', 'Enable local models without losing their setup.'],
      ['ollama.base_url', 'Ollama address', 'Connect to the computer hosting your local models.'],
      ['ollama.model', 'Local model', 'Choose the local model to use.'],
      ['ollama.api_key', 'Ollama access key', 'Store or remove an access key without showing it.'],
      ['openai_compatible.enabled', 'Compatible provider', 'Enable this provider without losing its setup.'],
      ['openai_compatible.preset', 'Provider preset', 'Choose a provider or configure a custom endpoint.'],
      ['openai_compatible.base_url', 'Provider address', 'Connect to the endpoint serving your models.'],
      ['openai_compatible.model', 'Provider model', 'Choose a model offered by this provider.'],
      ['openai_compatible.api_key', 'Provider access key', 'Store or remove an access key without showing it.'],
      ['openai_compatible.reasoning_effort', 'Provider reasoning effort', 'Choose reasoning supported by this model.'],
      ['openai_compatible.context_utilization', 'Provider context', 'Reserve room for responses in the model context.']
    ]),
    'more-options': category('Models and providers', [
      ['openai_codex.auxiliary.enabled', 'Background model', 'Use a separate model for summaries and background work.'],
      ['openai_codex.auxiliary.model', 'Background model choice', 'Choose the model used for background work.'],
      ['ollama.num_ctx', 'Local context size', 'Fit local-model context to available memory.'],
      ['openai_compatible.reasoning_content_feedback_policy', 'Reasoning history', 'Choose whether previous reasoning is included in conversation history.'],
      ['openai_compatible.openrouter.order', 'Preferred providers', 'List upstream providers in preference order.'],
      ['openai_compatible.openrouter.allow_fallbacks', 'Provider fallbacks', 'Allow another upstream when a preferred provider is unavailable.'],
      ['openai_compatible.openrouter.quantizations', 'Allowed quantizations', 'Restrict the model formats an upstream can serve.'],
      ['openai_compatible.openrouter.sort', 'Routing priority', 'Prefer lower prices, higher throughput or lower latency.'],
      ['openai_compatible.openrouter.data_collection', 'Provider data collection', 'Choose whether routes that collect data may be used.'],
      ['openai_compatible.openrouter.reasoning_effort', 'Routing reasoning default', 'Choose reasoning for routed requests.'],
      ['openai_compatible.openrouter.model_pins', 'Model provider pins', 'Prefer a specific upstream endpoint for individual models.'],
      ['sessions.adaptive_compaction', 'Adaptive conversation summaries', 'Summarize long conversations to keep useful context.'],
      ['image.openai.enabled', 'Image generation', 'Make image-generation tools available.'],
      ['image.openai.outer_model', 'Image host model', 'Follow the default or pin a model for image requests.'],
      ['image.openai.image_model', 'Image model', 'Follow the default or pin the model creating images.'],
      ['agents.thinking_mode', 'Agent thinking policy', 'Choose or inherit thinking behavior for compatible models.'],
      ['agents.model_selection_hints', 'Automatic selection guidance', 'Describe which tasks suit individual models.']
    ])
  },
  personality: { primary: category('Personality', [
    ['personality.preset', 'Personality', 'Choose Odin’s voice and behavior.'],
    ['personality.custom_name', 'Custom name', 'Name your custom personality.'],
    ['personality.custom_identity', 'Identity instructions', 'Describe who Odin should be.'],
    ['personality.custom_voice', 'Voice instructions', 'Describe how Odin should respond.'],
    ['personality.user_presets', 'Saved personalities', 'Save custom personalities for reuse.']
  ]), 'more-options': [] },
  tools: { primary: category('Tools', [
    ['tools.enabled', 'Tool availability', 'Make tools available; permissions still apply.'],
    ['browser.enabled', 'Browser tools', 'Make browser tools available without granting website access.'],
    ['computer.enabled', 'Computer use', 'Make supported desktop controls available; each session still needs consent.'],
    ['email.enabled', 'Email tools', 'Make email tools available without discarding account setup.'],
    ['email.smtp.host', 'Outgoing mail server', 'Enter the server used to send mail.'],
    ['email.smtp.port', 'Outgoing mail port', 'Use the port supplied by your mail provider.'],
    ['email.smtp.username', 'Outgoing mail username', 'Enter the account used to send mail.'],
    ['email.smtp.password', 'Outgoing mail password', 'Store or remove the password without showing it.'],
    ['email.smtp.from_address', 'Sender address', 'Choose the address shown on outgoing messages.'],
    ['email.imap.host', 'Incoming mail server', 'Enter the server used to read mail.'],
    ['email.imap.port', 'Incoming mail port', 'Use the port supplied by your mail provider.'],
    ['email.imap.username', 'Incoming mail username', 'Enter the account used to read mail.'],
    ['email.imap.password', 'Incoming mail password', 'Store or remove the password without showing it.']
  ]), 'more-options': category('Tools', [
    ['tools.command_timeout_seconds', 'Command deadline', 'Limit how long a command can run.'],
    ['tools.tool_timeouts', 'Individual tool deadlines', 'Set a different deadline for individual tools.'],
    ['tools.streaming.enabled', 'Tool progress updates', 'Show progress while long-running tools work.'],
    ['tools.streaming.tools', 'Tools reporting progress', 'Choose which tools report progress.'],
    ['email.tls_verify', 'Verify mail certificates', 'Check mail-server certificates before connecting.'],
    ['email.allowed_attachment_dirs', 'Mail attachment folders', 'Choose folders email tools may read attachments from.'],
    ['browser.cdp_url', 'Existing browser address', 'Leave empty to launch Odin’s browser, or connect to an existing debugging endpoint.'],
    ['browser.allow_private_targets', 'Private browser destinations', 'Allow browser access to private-network destinations.']
  ]) },
  skills: { primary: [], 'more-options': category('Skills', [
    ['tools.skill_allowed_urls', 'Allowed skill endpoints', 'Restrict the network addresses skill code may access.']
  ]) },
  mcp: { primary: [], 'more-options': [] },
  hosts: { primary: [], 'more-options': category('Hosts and access', [
    ['tools.governor.block_critical', 'Block critical commands', 'Block commands classified as critical.'],
    ['tools.governor.block_exfil', 'Block data-exfiltration commands', 'Block commands that could send private data away.'],
    ['tools.governor.owner_can_override', 'Allow your overrides', 'Let you explicitly approve a blocked command.']
  ]) },
  work: { primary: [], 'more-options': category('Work', [
    ['learning.loop_reflection_enabled', 'Learn from loops', 'Let loops save lessons from completed work.'],
    ['turn_state.auto_resume', 'Resume preserved work', 'Resume eligible work automatically; uncertain work remains paused.']
  ]) },
  data: { primary: category('Data and privacy', [
    ['learning.enabled', 'Learned context', 'Let Odin save useful lessons from past work.'],
    ['search.enabled', 'Indexed search', 'Search stored knowledge without deleting it when disabled.']
  ]), 'more-options': category('Data and privacy', [
    ['sessions.archive_max_bytes', 'Conversation archive size', 'Cap the disk space used by archived conversations.'],
    ['sessions.archive_max_files', 'Archived conversation count', 'Cap the number of archived conversations retained.'],
    ['observability.trajectory_user_content', 'Request text in activity records', 'Include scrubbed request text in activity records.']
  ]) }
}
/** Presentation entries only, never schema discovery or write routing. */
export function settingsFields(page: string, placement: SettingsPlacement = 'primary'): SettingsField[] {
  return (PAGE_FIELDS[page]?.[placement === 'more' ? 'more-options' : placement] ?? []).map((entry) => ({ ...entry, key: entry.path }))
}
// Navigation labels for dedicated workflows, never generic editors.
const MANAGED_PRESENTATIONS = [
  ...category('MCP servers', [
    ['mcp.enabled', 'MCP availability', 'Make saved MCP servers available.'],
    ['mcp.max_published_tools_per_server', 'Tools per MCP server', 'Limit published tools from one server.'],
    ['mcp.max_published_tools_global', 'Total MCP tools', 'Limit all published MCP tools.'],
    ['mcp.servers', 'MCP servers', 'Configure saved MCP servers.']
  ]),
  ...category('Hosts and access', [
    ['tools.hosts', 'Managed hosts', 'Configure enrolled remote hosts.'],
    ['tools.default_host', 'Default host', 'Choose the default target for remote work.'],
    ['tools.allow_host_tofu', 'First-connection trust', 'Choose whether new host keys may be trusted on first connection.']
  ]),
  ...category('Tools', [['tools.disabled_tools', 'Built-in tools', 'Choose which built-in tools are available.']]),
  ...category('Work', [['webhook', 'Incoming events', 'Configure incoming schedule events.'], ['outbound_webhooks.targets', 'Outgoing integrations', 'Configure outgoing event destinations.']])
]
const ALL_PRESENTED_FIELDS = [GENERAL_TIMEZONE, ...ADVANCED_FIELDS, ...Object.values(PAGE_FIELDS).flatMap((page) => [...page.primary, ...page['more-options']]), ...MANAGED_PRESENTATIONS]
export const curatedPaths = new Set(ALL_PRESENTED_FIELDS.map((entry) => entry.path))
export function isCuratedPath(path: string): boolean { return [...curatedPaths].some((parent) => path === parent || path.startsWith(`${parent}.`)) }
export function presentationFor(path: string): PresentedField | undefined { return ALL_PRESENTED_FIELDS.find((entry) => path === entry.path || path.startsWith(`${entry.path}.`)) }
/** Read/navigation ownership only. Specialized dialogs retain their own mutation contracts. */
export function presentationDestination(path: string): string | undefined {
  if (ADVANCED_FIELDS.some((entry) => path === entry.path || path.startsWith(`${entry.path}.`))) return 'advanced'
  for (const [page, fields] of Object.entries(PAGE_FIELDS)) {
    if ([...fields.primary, ...fields['more-options']].some((entry) => entry.path === path || path.startsWith(`${entry.path}.`))) return page
  }
  if (path.startsWith('mcp.')) return 'mcp'
  if (path.startsWith('tools.hosts') || path === 'tools.default_host' || path === 'tools.allow_host_tofu') return 'hosts'
  if (path === 'tools.disabled_tools') return 'tools'
  if (path.startsWith('webhook.') || path.startsWith('outbound_webhooks.targets')) return 'work'
  return undefined
}
export function advancedMatches(entry: PresentedField, search: string): boolean {
  return search.trim().toLowerCase().split(/\s+/).every((word) => `${entry.label} ${entry.help} ${entry.category}`.toLowerCase().includes(word))
}
export function restartFields(fields: readonly ConfigField[]): ConfigField[] { return fields.filter((field) => field.pending_restart || field.apply_state === 'pending_restart') }
