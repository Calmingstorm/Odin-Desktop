// Window state. Reply text shown here is always committed text (D9).
//
// Consistency rules (docs/design/protocol.md, delivery rules):
// - A conversation view is replaced only by a snapshot, and then advanced only by events above its watermark.
// - While a snapshot is in flight, that conversation's events are held and replayed above the watermark when it
//   arrives. The answer to a superseded snapshot request is dropped. The sidebar's activity works the same way
//   against the conversation list.
// - A reset discards every view: the interval it covers is unknown, never empty.
// - Losing the link or changing core starts a new recovery: from that moment no view is authoritative until a
//   snapshot taken during the current recovery has applied. Answers from an earlier recovery never restore it.
// - Nothing is sent, steered or stopped in a conversation until its view is authoritative. Drafts are kept.
// - Stop and Steer only ever target the running request and generation. Queued follow-ups are tracked separately.
// - A command without a receipt has an unknown outcome, never a failure. It keeps its ID, and the late receipt or the
//   core's events settle it. Commands this window sent are kept apart from the core's authoritative control
//   projection, which every snapshot replaces.
// - Unknown effects stay listed until the core reports them reconciled; later outcomes never push them out.
import { reactive } from 'vue'
import { images } from './artifacts'
import { isUnavailable, resultMessage } from './capability'
import { NAV } from './settings-form'
import type {
  AppState,
  ControlRecord,
  Conversation,
  ConversationListItem,
  ConversationSnapshot,
  CoreError,
  CoreEvent,
  LateReceipt,
  Message,
  NotificationSettings,
  QueuedRequest,
  Result,
  SearchHit,
  RunningRequest,
  TerminalKind,
  TerminalOutcome,
  ToolEntry
} from '../../shared/api'

export type { ToolEntry } from '../../shared/api'

export interface PendingSubmission {
  client_submission_id: string
  conversation_id: string
  text: string
  status: 'sending' | 'awaiting-receipt' | 'unknown'
}

export type ControlStatus =
  | 'sending'
  | 'awaiting-receipt'
  | 'unknown'
  | 'requested'
  | 'queued'
  | 'confirmed'
  | 'consumed'
  | 'closed'
  | 'not_running'
  | 'stale_binding'
  | 'not-delivered'

/** A Stop or Steer this window sent. */
export interface ControlItem {
  control_command_id: string
  kind: 'stop' | 'steer'
  conversation_id: string
  request_id: string
  generation: number
  text?: string
  status: ControlStatus
  detail?: string
}

/** The core's authoritative view of a control, from snapshots, receipts and events. */
export interface ControlProjection {
  control_command_id: string
  kind: 'stop' | 'steer'
  request_id: string
  generation: number
  status: ControlStatus
}

export interface SteerLine {
  control_command_id: string
  text?: string
  status: ControlStatus
  detail?: string
}

export interface ConversationView {
  status: 'loading' | 'ready'
  hasData: boolean
  /** The recovery its snapshot belongs to; authoritative only while that is the current one. */
  epoch: number
  /** The recovery the in-flight snapshot request belongs to. */
  loadEpoch: number
  /** The highest event sequence this view reflects. */
  watermark: number
  loadToken: number
  held: CoreEvent[]
  messages: Message[]
  hasMore: boolean
  loadingOlder: boolean
  running: RunningRequest | null
  queued: QueuedRequest[]
  recent: TerminalOutcome[]
  unresolved: TerminalOutcome[]
  tools: Record<string, ToolEntry[]>
  controls: Record<string, ControlProjection>
}

export type ComposerMode = 'steer' | 'queue'

const RECENT_LIMIT = 20
const CONTROL_LIMIT = 200

export const state = reactive({
  app: { link: 'starting', coreInstanceId: null, noTray: false, unreceipted: 0 } as AppState,
  loaded: false,
  conversations: [] as Conversation[],
  activeId: null as string | null,
  /** Bumped whenever the link is lost or the core changes. */
  recoveryEpoch: 0,
  /** Why the latest snapshot of a conversation failed, until a retry starts. */
  loadErrors: {} as Record<string, string | undefined>,
  /** Why the current recovery couldn't load the conversation list (or create the first chat), until a retry. */
  recoveryError: undefined as string | undefined,
  conversationsUnavailable: false,
  unavailableViews: {} as Record<string, boolean | undefined>,
  views: {} as Record<string, ConversationView | undefined>,
  /** Requests queued or running per conversation, for the sidebar: from the list, then from events. */
  busy: {} as Record<string, string[] | undefined>,
  pending: [] as PendingSubmission[],
  controls: [] as ControlItem[],
  notice: '',
  autostart: false,
  showArchived: false,
  search: { open: false, query: '', loading: false, hits: [] as SearchHit[], nextCursor: null as string | null, error: '', unavailable: false },
  /** A window of messages around a search hit that is outside the loaded history. The live view is untouched. */
  jump: null as { conversationId: string; messageId: string; items: Message[]; hasBefore: boolean; hasAfter: boolean } | null,
  /** The message a jump points at, highlighted and scrolled into view. */
  highlightId: null as string | null,
  /** Output of a command such as /status, shown in the window and never sent to Odin. */
  panel: null as { title: string; text: string } | null,
  /** Chat or the settings menu. */
  view: 'chat' as 'chat' | 'settings',
  /** Retained section only, never a local readiness or completion flag. */
  settingsSection: 'general',
  setupReminderHidden: false,
  /** The app's notification settings, from the main process. */
  notifications: null as NotificationSettings | null,
  /** Resume requests by `request_id:generation`, until the resumed request starts or the core says no. */
  resumes: {} as Record<string, ResumeState | undefined>,
  /** Counts each move to the latest messages, so the message list scrolls there once the view is on screen. */
  latestScroll: 0
})

export interface ResumeState {
  /** `unknown`: no answer yet. It stays under its first command, never sent again, until its receipt settles it. */
  status: 'sending' | 'admitted' | 'rejected' | 'failed' | 'unknown'
  reason?: string
  commandId?: string
}

type EventListener = (event: CoreEvent) => void
const eventListeners: EventListener[] = []
const readyListeners: Array<() => void> = []
const receiptListeners: Array<(receipt: LateReceipt) => void> = []

/** Lets other stores settle their own commands from late receipts. */
export function onLateReceipt(listener: (receipt: LateReceipt) => void): void {
  receiptListeners.push(listener)
}

/** Lets the work and status stores see every core event, without this store importing them. */
export function onCoreEvent(listener: EventListener): void {
  eventListeners.push(listener)
}

/** Runs whenever the link becomes ready: at start, and after every recovery. */
export function onReady(listener: () => void): void {
  readyListeners.push(listener)
}

