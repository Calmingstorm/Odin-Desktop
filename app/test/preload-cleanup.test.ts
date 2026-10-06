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
