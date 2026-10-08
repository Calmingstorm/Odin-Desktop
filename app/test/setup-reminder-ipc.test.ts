import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IPC } from '../src/shared/api'
import { registerIpc, type IpcDeps } from '../src/main/ipc'

const handlers = vi.hoisted(() => new Map<string, (event: unknown, raw: unknown) => Promise<unknown>>())
vi.mock('electron', () => ({ ipcMain: { handle: (channel: string, handler: (event: unknown, raw: unknown) => Promise<unknown>) => handlers.set(channel, handler) } }))
const frame = { url: 'app://odin/index.html', processId: 10, routingId: 20 }
const event = { sender: { id: 7 }, senderFrame: frame }
function fixture(owners: Partial<IpcDeps> = {}) {
  const request = vi.fn(() => { throw new Error('Core must not own UI dismissal') })
  registerIpc({ windowId: () => 7, mainFrame: () => frame, admitting: () => true,
    broker: { request }, ...owners } as unknown as IpcDeps)
  return { request, call: (channel: string, raw: unknown = {}, sender: unknown = event) => handlers.get(channel)!(sender, raw) }
}
describe('profile-local setup reminder IPC', () => {
  beforeEach(() => handlers.clear())
  it.each([false, true])('reads and writes only the app-owned boolean %s', async (initial) => {
    let hidden = initial
    const getSetupReminderHidden = vi.fn(() => hidden)
    const setSetupReminderHidden = vi.fn((value: boolean) => { hidden = value })
    const { call, request } = fixture({ getSetupReminderHidden, setSetupReminderHidden })
    expect(await call(IPC.getSetupReminderHidden)).toEqual({ ok: true, result: { hidden: initial } })
    expect(await call(IPC.setSetupReminderHidden, { hidden: !initial })).toEqual({ ok: true, result: { hidden: !initial } })
    expect(setSetupReminderHidden).toHaveBeenCalledExactlyOnceWith(!initial)
    expect(await call(IPC.getSetupReminderHidden)).toEqual({ ok: true, result: { hidden: !initial } })
    expect(request).not.toHaveBeenCalled()
  })
  it('rejects nonboolean, extra authority, paths and malformed requests before the owner', async () => {
    const owner = vi.fn()
    const { call } = fixture({ getSetupReminderHidden: owner, setSetupReminderHidden: owner })
    for (const value of [null, false, {}, { hidden: 1 }, { hidden: 'true' }, { hidden: true, profile: 'other' }, { hidden: true, path: '/private' }]) {
      expect(await call(IPC.setSetupReminderHidden, value)).toMatchObject({ ok: false, error: { code: 'bad_request' } })
    }
    expect(await call(IPC.getSetupReminderHidden, { profile: 'other' })).toMatchObject({ ok: false, error: { code: 'bad_request' } })
    expect(owner).not.toHaveBeenCalled()
  })
  it('requires the trusted current main frame for both routes', async () => {
    const owner = vi.fn()
    const { call } = fixture({ getSetupReminderHidden: owner, setSetupReminderHidden: owner })
    for (const sender of [{ sender: { id: 8 }, senderFrame: frame }, { sender: { id: 7 }, senderFrame: { ...frame, routingId: 21 } },
      { sender: { id: 7 }, senderFrame: { ...frame, url: 'https://example.test' } }, { sender: { id: 7 }, senderFrame: null }]) {
      for (const channel of [IPC.getSetupReminderHidden, IPC.setSetupReminderHidden]) expect(await call(channel, { hidden: true }, sender)).toMatchObject({ ok: false, error: { code: 'unauthorized' } })
    }
    expect(owner).not.toHaveBeenCalled()
  })
  it('refuses both routes while exit admission is closed', async () => {
    const owner = vi.fn()
    const { call } = fixture({ admitting: () => false, getSetupReminderHidden: owner, setSetupReminderHidden: owner })
    for (const channel of [IPC.getSetupReminderHidden, IPC.setSetupReminderHidden]) expect(await call(channel, { hidden: true })).toMatchObject({ ok: false, error: { code: 'busy', disposition: 'not_dispatched' } })
    expect(owner).not.toHaveBeenCalled()
  })
  it('fails closed for missing or malformed owners and scrubs persistence exceptions', async () => {
    const absent = fixture()
    for (const channel of [IPC.getSetupReminderHidden, IPC.setSetupReminderHidden]) expect(await absent.call(channel, channel === IPC.setSetupReminderHidden ? { hidden: true } : {})).toMatchObject({ ok: false, error: { code: 'capability_unavailable' } })
    const bad = fixture({ getSetupReminderHidden: (() => 'private') as unknown as IpcDeps['getSetupReminderHidden'],
      setSetupReminderHidden: () => { throw new Error('/private/path/secret') } })
    expect(await bad.call(IPC.getSetupReminderHidden)).toEqual({ ok: false, error: { code: 'internal', message: 'Invalid setup reminder preference.' } })
    expect(await bad.call(IPC.setSetupReminderHidden, { hidden: true })).toEqual({ ok: false, error: { code: 'internal', message: 'Internal app error.' } })
  })
})
