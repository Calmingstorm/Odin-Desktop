import { describe, expect, it, vi } from 'vitest'
import { IPC, type OdinApi } from '../src/shared/api'

const bridge = vi.hoisted(() => ({ invoke: vi.fn(), expose: vi.fn() }))
vi.mock('electron', () => ({ ipcRenderer: { invoke: bridge.invoke }, contextBridge: { exposeInMainWorld: bridge.expose } }))

describe('cleanup preload bridge', () => {
  it('exposes the narrow effect acknowledgement bridge without generic IPC access', async () => {
    await import('../src/preload/index')
    const [, api] = bridge.expose.mock.calls[0] as [string, OdinApi]
    bridge.invoke.mockClear()
    const target = { control_command_id: '11111111-1111-4111-8111-111111111111', conversation_id: 'c1', request_id: 'r1', generation: 1 }
    const result = { ok: true, result: { disposition: 'already_acknowledged', remaining: 0 } }
    bridge.invoke.mockResolvedValueOnce(result)
    expect(await api.acknowledgeEffects(target)).toBe(result)
    expect(IPC.acknowledgeEffects).toBe('odin:effects:acknowledge')
    expect(bridge.invoke).toHaveBeenCalledExactlyOnceWith(IPC.acknowledgeEffects, target)
    expect((api as unknown as Record<string, unknown>).ipcRenderer).toBeUndefined()
  })
  it('exposes only a named acknowledgment method with a token payload', async () => {
    await import('../src/preload/index')
    bridge.invoke.mockClear()
    const [name, api] = bridge.expose.mock.calls[0] as [string, OdinApi]
    expect(name).toBe('odin')
    const result = { ok: true, result: { cleanupWarning: null } }
    bridge.invoke.mockResolvedValueOnce(result)
    expect(await api.acknowledgeCleanup('notice-1')).toBe(result)
    expect(bridge.invoke).toHaveBeenCalledExactlyOnceWith(IPC.acknowledgeCleanup, { id: 'notice-1' })
  })
})

describe('local app preload bridge', () => {
  it('exposes named reminder get/set methods without renderer profile paths or storage access', async () => {
    await import('../src/preload/index')
    const [, api] = bridge.expose.mock.calls[0] as [string, OdinApi]
    bridge.invoke.mockClear()
    const receipt = { ok: true, result: { hidden: true } }
    bridge.invoke.mockResolvedValueOnce(receipt)
    expect(await api.getSetupReminderHidden()).toBe(receipt)
    expect(bridge.invoke).toHaveBeenCalledExactlyOnceWith(IPC.getSetupReminderHidden, {})
    for (const hidden of [true, false]) {
      bridge.invoke.mockClear()
      bridge.invoke.mockResolvedValueOnce(receipt)
      expect(await api.setSetupReminderHidden(hidden)).toBe(receipt)
      expect(bridge.invoke).toHaveBeenCalledExactlyOnceWith(IPC.setSetupReminderHidden, { hidden })
    }
  })

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
