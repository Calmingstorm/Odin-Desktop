// The narrow bridge: the window gets exactly these named methods as `window.odin`, nothing else.
// The window never receives ipcRenderer itself, Node APIs, or the core socket.
import { contextBridge, ipcRenderer, webUtils, type IpcRendererEvent } from 'electron'
import {
  IPC,
  MANAGEMENT,
  SETTINGS_SHAPED,
  type SettingsShapedApi,
  type AppState,
  type AttachmentProgress,
  type CoreEvent,
  type LateReceipt,
  type ManagementApi,
  type ManagementMethod,
  type OdinApi,
  type ResetNotice,
  type Result,
  type StagedBatch
} from '../shared/api'

// The management methods: one named method per entry of the shared table, each with its own channel.
const management = Object.fromEntries(
  (Object.keys(MANAGEMENT) as ManagementMethod[]).map((name) => [
    name,
    (params?: unknown) => ipcRenderer.invoke(MANAGEMENT[name].channel, params ?? {})
  ])
) as ManagementApi

// One named function per settings-shaped method, each on its own channel.
const settingsShaped = Object.fromEntries(
  Object.values(SETTINGS_SHAPED).map(({ call, channel }) => [call, (params: unknown) => ipcRenderer.invoke(channel, params)])
) as SettingsShapedApi

