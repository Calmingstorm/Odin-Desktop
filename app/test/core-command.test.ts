import { describe, expect, it } from 'vitest'
import { coreCommand, developmentArgv, type CoreCommandContext } from '../src/main/core-command'
import { profilePaths } from '../src/main/paths'

const paths = profilePaths('test', { HOME: '/tmp/isolated-home', XDG_RUNTIME_DIR: '/tmp/isolated-run' })
const context: CoreCommandContext = { packaged: false, resourcesPath: '/candidate/resources', appPath: '/checkout/app', env: {} }

describe('core launch selection', () => {
  it('explicitly selects the fixture only in development', () => {
    const launch = coreCommand(paths, context)
    expect(launch.command).toBe('python3')
    expect(launch.args[0]).toBe('/checkout/app/fixture-core/fixture_core.py')
    expect(launch.args).toContain(paths.tokenPath)
  })

  it('preserves literal JSON argv without shell parsing or interpolation', () => {
    const launch = coreCommand(paths, { ...context, env: { ODIN_DESKTOP_CORE_CMD: JSON.stringify(['/a path/python', '-m', 'src', 'literal;$(touch no)']) } })
    expect(launch.command).toBe('/a path/python')
    expect(launch.args.slice(0, 3)).toEqual(['-m', 'src', 'literal;$(touch no)'])
    expect(launch.args.slice(3)).toEqual(['--socket', paths.socketPath, '--token-file', paths.tokenPath, '--profile', 'test', '--data-dir', paths.dataDir])
  })

  it.each(['', 'python3 -m src', 'null', '{}', '[]', '[1]', '["python3",null]', '[" "]', '["python3", ""]', '["python3", "\\u0000"]'])('rejects malformed argv %s', (value) => {
    expect(() => developmentArgv(value)).toThrow(/ODIN_DESKTOP_CORE_CMD/)
  })

  it.each([
    ['/bin/sh', '-c', 'run core'], ['python3', '--token-file=/other/token'],
    ['python3', '--profile', 'other'], ['python3', '--password', 'do-not-log-me'],
    ['python3', '--api-key=do-not-log-me'], ['python3', 'a'.repeat(64)]
  ])('rejects shells, profile redirection and secret-bearing arguments without echoing them', (...argv) => {
    expect(() => developmentArgv(JSON.stringify(argv))).toThrow(/ODIN_DESKTOP_CORE_CMD/)
    try {
      developmentArgv(JSON.stringify(argv))
    } catch (error) {
      expect(String(error)).not.toContain('do-not-log-me')
      expect(String(error)).not.toContain('a'.repeat(64))
    }
  })

  it('never falls back to the fixture or honors overrides in a packaged build', () => {
    expect(() => coreCommand(paths, { ...context, packaged: true, env: { ODIN_DESKTOP_CORE_CMD: 'not JSON' } })).toThrow(/packaged core runtime is unavailable/)
  })

  it('hands app-owned arguments to the P4.1 resolver and excludes the development override', () => {
    const launch = coreCommand(paths, {
      ...context,
      packaged: true,
      env: { ODIN_DESKTOP_CORE_CMD: 'not JSON', HOME: '/tmp/home' },
      resolvePackaged: (resources, args, env) => {
        expect(resources).toBe('/candidate/resources')
        expect(env.ODIN_DESKTOP_CORE_CMD).toBeUndefined()
        return { command: `${resources}/runtime/python/bin/python3`, args: ['-I', '-m', 'src', ...args], env }
      }
    })
    expect(launch.command).toBe('/candidate/resources/runtime/python/bin/python3')
    expect(launch.args).toContain(paths.socketPath)
    expect(launch.env.HOME).toBe('/tmp/home')
  })
})
