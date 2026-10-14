// The installed Mac app's engine launch. The engine runs under the bundled guardian
// (app/packaging/macos/guardian/odin-guardian.c), which stops it on the app's Exit or loss without the engine's
// cooperation: the app's pipe closing starts its grace, then TERM, then KILL, then it reaps the engine and exits with
// the engine's status. The guardian is the engine's only escalation authority: the app never signals it, since a
// guardian killed before it has reaped would leave the engine unsupervised. Stop closes the pipe and waits the
// guardian's deadlines plus a reaping margin; past that the outcome is unknown and the guardian keeps its work.
//
// The engine's PATH (design: "your tools") is built without running any shell startup file: Homebrew's folders, then
// what path_helper reads (/etc/paths, then /etc/paths.d in name order, where an administrator adds custom folders and
// which Terminal's zsh reads too), then the PATH macOS gave the app, each folder once. A folder added only in a shell
// startup file (.zshrc, .zprofile) isn't on it: add the folder to /etc/paths.d, or run the tool by its full path.
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { CoreLaunch } from '../core-command'

export const GUARDIAN_GRACE_SECONDS = 14
export const GUARDIAN_TERM_SECONDS = 4
/** Beyond the guardian's own deadlines: its KILL, the engine's exit and its reaping. */
export const GUARDIAN_REAP_MARGIN_MS = 6_000
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
    env: { ...launch.env, PATH: macosPath(launch.env.PATH, files) },
    guardianWaitMs: (GUARDIAN_GRACE_SECONDS + GUARDIAN_TERM_SECONDS) * 1000 + GUARDIAN_REAP_MARGIN_MS
  }
}
