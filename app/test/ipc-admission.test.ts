import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IPC, MANAGEMENT } from '../src/shared/api'
import type { IpcDeps } from '../src/main/ipc'

const handlers = vi.hoisted(() => new Map<string, (event: unknown, raw?: unknown) => unknown>())
vi.mock('electron', () => ({ ipcMain: {
  handle: (channel: string, handler: (event: unknown, raw?: unknown) => unknown) => handlers.set(channel, handler)
} }))

import { registerIpc } from '../src/main/ipc'

const profile = { name: 'Aaron', user: null, personalities: {} }

describe('Exit admission boundary', () => {
  beforeEach(() => handlers.clear())
  function fixture() {
    let admitting = true
    const frame = { url: 'app://odin/index.html', processId: 2, routingId: 3 }
    const deps = {
      admitting: () => admitting,
      windowId: () => 1,
      mainFrame: () => frame,
      broker: { request: vi.fn(async (_method: string, _params?: Record<string, unknown>, _commandId?: string) => ({ ok: true, result: {} })) },
      drafts: { set: vi.fn(), get: vi.fn(() => '') },
      attachments: { stagePath: vi.fn(), stageBytes: vi.fn(), cancel: vi.fn() },
      artifacts: {},
      pickFiles: vi.fn(async () => []),
      chooseSavePath: vi.fn(async () => null),
      copyText: vi.fn(),
      getSettings: vi.fn(() => ({})),
      setAutostart: vi.fn(() => ({})),
      setNotifications: vi.fn(() => ({})),
      setAppearance: vi.fn(() => ({ appearance: 'light' })),
      setConversationMuted: vi.fn(() => ({})),
      appState: () => ({ link: 'ready' }),
      displayProfile: {
        read: vi.fn(() => profile),
        setName: vi.fn(() => profile),
        setPicture: vi.fn(() => profile),
        removePicture: vi.fn(() => profile)
      }
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
      [IPC.setAppearance, { appearance: 'light' }],
      [IPC.pickFiles, undefined],
      [IPC.status, undefined],
      [IPC.copyText, { text: 'late clipboard' }],
      [IPC.setDisplayName, { name: 'late name' }]
    ] as const) {
      expect(await call(channel, raw)).toEqual({ ok: false, error: {
        code: 'busy', message: 'Odin is stopping.', disposition: 'not_dispatched'
      } })
    }
    expect(deps.drafts.set).not.toHaveBeenCalled()
    expect(deps.setAutostart).not.toHaveBeenCalled()
    expect(deps.setNotifications).not.toHaveBeenCalled()
    expect(deps.setAppearance).not.toHaveBeenCalled()
    expect(deps.pickFiles).not.toHaveBeenCalled()
    expect(deps.copyText).not.toHaveBeenCalled()
    expect(deps.displayProfile.setName).not.toHaveBeenCalled()
    expect(deps.broker.request).not.toHaveBeenCalled()
    expect(await call(IPC.getAppState)).toEqual({ link: 'ready' })
  })

  it('keeps your name and pictures in the app, refusing bad input before the store', async () => {
    const { deps, call } = fixture()
    const picture = Buffer.from('fixture').toString('base64')
    expect(await call(IPC.getDisplayProfile)).toEqual({ ok: true, result: profile })
    expect(await call(IPC.setDisplayName, { name: 'Aaron' })).toEqual({ ok: true, result: profile })
    expect(deps.displayProfile.setName).toHaveBeenCalledExactlyOnceWith('Aaron')
    expect(await call(IPC.setDisplayPicture, { target: { target: 'personality', key: 'clippy' }, png_base64: picture }))
      .toEqual({ ok: true, result: profile })
    expect(deps.displayProfile.setPicture).toHaveBeenCalledExactlyOnceWith({ target: 'personality', key: 'clippy' }, picture)
    expect(await call(IPC.removeDisplayPicture, { target: { target: 'user' } })).toEqual({ ok: true, result: profile })
    expect(deps.displayProfile.removePicture).toHaveBeenCalledExactlyOnceWith({ target: 'user' })
    for (const [channel, raw] of [
      [IPC.setDisplayName, { name: 5 }],
      [IPC.setDisplayName, { name: 'Aaron', extra: 1 }],
      [IPC.setDisplayPicture, { target: { target: 'personality' }, png_base64: picture }],
      [IPC.setDisplayPicture, { target: { target: 'personality', key: '' }, png_base64: picture }],
      [IPC.setDisplayPicture, { target: { target: 'someone' }, png_base64: picture }],
      [IPC.setDisplayPicture, { target: { target: 'user' }, png_base64: 'A'.repeat(699_053) }],
      [IPC.removeDisplayPicture, { target: { target: 'user', key: 'x' } }]
    ] as const) {
      expect(await call(channel, raw)).toMatchObject({ ok: false })
    }
    expect(deps.displayProfile.setName).toHaveBeenCalledTimes(1)
    expect(deps.displayProfile.setPicture).toHaveBeenCalledTimes(1)
    expect(deps.displayProfile.removePicture).toHaveBeenCalledTimes(1)
    expect(deps.broker.request).not.toHaveBeenCalled()
  })

  it('reports a store refusal plainly and anything else as an internal error', async () => {
    const { DisplayProfileError } = await import('../src/main/display-profile')
    const { deps, call } = fixture()
    deps.displayProfile.setName.mockImplementationOnce(() => { throw new DisplayProfileError('Use up to 40 characters on one line.') })
    expect(await call(IPC.setDisplayName, { name: 'x' })).toEqual({
      ok: false, error: { code: 'bad_request', message: 'Use up to 40 characters on one line.' }
    })
    deps.displayProfile.setName.mockImplementationOnce(() => { throw new Error('disk detail') })
    expect(await call(IPC.setDisplayName, { name: 'x' })).toEqual({
      ok: false, error: { code: 'internal', message: 'Internal app error.' }
    })
  })

  it('still admits ordinary requests before Exit', async () => {
    const { deps, call } = fixture()
    expect(await call(IPC.status)).toEqual({ ok: true, result: {} })
    expect(deps.broker.request).toHaveBeenCalledWith('status.get')
  })

  it('acknowledges only an exact bound effect target, carrying the idempotency ID through the broker', async () => {
    const { deps, call, stop } = fixture()
    const target = { control_command_id: '11111111-1111-4111-8111-111111111111', conversation_id: 'c1', request_id: 'r1', generation: 1 }
    deps.broker.request.mockResolvedValueOnce({ ok: true, result: { disposition: 'acknowledged', remaining: 0 } })
    expect(await call('odin:effects:acknowledge', target)).toEqual({ ok: true, result: { disposition: 'acknowledged', remaining: 0 } })
    expect(deps.broker.request).toHaveBeenCalledExactlyOnceWith('effects.acknowledge', target, target.control_command_id)
    for (const raw of [undefined, {}, { ...target, generation: 0 }, { ...target, generation: 1.5 },
      { ...target, control_command_id: 'not-a-uuid' }, { ...target, request_id: '' }, { ...target, replay: true }]) {
      expect(await call('odin:effects:acknowledge', raw)).toMatchObject({ ok: false })
    }
    stop()
    expect(await call('odin:effects:acknowledge', target)).toMatchObject({ ok: false, error: { disposition: 'not_dispatched' } })
    expect(deps.broker.request).toHaveBeenCalledTimes(1)
  })

  it('applies a valid theme choice locally and refuses anything else before the handler', async () => {
    const { deps, call } = fixture()
    expect(await call(IPC.setAppearance, { appearance: 'light' })).toEqual({ ok: true, result: { appearance: 'light' } })
    expect(deps.setAppearance).toHaveBeenCalledExactlyOnceWith('light')
    for (const raw of [{ appearance: 'sepia' }, { appearance: 'dark', extra: 1 }, undefined]) {
      expect(await call(IPC.setAppearance, raw)).toMatchObject({ ok: false })
    }
    expect(deps.setAppearance).toHaveBeenCalledTimes(1)
    expect(deps.broker.request).not.toHaveBeenCalled()
  })

  it('dispatches trusted-key import as a command, keeps its uncertainty ID, and refuses extra fields or quiesced input', async () => {
    const { deps, call, stop } = fixture()
    const channel = MANAGEMENT.hostsImportLegacy.channel
    deps.broker.request.mockResolvedValue({ ok: false, error: { code: 'no_receipt', message: 'No receipt yet', disposition: 'outcome_unknown' } } as never)
    const answer = await call(channel, { alias: 'old' })
    const command_id = deps.broker.request.mock.calls[0]![2]
    expect(command_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(answer).toMatchObject({ ok: false, error: { disposition: 'outcome_unknown', command_id } })
    expect(deps.broker.request).toHaveBeenCalledExactlyOnceWith('hosts.import_legacy', { alias: 'old' }, command_id)
    for (const request of [{}, { alias: 'old', tested: true }, { alias: 'old', command_id }]) {
      expect(await call(channel, request)).toMatchObject({ ok: false })
    }
    expect(deps.broker.request).toHaveBeenCalledTimes(1)
    stop()
    expect(await call(channel, { alias: 'old' })).toMatchObject({ ok: false, error: { disposition: 'not_dispatched' } })
    expect(deps.broker.request).toHaveBeenCalledTimes(1)
  })
})