export function openSettings(section?: string): void {
  if (section && NAV.some((entry) => entry.id === section)) state.settingsSection = section
  state.view = 'settings'
}

function notifyReady(): void {
  for (const listener of readyListeners) listener()
}

export function showPanel(title: string, text: string): void {
  state.panel = { title, text }
}

const TERMINAL = new Set([
  'request.completed',
  'request.failed',
  'request.cancelled',
  'request.interrupted',
  'request.suspended'
])

/** Later states never move back: a stale snapshot or receipt can't undo a newer event. */
const CONTROL_RANK: Record<ControlStatus, number> = {
  sending: 0,
  'awaiting-receipt': 1,
  unknown: 1,
  requested: 2,
  queued: 2,
  confirmed: 3,
  consumed: 3,
  closed: 3,
  not_running: 3,
  stale_binding: 3,
  'not-delivered': 3
}

/** Sent, but with no answer yet: only these local states stand in for the core's projection. */
const UNRECEIPTED = new Set<ControlStatus>(['sending', 'awaiting-receipt', 'unknown'])

function note(text: string): void {
  state.notice = text
}

function errorText(result: Result<unknown>): string {
  return resultMessage(result, 'This capability')
}

/** No receipt, or a receipt that says the outcome is unknown: the command may have been admitted. */
export function isUnknownOutcome(error: CoreError): boolean {
  return error.code === 'no_receipt' || error.disposition === 'outcome_unknown'
}

function isAuthoritative(view: ConversationView | undefined): view is ConversationView {
  return Boolean(view && view.status === 'ready' && view.hasData && view.epoch === state.recoveryEpoch)
}

/** Whether a message, Steer or Stop may be routed to this conversation now. */
export function canAct(conversationId: string | null): boolean {
  return Boolean(conversationId && !state.conversationsUnavailable && !state.unavailableViews[conversationId] && state.app.link === 'ready' && isAuthoritative(state.views[conversationId]))
}

export async function init(): Promise<void> {
  let pushedAppState = false
  window.odin.onAppState((app) => {
    pushedAppState = true
    const previous = state.app
    const lostLink = previous.link === 'ready' && app.link !== 'ready'
    const coreChanged = Boolean(previous.coreInstanceId && app.coreInstanceId && app.coreInstanceId !== previous.coreInstanceId)
    // Synchronously, before a ready link can make any view routable again.
    if (lostLink || coreChanged) state.recoveryEpoch += 1
    const becameReady = app.link === 'ready' && (previous.link !== 'ready' || coreChanged)
    state.app = app
    if (becameReady) {
      notifyReady()
      void loadAll()
    }
  })
  window.odin.onEvent(applyEvent)
  window.odin.onReceipt(applyReceipt)
  window.odin.onReset(() => void resetViews())
  // The OS action identifies a committed message, which may no longer be the latest or in the loaded page.
  // A recreated preload can receive its queued click before the initial app/list/snapshot bootstrap. Let that
  // bootstrap finish first, or its default conversation selection would fence the user's click navigation.
  let initialized = false
  let pendingNotification: { conversationId: string; messageId: string } | null = null
  window.odin.onOpenConversation((target) => {
    if (!initialized) pendingNotification = target
    else void jumpToMessage(target.conversationId, target.messageId)
  })
  if (typeof document !== 'undefined') {
    // Coming back to the window counts as reading what is on screen.
    const attend = (): void => {
      if (state.activeId) void markReadIfAttentive(state.activeId)
    }
    document.addEventListener('visibilitychange', attend)
    window.addEventListener('focus', attend)
  }
  const app = await window.odin.getAppState()
  // A main-process state push can overtake this initial IPC reply. Never put
  // the window back on an older link/incarnation after it has learned newer state.
  if (app && !pushedAppState) state.app = app
  const settings = await window.odin.getSettings()
  if (settings.ok) {
    state.autostart = settings.result.autostart
    state.notifications = settings.result.notifications
  }
  if (state.app.link === 'ready') {
    notifyReady()
    await loadAll()
  }
  initialized = true
  if (pendingNotification) {
    const target = pendingNotification as { conversationId: string; messageId: string }
    void jumpToMessage(target.conversationId, target.messageId)
  }
}

let loadAllInFlight: { epoch: number; promise: Promise<void> } | null = null
let listLoading = false
let listHeld: CoreEvent[] = []

/** One load per recovery. A load started for an earlier recovery is followed by a fresh one, never reused. */
function loadAll(): Promise<void> {
  const epoch = state.recoveryEpoch
  if (loadAllInFlight?.epoch === epoch) return loadAllInFlight.promise
  const run = (): Promise<void> => loadAllOnce(epoch)
  // Start at once when nothing is loading; otherwise after the earlier recovery's load has settled.
  const entry = { epoch, promise: loadAllInFlight ? loadAllInFlight.promise.catch(() => undefined).then(run) : run() }
  loadAllInFlight = entry
  void entry.promise.finally(() => {
    if (loadAllInFlight === entry) loadAllInFlight = null
  })
  return entry.promise
}

async function loadAllOnce(epoch: number): Promise<void> {
  if (epoch !== state.recoveryEpoch) return
  state.recoveryError = undefined
  state.conversationsUnavailable = false
  appliedWatermark = -1
  listLoading = true
  const generation = ++listGeneration
  const listed = await window.odin.listConversations()
  const held = listHeld.sort((a, b) => a.seq - b.seq)
  listHeld = []
  listLoading = false
  if (!listed.ok || epoch !== state.recoveryEpoch) {
    // A failed list, or one answered for an earlier recovery, never replaces the sidebar.
    for (const event of held) trackBusy(event)
    if (!listed.ok && epoch === state.recoveryEpoch) {
      if (isUnavailable(listed.error)) {
        // A previous core may have served these views. Never present them as this core's conversations.
        state.conversationsUnavailable = true
        state.conversations = []
        state.activeId = null
        state.views = {}
        state.busy = {}
        clearNavigation()
        state.loaded = true
      } else state.recoveryError = listed.error.message
    }
    return
  }
  applyList(listed.result.items, Number(listed.result.watermark) || 0, generation, held)
  if (state.conversations.length === 0) {
    const created = await conversationCommand(
      'new',
      (command_id) => window.odin.createConversation({ command_id, title: 'Chat' }),
      (answer) => {
        if (answer.ok) upsertConversation(answer.result.conversation)
      }
    )
    if (!created?.ok) {
      if (epoch === state.recoveryEpoch) {
        if (created && !created.ok && isUnavailable(created.error)) state.conversationsUnavailable = true
        else state.recoveryError = created ? errorText(created) : 'Waiting for Odin to confirm the first conversation.'
      }
      return
    }
  }
  if (!state.activeId || !state.conversations.some((c) => c.id === state.activeId)) {
    state.activeId = state.conversations[0]?.id ?? null
  }
  if (state.activeId) await loadConversation(state.activeId)
  state.loaded = true
}

