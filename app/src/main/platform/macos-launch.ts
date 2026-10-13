// The installed Mac app's engine launch. The engine runs under the bundled guardian
// (app/packaging/macos/guardian/odin-guardian.c), which stops it on the app's Exit or loss without the engine's
// cooperation: the app's pipe closing starts its grace, then TERM, then KILL. Its grace ends a second before the
// supervisor's own TERM (15 s), so that TERM always reaches a guardian already terminating, which kills the engine at
// once; the supervisor's KILL (20 s) only ever meets a stuck guardian. The engine gets the PATH a Terminal user has
// (design: "your tools"), built without running any shell startup file: Homebrew's folders, then what path_helper
// reads (/etc/paths, then /etc/paths.d in name order), then the inherited PATH, each folder once.
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { CoreLaunch } from '../core-command'

export const GUARDIAN_GRACE_SECONDS = 14
export const GUARDIAN_TERM_SECONDS = 4
export const HOMEBREW_PATHS = ['/opt/homebrew/bin', '/opt/homebrew/sbin']

export interface PathFiles {
  read: (path: string) => string
  list: (folder: string) => string[]
}

const system: PathFiles = { read: (path) => readFileSync(path, 'utf8'), list: (folder) => readdirSync(folder) }

function lines(files: PathFiles, path: string): string[] {
  try {
    return files.read(path).split('\n').map((line) => line.trim()).filter(Boolean)
  } catch {
    return [] // a missing or unreadable file adds nothing, as with path_helper
  }
}

/** path_helper's folders: /etc/paths, then each file in /etc/paths.d in name order. */
export function systemPaths(files: PathFiles = system): string[] {
  let names: string[] = []
  try {
    names = files.list('/etc/paths.d').sort()
  } catch { /* no /etc/paths.d */ }
  return [...lines(files, '/etc/paths'), ...names.flatMap((name) => lines(files, join('/etc/paths.d', name)))]
}

/** The engine's PATH on macOS: absolute folders only, each once, Homebrew's first. */
export function macosPath(inherited: string | undefined, files: PathFiles = system): string {
  const seen = new Set<string>()
  const folders: string[] = []
  for (const folder of [...HOMEBREW_PATHS, ...systemPaths(files), ...(inherited ?? '').split(':')]) {
    if (!folder.startsWith('/') || seen.has(folder)) continue
    seen.add(folder)
    folders.push(folder)
  }
  return folders.join(':')
}

export function guardianPath(resourcesPath: string): string {
  return join(resourcesPath, 'runtime', 'odin-guardian')
}

/** The bundled engine's launch, run under the guardian with the Mac's PATH. */
export function underGuardian(resourcesPath: string, launch: CoreLaunch, files: PathFiles = system): CoreLaunch {
  return {
    command: guardianPath(resourcesPath),
    args: ['--grace', String(GUARDIAN_GRACE_SECONDS), '--term', String(GUARDIAN_TERM_SECONDS), '--',
      launch.command, ...launch.args],
    env: { ...launch.env, PATH: macosPath(launch.env.PATH, files) }
  }
}
