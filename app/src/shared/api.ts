// Types shared by the main process, the preload bridge and the renderer.
// They mirror docs/design/protocol.md (v0, minor 3).

export type CorePhase = 'starting' | 'ready' | 'degraded' | 'quiescing'

/** Core-authoritative provisioning. Saving a field or signing in is not readiness. */
export interface FirstRunStatus {
  state: 'fresh' | 'incomplete' | 'saved' | 'effective-ready' | 'degraded'
  reason: 'provider_not_configured' | 'provider_configuration_incomplete' | 'provider_runtime_unavailable' | 'provider_identity_not_adopted' | 'provider_effective' | 'provider_health_degraded' | 'provider_health_unknown' | 'keyring_unavailable' | 'credential_state_unavailable'
  keyring_unavailable: boolean
}

export interface CoreStatus {
  phase: CorePhase
  core_instance_id: string
  version: string
  capabilities: string[]
  first_run?: FirstRunStatus
  model?: { main: string; effort: string; provider: string }
  providers?: Array<{ name: string; health: string }>
  limits?: { chunk_bytes: number; attachment_bytes: number; attachments_per_turn: number }
  /** The text Odin's /status shows. */
  summary?: string
}

/** A value the core measured, estimated, or doesn't know. Never an invented number. */
export interface Measured {
  value: number | null
  kind: 'measured' | 'estimated' | 'unknown'
}

export interface UsageResult {
  period: string
  tokens: Measured
  /** Tokens in Odin's context now, against the budget the core derives for the model. */
  context: { used: Measured; budget: Measured }
  quota: Array<{ account: string; window: string; used_percent: Measured; resets_at: string | null }>
  /** The text Odin's /usage shows. */
  summary: string
}

export type WorkKind = 'agent' | 'task' | 'loop' | 'process' | 'schedule' | 'workflow'
export type WorkAction = 'stop' | 'cancel' | 'restart' | 'pause' | 'resume' | 'run_now'

/** Background work Odin is running or keeps: an agent, task, loop, process, schedule or workflow. */
export interface WorkItem {
  kind: WorkKind
  id: string
  title: string
  state: string
  conversation_id?: string
  request_id?: string
  started_at?: string
  detail: string
  /** The controls Odin offers for this item now. */
  actions: WorkAction[]
}

/** One tool call's scrubbed arguments, labeled previews and a cursor to its retained output. */
export interface ToolDetail {
  tool: string
  target?: string
  arguments: unknown
  previews: Array<{ label: string; text: string; truncated: boolean }>
  output: { cursor?: string; expires_at?: string }
}

export interface ToolOutputPage {
  text: string
  /** Retained binary output, never decoded as text: read each by `ref` with artifacts.read. */
  attachments: Array<{ ref: string; kind: string; mime: string; size: number; sha256: string }>
  next_cursor?: string
  eof: boolean
  expires_at: string
}

/** A file, image or stored report Odin produced, by core reference. */
export interface ArtifactRef {
  ref: string
  name: string
  mime: string
  size: number
  kind: 'image' | 'file' | 'report'
  available: boolean
}

export interface ReportPage {
  page: number
  pages: number
  text: string
}

/** An attachment the core holds, by reference. */
export interface AttachmentRef {
  ref: string
  name: string
  mime: string
  size: number
}

/** A file the user chose, held by the main process until it is uploaded. */
export interface StagedAttachment {
  id: string
  name: string
  mime: string
  size: number
}

export interface AttachmentProgress {
  id: string
  sent: number
  size: number
}

export interface StagedBatch {
  staged: StagedAttachment[]
  errors: string[]
}

export interface Conversation {
  id: string
  title: string
  rev: number
  parent_id: string | null
  /** Set on a child conversation: where its inherited context came from. */
  inherited_from?: { conversation_id: string; message_id: string | null; title: string } | null
  updated_at: string
  unread: number
  archived: boolean
}

export interface SearchHit {
  conversation_id: string
  message_id: string
  role: MessageRole
  snippet: string
  created_at: string
}

export interface SearchResult {
  hits: SearchHit[]
  next_cursor?: string | null
  watermark: string
}

export interface AroundResult {
  items: Message[]
  has_before: boolean
  has_after: boolean
}

export interface ConversationActivity {
  running: RequestRef | null
  queued: RequestRef[]
}

/** A `conversations.list` item: the record plus what is running or queued in it. */
export interface ConversationListItem extends Conversation {
  activity?: ConversationActivity
}

export type MessageRole = 'user' | 'assistant' | 'notice'

export interface Message {
  id: string
  role: MessageRole
  text: string
  created_at: string
  request_id?: string
  /** Present on user messages: the submission they were admitted under. */
  client_submission_id?: string
  /** Present on user messages that carried attachments. */
  attachments?: AttachmentRef[]
  /** Files, images and reports Odin produced with this message. */
  artifacts?: ArtifactRef[]
}

export interface RequestRef {
  request_id: string
  generation: number
}

export interface RunningRequest extends RequestRef {
  started_at: string
}

export interface QueuedRequest extends RequestRef {
  message_id: string
}

export type TerminalKind = 'completed' | 'failed' | 'cancelled' | 'interrupted' | 'suspended'

export interface TerminalOutcome extends RequestRef {
  outcome: TerminalKind
  unknown_effects: number
  at: string
}

export interface ToolEntry {
  invocation_id: string
  tool: string
  target?: string
  summary: string
  outcome?: 'success' | 'failure' | 'unknown'
  exit_code?: number
  duration_ms?: number
}

export interface ControlRecord {
  control_command_id: string
  kind: 'stop' | 'steer'
  request_id: string
  generation: number
  disposition: string
  sequence?: number
}

/** A conversation's authoritative state, complete through `watermark` (protocol.md, Snapshots). */
export interface ConversationSnapshot {
  watermark: string
  conversation: Conversation
  messages: { items: Message[]; has_more: boolean }
  running: RunningRequest | null
  queued: QueuedRequest[]
  recent: TerminalOutcome[]
  /** Outcomes whose unknown effects aren't reconciled yet. Never trimmed by later outcomes. */
  unresolved: TerminalOutcome[]
  tools: Record<string, ToolEntry[]>
  controls: ControlRecord[]
}

