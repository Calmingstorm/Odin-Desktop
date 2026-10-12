import { describe, expect, it } from 'vitest'
import * as autostart from '../src/main/autostart'
import * as ownership from '../src/main/package-ownership'
import * as packageState from '../src/main/package-state'
import * as paths from '../src/main/paths'
import { currentPlatform } from '../src/main/platform'
import { linuxPlatform } from '../src/main/platform/linux'
import * as session from '../src/main/session-logout'

describe('app platform seam', () => {
  it('hands Linux today\'s functions, unchanged', () => {
    expect(currentPlatform('linux')).toBe(linuxPlatform)
    expect(linuxPlatform.name).toBe('linux')
    expect(linuxPlatform.profilePaths).toBe(paths.profilePaths)
    expect(linuxPlatform.ensureProfileDirs).toBe(paths.ensureProfileDirs)
    expect(linuxPlatform.ensureToken).toBe(paths.ensureToken)
    expect(linuxPlatform.isAutostartEnabled).toBe(autostart.isAutostartEnabled)
    expect(linuxPlatform.setAutostart).toBe(autostart.setAutostart)
    expect(linuxPlatform.inspectPackagedState).toBe(packageState.inspectPackagedState)
    expect(linuxPlatform.acquirePackagedApp).toBe(ownership.acquirePackagedApp)
    expect(linuxPlatform.admitPackagedApp).toBe(ownership.admitPackagedApp)
    expect(linuxPlatform.startSessionMonitor).toBe(session.startSessionMonitor)
    expect(linuxPlatform.installLogoutHook).toBe(session.installKdeLogoutHook)
  })

  it('keeps the Linux profile paths and engine endpoint', () => {
    const env = { HOME: '/home/fixture', XDG_RUNTIME_DIR: '/run/user/1000' }
    expect(linuxPlatform.profilePaths('work', env)).toEqual(paths.profilePaths('work', env))
    expect(linuxPlatform.profilePaths('work', env).socketPath).toBe('/run/user/1000/odin-desktop/work/core.sock')
  })

  it('refuses other systems before any profile work', () => {
    for (const system of ['darwin', 'freebsd'] as const) {
      expect(() => currentPlatform(system)).toThrow('Odin Desktop runs on Linux and Windows only')
    }
  })
})
