// Window state, built only from core events and receipts. Reply text shown here is always committed text (D9).
import { reactive } from 'vue'
import type { AppState, Conversation, CoreEvent, Message, Result } from '../../shared/api'

export interface ToolEntry {
  invocation_id: string
  tool: string
  target?: string
  summary: string
  outcome?: 'success' | 'failure' | 'unknown'
  exit_code?: number
  duration_ms?: number
}

export interface ActiveRequest {
  request_id: string
  generation: number
  state: 'queued' | 'running'
}

export interface PendingSubmission {
  client_submission_id: string
  conversation_id: string
  text: string
  status: 'sending' | 'awaiting-receipt'
}

export type ComposerMode = 'steer' | 'queue'

export const state = reactive({
  app: { link: 'starting', coreInstanceId: null, noTray: false, unreceipted: 0 } as AppState,
  loaded: false,
  conversations: [] as Conversation[],
  activeId: null as string | null,
  messages: {} as Record<string, Message[]>,
  active: {} as Record<string, ActiveRequest | undefined>,
  tools: {} as Record<string, ToolEntry[]>,
  outcome: {} as Record<string, { type: string; unknown_effects: number } | undefined>,
  pending: [] as PendingSubmission[],
  notice: '',
  autostart: false
})

function note(text: string): void {
  state.notice = text
}

function errorText(result: Result<unknown>): string {
  return result.ok ? '' : result.error.message
}

export async function init(): Promise<void> {
  window.odin.onAppState((app) => {
    state.app = app
    if (app.link === 'ready') void loadAll()
  })
  window.odin.onEvent(applyEvent)
  window.odin.onReceipt((receipt) => {
    const pending = state.pending.find((p) => p.client_submission_id === receipt.id)
    if (!pending) return
    const settled = receipt.settled
    const accepted = settled.ok && (settled.result as { disposition?: string }).disposition === 'accepted'
    if (!accepted) {
      removePending(receipt.id)
      note(settled.ok ? `Not sent: ${(settled.result as { disposition?: string }).disposition}` : `Not sent: ${settled.error.message}`)
    }
  })
  const app = await window.odin.getAppState()
  if (app) state.app = app
  const settings = await window.odin.getSettings()
  if (settings.ok) state.autostart = settings.result.autostart
  if (state.app.link === 'ready') await loadAll()
}

async function loadAll(): Promise<void> {
  const listed = await window.odin.listConversations()
  if (!listed.ok) return note(errorText(listed))
  state.conversations = listed.result.items
  if (state.conversations.length === 0) {
    const created = await window.odin.createConversation({ title: 'Chat' })
    if (!created.ok) return note(errorText(created))
    upsertConversation(created.result.conversation)
  }
  if (!state.activeId || !state.conversations.some((c) => c.id === state.activeId)) {
    state.activeId = state.conversations[0]?.id ?? null
  }
  if (state.activeId) await loadMessages(state.activeId)
  state.loaded = true
}

async function loadMessages(conversationId: string): Promise<void> {
  const listed = await window.odin.listMessages({ conversation_id: conversationId })
  if (!listed.ok) return note(errorText(listed))
  state.messages[conversationId] = listed.result.items
}

export async function select(conversationId: string): Promise<void> {
  state.activeId = conversationId
  if (!state.messages[conversationId]) await loadMessages(conversationId)
}

export async function newConversation(): Promise<void> {
  const created = await window.odin.createConversation({ title: 'New chat' })
  if (!created.ok) return note(errorText(created))
  upsertConversation(created.result.conversation)
  await select(created.result.conversation.id)
}

/** Sends a new message. While a turn runs, the composer instead steers it or queues a follow-up (explicit modes). */
export async function send(text: string, mode: ComposerMode): Promise<boolean> {
  const conversationId = state.activeId
  if (!conversationId) return false
  const active = state.active[conversationId]
  if (active && mode === 'steer') return steer(conversationId, active, text)

  const pending: PendingSubmission = {
    client_submission_id: crypto.randomUUID(),
    conversation_id: conversationId,
    text,
    status: 'sending'
  }
  state.pending.push(pending)
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
  if (result.error.code === 'no_receipt') {
    // The core may have admitted it. Keep it visible; the same ID is reconciled when the receipt arrives.
    pending.status = 'awaiting-receipt'
    note('No receipt yet. Odin will reconcile this message when the core answers; it will not be sent twice.')
    return true
  }
  removePending(pending.client_submission_id)
  note(`Not sent: ${result.error.message}`)
  return false
}