export interface CoreEvent {
  seq: number
  cursor: string
  type: string
  entity: { kind: string; id: string; rev?: number }
  at: string
  payload: Record<string, unknown>
}

export interface CoreError {
  code: string
  message: string
  disposition?: string
  /** On an unanswered command: its ID, so the window can match the late receipt and never send it again. */
  command_id?: string
}

/** Every call through the bridge settles to one of these; nothing throws across it. */
export type Result<T> = { ok: true; result: T } | { ok: false; error: CoreError }

/** Connection state as the app's main process sees it. */
export type LinkState = 'starting' | 'connecting' | 'ready' | 'reconnecting' | 'core-restarting' | 'core-failed'

/** Retained cleanup uncertainty. Acknowledgment archives the notice, not resource quarantine or effects. */
export interface CleanupWarning {
  id: string
  at: string
  records: Array<{
    at: string
    reason: string
    processOutcome?: string
    shutdownAccepted?: boolean
    unsaved?: boolean
    unreceipted?: number
  }>
}

export interface AppState {
  link: LinkState
  coreInstanceId: string | null
  /** True when the window was opened on a desktop where no tray could be found. */
  noTray: boolean
  /** Commands that were sent but whose receipt is still pending reconciliation. */
  unreceipted: number
  cleanupWarning?: CleanupWarning | null
}

export type ApplyMode = 'live_read' | 'live_apply' | 'live_for_new_work' | 'restart' | 'activation_required' | 'dormant'
export type ApplyState = 'applied' | 'pending_restart' | 'dormant' | 'invalid' | 'drift' | 'unknown'

/** One setting, as Odin's apply registry describes it (GET /api/config/meta; protocol.md, Settings and secrets). */
export interface ConfigField {
  path: string
  label: string
  description: string
  /** `string`, `integer`, `number`, `boolean`, `array` or `object`; an enum is a `string` with `enum`. */
  type: string
  enum: string[] | null
  /** `minimum`, `maximum`, `exclusive_minimum`, `exclusive_maximum`, `min_length`, `max_length`. */
  constraints: Record<string, number>
  default: unknown
  nullable: boolean
  sensitivity: 'public' | 'sensitive' | 'secret_container'
  apply_mode: ApplyMode
  /** Where Odin applies the field: a dedicated desktop method (for example `models.main.set`), or null. */
  apply_handler: string | null
  restart_reason: string | null
  activation_policy: string | null
  consumers: Array<{ name: string; apply_mode: ApplyMode; detail: string }>
  /** Odin's two plain sentences: what saving does, and what the running core does now. */
  save_effect: string
  runtime_effect: string | null
  /** Saved and effective values; redacted for a sensitive field. */
  desired: unknown
  effective: unknown
  configured: boolean | null
  pending_restart: boolean
  apply_state: ApplyState
}

export type ImageLeaf = 'image_model' | 'outer_model'

/** Odin's image-model intent: `follow` moves with the shipped default, `pin` keeps the saved value. */
export interface ImageModelIntent {
  effective: string
  default: string
  status: 'follow' | 'pin'
}

export interface ConfigMeta {
  schema_version: number
  revision: string
  fields: ConfigField[]
  status: { counts: Record<string, number>; desired_revision: string; effective_revision: string | null; keyring_error?: string | null }
  image_models?: Record<ImageLeaf, ImageModelIntent>
  image_models_revision?: string
}

export type SettingsChange = { path: string; value: unknown } | { path: string; delete: true }

export interface SettingsSetResult {
  revision: string
  fields: ConfigField[]
}

// ---- Management domains (protocol.md): each in the shape of the Odin route it maps to ---------------------------------

export interface BuiltinTool {
  name: string
  description: string
  is_core: boolean
  enabled: boolean
  /** What the model experiences: the switch, the global switch, or a backend that hides the tool. */
  state: 'available' | 'disabled' | 'global_disabled' | 'unavailable'
  input_schema: Record<string, unknown>
}

export interface ToolInventory {
  global_enabled: boolean
  disabled_count: number
  tools: BuiltinTool[]
}

export interface ToolTimeouts {
  default_timeout: number
  overrides: Record<string, number>
}

export interface SkillSummary {
  name: string
  description: string
  loaded_at: string
  status: 'loaded' | 'disabled' | 'error'
  version: string
  author?: string
  tags?: string[]
  dependencies?: string[]
  has_config?: boolean
  diagnostics?: Array<{ level: string; message: string }>
  total_executions?: number
  execution_count?: number
  code?: string | null
}

export interface SkillDetail extends SkillSummary {
  input_schema: Record<string, unknown>
  file_path: string
  metadata: { version: string; author?: string; homepage?: string; tags?: string[]; dependencies?: string[]; has_config: boolean; config_schema: Record<string, unknown> }
  config: Record<string, unknown>
  handoff_to_codex: boolean
}

export interface SkillValidation {
  valid: boolean
  errors: string[]
  warnings: string[]
  metadata: unknown
  definition_keys: string[]
}

export interface McpServer {
  name: string
  transport: 'stdio' | 'http'
  enabled: boolean
  state: string
  discovered_count: number
  published_count: number
  excluded_count: number
  published_tools: string[]
  last_error: string
  blocked_reason: string
  last_refresh_age_seconds: number | null
  stderr_tail: string
  /** Names only: header and environment values are never read back. */
  header_keys: string[]
  env_keys: string[]
  url_display: string | null
  instructions?: string
  credential_migration?: string
}

export interface McpStatus {
  /** Real core settings binding. Legacy fixture status has no revision. */
  revision?: string
  enabled: boolean
  max_published_tools_per_server: number
  max_published_tools_global: number
  server_count: number
  enabled_server_count: number
  connected_count: number
  published_tool_count: number
  servers: McpServer[]
}

export interface McpTool {
  original_name: string
  published_name: string
  published: boolean
  excluded: boolean
  exclusion_reason: string
  description: string
}

export interface McpMutation {
  saved: boolean
  connected: boolean
  state: string
  last_error: string
}

