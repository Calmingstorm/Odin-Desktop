import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IPC, type AppState } from '../src/shared/api'
import type { IpcDeps } from '../src/main/ipc'

const handlers = vi.hoisted(() => new Map<string, (event: unknown, raw?: unknown) => unknown>())
vi.mock('electron', () => ({ ipcMain: {
  handle: (channel: string, handler: (event: unknown, raw?: unknown) => unknown) => handlers.set(channel, handler)
} }))
import { registerIpc } from '../src/main/ipc'

const frame = { url: 'app://odin/index.html', processId: 2, routingId: 3 }
const trusted = { sender: { id: 1 }, senderFrame: frame }
const app: AppState = { link: 'ready', coreInstanceId: 'core', noTray: false, unreceipted: 2,
  cleanupWarning: { id: 'notice-1', at: '2026-10-05T23:00:00Z', records: [{ at: '2026-10-05T22:00:00Z', reason: 'Unknown cleanup' }] } }

function fixture(available = true) {
  let admitting = true
  const acknowledge = vi.fn((_id: string): AppState => ({ ...app, cleanupWarning: null }))
  const broker = { request: vi.fn() }
  const deps = { windowId: () => 1, mainFrame: () => frame, admitting: () => admitting,
    appState: () => app, broker, ...(available ? { acknowledgeCleanup: acknowledge } : {}) }
  registerIpc(deps as unknown as IpcDeps)
  return {
    acknowledge, broker, stop: () => { admitting = false },
    call: async (raw: unknown, event: unknown = trusted) => handlers.get(IPC.acknowledgeCleanup)!(event, raw)
  }
}

describe('narrow cleanup acknowledgment IPC', () => {
  beforeEach(() => handlers.clear())

  it('passes only the current opaque token to the local archive action and returns its app state', async () => {
    const { call, acknowledge, broker } = fixture()
    expect(await call({ id: 'notice-1' })).toEqual({ ok: true, result: { ...app, cleanupWarning: null } })
    expect(acknowledge).toHaveBeenCalledExactlyOnceWith('notice-1')
    expect(broker.request).not.toHaveBeenCalled()
  })

  it.each([
    { sender: { id: 9 }, senderFrame: frame },
    { sender: { id: 1 }, senderFrame: { ...frame, url: 'https://example.com' } },
    { sender: { id: 1 }, senderFrame: { ...frame, routingId: 4 } },
    { sender: { id: 1 } }
  ])('rejects an untrusted sender or frame without invoking the archive action', async (event) => {
    const { call, acknowledge, broker } = fixture()
    expect(await call({ id: 'notice-1' }, event)).toMatchObject({ ok: false, error: { code: 'unauthorized' } })
    expect(acknowledge).not.toHaveBeenCalled()
    expect(broker.request).not.toHaveBeenCalled()
  })

  it.each([undefined, null, {}, { id: '' }, { id: '   ' }, { id: 42 }, { id: 'x'.repeat(129) },
    { id: 'notice-1', path: '/tmp/journal' }, { id: 'notice-1', method: 'cleanup' }])(
    'rejects malformed or expanded payloads before archival: %j', async (raw) => {
      const { call, acknowledge } = fixture()
      expect(await call(raw)).toMatchObject({ ok: false, error: { code: 'bad_request' } })
      expect(acknowledge).not.toHaveBeenCalled()
    }
  )

  it('refuses acknowledgment once Exit has quiesced local writes', async () => {
    const { call, acknowledge, stop } = fixture()
    stop()
    expect(await call({ id: 'notice-1' })).toMatchObject({ ok: false, error: { code: 'busy', disposition: 'not_dispatched' } })
    expect(acknowledge).not.toHaveBeenCalled()
  })

  it('rejects a stale notice token without dismissing the current warning', async () => {
    const { call, acknowledge } = fixture()
    expect(await call({ id: 'old-notice' })).toMatchObject({ ok: false, error: { code: 'conflict', disposition: 'rejected' } })
    expect(acknowledge).not.toHaveBeenCalled()
    expect(app.cleanupWarning?.id).toBe('notice-1')
  })

  it('returns unavailable with older harness dependencies, never a core fallback', async () => {
    const { call, broker } = fixture(false)
    expect(await call({ id: 'notice-1' })).toMatchObject({ ok: false, error: { code: 'unavailable' } })
    expect(broker.request).not.toHaveBeenCalled()
  })

  it('contains archival failure, does not expose internals, and leaves the notice unchanged', async () => {
    const { call, acknowledge, broker } = fixture()
    acknowledge.mockImplementation(() => { throw new Error('private archive path') })
    expect(await call({ id: 'notice-1' })).toEqual({ ok: false, error: { code: 'internal', message: 'Internal app error.' } })
    expect(app.cleanupWarning?.id).toBe('notice-1')
    expect(broker.request).not.toHaveBeenCalled()
  })
})
