import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'
import { IPC } from '../src/shared/api'
import { DeviceLoginBoundary } from '../src/main/device-login'
import { registerIpc, type IpcDeps } from '../src/main/ipc'

const { handlers } = vi.hoisted(() => ({ handlers: new Map<string, (event: IpcMainInvokeEvent, raw: unknown) => Promise<unknown>>() }))
vi.mock('electron', () => ({ ipcMain: { handle: (channel: string, handler: (event: IpcMainInvokeEvent, raw: unknown) => Promise<unknown>) => handlers.set(channel, handler) } }))
const event = { sender: { id: 7 }, senderFrame: { url: 'app://odin/', processId: 2, routingId: 3 } } as IpcMainInvokeEvent
let request: ReturnType<typeof vi.fn>

beforeEach(() => {
  handlers.clear()
  request = vi.fn(async () => ({ ok: true, result: { unlocked: true } }))
  registerIpc({ broker: { request }, windowId: () => 7, mainFrame: () => ({ processId: 2, routingId: 3 }),
    deviceLogin: new DeviceLoginBoundary() } as unknown as IpcDeps)
})

describe('explicit keyring Retry bridge', () => {
  it('does nothing on registration, then maps the named operation to one core command with empty params', async () => {
    expect(request).not.toHaveBeenCalled()
    expect(await handlers.get(IPC.secretsUnlock)!(event, {})).toEqual({ ok: true, result: { unlocked: true } })
    expect(request).toHaveBeenCalledExactlyOnceWith('secrets.unlock', {}, expect.any(String))
    expect(request.mock.calls[0]![2]).toMatch(/^[a-f0-9-]{36}$/)
  })

  it('rejects payloads, URLs and secret values instead of providing a generic keyring gateway', async () => {
    for (const value of [undefined, null, { path: 'codex_accounts' }, { value: 'synthetic-secret' }, { url: 'https://example.invalid' }]) {
      expect(await handlers.get(IPC.secretsUnlock)!(event, value)).toMatchObject({ ok: false, error: { code: 'bad_request' } })
    }
    expect(request).not.toHaveBeenCalled()
  })

  it('rejects another frame or window before any unlock command is sent', async () => {
    for (const changed of [
      { ...event, sender: { id: 8 } },
      { ...event, senderFrame: { ...event.senderFrame, routingId: 4 } },
      { ...event, senderFrame: { ...event.senderFrame, url: 'https://example.invalid' } }
    ]) {
      expect(await handlers.get(IPC.secretsUnlock)!(changed as IpcMainInvokeEvent, {})).toMatchObject({ ok: false, error: { code: 'unauthorized' } })
    }
    expect(request).not.toHaveBeenCalled()
  })
})