export interface McpSave {
  name: string
  create?: boolean
  expected_revision?: string
  transport?: 'stdio' | 'http'
  command?: string
  args?: string[]
  url?: string
  cwd?: string
  timeout_seconds?: number
  enabled?: boolean
  tool_allowlist?: string[] | null
  headers_set?: Record<string, string>
  headers_remove?: string[]
  env_set?: Record<string, string>
  env_remove?: string[]
}

export interface HostTest {
  ok?: boolean
  at?: string
  checked_at?: number
  detail?: string
  [key: string]: unknown
}

/** One managed host, as Odin's GET /api/hosts lists it. */
export interface HostRow {
  alias: string
  host_id: string
  address: string
  ssh_user: string
  os: string
  port: number
  description: string
  enabled: boolean
  active: boolean
  targetable: boolean
  trust_mode: string
  trust_state: string
  last_test: HostTest | null
  diagnostic: string | null
  draining: boolean
  generation: number
}

export interface HostList {
  hosts: HostRow[]
  /** Empty: Odin needs every command to name its host. */
  default_host: string
  /** Saved choice can be inactive while the effective default is empty. */
  configured_default_host?: string
  generation: number
  tofu_enabled: boolean
}

/** The body of Odin's POST /api/hosts/candidates. */
export interface HostPrepare {
  alias: string
  address: string
  ssh_user: string
  port?: number
  os?: 'linux' | 'macos'
  description?: string
  enabled?: boolean
  trust_mode: 'pinned' | 'ca' | 'tofu'
  expected_fingerprints?: string[]
  candidate_fingerprints?: string[]
  confirm_tofu?: boolean
  confirm_local?: boolean
}

export interface HostCandidate {
  candidate_token: string
  alias: string
  host_id: string
  fingerprints: string[]
  trust_mode: string
  tested: boolean
}

export interface HostTestResult {
  candidate_token: string
  tested: boolean
  last_test: HostTest | null
  error?: string
}

export interface HostSaved {
  saved: boolean
  active: boolean
  targetable: boolean
  trust_state: string
  last_test: HostTest | null
  draining: boolean
  pending_references: HostReference[]
  registry_generation: number
  ssh_paths: {
    desired_key: string
    effective_key: string
    desired_known_hosts: string
    effective_known_hosts: string
    restart_pending: boolean
  }
  host?: HostRow
}

export interface HostReference {
  kind: string
  location: string
}

export interface HostRevoked extends HostSaved {
  leases_interrupted: number
  processes: { attempted: number; killed: number; unknown: number }
}

export interface PublicKeyInfo {
  public_key: string
  fingerprint: string
  authorized_keys_command: string
  permissions: string
  effective_key_path: string
  desired_key_path: string
  restart_pending: boolean
}

export type ScheduleAction = 'reminder' | 'check' | 'workflow' | 'webhook'

/** One schedule, in the shape of Odin's GET /api/schedules. */
export interface ScheduleRow {
  id: string
  description: string
  action: ScheduleAction
  /** The conversation it reports to; empty for a webhook. */
  channel_id: string
  created_at: string
  cron?: string | null
  run_at?: string | null
  one_time?: boolean
  /** The zone a cron expression runs in, when it has one of its own. */
  timezone?: string | null
  next_run?: string | null
  last_run?: string | null
  paused?: boolean
  message?: string | null
  tool_name?: string | null
  tool_input?: Record<string, unknown> | null
  report_format?: string | null
  steps?: unknown[] | null
  webhook_config?: Record<string, unknown> | null
  trigger?: Record<string, unknown> | null
  max_retries?: number
  retry_backoff_seconds?: number
  consecutive_failures?: number
  retry_count?: number
  retry_at?: string | null
  last_error?: string | null
  last_error_at?: string | null
  /** Why the schedule can no longer fire, such as a one-time run whose time passed while paused. */
  inert_reason?: string | null
}

/** Fields both creating and changing a schedule take. Changing sends only what changed. */
interface ScheduleFields {
  description?: string
  channel_id?: string
  cron?: string
  run_at?: string
  cron_timezone?: string
  message?: string
  tool_name?: string
  tool_input?: Record<string, unknown>
  report_format?: string
  steps?: unknown[]
  webhook_config?: Record<string, unknown>
  max_retries?: number
  retry_backoff_seconds?: number
}

/** A new schedule (POST /api/schedules), or a change to one (PUT /api/schedules/{id}). The action is set once. */
export type ScheduleSave = (ScheduleFields & { action?: ScheduleAction }) | (ScheduleFields & { id: string; paused?: boolean })

/** One run, as Odin's schedule history records it. */
export interface ScheduleRun {
  timestamp: string
  schedule_id: string
  description: string
  action: ScheduleAction
  status: 'success' | 'failure'
  duration_ms: number
  error?: string
  retry_attempt?: number
}

export interface PersonalityPreset {
  name: string
  identity: string
  voice: string
}

/** Odin's GET /api/personality. */
export interface Personality {
  preset: string
  custom_name: string
  custom_identity: string
  custom_voice: string
  presets: Record<string, PersonalityPreset>
  builtin_presets: string[]
  user_presets: string[]
}

export interface PersonalitySet {
  preset: string
  custom_name?: string
  custom_identity?: string
  custom_voice?: string
}

/** Memory scopes and their keys (GET /api/memory). */
export type MemoryIndex = Record<string, { keys: string[]; count: number }>

export interface NamedList {
  name: string
  count: number
  updated_at: string
}

export interface KnowledgeSource {
  source: string
  chunks: number
  uploader: string
  ingested_at: string
  content_hash: string
  preview?: string
}

export interface KnowledgeHit {
  chunk_id: string
  content: string
  source: string
  score: number
  chunk_index: number
}

export interface KnowledgeIngest {
  source: string
  chunks?: number
  status?: string
  outcome?: 'created' | 'unchanged' | 'duplicate' | 'conflict'
  duplicate_of?: string
  message?: string
}

export interface KnowledgeVersion {
  id: number
  version: number
  content_hash: string
  chunk_count: number
  uploader: string
  action: string
  created_at: string
  diff_summary: string
}

