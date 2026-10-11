// Main-process launch selection. The fixture is deliberately development-only.
// P4.1 plugs its verified immutable resource layout into resolvePackaged; there
// is no production fallback to PATH Python, an override, or a developer tree.
import { basename, join, posix, win32 } from 'node:path'
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
  /** The system the app runs on (default: this one). */
  system?: NodeJS.Platform
}

/** Windows has no development fixture: a source run names the checkout's own engine. */
export const WINDOWS_SOURCE_CORE_REQUIRED = 'Set ODIN_DESKTOP_CORE_CMD to this checkout\'s engine before starting Odin '
  + 'from source on Windows, as a JSON argv such as ["C:\\\\path\\\\to\\\\checkout\\\\.venv\\\\Scripts\\\\python.exe","-I","-B","-m","src"] '
  + '(see docs/windows-from-source.md).'

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
  if ((context.system ?? process.platform) === 'win32') throw new Error(WINDOWS_SOURCE_CORE_REQUIRED)
  return {
    command: 'python3',
    args: [join(context.appPath, 'fixture-core', 'fixture_core.py'), ...coreArgs],
    env: context.env
  }
}

export interface PackagedLayout {
  /** The system the app runs on (default: this one). */
  system?: NodeJS.Platform
  exists?: (path: string) => boolean
}

/** Immutable production runtime; never recover with a system Python or fixture. Windows' standalone CPython keeps
 * its interpreter at the runtime's root (`python\\python.exe`), and its environment names ignore case. */
export function packagedCoreCommand(resourcesPath: string, coreArgs: string[], ambient: NodeJS.ProcessEnv,
  { system = process.platform, exists = existsSync }: PackagedLayout = {}): CoreLaunch {
  const windows = system === 'win32'
  const path = windows ? win32 : posix
  const root = path.join(resourcesPath, 'runtime')
  const python = windows ? path.join(root, 'python', 'python.exe') : path.join(root, 'python', 'bin', 'python3')
  if (!exists(python) || !exists(path.join(resourcesPath, 'bundle-manifest.json'))) {
    throw new Error('Odin bundled runtime is missing. Reinstall the candidate package.')
  }
  const env = { ...ambient }
  for (const key of Object.keys(env)) if ((windows ? key.toUpperCase() : key).startsWith('PYTHON')) delete env[key]
  delete env.ODIN_DESKTOP_CORE_CMD
  return {
    command: python,
    args: ['-I', '-B', '-m', 'src', ...coreArgs],
    env: {
      ...env,
      ODIN_DESKTOP_BUNDLE_ROOT: root,
      PLAYWRIGHT_BROWSERS_PATH: path.join(root, 'browser'),
      HF_HUB_OFFLINE: '1',
      TRANSFORMERS_OFFLINE: '1'
    }
  }
}