const api: OdinApi = {
  ...management,
  ...settingsShaped,
  status: () => ipcRenderer.invoke(IPC.status),
  listConversations: () => ipcRenderer.invoke(IPC.listConversations),
  createConversation: (params) => ipcRenderer.invoke(IPC.createConversation, params),
  updateConversation: (params) => ipcRenderer.invoke(IPC.updateConversation, params),
  deleteConversation: (params) => ipcRenderer.invoke(IPC.deleteConversation, params),
  resetContext: (params) => ipcRenderer.invoke(IPC.resetContext, params),
  markRead: (params) => ipcRenderer.invoke(IPC.markRead, params),
  search: (params) => ipcRenderer.invoke(IPC.search, params),
  messagesAround: (params) => ipcRenderer.invoke(IPC.messagesAround, params),
  listMessages: (params) => ipcRenderer.invoke(IPC.listMessages, params),
  snapshotConversation: (params) => ipcRenderer.invoke(IPC.snapshotConversation, params),
  submit: (params) => ipcRenderer.invoke(IPC.submit, params),
  stop: (params) => ipcRenderer.invoke(IPC.stop, params),
  steer: (params) => ipcRenderer.invoke(IPC.steer, params),
  usage: (period) => ipcRenderer.invoke(IPC.usage, { period }),
  reload: (scope) => ipcRenderer.invoke(IPC.reload, { scope }),
  getDraft: (conversationId) => ipcRenderer.invoke(IPC.getDraft, { conversation_id: conversationId }),
  setDraft: (conversationId, text) => ipcRenderer.invoke(IPC.setDraft, { conversation_id: conversationId, text }),
  pickFiles: () => ipcRenderer.invoke(IPC.pickFiles),
  // The path of each file comes from the operating system through Electron, never from the page: a File the page made
  // up has no path, so it can't name a file on disk.
  attachFiles: async (files) => {
    const paths: string[] = []
    const errors: string[] = []
    for (const file of files) {
      const path = webUtils.getPathForFile(file)
      if (path) paths.push(path)
      else errors.push(`${file.name || 'That item'} isn't a file on disk.`)
    }
    if (paths.length === 0) return { ok: true, result: { staged: [], errors } }
    const staged = (await ipcRenderer.invoke(IPC.attachPaths, { paths })) as Result<StagedBatch>
    return staged.ok ? { ok: true, result: { staged: staged.result.staged, errors: [...errors, ...staged.result.errors] } } : staged
  },
  attachBytes: (params) => ipcRenderer.invoke(IPC.attachBytes, params),
  uploadAttachment: (params) => ipcRenderer.invoke(IPC.uploadAttachment, params),
  cancelAttachment: (id) => ipcRenderer.invoke(IPC.cancelAttachment, { id }),
  onAttachmentProgress: (listener) => {
    const handler = (_event: IpcRendererEvent, progress: AttachmentProgress): void => listener(progress)
    ipcRenderer.on(IPC.attachmentProgress, handler)
    return () => {
      ipcRenderer.removeListener(IPC.attachmentProgress, handler)
    }
  },
  workList: (params) => ipcRenderer.invoke(IPC.workList, params ?? {}),
  workControl: (params) => ipcRenderer.invoke(IPC.workControl, params),
  resumeRequest: (params) => ipcRenderer.invoke(IPC.resumeRequest, params),
  toolDetail: (params) => ipcRenderer.invoke(IPC.toolDetail, params),
  toolOutput: (params) => ipcRenderer.invoke(IPC.toolOutput, params),
  fetchArtifact: (ref) => ipcRenderer.invoke(IPC.fetchArtifact, { ref }),
  checkArtifact: (ref) => ipcRenderer.invoke(IPC.checkArtifact, { ref }),
  openArtifact: (params) => ipcRenderer.invoke(IPC.openArtifact, params),
  saveArtifact: (params) => ipcRenderer.invoke(IPC.saveArtifact, params),
  revealArtifact: (params) => ipcRenderer.invoke(IPC.revealArtifact, params),
  reportPage: (params) => ipcRenderer.invoke(IPC.reportPage, params),
  copyText: (text) => ipcRenderer.invoke(IPC.copyText, { text }),
  getSettings: () => ipcRenderer.invoke(IPC.getSettings),
  setAutostart: (enabled) => ipcRenderer.invoke(IPC.setAutostart, { enabled }),
  setNotifications: (change) => ipcRenderer.invoke(IPC.setNotifications, change),
  settingsSchema: () => ipcRenderer.invoke(IPC.settingsSchema),
  settingsSet: (params) => ipcRenderer.invoke(IPC.settingsSet, params),
  imageModelIntent: (params) => ipcRenderer.invoke(IPC.imageModelIntent, params),
  secretsSet: (params) => ipcRenderer.invoke(IPC.secretsSet, params),
  secretsClear: (params) => ipcRenderer.invoke(IPC.secretsClear, params),
  editLeaf: (params) => ipcRenderer.invoke(IPC.editLeaf, params),
  codexAccounts: () => ipcRenderer.invoke(IPC.codexAccounts),
  codexActivate: (params) => ipcRenderer.invoke(IPC.codexActivate, params),
  codexLabel: (params) => ipcRenderer.invoke(IPC.codexLabel, params),
  codexRemove: (params) => ipcRenderer.invoke(IPC.codexRemove, params),
  codexLoginBegin: () => ipcRenderer.invoke(IPC.codexLoginBegin),
  codexLoginPoll: (params) => ipcRenderer.invoke(IPC.codexLoginPoll, params),
  codexOpenVerification: () => ipcRenderer.invoke(IPC.codexOpenVerification),
  setConversationMuted: (params) => ipcRenderer.invoke(IPC.setConversationMuted, params),
  onOpenConversation: (listener) => {
    const handler = (_event: IpcRendererEvent, conversationId: string): void => listener(conversationId)
    ipcRenderer.on(IPC.openConversation, handler)
    return () => ipcRenderer.removeListener(IPC.openConversation, handler)
  },
  getAppState: () => ipcRenderer.invoke(IPC.getAppState),
  onEvent: (listener) => {
    const handler = (_event: IpcRendererEvent, coreEvent: CoreEvent): void => listener(coreEvent)
    ipcRenderer.on(IPC.event, handler)
    return () => {
      ipcRenderer.removeListener(IPC.event, handler)
    }
  },
  onAppState: (listener) => {
    const handler = (_event: IpcRendererEvent, state: AppState): void => listener(state)
    ipcRenderer.on(IPC.appState, handler)
    return () => {
      ipcRenderer.removeListener(IPC.appState, handler)
    }
  },
  onReceipt: (listener) => {
    const handler = (_event: IpcRendererEvent, receipt: LateReceipt): void => listener(receipt)
    ipcRenderer.on(IPC.receipt, handler)
    return () => {
      ipcRenderer.removeListener(IPC.receipt, handler)
    }
  },
  onReset: (listener) => {
    const handler = (_event: IpcRendererEvent, reset: ResetNotice): void => listener(reset)
    ipcRenderer.on(IPC.reset, handler)
    return () => {
      ipcRenderer.removeListener(IPC.reset, handler)
    }
  }
}

contextBridge.exposeInMainWorld('odin', api)
