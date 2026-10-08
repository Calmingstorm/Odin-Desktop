import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IPC, type DesktopInfo } from '../src/shared/api'
import { registerIpc, type IpcDeps } from '../src/main/ipc'

const handlers = vi.hoisted(() => new Map<string, (event: unknown, raw: unknown) => Promise<unknown>>())
vi.mock('electron', () => ({ ipcMain: {
  handle: (channel: string, handler: (event: unknown, raw: unknown) => Promise<unknown>) => handlers.set(channel, handler)
} }))

const desktopInfo: DesktopInfo = {
  appVersion: '1.0.0', electronVersion: '44.5.1', chromiumVersion: '150.0.0.0', nodeVersion: '24.0.0',
  platform: 'linux', architecture: 'x64', license: 'MIT', packaged: false
}
const channels = [IPC.getDesktopInfo, IPC.openSettingsFolder, IPC.exitOdin]
const frame = { url: 'app://odin/index.html', processId: 10, routingId: 20 }
const event = { sender: { id: 7 }, senderFrame: frame }
const unavailable = { ok: false, error: {
  code: 'capability_unavailable', message: 'This app capability is unavailable.', disposition: 'not_dispatched'
} }

function fixture(owners: Partial<IpcDeps> = {}) {
  const forbidden = vi.fn(() => { throw new Error('Local app operation reached core or a writable dependency') })
  const deps = {
    windowId: () => 7, mainFrame: () => frame, admitting: () => true,
    broker: { request: forbidden }, drafts: { set: forbidden }, artifacts: { open: forbidden },
    pickFiles: forbidden, copyText: forbidden, setAutostart: forbidden, setNotifications: forbidden,
    ...owners
  } as unknown as IpcDeps
  registerIpc(deps)
  const call = (channel: string, payload: unknown = {}, sender: unknown = event) => handlers.get(channel)!(sender, payload)
  return { call, forbidden }
}

