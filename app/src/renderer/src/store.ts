// Window state. Reply text shown here is always committed text (D9).
//
// Consistency rules (docs/design/protocol.md, delivery rules):
// - A conversation view is replaced only by a snapshot, and then advanced only by events above its watermark.
// - While a snapshot is in flight, that conversation's events are held and replayed above the watermark when it
//   arrives. The answer to a superseded snapshot request is dropped.
// - A reset discards every view: the interval it covers is unknown, never empty.
// - Stop and Steer only ever target the running request. Queued follow-ups are tracked separately.
// - A command without a receipt has an unknown outcome, never a failure. It keeps its ID, and the late receipt or the
//   core's events settle it.
import { reactive } from 'vue'
import type {
  AppState,
  ControlRecord,
  Conversation,
  ConversationSnapshot,
  CoreError,
  CoreEvent,
  LateReceipt,
  Message,
  QueuedRequest,
  Result,
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

export interface ControlItem {
  control_command_id: string
  kind: 'stop' | 'steer'
  conversation_id: string
  request_id: string
  text?: string
  status: ControlStatus
  detail?: string
}

export interface ConversationView {
  status: 'loading' | 'ready'
  hasData: boolean
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
  tools: Record<string, ToolEntry[]>
}

export type ComposerMode = 'steer' | 'queue'

const RECENT_LIMIT = 20
const CONTROL_LIMIT = 200

export const state = reactive({
  app: { link: 'starting', coreInstanceId: null, noTray: false, unreceipted: 0 } as AppState,
  loaded: false,
  conversations: [] as Conversation[],
  activeId: null as string | null,
  views: {} as Record<string, ConversationView | undefined>,
  /** Requests queued or running per conversation, from events: the sidebar's view of conversations not loaded. */
  busy: {} as Record<string, string[] | undefined>,
  pending: [] as PendingSubmission[],
  controls: [] as ControlItem[],
  notice: '',
  autostart: false
})

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

function note(text: string): void {
  state.notice = text
}

function errorText(result: Result<unknown>): string {
  return result.ok ? '' : result.error.message
}

/** No receipt, or a receipt that says the outcome is unknown: the command may have been admitted. */
function isUnknownOutcome(error: CoreError): boolean {
  return error.code === 'no_receipt' || error.disposition === 'outcome_unknown'
}

export async function init(): Promise<void> {
  window.odin.onAppState((app) => {
    const becameReady = app.link === 'ready' && (state.app.link !== 'ready' || app.coreInstanceId !== state.app.coreInstanceId)
    state.app = app
    if (becameReady) void loadAll()
  })
  window.odin.onEvent(applyEvent)
  window.odin.onReceipt(applyReceipt)
  window.odin.onReset(() => void resetViews())
  const app = await window.odin.getAppState()
  if (app) state.app = app
  const settings = await window.odin.getSettings()
  if (settings.ok) state.autostart = settings.result.autostart
  if (state.app.link === 'ready') await loadAll()
}

let loadAllInFlight: Promise<void> | null = null

function loadAll(): Promise<void> {
  loadAllInFlight ??= loadAllOnce().finally(() => {
    loadAllInFlight = null
  })
  return loadAllInFlight
}

async function loadAllOnce(): Promise<void> {
  const listed = await window.odin.listConversations()
  if (!listed.ok) return note(errorText(listed))
  for (const conversation of listed.result.items) upsertConversation(conversation)
  if (state.conversations.length === 0) {
    const created = await window.odin.createConversation({ title: 'Chat' })
    if (!created.ok) return note(errorText(created))
    upsertConversation(created.result.conversation)
  }
  if (!state.activeId || !state.conversations.some((c) => c.id === state.activeId)) {
    state.activeId = state.conversations[0]?.id ?? null
  }
  if (state.activeId) await loadConversation(state.activeId)
  state.loaded = true
}

function viewFor(conversationId: string): ConversationView {
  if (!state.views[conversationId]) {
    state.views[conversationId] = {
      status: 'loading',
      hasData: false,
      watermark: 0,
      loadToken: 0,
      held: [],
      messages: [],
      hasMore: false,
      loadingOlder: false,
      running: null,
      queued: [],
      recent: [],
      tools: {}
    }
  }
  return state.views[conversationId]!
}

/** Rebuilds a conversation view from the core's authoritative snapshot, holding events until it applies. */
export async function loadConversation(conversationId: string): Promise<void> {
  const view = viewFor(conversationId)
  const token = ++view.loadToken
  view.status = 'loading'
  const result = await window.odin.snapshotConversation({ conversation_id: conversationId })
  if (state.views[conversationId] !== view || view.loadToken !== token) return
  if (!result.ok) {
    note(errorText(result))
    if (view.hasData) releaseHeld(view)
    else state.views[conversationId] = undefined
    return
  }
  applySnapshot(conversationId, view, result.result)
}

function applySnapshot(conversationId: string, view: ConversationView, snapshot: ConversationSnapshot): void {
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
  view.tools = Object.fromEntries(Object.entries(snapshot.tools).map(([id, entries]) => [id, entries.map((e) => ({ ...e }))]))
  view.watermark = watermark
  view.hasData = true
  upsertConversation(snapshot.conversation)
  state.busy[conversationId] = [
    ...(snapshot.running ? [snapshot.running.request_id] : []),
    ...snapshot.queued.map((q) => q.request_id)
  ]
  for (const record of snapshot.controls) mergeControl(conversationId, record)
  for (const message of view.messages) {
    if (message.role === 'user' && message.client_submission_id) removePending(message.client_submission_id)
  }
  releaseHeld(view)
}

function releaseHeld(view: ConversationView): void {
  const held = [...view.held].sort((a, b) => a.seq - b.seq)
  view.held = []
  view.status = 'ready'
  for (const event of held) applyToView(view, event)
}

/** The core couldn't replay the interval since our cursor, so nothing in the current views can be trusted. */
async function resetViews(): Promise<void> {
  for (const view of Object.values(state.views)) if (view) view.loadToken += 1
  state.views = {}
  state.busy = {}
  // A load already in flight may have read the old views; run a fresh one after it.
  if (loadAllInFlight) await loadAllInFlight.catch(() => undefined)
  await loadAll()
}

export async function select(conversationId: string): Promise<void> {
  state.activeId = conversationId
  const view = state.views[conversationId]
  if (!view || (!view.hasData && view.status !== 'loading')) await loadConversation(conversationId)
}

export async function newConversation(): Promise<void> {
  const created = await window.odin.createConversation({ title: 'New chat' })
  if (!created.ok) return note(errorText(created))
  upsertConversation(created.result.conversation)
  await select(created.result.conversation.id)
}

/** Loads the page of history before the oldest message shown. */
export async function loadOlder(conversationId: string): Promise<void> {
  const view = state.views[conversationId]
  const oldest = view?.messages[0]
  if (!view || !view.hasData || !view.hasMore || view.loadingOlder || !oldest) return
  view.loadingOlder = true
  const result = await window.odin.listMessages({ conversation_id: conversationId, before: oldest.id, limit: 100 })
  view.loadingOlder = false
  if (state.views[conversationId] !== view) return
  if (!result.ok) return note(errorText(result))
  const known = new Set(view.messages.map((m) => m.id))
  view.messages = [...result.result.items.filter((m) => !known.has(m.id)), ...view.messages]
  view.hasMore = result.result.has_more
}

/** Sends a new message. While a task runs, the composer instead steers it or queues a follow-up (explicit modes). */
export async function send(text: string, mode: ComposerMode): Promise<boolean> {
  const conversationId = state.activeId
  if (!conversationId) return false
  const running = state.views[conversationId]?.running
  if (running && mode === 'steer') return steer(conversationId, running, text)

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
    text
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
    advanceControl(item, 'queued')
    return true
  }
  if (!result.ok && isUnknownOutcome(result.error)) {
    // Possibly delivered: it keeps its ID and its place, and the text leaves the composer so it isn't sent twice.
    advanceControl(item, 'awaiting-receipt')
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
  const running = conversationId ? state.views[conversationId]?.running : null
  if (!conversationId || !running || stopPending(running.request_id)) return
  const item = addControl({
    control_command_id: crypto.randomUUID(),
    kind: 'stop',
    conversation_id: conversationId,
    request_id: running.request_id,
    status: 'sending'
  })
  const result = await window.odin.stop({
    control_command_id: item.control_command_id,
    conversation_id: conversationId,
    request_id: running.request_id,
    generation: running.generation
  })
  if (result.ok) advanceControl(item, result.result.disposition)
  else if (isUnknownOutcome(result.error)) advanceControl(item, 'awaiting-receipt')
  else {
    removeControl(item.control_command_id)
    note(`Stop not delivered: ${result.error.message}`)
  }
}

/** A Stop for this request is on its way or accepted, so another one would only be a duplicate. */
export function stopPending(requestId: string): boolean {
  return state.controls.some(
    (c) =>
      c.kind === 'stop' &&
      c.request_id === requestId &&
      (c.status === 'sending' || c.status === 'awaiting-receipt' || c.status === 'unknown' || c.status === 'requested')
  )
}

export function steersFor(requestId: string): ControlItem[] {
  return state.controls.filter((c) => c.kind === 'steer' && c.request_id === requestId)
}

export function isBusy(conversationId: string): boolean {
  const view = state.views[conversationId]
  if (view?.hasData) return Boolean(view.running || view.queued.length)
  return Boolean(state.busy[conversationId]?.length)
}

export async function setAutostart(enabled: boolean): Promise<void> {
  const result = await window.odin.setAutostart(enabled)
  if (result.ok) state.autostart = result.result.autostart
}

function applyReceipt(receipt: LateReceipt): void {
  const pending = state.pending.find((p) => p.client_submission_id === receipt.id)
  if (pending) {
    const settled = receipt.settled
    if (settled.ok && (settled.result as { disposition?: string }).disposition === 'accepted') return
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
  if (settled.ok) advanceControl(control, String((settled.result as { disposition?: string }).disposition))
  else if (isUnknownOutcome(settled.error)) advanceControl(control, 'unknown')
  else {
    advanceControl(control, 'not-delivered')
    control.detail = settled.error.message
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

function advanceControl(control: ControlItem, next: string): void {
  const status = (next in CONTROL_RANK ? next : 'unknown') as ControlStatus
  if (CONTROL_RANK[status] >= CONTROL_RANK[control.status]) control.status = status
}

function mergeControl(conversationId: string, record: ControlRecord): void {
  const known = state.controls.find((c) => c.control_command_id === record.control_command_id)
  const item =
    known ??
    addControl({
      control_command_id: record.control_command_id,
      kind: record.kind,
      conversation_id: conversationId,
      request_id: record.request_id,
      status: 'awaiting-receipt'
    })
  advanceControl(item, record.disposition)
}

function removePending(id: string): void {
  state.pending = state.pending.filter((p) => p.client_submission_id !== id)
}

/** Conversation records only move forward in revision. */
function upsertConversation(conversation: Conversation): void {
  const index = state.conversations.findIndex((c) => c.id === conversation.id)
  if (index < 0) state.conversations.push(conversation)
  else if (conversation.rev >= state.conversations[index]!.rev) state.conversations[index] = conversation
}

function trackBusy(event: CoreEvent, conversationId: string): void {
  const requestId = String(event.payload.request_id ?? '')
  if (event.type === 'request.queued' || event.type === 'request.started') {
    const list = state.busy[conversationId] ?? []
    if (!list.includes(requestId)) state.busy[conversationId] = [...list, requestId]
  } else if (TERMINAL.has(event.type)) {
    state.busy[conversationId] = (state.busy[conversationId] ?? []).filter((id) => id !== requestId)
  }
}

export function applyEvent(event: CoreEvent): void {
  const p = event.payload
  if (event.type === 'conversation.created' || event.type === 'conversation.updated') {
    upsertConversation(p.conversation as Conversation)
    return
  }
  if (event.type === 'message.committed') {
    const message = p.message as Message
    if (message.role === 'user' && message.client_submission_id) removePending(message.client_submission_id)
  }
  if (event.type === 'control.receipt') applyControlReceipt(p)
  const conversationId = typeof p.conversation_id === 'string' ? p.conversation_id : null
  if (!conversationId) return
  trackBusy(event, conversationId)
  const view = state.views[conversationId]
  if (!view) return // Not loaded: its snapshot will include this.
  if (view.status === 'loading') {
    view.held.push(event)
    return
  }
  applyToView(view, event)
}

function applyControlReceipt(p: Record<string, unknown>): void {
  const id = String(p.control_command_id)
  let item = state.controls.find((c) => c.control_command_id === id)
  if (!item) {
    if (typeof p.conversation_id !== 'string' || typeof p.request_id !== 'string') return
    item = addControl({
      control_command_id: id,
      kind: p.kind === 'stop' ? 'stop' : 'steer',
      conversation_id: p.conversation_id,
      request_id: p.request_id,
      status: 'awaiting-receipt'
    })
  }
  advanceControl(item, String(p.disposition))
}

function applyToView(view: ConversationView, event: CoreEvent): void {
  if (event.seq <= view.watermark) return
  view.watermark = event.seq
  const p = event.payload
  const requestId = String(p.request_id ?? '')
  switch (event.type) {
    case 'message.committed': {
      const message = p.message as Message
      const index = view.messages.findIndex((m) => m.id === message.id)
      if (index >= 0) view.messages[index] = message
      else view.messages.push(message)
      return
    }
    case 'request.queued':
      if (view.running?.request_id !== requestId && !view.queued.some((q) => q.request_id === requestId)) {
        view.queued.push({
          request_id: requestId,
          generation: Number(p.generation) || 0,
          message_id: String(p.message_id ?? '')
        })
      }
      return
    case 'request.started':
      view.queued = view.queued.filter((q) => q.request_id !== requestId)
      view.running = { request_id: requestId, generation: Number(p.generation) || 0, started_at: event.at }
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
    default:
      if (!TERMINAL.has(event.type)) return
      if (view.running?.request_id === requestId) view.running = null
      view.queued = view.queued.filter((q) => q.request_id !== requestId)
      view.recent.push({
        request_id: requestId,
        generation: Number(p.generation) || 0,
        outcome: event.type.slice('request.'.length) as TerminalKind,
        unknown_effects: Number(p.unknown_effects) || 0,
        at: event.at
      })
      if (view.recent.length > RECENT_LIMIT) view.recent.splice(0, view.recent.length - RECENT_LIMIT)
  }
}