export interface AuditEntry {
  timestamp: string
  tool_name: string
  tool_input?: Record<string, unknown>
  approved?: boolean
  result_summary?: string
  execution_time_ms?: number
  error?: string | null
  host?: string
  type?: string
  detail?: string
}

export interface AuditVerify {
  valid: boolean
  availability?: 'available' | 'not_enabled'
  total?: number
  verified?: number
  unsigned_prefix?: number
  error?: string | null
  segments?: Array<Record<string, unknown>>
  first_bad?: number | null
  reason?: string
  [key: string]: unknown
}

export interface HealthComponent {
  name: string
  healthy: boolean
  status: string
  detail: string
}

export interface HealthReport {
  browser?: BrowserStatus
  overall: string
  components: HealthComponent[]
  healthy_count: number
  degraded_count: number
  down_count: number
  unconfigured_count: number
  unavailable_count?: number
  total: number
  checked_at: string
}

export interface LogEntry extends AuditEntry {
  /** Older fixture rows only. Real core log rows are scrubbed audit entries. */
  level?: string
  message?: string
  tool?: string
}

export interface TurnRecord {
  source: string
  channel_id: string
  message_id: string
  turn_generation: number
  status: string
  created_at: number
  last_progress_at: number | null
  suspended_at: number | null
  has_checkpoint: boolean
  manual_resolution_operations: number
  outcome_unknown_operations: number
  requires_attention: boolean
}

/** Odin's turn-state envelope (GET /api/turn-state/turns). */
export interface TurnStateReport {
  schema_version: number
  availability: 'available' | 'not_enabled' | 'unavailable'
  observed_at: string
  data: { total_matching?: number; attention_count?: number; turns?: TurnRecord[] }
}

/** Where a computer-use session's recovery stands, as Odin records it. `complete` is never implied by success. */
export interface ComputerRecovery {
  status: string
  reason: string
  complete: boolean
  released?: boolean
  receiver_release_verified?: boolean
  unknown_release?: boolean
}

/**
 * Odin's computer-use status (GET /api/computer): one lifecycle at a time. Reconciling binds `session_generation`,
 * the session's own generation, not the runtime's `generation`.
 */
export interface BrowserStatus {
  state: string
  ready: boolean
  reason: string | null
  retry_available?: boolean
}

export interface LegacyComputerStatus {
  available: boolean
  state: string
  session_id: string
  generation?: number
  session_generation?: number
  enabled?: boolean
  configured_enabled?: boolean
  runtime_enabled?: boolean
  last_action?: string
  last_verification?: string
  error?: string
  recovery?: ComputerRecovery
}

/** Retained real-core lifecycle data; never a grant of foreground input. */
export interface ComputerSession {
  session_id: string
  generation: number
  state: string
  recovery?: ComputerRecovery | null
  cleanup?: { released?: boolean; unknown_release?: boolean; receiver_release_verified?: boolean; [key: string]: unknown } | null
  input_supported?: boolean
  input_readiness?: string
  last_action?: string
  last_verification?: string
  error?: string
  [key: string]: unknown
}

export interface DesktopComputerStatus {
  session: ComputerSession | null
  readiness: {
    management_available: boolean
    foreground_available: false
    native_qualified: false
    input_supported: false
    dispatch: 'none'
    reason: string
  }
}

export type ComputerStatus = LegacyComputerStatus | DesktopComputerStatus
export type McpRevision = { expected_revision?: string }
export type McpMutationOutcome = McpStatus | McpMutation

export interface ScheduleRunResult {
  status: 'success' | 'failure' | 'skipped'
  schedule_id: string
  error?: string
  warning?: string
}

type Empty = Record<string, never>

