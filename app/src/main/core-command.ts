// Main-process launch selection. The fixture is deliberately development-only.
// P4.1 plugs its verified immutable resource layout into resolvePackaged; there
// is no production fallback to PATH Python, an override, or a developer tree.
import { basename, join } from 'node:path'
import { existsSync } from 'node:fs'
import type { ProfilePaths } from './paths'

export interface CoreLaunch {
  command: string
  args: string[]
  env: NodeJS.ProcessEnv
}

export interface CoreCommandContext {
  packaged: boolean
  resourcesPath: string
  appPath: string
  env: NodeJS.ProcessEnv
  /** Packaging owns layout, bundle verification and isolated interpreter flags. */
  resolvePackaged?: (resourcesPath: string, coreArgs: string[], env: NodeJS.ProcessEnv) => CoreLaunch
}

const SHELLS = new Set(['sh', 'bash', 'dash', 'zsh', 'fish', 'ksh', 'cmd', 'cmd.exe', 'powershell', 'pwsh'])
const RESERVED = /^--(?:socket|token-file|profile|data-dir)(?:=|$)/
const SECRET_FLAG = /^--?(?:token|password|passwd|secret|api[-_]key|access[-_]token|authorization|credential)(?:=|$)/i

/** Errors intentionally do not repeat argv: it may contain a credential. */
export function developmentArgv(value: string): string[] {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    throw new Error('ODIN_DESKTOP_CORE_CMD must be a JSON argv array, not a shell command.')
  }
  if (!Array.isArray(parsed) || !parsed.length || parsed.some((part) =>
    typeof part !== 'string' || !part.trim() || /[\u0000-\u001f\u007f]/.test(part))) {
    throw new Error('ODIN_DESKTOP_CORE_CMD must contain nonempty strings without control characters.')
  }
  const argv = parsed as [string, ...string[]]
  if (SHELLS.has(basename(argv[0]).toLowerCase())) {
    throw new Error('ODIN_DESKTOP_CORE_CMD must launch the core directly, not through a shell.')
  }
  if (argv.slice(1).some((part) => RESERVED.test(part))) {
    throw new Error('ODIN_DESKTOP_CORE_CMD cannot override the app-owned profile or IPC paths.')
  }
  if (argv.some((part) => SECRET_FLAG.test(part) || /^[0-9a-f]{64}$/i.test(part) || /^Bearer\s/i.test(part))) {
    throw new Error('ODIN_DESKTOP_CORE_CMD cannot contain credentials. Use core-owned credential files.')
  }
  return argv
}

export function coreCommand(paths: ProfilePaths, context: CoreCommandContext): CoreLaunch {
  const coreArgs = ['--socket', paths.socketPath, '--token-file', paths.tokenPath, '--profile', paths.profileId, '--data-dir', paths.dataDir]
  if (context.packaged) {
    const env = { ...context.env }
    delete env.ODIN_DESKTOP_CORE_CMD
    return (context.resolvePackaged ?? packagedCoreCommand)(context.resourcesPath, coreArgs, env)
  }
  const override = context.env.ODIN_DESKTOP_CORE_CMD
  if (override !== undefined) {
    const argv = developmentArgv(override) as [string, ...string[]]
    const [command, ...args] = argv
    return { command, args: [...args, ...coreArgs], env: context.env }
  }
  // Explicit development selection, not a recovery path after a real core fails.
  return {
    command: 'python3',
    args: [join(context.appPath, 'fixture-core', 'fixture_core.py'), ...coreArgs],
    env: context.env
  }
}

/** Immutable production runtime; never recover with a system Python or fixture. */
export function packagedCoreCommand(resourcesPath: string, coreArgs: string[], ambient: NodeJS.ProcessEnv): CoreLaunch {
  const root = join(resourcesPath, 'runtime')
  const python = join(root, 'python', 'bin', 'python3')
  if (!existsSync(python) || !existsSync(join(resourcesPath, 'bundle-manifest.json'))) {
    throw new Error('Odin bundled runtime is missing. Reinstall the candidate package.')
  }
  const env = { ...ambient }
  for (const key of Object.keys(env)) if (key.startsWith('PYTHON')) delete env[key]
  delete env.ODIN_DESKTOP_CORE_CMD
  return {
    command: python,
    args: ['-I', '-B', '-m', 'src', ...coreArgs],
    env: {
      ...env,
      ODIN_DESKTOP_BUNDLE_ROOT: root,
      PLAYWRIGHT_BROWSERS_PATH: join(root, 'browser'),
      HF_HUB_OFFLINE: '1',
      TRANSFORMERS_OFFLINE: '1'
    }
  }
}
