import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IPC } from '../src/shared/api'
import type { IpcDeps } from '../src/main/ipc'

const handlers = vi.hoisted(() => new Map<string, (event: unknown, raw?: unknown) => unknown>())
vi.mock('electron', () => ({ ipcMain: {
  handle: (channel: string, handler: (event: unknown, raw?: unknown) => unknown) => handlers.set(channel, handler)
} }))

import { registerIpc } from '../src/main/ipc'

describe('Exit admission boundary', () => {
  beforeEach(() => handlers.clear())
  function fixture() {
    let admitting = true
    const frame = { url: 'app://odin/index.html', processId: 2, routingId: 3 }
    const deps = {
      admitting: () => admitting,
      windowId: () => 1,
      mainFrame: () => frame,
      broker: { request: vi.fn(async () => ({ ok: true, result: {} })) },
      drafts: { set: vi.fn(), get: vi.fn(() => '') },
      attachments: { stagePath: vi.fn(), stageBytes: vi.fn(), cancel: vi.fn() },
      artifacts: {},
      pickFiles: vi.fn(async () => []),
      chooseSavePath: vi.fn(async () => null),
      copyText: vi.fn(),
      getSettings: vi.fn(() => ({})),
      setAutostart: vi.fn(() => ({})),
      setNotifications: vi.fn(() => ({})),
      setConversationMuted: vi.fn(() => ({})),
      appState: () => ({ link: 'ready' })
    }
    registerIpc(deps as unknown as IpcDeps)
    const event = { sender: { id: 1 }, senderFrame: frame }
    const call = async (channel: string, raw?: unknown) => handlers.get(channel)!(event, raw)
    return { deps, call, stop: () => { admitting = false } }
  }

  it('refuses local writes, picker and core calls after quiescing without invoking their handlers', async () => {
    const { deps, call, stop } = fixture()
    stop()
    for (const [channel, raw] of [
      [IPC.setDraft, { conversation_id: 'c', text: 'late draft' }],
      [IPC.setAutostart, { enabled: true }],
      [IPC.setNotifications, { previews: false }],
      [IPC.pickFiles, undefined],
      [IPC.status, undefined],
      [IPC.copyText, { text: 'late clipboard' }]
    ] as const) {
      expect(await call(channel, raw)).toEqual({ ok: false, error: {
        code: 'busy', message: 'Odin is stopping.', disposition: 'not_dispatched'
      } })
    }
    expect(deps.drafts.set).not.toHaveBeenCalled()
    expect(deps.setAutostart).not.toHaveBeenCalled()
    expect(deps.setNotifications).not.toHaveBeenCalled()
    expect(deps.pickFiles).not.toHaveBeenCalled()
    expect(deps.copyText).not.toHaveBeenCalled()
    expect(deps.broker.request).not.toHaveBeenCalled()
    expect(await call(IPC.getAppState)).toEqual({ link: 'ready' })
  })

  it('still admits ordinary requests before Exit', async () => {
    const { deps, call } = fixture()
    expect(await call(IPC.status)).toEqual({ ok: true, result: {} })
    expect(deps.broker.request).toHaveBeenCalledWith('status.get')
  })
})