/** Each management bridge method: its params and its answer. */
export interface ManagementCalls {
  toolsList: [Empty, ToolInventory]
  toolsSetEnabled: [{ name: string; enabled: boolean }, ToolInventory]
  toolsTimeoutsGet: [Empty, ToolTimeouts]
  toolsTimeoutsSet: [{ default_timeout?: number; overrides?: Record<string, number> }, ToolTimeouts]
  skillsList: [Empty, SkillSummary[]]
  skillsGet: [{ name: string }, SkillDetail]
  skillsSave: [{ name: string; code: string; create: boolean }, { result: string }]
  skillsValidate: [{ code: string }, SkillValidation]
  skillsTest: [{ name: string }, { result: string; is_error: boolean }]
  skillsSetEnabled: [{ name: string; enabled: boolean }, { result: string }]
  skillsDelete: [{ name: string }, { result: string }]
  skillsConfigGet: [{ name: string }, { config: Record<string, unknown>; schema: Record<string, unknown> }]
  skillsConfigSet: [{ name: string; config: Record<string, unknown> }, { config: Record<string, unknown> }]
  mcpStatus: [Empty, McpStatus]
  mcpSave: [McpSave, McpMutationOutcome]
  mcpSetEnabled: [{ name: string; enabled: boolean } & McpRevision, McpStatus]
  mcpDelete: [{ name: string } & McpRevision, McpMutationOutcome]
  mcpReconnect: [{ name: string } & McpRevision, McpMutationOutcome]
  mcpRefreshTools: [{ name: string } & McpRevision, McpMutationOutcome]
  mcpTools: [{ name: string }, { server?: string; name?: string; tools: McpTool[] }]
  mcpSetGlobalEnabled: [{ enabled: boolean } & McpRevision, McpStatus | { saved: boolean; enabled: boolean; connected_count: number }]
  mcpSetLimits: [{ max_published_tools_per_server?: number; max_published_tools_global?: number } & McpRevision, McpStatus & { saved?: boolean }]
  hostsList: [Empty, HostList]
  hostsSettings: [{ default_host?: string; allow_host_tofu?: boolean }, { saved: boolean; default_host: string; configured_default_host: string; tofu_enabled: boolean; registry_generation: number }]
  hostsPublicKey: [Empty, PublicKeyInfo]
  hostsPrepare: [HostPrepare, HostCandidate]
  hostsTest: [{ token: string }, HostTestResult]
  hostsCommit: [{ token: string }, HostSaved]
  hostsSetEnabled: [{ alias: string; enabled: boolean }, HostSaved]
  hostsReferences: [{ alias: string }, { alias: string; references: HostReference[] }]
  hostsDelete: [{ alias: string }, HostSaved]
  hostsForceRevoke: [{ alias: string }, HostRevoked]
  schedulesList: [Empty, ScheduleRow[]]
  schedulesSave: [ScheduleSave, ScheduleRow]
  schedulesDelete: [{ id: string }, { status: string }]
  schedulesRun: [{ id: string }, ScheduleRunResult]
  schedulesResetFailures: [{ id: string }, ScheduleRow]
  schedulesHistory: [{ id?: string; limit?: number }, ScheduleRun[]]
  schedulesValidateCron: [{ expression: string }, { valid: boolean; next_runs: string[] }]
  personalityGet: [Empty, Personality]
  personalitySet: [PersonalitySet, { status: string; preset: string }]
  personalityPresetsSave: [{ name: string; display_name?: string; identity?: string; voice?: string }, { status: string; name: string }]
  personalityPresetsDelete: [{ name: string }, { status: string; name: string }]
  memoryList: [Empty, MemoryIndex]
  memoryGet: [{ scope: string; key?: string }, { scope: string; entries?: Record<string, unknown>; key?: string; value?: unknown }]
  memorySet: [{ scope: string; key: string; value: unknown }, { status: string; scope: string; key: string }]
  memoryDelete: [{ scope: string; key: string }, { status: string; scope: string; key: string }]
  memoryBulkDelete: [{ entries: Array<{ scope: string; key: string }> }, { status: string; count: number }]
  listsList: [Empty, { items: NamedList[] }]
  listsGet: [{ name: string }, { name: string; items: unknown[] }]
  listsDelete: [{ name: string }, { status: string; name: string }]
  knowledgeList: [Empty, KnowledgeSource[]]
  knowledgeSearch: [{ q: string; limit?: number }, KnowledgeHit[]]
  knowledgeIngest: [{ source: string; content: string }, KnowledgeIngest]
  knowledgeReingest: [{ source: string }, KnowledgeIngest]
  knowledgeDelete: [{ source: string }, { status: string; chunks_removed: number }]
  knowledgeVersions: [{ source: string }, KnowledgeVersion[]]
  knowledgeRestore: [{ source: string; version: number }, { status: string; source: string; version: number; chunks: number }]
  auditQuery: [{ tool?: string; user?: string; host?: string; q?: string; date?: string; error_only?: boolean; limit?: number }, AuditEntry[]]
  auditVerify: [Empty, AuditVerify]
  healthGet: [Empty, HealthReport]
  logsSearch: [{ q?: string; level?: 'error' | 'info' | 'all'; tool?: string; start?: string; end?: string; limit?: number }, { entries: LogEntry[]; count: number }]
  turnStateList: [{ limit?: number }, TurnStateReport]
  computerStatus: [Empty, ComputerStatus]
  computerReconcile: [{ session_id: string; generation: number; acknowledgment?: string }, ComputerStatus]
}

export type ManagementMethod = keyof ManagementCalls
export type ManagementApi = {
  [K in ManagementMethod]: (params: ManagementCalls[K][0]) => Promise<Result<ManagementCalls[K][1]>>
}

/**
 * Each management bridge method's own IPC channel and the one core method it maps to. `command` methods change
 * something and travel with a command ID. The main process validates each one with its own schema
 * (schemas.ts, MANAGEMENT_SCHEMAS): there is no generic passthrough.
 */