/** The latest event sequence seen per conversation. A list complete only through an earlier point can't undo it. */
const conversationSeq = new Map<string, number>()
/** Deleted conversations. Their IDs are never reused, so nothing may bring one back. */
const deleted = new Set<string>()
/** Each list request's generation, and when the window learned of a conversation outside any list. */
let listGeneration = 0
const learnedIn = new Map<string, number>()
/** The watermark of the newest complete list applied since the core last started; an older one is obsolete. */
let appliedWatermark = -1

/**
 * The list is complete through `watermark`: it replaces what the window knows, except where an event after the
 * watermark, or a command's answer after the list was asked for, says something newer. With `held`, it also rebuilds
 * the sidebar's activity and applies what came after.
 */
function applyList(items: ConversationListItem[], watermark: number, generation: number, held?: CoreEvent[]): void {
  if (watermark < appliedWatermark) {
    // An answer to an earlier list: everything in it is already known, and a newer list says what's gone.
    if (held) for (const event of held) trackBusy(event)
    return
  }
  appliedWatermark = watermark
  const listed = new Set(items.map((item) => item.id))
  for (const item of items) {
    if (deleted.has(item.id) || (conversationSeq.get(item.id) ?? 0) > watermark) continue
    const { activity, ...conversation } = item
    upsertConversation(conversation, true)
    if (activity && held) {
      state.busy[item.id] = [
        ...(activity.running ? [activity.running.request_id] : []),
        ...activity.queued.map((q) => q.request_id)
      ]
    }
  }
  for (const conversation of [...state.conversations]) {
    if (listed.has(conversation.id) || (conversationSeq.get(conversation.id) ?? 0) > watermark) continue
    if ((learnedIn.get(conversation.id) ?? -1) >= generation) continue
    // Missing from a complete list: gone for now, but not a deletion. Only a deletion is final.
    removeConversation(conversation.id, false)
  }
  if (held) for (const event of held) if (event.seq > watermark) trackBusy(event)
}

function viewFor(conversationId: string): ConversationView {
  if (!state.views[conversationId]) {
    state.views[conversationId] = {
      status: 'loading',
      hasData: false,
      epoch: -1,
      loadEpoch: -1,
      watermark: 0,
      loadToken: 0,
      held: [],
      messages: [],
      hasMore: false,
      loadingOlder: false,
      running: null,
      queued: [],
      recent: [],
      unresolved: [],
      tools: {},
      controls: {}
    }
  }
  return state.views[conversationId]!
}

/** Rebuilds a conversation view from the core's authoritative snapshot, holding events until it applies. */
export async function loadConversation(conversationId: string): Promise<void> {
  const epoch = state.recoveryEpoch
  const view = viewFor(conversationId)
  const token = ++view.loadToken
  view.status = 'loading'
  view.loadEpoch = epoch
  state.loadErrors[conversationId] = undefined
  state.unavailableViews[conversationId] = false
  const result = await window.odin.snapshotConversation({ conversation_id: conversationId })
  if (state.views[conversationId] !== view || view.loadToken !== token) return
  if (!result.ok || epoch !== state.recoveryEpoch) {
    // A failure, or an answer from an earlier recovery: it never makes the view authoritative.
    if (view.hasData) releaseHeld(view)
    else state.views[conversationId] = undefined
    if (!result.ok) {
      if (epoch === state.recoveryEpoch) {
        if (isUnavailable(result.error)) {
          state.unavailableViews[conversationId] = true
          state.views[conversationId] = undefined
        } else state.loadErrors[conversationId] = result.error.message
      }
    } else if (conversationId === state.activeId && state.app.link === 'ready') {
      // The open conversation must not be left without a load for the current recovery.
      void loadConversation(conversationId)
    }
    return
  }
  applySnapshot(conversationId, view, result.result, epoch)
}

function applySnapshot(conversationId: string, view: ConversationView, snapshot: ConversationSnapshot, epoch: number): void {
  const watermark = Number(snapshot.watermark) || 0
  if (view.hasData && watermark < view.watermark) {
    // Older than what this view already shows: keep the view.
    releaseHeld(view)
    return
  }
  view.messages = [...snapshot.messages.items]
  view.hasMore = snapshot.messages.has_more
  view.running = snapshot.running
  view.queued = [...snapshot.queued]
  view.recent = [...snapshot.recent].slice(-RECENT_LIMIT)
  view.unresolved = [...(snapshot.unresolved ?? [])]
  view.tools = Object.fromEntries(Object.entries(snapshot.tools).map(([id, entries]) => [id, entries.map((e) => ({ ...e }))]))
  view.controls = Object.fromEntries(snapshot.controls.map((record) => [record.control_command_id, projection(record)]))
  view.watermark = watermark
  view.hasData = true
  view.epoch = epoch
  upsertConversation(snapshot.conversation)
  state.busy[conversationId] = [
    ...(snapshot.running ? [snapshot.running.request_id] : []),
    ...snapshot.queued.map((q) => q.request_id)
  ]
  for (const record of snapshot.controls) {
    const local = state.controls.find((c) => c.control_command_id === record.control_command_id)
    if (local) advance(local, record.disposition)
  }
  for (const message of view.messages) {
    settleCommittedSubmission(message)
  }
  releaseHeld(view)
  void markReadIfAttentive(conversationId)
}

function projection(record: ControlRecord): ControlProjection {
  return {
    control_command_id: record.control_command_id,
    kind: record.kind,
    request_id: record.request_id,
    generation: record.generation,
    status: statusOf(record.disposition)
  }
}

function releaseHeld(view: ConversationView): void {
  const held = [...view.held].sort((a, b) => a.seq - b.seq)
  view.held = []
  view.status = 'ready'
  for (const event of held) applyToView(view, event)
}

/** The core couldn't replay the interval since our cursor, so nothing in the current views can be trusted. */
async function resetViews(): Promise<void> {
  // A reset is a recovery of its own: earlier answers can't restore anything. The sidebar's activity is rebuilt
  // from the reloaded conversation list.
  state.recoveryEpoch += 1
  for (const view of Object.values(state.views)) if (view) view.loadToken += 1
  state.views = {}
  clearNavigation() // a search window may show what no longer exists
  await loadAll()
}

export async function select(conversationId: string): Promise<void> {
  // Navigation belongs to the conversation it was made in: leaving it ends any jump or highlight, and fences a jump
  // still on its way.
  if (conversationId !== state.activeId || (state.jump && state.jump.conversationId !== conversationId)) clearNavigation()
  await open(conversationId)
}

