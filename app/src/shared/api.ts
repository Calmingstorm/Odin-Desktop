// Types shared by the main process, the preload bridge and the renderer.
// They mirror docs/design/protocol.md (v0, minor 3).

export type CorePhase = 'starting' | 'ready' | 'degraded' | 'quiescing'

export interface CoreStatus {
  phase: CorePhase
  core_instance_id: string
  version: string
  capabilities: string[]
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
}

/** Every call through the bridge settles to one of these; nothing throws across it. */
export type Result<T> = { ok: true; result: T } | { ok: false; error: CoreError }

/** Connection state as the app's main process sees it. */
export type LinkState = 'starting' | 'connecting' | 'ready' | 'reconnecting' | 'core-restarting' | 'core-failed'

export interface AppState {
  link: LinkState
  coreInstanceId: string | null
  /** True when the window was opened on a desktop where no tray could be found. */
  noTray: boolean
  /** Commands that were sent but whose receipt is still pending reconciliation. */
  unreceipted: number
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
  configured: boolean
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
  status: { counts: Record<string, number>; desired_revision: string; effective_revision: string | null }
  image_models?: Record<ImageLeaf, ImageModelIntent>
  image_models_revision?: string
}

export type SettingsChange = { path: string; value: unknown } | { path: string; delete: true }

export interface SettingsSetResult {
  revision: string
  fields: ConfigField[]
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
  device_auth_id: string
  user_code: string
  interval: number
  verify_url: string
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
export interface OdinApi extends SettingsShapedApi {
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
  /** A field whose `apply_handler` is a dedicated method: models.main.set or models.agents.set. */
  editLeaf(params: { method: string; params: Record<string, unknown> }): Promise<Result<Record<string, unknown>>>
  codexAccounts(): Promise<Result<CodexStatus>>
  codexActivate(params: { index: number }): Promise<Result<{ status: string; active_index: number }>>
  codexLabel(params: { index: number; label: string }): Promise<Result<{ status: string; label: string }>>
  codexRemove(params: { index: number }): Promise<Result<{ status: string; email: string }>>
  codexLoginBegin(): Promise<Result<DeviceCode>>
  codexLoginPoll(params: { device_auth_id: string; user_code: string }): Promise<Result<LoginPoll>>
  setConversationMuted(params: { conversation_id: string; muted: boolean }): Promise<Result<Settings>>
  /** A notification was clicked: the window should show that conversation. */
  onOpenConversation(listener: (conversationId: string) => void): () => void
  getAppState(): Promise<AppState>
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
  editLeaf: 'odin:core-settings:edit-leaf',
  codexAccounts: 'odin:codex:accounts',
  codexActivate: 'odin:codex:activate',
  codexLabel: 'odin:codex:label',
  codexRemove: 'odin:codex:remove',
  codexLoginBegin: 'odin:codex:login-begin',
  codexLoginPoll: 'odin:codex:login-poll',
  setConversationMuted: 'odin:settings:set-muted',
  openConversation: 'odin:open-conversation',
  getAppState: 'odin:app-state:get',
  event: 'odin:event',
  appState: 'odin:app-state',
  receipt: 'odin:receipt',
  reset: 'odin:reset'
} as const
