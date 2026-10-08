import { describe, expect, it, vi } from 'vitest'
import { IPC, type OdinApi } from '../src/shared/api'

const bridge = vi.hoisted(() => ({ invoke: vi.fn(), expose: vi.fn() }))
vi.mock('electron', () => ({ ipcRenderer: { invoke: bridge.invoke }, contextBridge: { exposeInMainWorld: bridge.expose } }))

describe('cleanup preload bridge', () => {
  it('exposes only a named acknowledgment method with a token payload', async () => {
    await import('../src/preload/index')
    const [name, api] = bridge.expose.mock.calls[0] as [string, OdinApi]
    expect(name).toBe('odin')
    const result = { ok: true, result: { cleanupWarning: null } }
    bridge.invoke.mockResolvedValueOnce(result)
    expect(await api.acknowledgeCleanup('notice-1')).toBe(result)
    expect(bridge.invoke).toHaveBeenCalledExactlyOnceWith(IPC.acknowledgeCleanup, { id: 'notice-1' })
  })
})

describe('local app preload bridge', () => {
  it('exposes only named argument-free operations with strict empty IPC payloads', async () => {
    await import('../src/preload/index')
    const [, api] = bridge.expose.mock.calls[0] as [string, OdinApi]
    for (const name of ['getDesktopInfo', 'openSettingsFolder', 'exitOdin'] as const) {
      bridge.invoke.mockClear()
      const result = { ok: false, error: { code: 'capability_unavailable', message: 'Unavailable' } }
      bridge.invoke.mockResolvedValueOnce(result)
      // Extra runtime JS arguments must not become general paths, commands or diagnostics.
      expect(await (api[name] as (...args: unknown[]) => Promise<unknown>)({ path: '/private', cmd: 'exit' })).toBe(result)
      expect(bridge.invoke).toHaveBeenCalledExactlyOnceWith(IPC[name], {})
    }
    for (const name of ['ipcRenderer', 'openPath', 'openExternal', 'command', 'diagnostics']) {
      expect((api as unknown as Record<string, unknown>)[name]).toBeUndefined()
    }
  })
})