/** Shows a conversation: a cached view at once, otherwise once its snapshot loads. */
async function open(conversationId: string): Promise<void> {
  state.activeId = conversationId
  const view = state.views[conversationId]
  // A view from an earlier recovery is shown but must be refreshed before anything is routed to it, and so must one
  // whose in-flight load belongs to an earlier recovery.
  const stale = view && (view.status === 'loading' ? view.loadEpoch !== state.recoveryEpoch : !view.hasData || view.epoch !== state.recoveryEpoch)
  if (!view || stale) await loadConversation(conversationId)
  else void markReadIfAttentive(conversationId) // a cached view is on screen at once
}

/** The error that keeps the open conversation from loading, if any: the recovery's own first, then its snapshot's. */
export function loadFailure(): string | undefined {
  return state.recoveryError ?? (state.activeId ? state.loadErrors[state.activeId] : undefined)
}

/** Explicit refusal, separate from loading, transport failures and an empty conversation. */
export function chatUnavailable(): boolean {
  return state.conversationsUnavailable || Boolean(state.activeId && state.unavailableViews[state.activeId])
}

/** Retries whatever failed: the whole recovery (list, then snapshot), or just the open conversation's snapshot. */
export async function retry(): Promise<void> {
  if (state.app.link !== 'ready') return
  if (state.recoveryError) await loadAll()
  else if (state.activeId) await loadConversation(state.activeId)
}

/** The window is visible and focused, so what the open conversation shows has been seen. */
function attentive(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'visible' && document.hasFocus()
}

/** Reads in flight, by conversation; true when another is owed because more arrived meanwhile. */
const markingRead = new Map<string, boolean>()

/**
 * Marks the open conversation read through its latest message, but only while someone can see it, and only while it
 * shows the latest messages: not while a search result's older window is on screen. Calls during a read in flight
 * are coalesced into one more read after it.
 */
async function markReadIfAttentive(conversationId: string): Promise<void> {
  if (markingRead.has(conversationId)) {
    markingRead.set(conversationId, true)
    return
  }
  const conversation = state.conversations.find((c) => c.id === conversationId)
  const view = state.views[conversationId]
  const last = view?.messages[view.messages.length - 1]
  if (!conversation || conversation.unread <= 0 || state.activeId !== conversationId || !last) return
  // A search jump shows older messages, or is on its way to: the latest ones aren't on screen.
  if (state.jump?.conversationId === conversationId || jumpPending === conversationId) return
  if (!isAuthoritative(view) || !attentive()) return
  markingRead.set(conversationId, false)
  try {
    const result = await window.odin.markRead({ id: conversationId, through_message_id: last.id })
    if (result.ok) upsertConversation(result.result.conversation)
  } finally {
    const owed = markingRead.get(conversationId)
    markingRead.delete(conversationId)
    if (owed) void markReadIfAttentive(conversationId)
  }
}

function conversationById(id: string): Conversation | undefined {
  return state.conversations.find((c) => c.id === id)
}

/**
 * Conversation commands whose answer never arrived, by command ID. The broker re-sends each with the same ID after
 * reconnecting, and its late receipt settles it here. Until then, nothing else changes that conversation, so a retry
 * can never create a second thread or reset twice.
 */
const unconfirmed = new Map<string, { key: string; settle: (answer: Result<unknown>, late: boolean) => void }>()
/** Keys with a command on its way, before any answer. */
const sending = new Set<string>()

function awaitingConfirmation(key: string): boolean {
  if (sending.has(key)) return true
  for (const command of unconfirmed.values()) if (command.key === key) return true
  return false
}

/** Sends one conversation command under a fresh ID and settles it now, or when its late receipt arrives. */
async function conversationCommand<T>(
  key: string,
  send: (commandId: string) => Promise<Result<T>>,
  settle: (answer: Result<T>, late: boolean) => void
): Promise<Result<T> | null> {
  if (awaitingConfirmation(key)) {
    note("Odin hasn't confirmed your last change to this conversation yet. It applies once, when he answers.")
    return null
  }
  const commandId = crypto.randomUUID()
  sending.add(key)
  let answer: Result<T>
  try {
    answer = await send(commandId)
  } finally {
    sending.delete(key)
  }
  if (!answer.ok && isUnknownOutcome(answer.error)) {
    unconfirmed.set(commandId, { key, settle: settle as (answer: Result<unknown>, late: boolean) => void })
    note('Waiting for Odin to confirm that change. It is never sent twice.')
    return null
  }
  settle(answer, false)
  return answer
}

/** A changed conversation from a command's answer; a revision conflict refreshes the list so the user can retry. */
function settleConversation(result: Result<{ conversation: Conversation }>): boolean {
  if (result.ok) {
    upsertConversation(result.result.conversation)
    return true
  }
  if (result.error.code === 'stale_binding') {
    note('That conversation changed elsewhere, so it was refreshed. Try again.')
    void refreshConversations()
  } else note(resultMessage(result, 'Conversations'))
  return false
}

async function refreshConversations(): Promise<void> {
  const epoch = state.recoveryEpoch
  const generation = ++listGeneration
  const listed = await window.odin.listConversations()
  if (!listed.ok || epoch !== state.recoveryEpoch) return
  applyList(listed.result.items, Number(listed.result.watermark) || 0, generation)
}

export async function renameConversation(id: string, title: string): Promise<boolean> {
  const conversation = conversationById(id)
  if (!conversation) return false
  const answer = await conversationCommand(
    id,
    (command_id) => window.odin.updateConversation({ command_id, id, expected_rev: conversation.rev, title }),
    settleConversation
  )
  return Boolean(answer?.ok)
}

export async function setArchived(id: string, archived: boolean): Promise<boolean> {
  const conversation = conversationById(id)
  if (!conversation) return false
  const answer = await conversationCommand(
    id,
    (command_id) => window.odin.updateConversation({ command_id, id, expected_rev: conversation.rev, archived }),
    settleConversation
  )
  return Boolean(answer?.ok)
}

export async function resetContext(id: string): Promise<boolean> {
  const conversation = conversationById(id)
  if (!conversation) return false
  const answer = await conversationCommand(
    id,
    (command_id) => window.odin.resetContext({ command_id, id, expected_rev: conversation.rev }),
    settleConversation
  )
  return Boolean(answer?.ok)
}

export async function deleteConversation(id: string): Promise<boolean> {
  const conversation = conversationById(id)
  if (!conversation) return false
  const answer = await conversationCommand(
    id,
    (command_id) => window.odin.deleteConversation({ command_id, id, expected_rev: conversation.rev }),
    (result) => {
      if (result.ok) return removeConversation(id)
      if (result.error.code === 'stale_binding') {
        note('That conversation changed elsewhere, so it was refreshed. Try again.')
        void refreshConversations()
      } else note(resultMessage(result, 'Conversations'))
    }
  )
  return Boolean(answer?.ok)
}