describe('local app IPC boundary', () => {
  beforeEach(() => handlers.clear())

  it('projects only DesktopInfo, opens through its fixed owner, and accepts only the exit scheduler', async () => {
    const getDesktopInfo = vi.fn(() => ({ ...desktopInfo,
      configDir: '/private/profile', argv: ['secret'], env: { TOKEN: 'secret' }, config: { api_key: 'secret' },
      diagnostics: { credential: 'secret' } }))
    const openSettingsFolder = vi.fn(async () => '')
    const exitOdin = vi.fn()
    const { call, forbidden } = fixture({ getDesktopInfo, openSettingsFolder, exitOdin })
    expect(await call(IPC.getDesktopInfo)).toEqual({ ok: true, result: desktopInfo })
    expect(await call(IPC.openSettingsFolder)).toEqual({ ok: true, result: { opened: true } })
    expect(await call(IPC.exitOdin)).toEqual({ ok: true, result: { accepted: true } })
    for (const owner of [getDesktopInfo, openSettingsFolder, exitOdin]) expect(owner).toHaveBeenCalledExactlyOnceWith()
    expect(forbidden).not.toHaveBeenCalled()
    for (const channel of ['odin:open-path', 'odin:open', 'odin:command', 'odin:diagnostics']) expect(handlers.has(channel)).toBe(false)
  })

  it('reports absent optional owners without affecting existing IPC fixtures', async () => {
    const { call, forbidden } = fixture()
    for (const channel of channels) expect(await call(channel)).toEqual(unavailable)
    expect(forbidden).not.toHaveBeenCalled()
  })

  it('delivers acceptance before the owner-scheduled shutdown callback runs', async () => {
    const shutdown = vi.fn()
    const exitOdin = vi.fn(() => { setImmediate(shutdown) })
    const { call } = fixture({ exitOdin })
    expect(await call(IPC.exitOdin)).toEqual({ ok: true, result: { accepted: true } })
    expect(exitOdin).toHaveBeenCalledExactlyOnceWith()
    expect(shutdown).not.toHaveBeenCalled()
    await new Promise<void>((resolve) => setImmediate(resolve))
    expect(shutdown).toHaveBeenCalledOnce()
  })

  it('requires the exact trusted main frame and webContents before invoking any owner', async () => {
    const owner = vi.fn()
    const { call } = fixture({ getDesktopInfo: owner, openSettingsFolder: owner, exitOdin: owner })
    for (const sender of [
      { sender: { id: 8 }, senderFrame: frame },
      { sender: { id: 7 }, senderFrame: { ...frame, url: 'https://example.test' } },
      { sender: { id: 7 }, senderFrame: { ...frame, url: 'app://other/index.html' } },
      { sender: { id: 7 }, senderFrame: { ...frame, routingId: 21 } },
      { sender: { id: 7 }, senderFrame: { ...frame, processId: 11 } },
      { sender: { id: 7 }, senderFrame: null }
    ]) {
      for (const channel of channels) expect(await call(channel, {}, sender)).toMatchObject({
        ok: false, error: { code: 'unauthorized', disposition: 'rejected' }
      })
    }
    expect(owner).not.toHaveBeenCalled()
  })

  it('refuses quiesced admission and missing current frame/window, even with absent owners', async () => {
    for (const owner of [
      { admitting: () => false }, { mainFrame: () => null }, { windowId: () => null }
    ]) {
      const { call } = fixture(owner)
      for (const channel of channels) expect(await call(channel)).toMatchObject({
        ok: false, error: { code: 'admitting' in owner ? 'busy' : 'unauthorized' }
      })
    }
  })

  it('strictly rejects nonempty, unknown, missing, and malformed payloads before any callback', async () => {
    const owner = vi.fn()
    fixture({ getDesktopInfo: owner, openSettingsFolder: owner, exitOdin: owner })
    for (const raw of [undefined, null, [], '', true, 42, { path: '/tmp' }, { cmd: 'exit' },
      { diagnostics: true }, { appVersion: 'forged' }, { command_id: 'forged' }]) {
      for (const channel of channels) {
        // Call the captured IPC handler directly so undefined is not defaulted by this test helper.
        expect(await handlers.get(channel)!(event, raw)).toMatchObject({ ok: false, error: { code: 'bad_request' } })
      }
    }
    expect(owner).not.toHaveBeenCalled()
    const absent = fixture()
    expect(await absent.call(IPC.openSettingsFolder, { path: '/tmp' })).toMatchObject({
      ok: false, error: { code: 'bad_request' }
    })
  })

  it('honestly reports OS failure without disclosing private raw diagnostics', async () => {
    const { call } = fixture({ openSettingsFolder: vi.fn(async () => '/private/profile: credential=secret') })
    expect(await call(IPC.openSettingsFolder)).toEqual({ ok: false, error: {
      code: 'open_failed', message: 'The settings folder could not be opened.'
    } })
    const malformed = fixture({ openSettingsFolder: vi.fn(async () => undefined) as unknown as IpcDeps['openSettingsFolder'] })
    expect(await malformed.call(IPC.openSettingsFolder)).toEqual({ ok: false, error: {
      code: 'internal', message: 'Invalid folder-open receipt.'
    } })
  })

  it('turns thrown/rejected owner errors into safe internal errors, never success receipts', async () => {
    const thrown = vi.fn(() => { throw new Error('/private/profile: api_key=secret') })
    const { call } = fixture({ getDesktopInfo: thrown, openSettingsFolder: thrown, exitOdin: thrown })
    for (const channel of channels) expect(await call(channel)).toEqual({
      ok: false, error: { code: 'internal', message: 'Internal app error.' }
    })
    const rejected = fixture({ openSettingsFolder: vi.fn(async () => { throw { secret: 'raw diagnostic' } }) })
    expect(await rejected.call(IPC.openSettingsFolder)).toEqual({
      ok: false, error: { code: 'internal', message: 'Internal app error.' }
    })
  })

  it('rejects malformed owner metadata without leaking it', async () => {
    for (const value of [null, {}, { ...desktopInfo, license: 'proprietary' },
      { ...desktopInfo, packaged: 'false' }, { ...desktopInfo, nodeVersion: undefined }]) {
      const { call } = fixture({ getDesktopInfo: vi.fn(() => value) as unknown as IpcDeps['getDesktopInfo'] })
      expect(await call(IPC.getDesktopInfo)).toEqual({ ok: false, error: {
        code: 'internal', message: 'Invalid desktop information.'
      } })
    }
  })
})
