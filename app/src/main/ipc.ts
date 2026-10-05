// The named bridge methods. Each one validates its sender and its payload, then maps to exactly one core method.
import { ipcMain, type IpcMainInvokeEvent } from 'electron'
import type { z } from 'zod'
import {
  IPC,
  type AppState,
  type NotificationChange,
  type Result,
  type Settings,
  type StagedAttachment,
  type StagedBatch
} from '../shared/api'
import type { AttachmentManager } from './attachments'
import type { ArtifactStore } from './artifacts'
import type { Broker, Settled } from './broker'
import type { DraftStore } from './drafts'
import {
  artifactActionSchema,
  toolDetailSchema,
  toolOutputSchema,
  workControlSchema,
  workListSchema,
  copyTextSchema,
  fetchArtifactSchema,
  reportPageSchema,
  attachBytesSchema,
  attachPathsSchema,
  cancelAttachmentSchema,
  controlSchema,
  conversationRevisionSchema,
  draftGetSchema,
  draftSetSchema,
  reloadSchema,
  uploadAttachmentSchema,
  usageSchema,
  createConversationSchema,
  listMessagesSchema,
  markReadSchema,
  messagesAroundSchema,
  searchSchema,
  updateConversationSchema,
  parseRequest,
  setAutostartSchema,
  setMutedSchema,
  setNotificationsSchema,
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
  drafts: DraftStore
  attachments: AttachmentManager
  /** Opens the system file picker and returns the chosen paths. */
  pickFiles: () => Promise<string[]>
  artifacts: ArtifactStore
  /** Asks where to save a file; null when the user cancels. */
  chooseSavePath: (name: string) => Promise<string | null>
  copyText: (text: string) => void
  getSettings: () => Settings
  setAutostart: (enabled: boolean) => Settings
  setNotifications: (change: NotificationChange) => Settings
  setConversationMuted: (conversationId: string, muted: boolean) => Settings
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
  // Conversation commands carry the window's command ID, so their late receipts can be matched (store.ts).
  const command = async (method: string, { command_id: id, ...params }: { command_id: string }) =>
    fromSettled(await deps.broker.request(method, params, id))
  handle(IPC.createConversation, createConversationSchema, (v) => command('conversations.create', v))
  handle(IPC.updateConversation, updateConversationSchema, (v) => command('conversations.update', v))
  handle(IPC.deleteConversation, conversationRevisionSchema, (v) => command('conversations.delete', v))
  handle(IPC.resetContext, conversationRevisionSchema, (v) => command('conversations.reset_context', v))
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
  handle(IPC.usage, usageSchema, async (v) => fromSettled(await deps.broker.request('usage.get', v)))
  handle(IPC.reload, reloadSchema, async (v) => fromSettled(await deps.broker.request('runtime.reload', v)))
  handle(IPC.getDraft, draftGetSchema, (v) => ({ ok: true, result: { text: deps.drafts.get(v.conversation_id) } }))
  handle(IPC.setDraft, draftSetSchema, (v) => {
    deps.drafts.set(v.conversation_id, v.text)
    return { ok: true, result: { saved: true } }
  })
  const stageAll = async (paths: string[]): Promise<Result<StagedBatch>> => {
    const staged: StagedAttachment[] = []
    const errors: string[] = []
    for (const path of paths) {
      const result = await deps.attachments.stagePath(path)
      if (result.ok) staged.push(result.result)
      else errors.push(result.error.message)
    }
    return { ok: true, result: { staged, errors } }
  }
  handle(IPC.pickFiles, null, async () => stageAll(await deps.pickFiles()))
  // Only the bridge calls this, with paths Electron derived from real dropped or pasted files.
  handle(IPC.attachPaths, attachPathsSchema, (v) => stageAll(v.paths))
  handle(IPC.attachBytes, attachBytesSchema, (v) => deps.attachments.stageBytes(v.name, v.mime, Buffer.from(v.data)))
  handle(IPC.uploadAttachment, uploadAttachmentSchema, (v) => deps.attachments.upload(v.id, v.conversation_id))
  handle(IPC.cancelAttachment, cancelAttachmentSchema, (v) => {
    deps.attachments.cancel(v.id)
    return { ok: true, result: { cancelled: true } }
  })
  handle(IPC.workList, workListSchema, async (v) => fromSettled(await deps.broker.request('work.list', v)))
  handle(IPC.workControl, workControlSchema, async (v) =>
    fromSettled(await deps.broker.request('work.control', v, v.control_command_id))
  )
  handle(IPC.resumeRequest, controlSchema, async (v) =>
    fromSettled(await deps.broker.request('control.resume', v, v.control_command_id))
  )
  handle(IPC.toolDetail, toolDetailSchema, async (v) => fromSettled(await deps.broker.request('tool.detail', v)))
  handle(IPC.toolOutput, toolOutputSchema, async (v) => fromSettled(await deps.broker.request('tool.output', v)))
  handle(IPC.fetchArtifact, fetchArtifactSchema, async (v) => {
    const bytes = await deps.artifacts.fetchBytes(v.ref)
    return bytes.ok ? { ok: true, result: { data: new Uint8Array(bytes.result) } } : bytes
  })
  handle(IPC.openArtifact, artifactActionSchema, (v) => deps.artifacts.open(v.ref, v.name))
  handle(IPC.saveArtifact, artifactActionSchema, async (v) => deps.artifacts.saveAs(v.ref, await deps.chooseSavePath(v.name)))
  handle(IPC.revealArtifact, artifactActionSchema, (v) => deps.artifacts.reveal(v.ref, v.name))
  handle(IPC.reportPage, reportPageSchema, async (v) => fromSettled(await deps.broker.request('reports.page', v)))
  handle(IPC.copyText, copyTextSchema, (v) => {
    deps.copyText(v.text)
    return { ok: true, result: { copied: true } }
  })
  handle(IPC.getSettings, null, () => ({ ok: true, result: deps.getSettings() }))
  handle(IPC.setAutostart, setAutostartSchema, (v) => ({ ok: true, result: deps.setAutostart(v.enabled) }))
  handle(IPC.setNotifications, setNotificationsSchema, (v) => ({ ok: true, result: deps.setNotifications(v) }))
  handle(IPC.setConversationMuted, setMutedSchema, (v) => ({
    ok: true,
    result: deps.setConversationMuted(v.conversation_id, v.muted)
  }))

  ipcMain.handle(IPC.getAppState, (event) => (trusted(event) ? deps.appState() : null))
}