/** Opens a conversation a command created: at once, or with a note when it was confirmed later. */
function openCreated(answer: Result<{ conversation: Conversation }>, late: boolean, what: string): void {
  if (!answer.ok) return note(resultMessage(answer, 'Conversations'))
  upsertConversation(answer.result.conversation)
  if (late) note(`${what} is ready: “${answer.result.conversation.title}”.`)
  else void select(answer.result.conversation.id)
}

/** A child conversation seeded from the parent's context through a message (default: its latest). */
export async function startThread(parentId: string, fromMessageId?: string): Promise<void> {
  const parent = conversationById(parentId)
  await conversationCommand(
    `thread:${parentId}`,
    (command_id) =>
      window.odin.createConversation({
        command_id,
        title: `Thread: ${parent?.title ?? 'Chat'}`.slice(0, 200),
        parent_id: parentId,
        ...(fromMessageId ? { from_message_id: fromMessageId } : {})
      }),
    (answer, late) => openCreated(answer, late, 'Your new thread')
  )
}

/**
 * Drops everything the window holds for a conversation, and moves to another one if it was open. A deletion is final;
 * missing from a list is not, since a newer fact can bring it back.
 */
function removeConversation(id: string, final = true): void {
  if (final) deleted.add(id)
  state.conversations = state.conversations.filter((c) => c.id !== id)
  // Nothing found in it can be shown or opened any more.
  state.search.hits = state.search.hits.filter((h) => h.conversation_id !== id)
  const view = state.views[id]
  if (view) view.loadToken += 1
  delete state.views[id]
  delete state.busy[id]
  state.pending = state.pending.filter((p) => p.conversation_id !== id)
  if (state.jump?.conversationId === id) clearNavigation()
  if (state.activeId !== id) return
  const next = state.conversations.find((c) => !c.archived) ?? state.conversations[0]
  if (next) void select(next.id)
  else {
    state.activeId = null
    void newConversation()
  }
}

/** Each search's generation: an answer to an earlier search, even for the same words, never replaces a newer one. */
let searchGeneration = 0

export async function runSearch(query: string): Promise<void> {
  const mine = ++searchGeneration
  state.search.query = query
  state.search.loading = true
  state.search.error = ''
  state.search.unavailable = false
  const result = await window.odin.search({ query, limit: 20 })
  if (mine !== searchGeneration) return
  state.search.loading = false
  if (!result.ok) {
    state.search.hits = []
    state.search.nextCursor = null
    state.search.unavailable = isUnavailable(result.error)
    state.search.error = resultMessage(result, 'Search')
    return
  }
  state.search.hits = result.result.hits.filter((h) => !deleted.has(h.conversation_id))
  state.search.nextCursor = result.result.next_cursor ?? null
}

export async function moreResults(): Promise<void> {
  const { query, nextCursor } = state.search
  if (!nextCursor || state.search.loading) return
  const mine = searchGeneration
  state.search.loading = true
  const result = await window.odin.search({ query, limit: 20, cursor: nextCursor })
  if (mine !== searchGeneration) return
  state.search.loading = false
  if (!result.ok) {
    state.search.unavailable = isUnavailable(result.error)
    state.search.error = resultMessage(result, 'Search')
    if (state.search.unavailable) {
      state.search.hits = []
      state.search.nextCursor = null
    }
    return
  }
  const known = new Set(state.search.hits.map((h) => h.message_id))
  state.search.hits = [
    ...state.search.hits,
    ...result.result.hits.filter((h) => !known.has(h.message_id) && !deleted.has(h.conversation_id))
  ]
  state.search.nextCursor = result.result.next_cursor ?? null
}

/**
 * Each navigation's generation: a jump, going back to the latest, opening at the latest, a switch or a reset fences an
 * older one.
 */
let navigationGeneration = 0
/** The conversation a jump is opening. Until it lands, the latest messages aren't what the user is shown. */
let jumpPending: string | null = null

/** Opens a hit's conversation at the message: in place when it is loaded, otherwise in a window around it. */
export async function jumpTo(hit: SearchHit): Promise<void> {
  return jumpToMessage(hit.conversation_id, hit.message_id)
}

/** Both search and OS notification clicks use the same generation-fenced exact-message navigation. */
export async function jumpToMessage(conversationId: string, messageId: string): Promise<void> {
  // Fence what came before, and hold back reading, before anything loads.
  clearNavigation()
  const mine = navigationGeneration
  jumpPending = conversationId
  const current = (): boolean => mine === navigationGeneration && state.activeId === conversationId
  await open(conversationId)
  if (!current()) return
  const view = state.views[conversationId]
  if (view?.messages.some((m) => m.id === messageId)) {
    // In place: the latest messages are on screen after all.
    jumpPending = null
    state.jump = null
    state.highlightId = messageId
    void markReadIfAttentive(conversationId)
    return
  }
  const result = await window.odin.messagesAround({
    conversation_id: conversationId,
    message_id: messageId,
    before: 20,
    after: 20
  })
  if (!current()) return
  jumpPending = null
  if (!result.ok) {
    note(result.error.message)
    void markReadIfAttentive(conversationId) // the latest messages stay on screen
    return
  }
  state.jump = {
    conversationId,
    messageId,
    items: result.result.items,
    hasBefore: result.result.has_before,
    hasAfter: result.result.has_after
  }
  state.highlightId = messageId
}

/** Ends any jump or highlight, and fences a jump still on its way. */
function clearNavigation(): void {
  navigationGeneration += 1
  jumpPending = null
  state.jump = null
  state.highlightId = null
}

/** Opens a conversation at its latest messages, ending any search window, even one in that conversation. */
export async function openLatest(conversationId: string): Promise<void> {
  clearNavigation()
  const mine = navigationGeneration
  await open(conversationId)
  // A newer navigation, or another conversation opened meanwhile, owns the view now.
  if (mine === navigationGeneration && state.activeId === conversationId) state.latestScroll += 1
}

/** The user went back to the latest messages, so they are on screen again. */
export function backToLatest(): void {
  const wasJump = state.jump?.conversationId
  clearNavigation()
  state.latestScroll += 1
  if (wasJump && wasJump === state.activeId) void markReadIfAttentive(wasJump)
}

export async function newConversation(): Promise<void> {
  await conversationCommand(
    'new',
    (command_id) => window.odin.createConversation({ command_id, title: 'New chat' }),
    (answer, late) => openCreated(answer, late, 'Your new conversation')
  )
}

