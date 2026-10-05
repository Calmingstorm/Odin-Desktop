// The named bridge methods. Each one validates its sender and its payload, then maps to exactly one core method.
import { ipcMain, type IpcMainInvokeEvent } from 'electron'
import type { z } from 'zod'
import { IPC, type AppState, type Result, type Settings } from '../shared/api'
import type { Broker, Settled } from './broker'
import {
  controlSchema,
  conversationRevisionSchema,
  createConversationSchema,
  listMessagesSchema,
  markReadSchema,
  messagesAroundSchema,
  searchSchema,
  updateConversationSchema,
  parseRequest,
  setAutostartSchema,
  snapshotConversationSchema,
  steerSchema,
  submitSchema
} from './schemas'
import { isSameFrame, isTrustedSender, type FrameIdentity } from './security-policy'

export interface IpcDeps {
  broker: Broker
  windowId: () => number | null
  /** The window's top frame; requests from any other frame are refused. */
  mainFrame: () => FrameIdentity | null
  getSettings: () => Settings
  setAutostart: (enabled: boolean) => Settings
  appState: () => AppState
}

const UNTRUSTED: Result<never> = {
  ok: false,
  error: { code: 'unauthorized', message: 'Request did not come from the Odin window.', disposition: 'rejected' }
}

function fromSettled<T>(settled: Settled): Result<T> {
  return settled.ok ? { ok: true, result: settled.result as T } : settled
}

export function registerIpc(deps: IpcDeps): void {
  const trusted = (event: IpcMainInvokeEvent): boolean =>
    isTrustedSender(event.senderFrame?.url, event.sender.id, deps.windowId()) &&
    isSameFrame(event.senderFrame, deps.mainFrame())

  function handle<S extends z.ZodType>(
    channel: string,
    schema: S | null,
    handler: (value: z.infer<S>) => Promise<Result<unknown>> | Result<unknown>
  ): void {
    ipcMain.handle(channel, async (event, raw: unknown) => {
      if (!trusted(event)) return UNTRUSTED
      let value: z.infer<S> = undefined as z.infer<S>
      if (schema) {
        const parsed = parseRequest(schema, raw)
        if (!parsed.ok) return parsed
        value = parsed.value as z.infer<S>
      }
      try {
        return await handler(value)
      } catch {
        return { ok: false, error: { code: 'internal', message: 'Internal app error.' } }
      }
    })
  }

  handle(IPC.status, null, async () => fromSettled(await deps.broker.request('status.get')))
  handle(IPC.listConversations, null, async () => fromSettled(await deps.broker.request('conversations.list')))
  handle(IPC.createConversation, createConversationSchema, async (v) =>
    fromSettled(await deps.broker.request('conversations.create', v))
  )
  handle(IPC.updateConversation, updateConversationSchema, async (v) =>
    fromSettled(await deps.broker.request('conversations.update', v))
  )
  handle(IPC.deleteConversation, conversationRevisionSchema, async (v) =>
    fromSettled(await deps.broker.request('conversations.delete', v))
  )
  handle(IPC.resetContext, conversationRevisionSchema, async (v) =>
    fromSettled(await deps.broker.request('conversations.reset_context', v))
  )
  handle(IPC.markRead, markReadSchema, async (v) => fromSettled(await deps.broker.request('conversations.mark_read', v)))
  handle(IPC.search, searchSchema, async (v) => fromSettled(await deps.broker.request('search.query', v)))
  handle(IPC.messagesAround, messagesAroundSchema, async (v) =>
    fromSettled(await deps.broker.request('messages.around', v))
  )
  handle(IPC.listMessages, listMessagesSchema, async (v) =>
    fromSettled(await deps.broker.request('messages.list', { limit: 100, ...v }))
  )
  handle(IPC.snapshotConversation, snapshotConversationSchema, async (v) =>
    fromSettled(await deps.broker.request('conversation.snapshot', { limit: 100, ...v }))
  )
  // The client-generated ID doubles as the command ID, so a lost receipt is always re-sent under the same ID.
  handle(IPC.submit, submitSchema, async (v) =>
    fromSettled(await deps.broker.request('submission.send', v, v.client_submission_id))
  )
  handle(IPC.stop, controlSchema, async (v) =>
    fromSettled(await deps.broker.request('control.stop', v, v.control_command_id))
  )
  handle(IPC.steer, steerSchema, async (v) =>
    fromSettled(await deps.broker.request('control.steer', v, v.control_command_id))
  )
  handle(IPC.getSettings, null, () => ({ ok: true, result: deps.getSettings() }))
  handle(IPC.setAutostart, setAutostartSchema, (v) => ({ ok: true, result: deps.setAutostart(v.enabled) }))

  ipcMain.handle(IPC.getAppState, (event) => (trusted(event) ? deps.appState() : null))
}
