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

export interface Settings {
  autostart: boolean
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
export interface OdinApi {
  status(): Promise<Result<CoreStatus>>
  listConversations(): Promise<Result<{ items: ConversationListItem[]; watermark: string }>>
  createConversation(params: { title?: string; parent_id?: string; from_message_id?: string }): Promise<Result<{ conversation: Conversation }>>
  updateConversation(params: { id: string; expected_rev: number; title?: string; archived?: boolean }): Promise<Result<{ conversation: Conversation }>>
  deleteConversation(params: { id: string; expected_rev: number }): Promise<Result<{ disposition: string }>>
  resetContext(params: { id: string; expected_rev: number }): Promise<Result<{ conversation: Conversation }>>
  markRead(params: { id: string; through_message_id: string }): Promise<Result<{ conversation: Conversation }>>
  search(params: { query: string; conversation_id?: string; limit?: number; cursor?: string }): Promise<Result<SearchResult>>
  messagesAround(params: { conversation_id: string; message_id: string; before?: number; after?: number }): Promise<Result<AroundResult>>
  listMessages(params: { conversation_id: string; before?: string; limit?: number }): Promise<Result<{ items: Message[]; has_more: boolean; watermark: string }>>
  snapshotConversation(params: { conversation_id: string; limit?: number }): Promise<Result<ConversationSnapshot>>
  submit(params: SubmitParams): Promise<Result<{ disposition: string; request_id?: string; message_id?: string }>>
  stop(params: ControlTarget): Promise<Result<{ disposition: string }>>
  steer(params: ControlTarget & { text: string }): Promise<Result<{ disposition: string; sequence?: number }>>
  usage(period: 'session' | 'day' | 'week'): Promise<Result<UsageResult>>
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
  openArtifact(params: { ref: string; name: string }): Promise<Result<{ opened: boolean }>>
  saveArtifact(params: { ref: string; name: string }): Promise<Result<{ saved: boolean }>>
  revealArtifact(params: { ref: string; name: string }): Promise<Result<{ revealed: boolean }>>
  reportPage(params: { report_id: string; page: number }): Promise<Result<ReportPage>>
  copyText(text: string): Promise<Result<{ copied: boolean }>>
  getSettings(): Promise<Result<Settings>>
  setAutostart(enabled: boolean): Promise<Result<Settings>>
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
  openArtifact: 'odin:artifacts:open',
  saveArtifact: 'odin:artifacts:save',
  revealArtifact: 'odin:artifacts:reveal',
  reportPage: 'odin:reports:page',
  copyText: 'odin:clipboard:copy',
  getSettings: 'odin:settings:get',
  setAutostart: 'odin:settings:set-autostart',
  getAppState: 'odin:app-state:get',
  event: 'odin:event',
  appState: 'odin:app-state',
  receipt: 'odin:receipt',
  reset: 'odin:reset'
} as const