/** Loads the page of history before the oldest message shown. */
export async function loadOlder(conversationId: string): Promise<void> {
  const view = state.views[conversationId]
  const oldest = view?.messages[0]
  if (!view || !view.hasData || !view.hasMore || view.loadingOlder || !oldest) return
  view.loadingOlder = true
  const loadToken = view.loadToken
  const epoch = state.recoveryEpoch
  const result = await window.odin.listMessages({ conversation_id: conversationId, before: oldest.id, limit: 100 })
  view.loadingOlder = false
  if (state.views[conversationId] !== view || view.loadToken !== loadToken || epoch !== state.recoveryEpoch) return
  if (!result.ok) return note(errorText(result))
  const known = new Set(view.messages.map((m) => m.id))
  view.messages = [...result.result.items.filter((m) => !known.has(m.id)), ...view.messages]
  view.hasMore = result.result.has_more
}

/**
 * Submits text. The core may consume a bare resume trigger instead of committing a new user message.
 * While a task runs, the composer instead steers it or queues a follow-up (explicit modes).
 * Attachments go only with a message: a steer carries text alone.
 */
export async function send(
  text: string,
  mode: ComposerMode,
  attachments: Array<{ ref: string; add_to_knowledge: boolean }> = []
): Promise<boolean> {
  const conversationId = state.activeId
  if (!conversationId) return false
  const view = state.views[conversationId]
  if (!canAct(conversationId) || !isAuthoritative(view)) {
    // Until the snapshot arrives we don't know what is running, so nothing is routed. The draft stays.
    note('Odin is still loading this conversation. Your text is still in the box.')
    return false
  }
  const running = view.running
  if (running && mode === 'steer') {
    if (attachments.length) {
      note('Attachments go with a message, not a steer. Choose Queue to send them as a follow-up.')
      return false
    }
    return steer(conversationId, running, text)
  }

  // Sending ends a search jump: the view returns to the latest messages and follows the reply, as on Discord.
  backToLatest()
  state.pending.push({
    client_submission_id: crypto.randomUUID(),
    conversation_id: conversationId,
    text,
    status: 'sending'
  })
  const pending = state.pending[state.pending.length - 1]!
  const result = await window.odin.submit({
    client_submission_id: pending.client_submission_id,
    conversation_id: conversationId,
    text,
    ...(attachments.length ? { attachments } : {})
  })
  if (result.ok) {
    removePending(pending.client_submission_id)
    if (result.result.disposition !== 'accepted') note(`Not sent: ${result.result.disposition}`)
    return result.result.disposition === 'accepted'
  }
  if (isUnknownOutcome(result.error)) {
    // The core may have admitted it. Keep it visible; the same ID is reconciled when the receipt arrives.
    pending.status = 'awaiting-receipt'
    return true
  }
  removePending(pending.client_submission_id)
  note(`Not sent: ${result.error.message}`)
  return false
}

async function steer(conversationId: string, running: RunningRequest, text: string): Promise<boolean> {
  const item = addControl({
    control_command_id: crypto.randomUUID(),
    kind: 'steer',
    conversation_id: conversationId,
    request_id: running.request_id,
    generation: running.generation,
    text,
    status: 'sending'
  })
  const result = await window.odin.steer({
    control_command_id: item.control_command_id,
    conversation_id: conversationId,
    request_id: running.request_id,
    generation: running.generation,
    text
  })
  if (result.ok && result.result.disposition === 'queued') {
    receipted(item, 'queued')
    return true
  }
  if (!result.ok && isUnknownOutcome(result.error)) {
    // Possibly delivered: it keeps its ID and its place, and the text leaves the composer so it isn't sent twice.
    advance(item, 'awaiting-receipt')
    return true
  }
  // Definitely not used, so the text stays in the composer.
  removeControl(item.control_command_id)
  if (result.ok) note('That task had already finished, so the steer was not used. Your text is still in the box.')
  else note(`Steer not delivered: ${result.error.message}`)
  return false
}

export async function stop(): Promise<void> {
  const conversationId = state.activeId
  const view = conversationId ? state.views[conversationId] : undefined
  if (!conversationId || !canAct(conversationId) || !isAuthoritative(view) || !view.running) return
  const running = view.running
  if (stopPending(running.request_id, running.generation)) return
  const item = addControl({
    control_command_id: crypto.randomUUID(),
    kind: 'stop',
    conversation_id: conversationId,
    request_id: running.request_id,
    generation: running.generation,
    status: 'sending'
  })
  const result = await window.odin.stop({
    control_command_id: item.control_command_id,
    conversation_id: conversationId,
    request_id: running.request_id,
    generation: running.generation
  })
  if (result.ok) receipted(item, result.result.disposition)
  else if (isUnknownOutcome(result.error)) advance(item, 'awaiting-receipt')
  else {
    removeControl(item.control_command_id)
    note(`Stop not delivered: ${result.error.message}`)
  }
}

/**
 * A Stop for exactly this request and generation is unanswered, or the core's projection says one is in progress.
 * Another one would only be a duplicate. A Stop for an earlier generation never counts.
 */
export function stopPending(requestId: string, generation: number): boolean {
  const matches = (c: { kind: string; request_id: string; generation: number }): boolean =>
    c.kind === 'stop' && c.request_id === requestId && c.generation === generation
  if (state.controls.some((c) => matches(c) && UNRECEIPTED.has(c.status))) return true
  return Object.values(state.views).some((view) =>
    Object.values(view?.controls ?? {}).some((c) => matches(c) && c.status === 'requested')
  )
}

/** Steers for the running request and generation: this window's own, plus any the core reports that aren't ours. */
export function steersFor(conversationId: string, requestId: string, generation: number): SteerLine[] {
  const projected = state.views[conversationId]?.controls ?? {}
  const matches = (c: { kind: string; request_id: string; generation: number }): boolean =>
    c.kind === 'steer' && c.request_id === requestId && c.generation === generation
  const lines: SteerLine[] = state.controls.filter(matches).map((c) => ({
    control_command_id: c.control_command_id,
    text: c.text,
    status: higher(c.status, projected[c.control_command_id]?.status),
    detail: c.detail
  }))
  const own = new Set(lines.map((l) => l.control_command_id))
  for (const p of Object.values(projected)) {
    if (matches(p) && !own.has(p.control_command_id)) lines.push({ control_command_id: p.control_command_id, status: p.status })
  }
  return lines
}

export function isBusy(conversationId: string): boolean {
  const view = state.views[conversationId]
  if (isAuthoritative(view)) return Boolean(view.running || view.queued.length)
  return Boolean(state.busy[conversationId]?.length)
}

export async function setAutostart(enabled: boolean): Promise<void> {
  const result = await window.odin.setAutostart(enabled)
  if (result.ok) state.autostart = result.result.autostart
}

