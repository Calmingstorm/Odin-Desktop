// The narrow bridge: the window gets exactly these named methods as `window.odin`, nothing else.
// The window never receives ipcRenderer itself, Node APIs, or the core socket.
import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import { IPC, type AppState, type CoreEvent, type LateReceipt, type OdinApi, type ResetNotice } from '../shared/api'

const api: OdinApi = {
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
  getSettings: () => ipcRenderer.invoke(IPC.getSettings),
  setAutostart: (enabled) => ipcRenderer.invoke(IPC.setAutostart, { enabled }),
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