async function steer(conversationId: string, active: ActiveRequest, text: string): Promise<boolean> {
  const result = await window.odin.steer({
    control_command_id: crypto.randomUUID(),
    conversation_id: conversationId,
    request_id: active.request_id,
    generation: active.generation,
    text
  })
  if (!result.ok) {
    note(`Steer not delivered: ${result.error.message}`)
    return false
  }
  note(`Steer ${result.result.disposition}.`)
  return result.result.disposition === 'queued'
}

export async function stop(): Promise<void> {
  const conversationId = state.activeId
  const active = conversationId ? state.active[conversationId] : undefined
  if (!conversationId || !active) return
  const result = await window.odin.stop({
    control_command_id: crypto.randomUUID(),
    conversation_id: conversationId,
    request_id: active.request_id,
    generation: active.generation
  })
  note(result.ok ? `Stop ${result.result.disposition}.` : `Stop not delivered: ${result.error.message}`)
}

export async function setAutostart(enabled: boolean): Promise<void> {
  const result = await window.odin.setAutostart(enabled)
  if (result.ok) state.autostart = result.result.autostart
}

function removePending(id: string): void {
  state.pending = state.pending.filter((p) => p.client_submission_id !== id)
}

function upsertConversation(conversation: Conversation): void {
  const index = state.conversations.findIndex((c) => c.id === conversation.id)
  if (index >= 0) state.conversations[index] = conversation
  else state.conversations.push(conversation)
}

function upsertMessage(conversationId: string, message: Message): void {
  const list = (state.messages[conversationId] ??= [])
  const index = list.findIndex((m) => m.id === message.id)
  if (index >= 0) list[index] = message
  else list.push(message)
}

const TERMINAL = new Set([
  'request.completed',
  'request.failed',
  'request.cancelled',
  'request.interrupted',
  'request.suspended'
])

export function applyEvent(event: CoreEvent): void {
  const p = event.payload as Record<string, unknown>
  const conversationId = typeof p.conversation_id === 'string' ? p.conversation_id : null
  switch (event.type) {
    case 'conversation.created':
    case 'conversation.updated':
      upsertConversation(p.conversation as Conversation)
      return
    case 'message.committed': {
      if (!conversationId) return
      const message = p.message as Message
      upsertMessage(conversationId, message)
      if (message.role === 'user' && message.client_submission_id) removePending(message.client_submission_id)
      return
    }
    case 'request.queued':
    case 'request.started':
      if (!conversationId) return
      state.active[conversationId] = {
        request_id: String(p.request_id),
        generation: Number(p.generation) || 0,
        state: event.type === 'request.started' ? 'running' : 'queued'
      }
      state.outcome[conversationId] = undefined
      return
    case 'tool.started': {
      const requestId = String(p.request_id)
      const list = (state.tools[requestId] ??= [])
      list.push({
        invocation_id: String(p.invocation_id),
        tool: String(p.tool),
        target: typeof p.target === 'string' ? p.target : undefined,
        summary: String(p.summary ?? '')
      })
      return
    }
    case 'tool.settled': {
      const entry = state.tools[String(p.request_id)]?.find((t) => t.invocation_id === String(p.invocation_id))
      if (!entry) return
      entry.outcome = p.outcome as ToolEntry['outcome']
      entry.exit_code = typeof p.exit_code === 'number' ? p.exit_code : undefined
      entry.duration_ms = typeof p.duration_ms === 'number' ? p.duration_ms : undefined
      return
    }
    case 'control.receipt':
      note(`${String(p.kind)} ${String(p.disposition)}.`)
      return
    default:
      if (TERMINAL.has(event.type) && conversationId) {
        const active = state.active[conversationId]
        if (active && active.request_id === String(p.request_id)) state.active[conversationId] = undefined
        state.outcome[conversationId] = { type: event.type, unknown_effects: Number(p.unknown_effects) || 0 }
      }
  }
}
