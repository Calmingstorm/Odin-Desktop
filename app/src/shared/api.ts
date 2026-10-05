// Types shared by the main process, the preload bridge and the renderer.
// They mirror docs/design/protocol.md (v0, minor 2).

export type CorePhase = 'starting' | 'ready' | 'degraded' | 'quiescing'

export interface CoreStatus {
  phase: CorePhase
  core_instance_id: string
  version: string
  capabilities: string[]
}

export interface Conversation {
  id: string
  title: string
  rev: number
  parent_id: string | null
  updated_at: string
  unread: number
  archived: boolean
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
  listConversations(): Promise<Result<{ items: Conversation[] }>>
  createConversation(params: { title?: string; parent_id?: string }): Promise<Result<{ conversation: Conversation }>>
  listMessages(params: { conversation_id: string; before?: string; limit?: number }): Promise<Result<{ items: Message[]; has_more: boolean; watermark: string }>>
  snapshotConversation(params: { conversation_id: string; limit?: number }): Promise<Result<ConversationSnapshot>>
  submit(params: SubmitParams): Promise<Result<{ disposition: string; request_id?: string; message_id?: string }>>
  stop(params: ControlTarget): Promise<Result<{ disposition: string }>>
  steer(params: ControlTarget & { text: string }): Promise<Result<{ disposition: string; sequence?: number }>>
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
  listMessages: 'odin:messages:list',
  snapshotConversation: 'odin:conversation:snapshot',
  submit: 'odin:submit',
  stop: 'odin:stop',
  steer: 'odin:steer',
  getSettings: 'odin:settings:get',
  setAutostart: 'odin:settings:set-autostart',
  getAppState: 'odin:app-state:get',
  event: 'odin:event',
  appState: 'odin:app-state',
  receipt: 'odin:receipt',
  reset: 'odin:reset'
} as const