export function applyReceipt(receipt: LateReceipt): void {
  for (const listener of receiptListeners) listener(receipt)
  for (const [key, attempt] of Object.entries(state.resumes)) {
    if (attempt?.status !== 'unknown' || attempt.commandId !== receipt.id) continue
    if (!receipt.settled.ok && isUnknownOutcome(receipt.settled.error)) return
    state.resumes[key] = resumeAnswer(receipt.settled as Result<{ disposition: string; reason?: string }>)
    return
  }
  const command = unconfirmed.get(receipt.id)
  if (command) {
    if (!receipt.settled.ok && isUnknownOutcome(receipt.settled.error)) return
    unconfirmed.delete(receipt.id)
    command.settle(receipt.settled, true)
    return
  }
  const pending = state.pending.find((p) => p.client_submission_id === receipt.id)
  if (pending) {
    const settled = receipt.settled
    if (settled.ok && (settled.result as { disposition?: string }).disposition === 'accepted') {
      // A typed resume is admitted under the ORIGINAL request/message IDs. No new user message will arrive
      // with this submission ID. Admission itself settles the optimistic bubble, just as a direct answer does.
      removePending(receipt.id)
      return
    }
    if (!settled.ok && isUnknownOutcome(settled.error)) {
      pending.status = 'unknown'
      return
    }
    removePending(receipt.id)
    note(settled.ok ? `Not sent: ${(settled.result as { disposition?: string }).disposition}` : `Not sent: ${settled.error.message}`)
    return
  }
  const control = state.controls.find((c) => c.control_command_id === receipt.id)
  if (!control) return
  const settled = receipt.settled
  if (settled.ok) receipted(control, String((settled.result as { disposition?: string }).disposition))
  else if (isUnknownOutcome(settled.error)) advance(control, 'unknown')
  else {
    advance(control, 'not-delivered')
    control.detail = settled.error.message
  }
}

/** The core answered one of our commands: that answer is also authoritative for its conversation's projection. */
function receipted(control: ControlItem, disposition: string): void {
  advance(control, disposition)
  const view = state.views[control.conversation_id]
  if (!isAuthoritative(view)) return // the next snapshot carries it
  const current = view.controls[control.control_command_id]
  if (current) advance(current, disposition)
  else {
    view.controls[control.control_command_id] = {
      control_command_id: control.control_command_id,
      kind: control.kind,
      request_id: control.request_id,
      generation: control.generation,
      status: statusOf(disposition)
    }
  }
}

function addControl(item: ControlItem): ControlItem {
  state.controls.push(item)
  if (state.controls.length > CONTROL_LIMIT) {
    const settled = state.controls.findIndex((c) => CONTROL_RANK[c.status] === 3)
    if (settled >= 0) state.controls.splice(settled, 1)
  }
  return state.controls.find((c) => c.control_command_id === item.control_command_id)!
}

function removeControl(id: string): void {
  state.controls = state.controls.filter((c) => c.control_command_id !== id)
}

function statusOf(disposition: string): ControlStatus {
  return (disposition in CONTROL_RANK ? disposition : 'unknown') as ControlStatus
}

function higher(a: ControlStatus, b: ControlStatus | undefined): ControlStatus {
  return b !== undefined && CONTROL_RANK[b] > CONTROL_RANK[a] ? b : a
}

function advance(control: { status: ControlStatus }, next: string): void {
  const status = statusOf(next)
  if (CONTROL_RANK[status] >= CONTROL_RANK[control.status]) control.status = status
}

function removePending(id: string): void {
  state.pending = state.pending.filter((p) => p.client_submission_id !== id)
}

/** Both ordinary user messages and typed-resume failure notices settle their submission, including after recovery. */
function settleCommittedSubmission(message: Message): void {
  if ((message.role === 'user' || message.role === 'notice') && message.client_submission_id) {
    removePending(message.client_submission_id)
  }
}

/** Conversation records only move forward in revision, and a deleted one never comes back. */
function upsertConversation(conversation: Conversation, fromList = false): void {
  if (deleted.has(conversation.id)) return
  if (!fromList) learnedIn.set(conversation.id, listGeneration)
  const index = state.conversations.findIndex((c) => c.id === conversation.id)
  if (index < 0) state.conversations.push(conversation)
  else if (conversation.rev >= state.conversations[index]!.rev) state.conversations[index] = conversation
}

function trackBusy(event: CoreEvent): void {
  const conversationId = event.payload.conversation_id
  if (typeof conversationId !== 'string') return
  const requestId = String(event.payload.request_id ?? '')
  if (event.type === 'request.queued' || event.type === 'request.started') {
    const list = state.busy[conversationId] ?? []
    if (!list.includes(requestId)) state.busy[conversationId] = [...list, requestId]
  } else if (TERMINAL.has(event.type)) {
    state.busy[conversationId] = (state.busy[conversationId] ?? []).filter((id) => id !== requestId)
  }
}

export function applyEvent(event: CoreEvent): void {
  for (const listener of eventListeners) listener(event)
  const p = event.payload
  if (event.type === 'conversation.created' || event.type === 'conversation.updated') {
    const conversation = p.conversation as Conversation
    conversationSeq.set(conversation.id, event.seq)
    upsertConversation(conversation)
    if (conversation.id === state.activeId && conversation.unread > 0) void markReadIfAttentive(conversation.id)
    return
  }
  if (event.type === 'conversation.deleted') {
    conversationSeq.set(String(p.conversation_id), event.seq)
    removeConversation(String(p.conversation_id))
    return
  }
  if (event.type === 'message.committed') {
    const message = p.message as Message
    settleCommittedSubmission(message)
  }
  const jump = state.jump
  // Whatever the window holds of a file that is gone goes too, whether or not its conversation is loaded.
  if (event.type === 'artifact.unavailable') images.invalidate(String(p.ref))
  if (event.type === 'artifact.unavailable' && jump && jump.conversationId === p.conversation_id) {
    // The search window shows its own copies of messages; they lose the file too.
    const artifact = jump.items.find((m) => m.id === String(p.message_id))?.artifacts?.find((a) => a.ref === String(p.ref))
    if (artifact) artifact.available = false
  }
  if (event.type === 'control.receipt') {
    const local = state.controls.find((c) => c.control_command_id === String(p.control_command_id))
    if (local) advance(local, String(p.disposition))
  }
  if (listLoading) listHeld.push(event)
  else trackBusy(event)
  const conversationId = typeof p.conversation_id === 'string' ? p.conversation_id : null
  if (!conversationId) return
  const view = state.views[conversationId]
  if (!view) return // Not loaded: its snapshot will include this.
  if (view.status === 'loading') {
    view.held.push(event)
    return
  }
  applyToView(view, event)
}