export const MANAGEMENT: { [K in ManagementMethod]: { channel: string; core: string; command: boolean } } = {
  toolsList: { channel: 'odin:manage:tools.list', core: 'tools.list', command: false },
  toolsSetEnabled: { channel: 'odin:manage:tools.set_enabled', core: 'tools.set_enabled', command: true },
  toolsTimeoutsGet: { channel: 'odin:manage:tools.timeouts.get', core: 'tools.timeouts.get', command: false },
  toolsTimeoutsSet: { channel: 'odin:manage:tools.timeouts.set', core: 'tools.timeouts.set', command: true },
  skillsList: { channel: 'odin:manage:skills.list', core: 'skills.list', command: false },
  skillsGet: { channel: 'odin:manage:skills.get', core: 'skills.get', command: false },
  skillsSave: { channel: 'odin:manage:skills.save', core: 'skills.save', command: true },
  skillsValidate: { channel: 'odin:manage:skills.validate', core: 'skills.validate', command: false },
  skillsTest: { channel: 'odin:manage:skills.test', core: 'skills.test', command: true },
  skillsSetEnabled: { channel: 'odin:manage:skills.set_enabled', core: 'skills.set_enabled', command: true },
  skillsDelete: { channel: 'odin:manage:skills.delete', core: 'skills.delete', command: true },
  skillsConfigGet: { channel: 'odin:manage:skills.config.get', core: 'skills.config.get', command: false },
  skillsConfigSet: { channel: 'odin:manage:skills.config.set', core: 'skills.config.set', command: true },
  mcpStatus: { channel: 'odin:manage:mcp.status', core: 'mcp.status', command: false },
  mcpSave: { channel: 'odin:manage:mcp.save', core: 'mcp.save', command: true },
  mcpSetEnabled: { channel: 'odin:manage:mcp.set_enabled', core: 'mcp.set_enabled', command: true },
  mcpDelete: { channel: 'odin:manage:mcp.delete', core: 'mcp.delete', command: true },
  mcpReconnect: { channel: 'odin:manage:mcp.reconnect', core: 'mcp.reconnect', command: true },
  mcpRefreshTools: { channel: 'odin:manage:mcp.refresh_tools', core: 'mcp.refresh_tools', command: true },
  mcpTools: { channel: 'odin:manage:mcp.tools', core: 'mcp.tools', command: false },
  mcpSetGlobalEnabled: { channel: 'odin:manage:mcp.set_global_enabled', core: 'mcp.set_global_enabled', command: true },
  mcpSetLimits: { channel: 'odin:manage:mcp.set_limits', core: 'mcp.set_limits', command: true },
  hostsList: { channel: 'odin:manage:hosts.list', core: 'hosts.list', command: false },
  hostsSettings: { channel: 'odin:manage:hosts.settings', core: 'hosts.settings', command: true },
  hostsPublicKey: { channel: 'odin:manage:hosts.public_key', core: 'hosts.public_key', command: false },
  hostsPrepare: { channel: 'odin:manage:hosts.prepare', core: 'hosts.prepare', command: true },
  hostsTest: { channel: 'odin:manage:hosts.test', core: 'hosts.test', command: true },
  hostsCommit: { channel: 'odin:manage:hosts.commit', core: 'hosts.commit', command: true },
  hostsSetEnabled: { channel: 'odin:manage:hosts.set_enabled', core: 'hosts.set_enabled', command: true },
  hostsReferences: { channel: 'odin:manage:hosts.references', core: 'hosts.references', command: false },
  hostsDelete: { channel: 'odin:manage:hosts.delete', core: 'hosts.delete', command: true },
  hostsForceRevoke: { channel: 'odin:manage:hosts.force_revoke', core: 'hosts.force_revoke', command: true },
  schedulesList: { channel: 'odin:manage:schedules.list', core: 'schedules.list', command: false },
  schedulesSave: { channel: 'odin:manage:schedules.save', core: 'schedules.save', command: true },
  schedulesDelete: { channel: 'odin:manage:schedules.delete', core: 'schedules.delete', command: true },
  schedulesRun: { channel: 'odin:manage:schedules.run', core: 'schedules.run', command: true },
  schedulesResetFailures: { channel: 'odin:manage:schedules.reset_failures', core: 'schedules.reset_failures', command: true },
  schedulesHistory: { channel: 'odin:manage:schedules.history', core: 'schedules.history', command: false },
  schedulesValidateCron: { channel: 'odin:manage:schedules.validate_cron', core: 'schedules.validate_cron', command: false },
  personalityGet: { channel: 'odin:manage:personality.get', core: 'personality.get', command: false },
  personalitySet: { channel: 'odin:manage:personality.set', core: 'personality.set', command: true },
  personalityPresetsSave: { channel: 'odin:manage:personality.presets.save', core: 'personality.presets.save', command: true },
  personalityPresetsDelete: { channel: 'odin:manage:personality.presets.delete', core: 'personality.presets.delete', command: true },
  memoryList: { channel: 'odin:manage:memory.list', core: 'memory.list', command: false },
  memoryGet: { channel: 'odin:manage:memory.get', core: 'memory.get', command: false },
  memorySet: { channel: 'odin:manage:memory.set', core: 'memory.set', command: true },
  memoryDelete: { channel: 'odin:manage:memory.delete', core: 'memory.delete', command: true },
  memoryBulkDelete: { channel: 'odin:manage:memory.bulk_delete', core: 'memory.bulk_delete', command: true },
  listsList: { channel: 'odin:manage:lists.list', core: 'lists.list', command: false },
  listsGet: { channel: 'odin:manage:lists.get', core: 'lists.get', command: false },
  listsDelete: { channel: 'odin:manage:lists.delete', core: 'lists.delete', command: true },
  knowledgeList: { channel: 'odin:manage:knowledge.list', core: 'knowledge.list', command: false },
  knowledgeSearch: { channel: 'odin:manage:knowledge.search', core: 'knowledge.search', command: false },
  knowledgeIngest: { channel: 'odin:manage:knowledge.ingest', core: 'knowledge.ingest', command: true },
  knowledgeReingest: { channel: 'odin:manage:knowledge.reingest', core: 'knowledge.reingest', command: true },
  knowledgeDelete: { channel: 'odin:manage:knowledge.delete', core: 'knowledge.delete', command: true },
  knowledgeVersions: { channel: 'odin:manage:knowledge.versions', core: 'knowledge.versions', command: false },
  knowledgeRestore: { channel: 'odin:manage:knowledge.restore', core: 'knowledge.restore', command: true },
  auditQuery: { channel: 'odin:manage:audit.query', core: 'audit.query', command: false },
  auditVerify: { channel: 'odin:manage:audit.verify', core: 'audit.verify', command: false },
  healthGet: { channel: 'odin:manage:health.get', core: 'health.get', command: false },
  logsSearch: { channel: 'odin:manage:logs.search', core: 'logs.search', command: false },
  turnStateList: { channel: 'odin:manage:turn_state.list', core: 'turn_state.list', command: false },
  computerStatus: { channel: 'odin:manage:computer.status', core: 'computer.status', command: false },
  computerReconcile: { channel: 'odin:manage:computer.reconcile', core: 'computer.reconcile', command: true }
}

export interface SettingsSetParams {
  expected_revision: string
  changes: SettingsChange[]
}

/**
 * The settings-shaped methods (protocol.md, Dedicated settings methods): each takes settings.set's params and answers
 * its result, for the fields whose apply_handler names it, and runs its owner's transaction. Each has its own channel.
 */
export const SETTINGS_SHAPED = {
  'providers.codex.set': { call: 'providersCodexSet', channel: 'odin:core-settings:providers.codex.set' },
  'providers.auxiliary.set': { call: 'providersAuxiliarySet', channel: 'odin:core-settings:providers.auxiliary.set' },
  'providers.ollama.set': { call: 'providersOllamaSet', channel: 'odin:core-settings:providers.ollama.set' },
  'providers.compat.set': { call: 'providersCompatSet', channel: 'odin:core-settings:providers.compat.set' },
  'computer.activation.set': { call: 'computerActivationSet', channel: 'odin:core-settings:computer.activation.set' }
} as const

export type SettingsShapedMethod = keyof typeof SETTINGS_SHAPED
export type SettingsShapedApi = {
  [M in SettingsShapedMethod as (typeof SETTINGS_SHAPED)[M]['call']]: (params: SettingsSetParams) => Promise<Result<SettingsSetResult>>
}

export interface QuotaWindow {
  used_percent: number
  window_minutes: number
  resets_at: number | null
}

