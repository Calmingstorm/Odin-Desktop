import { beforeEach, describe, expect, it, vi } from 'vitest'
import { inspectPackagedState } from '../src/main/package-state'

const mocked = vi.hoisted(() => ({ exec: vi.fn(), exists: vi.fn(() => true) }))
vi.mock('node:child_process', () => ({ execFileSync: mocked.exec }))
vi.mock('node:fs', () => ({ existsSync: mocked.exists }))

const paths = {
  profileId: 'default', tokenPath: '/temporary/profile/ipc.token', dataDir: '/temporary/data'
} as Parameters<typeof inspectPackagedState>[0]

describe('packaged state preflight', () => {
  beforeEach(() => { mocked.exec.mockReset(); mocked.exists.mockReturnValue(true) })

  it('uses only bundled isolated inspector without core/IPC bootstrap', () => {
    inspectPackagedState(paths, '/candidate/resources', {
      PYTHONPATH: '/foreign', ODIN_DESKTOP_CORE_CMD: 'foreign'
    })
    expect(mocked.exec).toHaveBeenCalledWith('/candidate/resources/runtime/python/bin/python3', [
      '-I', '-B', '-m', 'src.desktop.package_state', '--profile', 'default',
      '--token-file', paths.tokenPath, '--data-dir', paths.dataDir
    ], expect.objectContaining({
      env: expect.objectContaining({ ODIN_DESKTOP_BUNDLE_ROOT: '/candidate/resources/runtime' }),
      timeout: 30_000
    }))
    const env = mocked.exec.mock.calls[0]![2].env
    expect(env.PYTHONPATH).toBeUndefined()
    expect(env.ODIN_DESKTOP_CORE_CMD).toBeUndefined()
  })

  it('refuses missing bundle without system/fixture execution', () => {
    mocked.exists.mockReturnValue(false)
    expect(() => inspectPackagedState(paths, '/missing', {})).toThrow('missing')
    expect(mocked.exec).not.toHaveBeenCalled()
  })

  it('refuses failed or timed-out inspection without exposing process output', () => {
    mocked.exec.mockImplementation(() => { throw new Error('secret-adjacent output') })
    expect(() => inspectPackagedState(paths, '/candidate/resources', {})).toThrow('preserved')
    try { inspectPackagedState(paths, '/candidate/resources', {}) } catch (error) {
      expect(String(error)).not.toContain('secret-adjacent')
    }
  })
})