function applyToView(view: ConversationView, event: CoreEvent): void {
  if (event.seq <= view.watermark) return
  view.watermark = event.seq
  const p = event.payload
  const requestId = String(p.request_id ?? '')
  const generation = Number(p.generation) || 0
  switch (event.type) {
    case 'message.committed': {
      const message = p.message as Message
      const index = view.messages.findIndex((m) => m.id === message.id)
      if (index >= 0) view.messages[index] = message
      else view.messages.push(message)
      // The real core's queued event carries a request binding, not a message ID.
      // A replay may also deliver that event before this committed message.
      if (message.role === 'user' && message.request_id) {
        const queued = view.queued.find((q) => q.request_id === message.request_id)
        if (queued) queued.message_id = message.id
      }
      return
    }
    case 'request.queued':
      if (view.running?.request_id !== requestId && !view.queued.some((q) => q.request_id === requestId)) {
        const messageId = view.messages.find((m) => m.role === 'user' && m.request_id === requestId)?.id
        view.queued.push({ request_id: requestId, generation, message_id: String(p.message_id ?? messageId ?? '') })
      }
      return
    case 'request.started':
      view.queued = view.queued.filter((q) => q.request_id !== requestId)
      view.running = { request_id: requestId, generation, started_at: event.at }
      return
    case 'tool.started': {
      if (!view.tools[requestId]) view.tools[requestId] = []
      const list = view.tools[requestId]!
      const invocationId = String(p.invocation_id)
      if (list.some((t) => t.invocation_id === invocationId)) return
      list.push({
        invocation_id: invocationId,
        tool: String(p.tool),
        target: typeof p.target === 'string' ? p.target : undefined,
        summary: String(p.summary ?? '')
      })
      return
    }
    case 'tool.settled': {
      const entry = view.tools[requestId]?.find((t) => t.invocation_id === String(p.invocation_id))
      if (!entry) return
      entry.outcome = p.outcome as ToolEntry['outcome']
      entry.exit_code = typeof p.exit_code === 'number' ? p.exit_code : undefined
      entry.duration_ms = typeof p.duration_ms === 'number' ? p.duration_ms : undefined
      return
    }
    case 'control.receipt': {
      const id = String(p.control_command_id)
      const current = view.controls[id]
      if (current) advance(current, String(p.disposition))
      else {
        view.controls[id] = {
          control_command_id: id,
          kind: p.kind === 'stop' ? 'stop' : 'steer',
          request_id: requestId,
          generation,
          status: statusOf(String(p.disposition))
        }
      }
      return
    }
    case 'artifact.unavailable': {
      const message = view.messages.find((m) => m.id === String(p.message_id))
      const artifact = message?.artifacts?.find((a) => a.ref === String(p.ref))
      if (artifact) artifact.available = false
      return
    }
    case 'effects.resolved': {
      const remaining = Number(p.remaining) || 0
      const index = view.unresolved.findIndex((o) => o.request_id === requestId && o.generation === generation)
      if (index < 0) return
      if (remaining <= 0) view.unresolved.splice(index, 1)
      else view.unresolved[index]!.unknown_effects = remaining
      return
    }
    default: {
      if (!TERMINAL.has(event.type)) return
      if (view.running?.request_id === requestId) view.running = null
      view.queued = view.queued.filter((q) => q.request_id !== requestId)
      const outcome: TerminalOutcome = {
        request_id: requestId,
        generation,
        outcome: event.type.slice('request.'.length) as TerminalKind,
        unknown_effects: Number(p.unknown_effects) || 0,
        at: event.at
      }
      view.recent.push(outcome)
      if (view.recent.length > RECENT_LIMIT) view.recent.splice(0, view.recent.length - RECENT_LIMIT)
      if (outcome.unknown_effects > 0 && !view.unresolved.some((o) => o.request_id === requestId && o.generation === generation)) {
        view.unresolved.push({ ...outcome })
      }
    }
  }
}

/** A conversation's preserved request: its latest outcome was interrupted or suspended, and nothing runs after it. */
export interface ResumeTarget {
  outcome: TerminalOutcome
  /** Why it can't resume, when its effects are unknown. The core makes the final decision. */
  blocked: string | null
}

export function resumeTarget(view: ConversationView | undefined): ResumeTarget | null {
  if (!view || view.running || view.queued.length) return null
  const last = view.recent[view.recent.length - 1]
  if (!last || (last.outcome !== 'interrupted' && last.outcome !== 'suspended')) return null
  // `unresolved` is the authority: an entry leaves it only when the effects are reconciled (effects.resolved).
  const unknown = view.unresolved.some((o) => o.request_id === last.request_id && o.generation === last.generation)
  return {
    outcome: last,
    blocked: unknown ? "Odin may have changed something it couldn't confirm, so it won't carry on until that is reconciled." : null
  }
}

export function resumeKey(outcome: TerminalOutcome): string {
  return `${outcome.request_id}:${outcome.generation}`
}

function resumeAnswer(result: Result<{ disposition: string; reason?: string }>): ResumeState {
  if (!result.ok) return { status: 'failed', reason: errorText(result) }
  if (result.result.disposition === 'rejected') return { status: 'rejected', reason: result.result.reason ?? 'Odin declined to resume it.' }
  return { status: 'admitted' }
}

/**
 * Asks the core to carry on with exactly this preserved request. One attempt; the core decides. An attempt with no
 * answer stays under its own command until its receipt arrives, so it is never sent again under a new one.
 */
export async function resume(conversationId: string, outcome: TerminalOutcome): Promise<void> {
  const key = resumeKey(outcome)
  const status = state.resumes[key]?.status
  if (!canAct(conversationId) || status === 'sending' || status === 'admitted' || status === 'unknown') return
  state.resumes[key] = { status: 'sending' }
  const commandId = crypto.randomUUID()
  const result = await window.odin.resumeRequest({
    control_command_id: commandId,
    conversation_id: conversationId,
    request_id: outcome.request_id,
    generation: outcome.generation
  })
  if (!result.ok && isUnknownOutcome(result.error)) state.resumes[key] = { status: 'unknown', commandId }
  else state.resumes[key] = resumeAnswer(result)
}

export function isMuted(conversationId: string): boolean {
  return Boolean(state.notifications?.muted.includes(conversationId))
}

/** Mutes or unmutes one conversation's notifications. Its unread count still shows. */
export async function setMuted(conversationId: string, muted: boolean): Promise<void> {
  const result = await window.odin.setConversationMuted({ conversation_id: conversationId, muted })
  if (result.ok) state.notifications = result.result.notifications
  else note(errorText(result))
}