/** One Codex account, in the shape of Odin's GET /api/codex/status. */
export interface CodexAccount {
  index: number
  label?: string
  email?: string
  account_id?: string
  plan_type?: string
  expires_at?: number
  expired?: boolean
  rate_limited?: boolean
  is_current?: boolean
  quota?: { primary: QuotaWindow | null; secondary: QuotaWindow | null; observed_at: number; limit_reached_type: string | null } | null
  limit_reached?: boolean
  quota_check_failed?: unknown
  /** Present instead of the rest when the account's credentials couldn't be read. */
  error?: string
}

export interface CodexStatus {
  configured: boolean
  account_count?: number
  current_index?: number
  accounts: CodexAccount[]
}

export interface DeviceCode {
  /** Local opaque main-process handle, never the provider's device authorization secret. */
  login_id: string
  user_code: string
  interval: number
  verify_url: string
  expires_in: number
}

export type LoginPoll = { status: 'pending' } | { status: 'authenticated'; email: string; account_id: string }

export interface QuietHours {
  enabled: boolean
  /** Local time, "HH:MM". The window may cross midnight. */
  start: string
  end: string
}

/** How desktop notifications behave (D13: previews on by default). Stored by the app, not the core. */
export interface NotificationSettings {
  enabled: boolean
  previews: boolean
  quietHours: QuietHours
  /** Conversations whose notifications are muted. Their unread state still counts. */
  muted: string[]
}

export interface NotificationChange {
  enabled?: boolean
  previews?: boolean
  quietHours?: Partial<QuietHours>
}

export interface Settings {
  autostart: boolean
  notifications: NotificationSettings
}

export interface SubmitParams {
  client_submission_id: string
  conversation_id: string
  text: string
  attachments?: Array<{ ref: string; add_to_knowledge: boolean }>
}

export interface ControlTarget {
  control_command_id: string
  conversation_id: string
  request_id: string
  generation: number
}

/** The API the preload bridge exposes as `window.odin`. Nothing else crosses the bridge. */
export interface OdinApi extends ManagementApi, SettingsShapedApi {
  status(): Promise<Result<CoreStatus>>
  listConversations(): Promise<Result<{ items: ConversationListItem[]; watermark: string }>>
  createConversation(params: {
    command_id: string
    title?: string
    parent_id?: string
    from_message_id?: string
  }): Promise<Result<{ conversation: Conversation }>>
  updateConversation(params: {
    command_id: string
    id: string
    expected_rev: number
    title?: string
    archived?: boolean
  }): Promise<Result<{ conversation: Conversation }>>
  deleteConversation(params: { command_id: string; id: string; expected_rev: number }): Promise<Result<{ disposition: string }>>
  resetContext(params: { command_id: string; id: string; expected_rev: number }): Promise<Result<{ conversation: Conversation }>>
  markRead(params: { id: string; through_message_id: string }): Promise<Result<{ conversation: Conversation }>>
  search(params: { query: string; conversation_id?: string; limit?: number; cursor?: string }): Promise<Result<SearchResult>>
  messagesAround(params: { conversation_id: string; message_id: string; before?: number; after?: number }): Promise<Result<AroundResult>>
  listMessages(params: { conversation_id: string; before?: string; limit?: number }): Promise<Result<{ items: Message[]; has_more: boolean; watermark: string }>>
  snapshotConversation(params: { conversation_id: string; limit?: number }): Promise<Result<ConversationSnapshot>>
  submit(params: SubmitParams): Promise<Result<{ disposition: string; request_id?: string; message_id?: string }>>
  stop(params: ControlTarget): Promise<Result<{ disposition: string }>>
  steer(params: ControlTarget & { text: string }): Promise<Result<{ disposition: string; sequence?: number }>>
  usage(period: '24h' | '7d' | '30d' | 'all'): Promise<Result<UsageResult>>
  reload(scope: 'skills' | 'config' | 'context'): Promise<Result<{ disposition: string; summary: string }>>
  getDraft(conversationId: string): Promise<Result<{ text: string }>>
  setDraft(conversationId: string, text: string): Promise<Result<{ saved: boolean }>>
  /** Opens the system file picker. */
  pickFiles(): Promise<Result<StagedBatch>>
  /** Files dropped on or pasted into the window. Their paths come from the operating system, never from the page. */
  attachFiles(files: readonly File[]): Promise<Result<StagedBatch>>
  /** Bytes with no file behind them, such as a pasted screenshot. */
  attachBytes(params: { name: string; mime: string; data: Uint8Array }): Promise<Result<StagedAttachment>>
  uploadAttachment(params: { id: string; conversation_id: string }): Promise<Result<AttachmentRef>>
  cancelAttachment(id: string): Promise<Result<{ cancelled: boolean }>>
  onAttachmentProgress(listener: (progress: AttachmentProgress) => void): () => void
  workList(params?: { kind?: WorkKind; conversation_id?: string }): Promise<Result<{ items: WorkItem[] }>>
  workControl(params: { control_command_id: string; kind: WorkKind; id: string; action: WorkAction }): Promise<Result<{ disposition: string }>>
  resumeRequest(params: {
    control_command_id: string
    conversation_id: string
    request_id: string
    generation: number
  }): Promise<Result<{ disposition: 'admitted' | 'rejected'; reason?: string }>>
  toolDetail(params: { request_id: string; invocation_id: string }): Promise<Result<ToolDetail>>
  toolOutput(params: { cursor: string; limit: number }): Promise<Result<ToolOutputPage>>
  /** An image's bytes, for showing it inline. */
  fetchArtifact(ref: string): Promise<Result<{ data: Uint8Array }>>
  /** Whether the core still has a file: one byte read. A file it no longer has is dropped from the private cache. */
  checkArtifact(ref: string): Promise<Result<{ available: boolean }>>
  openArtifact(params: { ref: string; name: string }): Promise<Result<{ opened: boolean }>>
  saveArtifact(params: { ref: string; name: string }): Promise<Result<{ saved: boolean }>>
  revealArtifact(params: { ref: string; name: string }): Promise<Result<{ revealed: boolean }>>
  reportPage(params: { report_id: string; page: number }): Promise<Result<ReportPage>>
  copyText(text: string): Promise<Result<{ copied: boolean }>>
  getSettings(): Promise<Result<Settings>>
  setAutostart(enabled: boolean): Promise<Result<Settings>>
  setNotifications(change: NotificationChange): Promise<Result<Settings>>
  settingsSchema(): Promise<Result<ConfigMeta>>
  settingsSet(params: SettingsSetParams): Promise<Result<SettingsSetResult>>
  /** Odin's POST /api/config/image-models: follow the shipped default, or pin the value in effect. */
  imageModelIntent(params: {
    expected_revision: string
    operations: Partial<Record<ImageLeaf, 'follow' | 'pin'>>
  }): Promise<Result<{ image_models: Record<ImageLeaf, ImageModelIntent>; image_models_revision: string; revision: string }>>
  secretsSet(params: { path: string; value: string }): Promise<Result<{ set: boolean }>>
  secretsClear(params: { path: string }): Promise<Result<{ set: boolean }>>
  /** Explicit owner Retry only. Background reads never unlock or display a keyring prompt. */
  secretsUnlock(): Promise<Result<{ unlocked: true }>>
  /** A field whose `apply_handler` is a dedicated method: models.main.set or models.agents.set. */
  editLeaf(params: { method: string; params: Record<string, unknown> }): Promise<Result<Record<string, unknown>>>
  codexAccounts(): Promise<Result<CodexStatus>>
  codexActivate(params: { index: number }): Promise<Result<{ status: string; active_index: number }>>
  codexLabel(params: { index: number; label: string }): Promise<Result<{ status: string; label: string }>>
  codexRemove(params: { index: number }): Promise<Result<{ status: string; email: string }>>
  codexLoginBegin(): Promise<Result<DeviceCode>>
  codexLoginPoll(params: { login_id: string }): Promise<Result<LoginPoll>>
  codexOpenVerification(): Promise<Result<{ opened: boolean }>>
  setConversationMuted(params: { conversation_id: string; muted: boolean }): Promise<Result<Settings>>
  /** A notification was clicked: open its exact committed message, including older history. Main-to-window only. */
  onOpenConversation(listener: (target: { conversationId: string; messageId: string }) => void): () => void
  getAppState(): Promise<AppState>
  /** Archives only the current cleanup notice by its opaque ID. Never replays work or reconciles resources. */
  acknowledgeCleanup(id: string): Promise<Result<AppState>>
  onEvent(listener: (event: CoreEvent) => void): () => void
  onAppState(listener: (state: AppState) => void): () => void
  /** Late receipts for commands whose first answer was 'no_receipt'. */
  onReceipt(listener: (receipt: LateReceipt) => void): () => void
  /** The core could not replay the events since the app's cursor: every view must be rebuilt from snapshots. */
  onReset(listener: (reset: ResetNotice) => void): () => void
}

