// The named bridge methods. Each one validates its sender and its payload, then maps to exactly one core method.
import { randomUUID } from 'node:crypto'
import { ipcMain, type IpcMainInvokeEvent } from 'electron'
import type { z } from 'zod'
import {
  IPC,
  MANAGEMENT,
  type ManagementMethod,
  SETTINGS_SHAPED,
  type SettingsShapedMethod,
  type AppState,
  type Appearance,
  type DesktopInfo,
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
import type { ReleaseNoticeService } from './release-notice'
import {
  acknowledgeCleanupSchema,
  artifactActionSchema,
  releaseNoticeSchema,
  toolDetailSchema,
  toolOutputSchema,
  workControlSchema,
  workListSchema,
  copyTextSchema,
  fetchArtifactSchema,
  firstRunStatusSchema,
  webhookIngressStatusSchema,
  reportPageSchema,
  attachBytesSchema,
  attachPathsSchema,
  cancelAttachmentSchema,
  controlSchema,
  conversationRevisionSchema,
  draftGetSchema,
  draftSetSchema,
  desktopInfoSchema,
  odinImportApplySchema,
  odinImportPreviewSchema,
  localAppSchema,
  setupReminderSchema,
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
  setAppearanceSchema,
  setAutostartSchema,
  setMutedSchema,
  MANAGEMENT_SCHEMAS,
  codexIndexSchema,
  codexLabelSchema,
  codexPollSchema,
  editLeafSchema,
  imageIntentSchema,
  secretClearSchema,
  secretSetSchema,
  secretUnlockSchema,
  settingsSetSchema,
  setNotificationsSchema,
  snapshotConversationSchema,
  steerSchema,
  submitSchema
} from './schemas'
import { withCommandId } from './command-id'
import { applyOdinImport, previewOdinImport, type FetchLike } from './odin-import'
import { DeviceLoginBoundary } from './device-login'
import { isSameFrame, isTrustedSender, type FrameIdentity } from './security-policy'

export interface IpcDeps {
  /** Current profile's app-owned invitation preference, independent of core health. */
  getSetupReminderHidden?: () => boolean
  setSetupReminderHidden?: (hidden: boolean) => void
  /** Main-owned runtime fields; the IPC boundary projects the explicit whitelist. */
  getDesktopInfo?: () => DesktopInfo
  /** Fixed current-profile configDir only. Returns shell.openPath's error string. */
  openSettingsFolder?: () => Promise<string>
  /** Schedules the existing bounded shutdown after the acceptance receipt is queued. */
  exitOdin?: () => void
  /** Import from Odin's HTTP client; tests inject one. Defaults to the runtime's fetch. */
  odinFetch?: FetchLike
  releases: ReleaseNoticeService
  broker: Broker
  /** Exit quiesces local app writes as well as core requests before persistence. */
  admitting?: () => boolean
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
  openVerification: (url: string) => Promise<void>
  deviceLogin: DeviceLoginBoundary
  getSettings: () => Settings
  setAutostart: (enabled: boolean) => Settings
  setNotifications: (change: NotificationChange) => Settings
  /** Applies the theme to the window and saves it with the other app preferences. */
  setAppearance: (appearance: Appearance) => Settings
  setConversationMuted: (conversationId: string, muted: boolean) => Settings
  appState: () => AppState
  /** Archives only this notice token; resource quarantine and reconciliation remain unchanged. */
  acknowledgeCleanup?: (id: string) => AppState
}

const UNTRUSTED: Result<never> = {
  ok: false,
  error: { code: 'unauthorized', message: 'Request did not come from the Odin window.', disposition: 'rejected' }
}

function fromSettled<T>(settled: Settled): Result<T> {
  return settled.ok ? { ok: true, result: settled.result as T } : settled
}

export function registerIpc(deps: IpcDeps): void {
  const deviceLogin = deps.deviceLogin
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
      if (deps.admitting && !deps.admitting()) {
        return { ok: false, error: {
          code: 'busy', message: 'Odin is stopping.', disposition: 'not_dispatched'
        } }
      }
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

  handle(IPC.status, null, async () => {
    const answer = await deps.broker.request('status.get')
    if (!answer.ok) return answer
    const raw = answer.result as Record<string, unknown> | null
    if (!raw || typeof raw !== 'object') return { ok: false, error: { code: 'internal', message: 'Invalid core status.' } }
    const projected = { ...raw }
    if (raw.first_run !== undefined) {
      const projection = firstRunStatusSchema.safeParse(raw.first_run)
      if (!projection.success) return { ok: false, error: { code: 'internal', message: 'Invalid core readiness status.' } }
      projected.first_run = projection.data
    }
    if (raw.webhook_ingress !== undefined) {
      const ingress = webhookIngressStatusSchema.safeParse(raw.webhook_ingress)
      if (!ingress.success) return { ok: false, error: { code: 'internal', message: 'Invalid webhook ingress status.' } }
      projected.webhook_ingress = ingress.data
    }
    return { ok: true, result: projected }
  })
  handle(IPC.checkReleases, releaseNoticeSchema, async () => ({ ok: true, result: await deps.releases.check() }))
  const unavailable: Result<never> = { ok: false, error: {
    code: 'capability_unavailable', message: 'This app capability is unavailable.', disposition: 'not_dispatched'
  } }
  handle(IPC.getSetupReminderHidden, localAppSchema, () => {
    if (!deps.getSetupReminderHidden) return unavailable
    const hidden = deps.getSetupReminderHidden()
    if (typeof hidden !== 'boolean') return { ok: false, error: { code: 'internal', message: 'Invalid setup reminder preference.' } }
    return { ok: true, result: { hidden } }
  })
  handle(IPC.setSetupReminderHidden, setupReminderSchema, (v) => {
    if (!deps.setSetupReminderHidden) return unavailable
    deps.setSetupReminderHidden(v.hidden)
    return { ok: true, result: { hidden: v.hidden } }
  })
  handle(IPC.getDesktopInfo, localAppSchema, () => {
    if (!deps.getDesktopInfo) return unavailable
    const info = desktopInfoSchema.safeParse(deps.getDesktopInfo())
    if (!info.success) return { ok: false, error: { code: 'internal', message: 'Invalid desktop information.' } }
    return { ok: true, result: info.data }
  })
  handle(IPC.openSettingsFolder, localAppSchema, async () => {
    if (!deps.openSettingsFolder) return unavailable
    const error = await deps.openSettingsFolder()
    // The OS may include private paths in its diagnostic. Report failure, never that text.
    if (typeof error !== 'string') return { ok: false, error: { code: 'internal', message: 'Invalid folder-open receipt.' } }
    if (error) return { ok: false, error: { code: 'open_failed', message: 'The settings folder could not be opened.' } }
    return { ok: true, result: { opened: true } }
  })
  handle(IPC.exitOdin, localAppSchema, () => {
    if (!deps.exitOdin) return unavailable
    deps.exitOdin()
    return { ok: true, result: { accepted: true } }
  })
  // Import from Odin: Odin's API is read with the user's token for this call only; writes use the core's own methods.
  const odinFetch: FetchLike = deps.odinFetch ?? ((url, init) => fetch(url, init))
  handle(IPC.odinImportPreview, odinImportPreviewSchema, (v) => previewOdinImport(v, deps.broker, odinFetch))
  handle(IPC.odinImportApply, odinImportApplySchema, (v) =>
    applyOdinImport({ url: v.url, token: v.token }, v.picks, deps.broker, odinFetch)
  )
  handle(IPC.openRelease, releaseNoticeSchema, () => deps.releases.open())
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
  handle(IPC.checkArtifact, fetchArtifactSchema, (v) => deps.artifacts.check(v.ref))
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
  handle(IPC.setAppearance, setAppearanceSchema, (v) => ({ ok: true, result: deps.setAppearance(v.appearance) }))
  // The core's settings and Codex accounts: each a named method, validated here; nothing passes through generically.
  handle(IPC.settingsSchema, null, async () => fromSettled(await deps.broker.request('settings.schema')))
  handle(IPC.settingsSet, settingsSetSchema, async (v) => {
    const id = randomUUID()
    return fromSettled(await deps.broker.request('settings.set', v, id))
  })
  // Each settings-shaped method has its own channel, with settings.set's schema, and reaches exactly that method.
  for (const method of Object.keys(SETTINGS_SHAPED) as SettingsShapedMethod[]) {
    handle(SETTINGS_SHAPED[method].channel, settingsSetSchema, async (v) => fromSettled(await deps.broker.request(method, v, randomUUID())))
  }
  handle(IPC.imageModelIntent, imageIntentSchema, async (v) => fromSettled(await deps.broker.request('models.image.intent', v, randomUUID())))
  handle(IPC.secretsSet, secretSetSchema, async (v) => {
    const id = randomUUID()
    return fromSettled(await deps.broker.request('secrets.set', v, id))
  })
  handle(IPC.secretsClear, secretClearSchema, async (v) => {
    const id = randomUUID()
    return fromSettled(await deps.broker.request('secrets.clear', v, id))
  })
  handle(IPC.secretsUnlock, secretUnlockSchema, async () =>
    fromSettled(await deps.broker.request('secrets.unlock', {}, randomUUID()))
  )
  handle(IPC.editLeaf, editLeafSchema, async (v) => {
    const id = randomUUID()
    return fromSettled(await deps.broker.request(v.method, v.params, id))
  })
  handle(IPC.codexAccounts, null, async () => fromSettled(await deps.broker.request('codex.accounts.list')))
  handle(IPC.codexActivate, codexIndexSchema, async (v) => {
    const id = randomUUID()
    return fromSettled(await deps.broker.request('codex.accounts.activate', v, id))
  })
  handle(IPC.codexLabel, codexLabelSchema, async (v) => {
    const id = randomUUID()
    return fromSettled(await deps.broker.request('codex.accounts.label', v, id))
  })
  handle(IPC.codexRemove, codexIndexSchema, async (v) => {
    const id = randomUUID()
    return fromSettled(await deps.broker.request('codex.accounts.remove', v, id))
  })
  handle(IPC.codexLoginBegin, null, async () => {
    const id = randomUUID()
    deviceLogin.clear()
    deviceLogin.track(id, 'begin')
    const result = await deps.broker.request('codex.login.begin', {}, id)
    deviceLogin.settle(id, result)
    return result.ok ? deviceLogin.begin(result.result, deps.broker.coreInstanceId) : result
  })
  handle(IPC.codexLoginPoll, codexPollSchema, async (v) => {
    const params = deviceLogin.poll(v.login_id, deps.broker.coreInstanceId)
    if (!params.ok) return params
    const id = randomUUID()
    deviceLogin.track(id, 'poll')
    const result = await deps.broker.request('codex.login.poll', params.result, id)
    deviceLogin.settle(id, result)
    if (!result.ok) return result
    return deviceLogin.pollResult(result.result)
  })
  handle(IPC.codexOpenVerification, null, async () => {
    const target = deviceLogin.verification(deps.broker.coreInstanceId)
    if (!target.ok) return target
    await deps.openVerification(target.result.url)
    return { ok: true, result: { opened: true } }
  })
  // The management domains: each named method has its own channel and schema and maps to exactly one core method.
  for (const name of Object.keys(MANAGEMENT) as ManagementMethod[]) {
    const { channel, core, command: changes } = MANAGEMENT[name]
    handle(channel, MANAGEMENT_SCHEMAS[name], async (v) => {
      const commandId = changes ? randomUUID() : undefined
      return withCommandId(fromSettled(await deps.broker.request(core, v as Record<string, unknown>, commandId)), commandId)
    })
  }
  handle(IPC.setConversationMuted, setMutedSchema, (v) => ({
    ok: true,
    result: deps.setConversationMuted(v.conversation_id, v.muted)
  }))

  handle(IPC.acknowledgeCleanup, acknowledgeCleanupSchema, ({ id }) => {
    if (!deps.acknowledgeCleanup) return { ok: false, error: {
      code: 'unavailable', message: 'Cleanup acknowledgment is unavailable.', disposition: 'not_dispatched'
    } }
    if (deps.appState().cleanupWarning?.id !== id) return { ok: false, error: {
      code: 'conflict', message: 'This cleanup notice has changed. Review the current notice before acknowledging.', disposition: 'rejected'
    } }
    return { ok: true, result: deps.acknowledgeCleanup(id) }
  })

  ipcMain.handle(IPC.getAppState, (event) => (trusted(event) ? deps.appState() : null))
}