export interface ResetNotice {
  event_high: string
}

export interface LateReceipt {
  id: string
  settled: Result<unknown>
}

export const IPC = {
  status: 'odin:status',
  listConversations: 'odin:conversations:list',
  createConversation: 'odin:conversations:create',
  updateConversation: 'odin:conversations:update',
  deleteConversation: 'odin:conversations:delete',
  resetContext: 'odin:conversations:reset-context',
  markRead: 'odin:conversations:mark-read',
  search: 'odin:search',
  messagesAround: 'odin:messages:around',
  listMessages: 'odin:messages:list',
  snapshotConversation: 'odin:conversation:snapshot',
  submit: 'odin:submit',
  stop: 'odin:stop',
  steer: 'odin:steer',
  usage: 'odin:usage',
  reload: 'odin:reload',
  getDraft: 'odin:drafts:get',
  setDraft: 'odin:drafts:set',
  pickFiles: 'odin:attachments:pick',
  attachPaths: 'odin:attachments:add-paths',
  attachBytes: 'odin:attachments:add-bytes',
  uploadAttachment: 'odin:attachments:upload',
  cancelAttachment: 'odin:attachments:cancel',
  attachmentProgress: 'odin:attachments:progress',
  workList: 'odin:work:list',
  workControl: 'odin:work:control',
  resumeRequest: 'odin:resume',
  toolDetail: 'odin:tool:detail',
  toolOutput: 'odin:tool:output',
  fetchArtifact: 'odin:artifacts:fetch',
  checkArtifact: 'odin:artifacts:check',
  openArtifact: 'odin:artifacts:open',
  saveArtifact: 'odin:artifacts:save',
  revealArtifact: 'odin:artifacts:reveal',
  reportPage: 'odin:reports:page',
  copyText: 'odin:clipboard:copy',
  getSettings: 'odin:settings:get',
  setAutostart: 'odin:settings:set-autostart',
  setNotifications: 'odin:settings:set-notifications',
  settingsSchema: 'odin:core-settings:schema',
  settingsSet: 'odin:core-settings:set',
  imageModelIntent: 'odin:core-settings:image-intent',
  secretsSet: 'odin:secrets:set',
  secretsClear: 'odin:secrets:clear',
  secretsUnlock: 'odin:secrets:unlock',
  editLeaf: 'odin:core-settings:edit-leaf',
  codexAccounts: 'odin:codex:accounts',
  codexActivate: 'odin:codex:activate',
  codexLabel: 'odin:codex:label',
  codexRemove: 'odin:codex:remove',
  codexLoginBegin: 'odin:codex:login-begin',
  codexLoginPoll: 'odin:codex:login-poll',
  codexOpenVerification: 'odin:codex:open-verification',
  setConversationMuted: 'odin:settings:set-muted',
  openConversation: 'odin:open-conversation',
  /** Preload listener readiness only. No payload, target, command or renderer-controlled core operation. */
  notificationRouteReady: 'odin:notification-route-ready',
  getAppState: 'odin:app-state:get',
  acknowledgeCleanup: 'odin:cleanup:acknowledge',
  event: 'odin:event',
  appState: 'odin:app-state',
  receipt: 'odin:receipt',
  reset: 'odin:reset'
} as const
