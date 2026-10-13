import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { dirname, posix, resolve, win32 } from 'node:path'
import { packagedCoreCommand } from './core-command'
import type { ProfilePaths } from './paths'

/** Whether the guardian's output holds `word` as a whole line, LF- or CRLF-terminated (chunks may split it). */
export function hasLine(output: string, word: string): boolean {
  return new RegExp(`(?:^|\\n)${word}\\r?\\n`).test(output)
}

/** The Windows guardian's exit for an unfinished installer run: the fence it leaves refuses every start. */
export const PENDING_EXIT = 75
export const INSTALL_UNFINISHED = 'An Odin installation didn\'t finish. Run the Odin installer again.'

/** Independent guardian even when a user invokes the raw Electron executable. macOS' per-user installation is `macos`,
 * whose lease lives under ~/Library/odin-desktop. Windows' per-user installation is
 * `nsis`, whose lease lives in local AppData; its guardian runs without a console window, detached: on Windows
 * Node puts every other child in a job that ends it when the app exits, and the guardian outlives the app to
 * record its clean Exit after the app's real exit. */
export function acquirePackagedApp(paths: ProfilePaths, resources: string, env: NodeJS.ProcessEnv,
  system: NodeJS.Platform = process.platform): Promise<ChildProcessWithoutNullStreams> {
  const windows = system === 'win32'
  const path = windows ? win32 : posix
  const launch = packagedCoreCommand(resources, [], env, { system })
  const kind = windows ? 'nsis' : system === 'darwin' ? 'macos'
    : dirname(resolve(resources)) === '/opt/odin-desktop' ? 'deb' : 'appimage'
  const child = spawn(launch.command, ['-I', '-B', path.join(resources, 'ownership.py'),
    '--kind', kind, '--role', 'app',
    '--app-cleanup', path.join(paths.configDir, '..', `${paths.profileId}-cleanup-state.json`),
    '--core-cleanup', path.join(paths.dataDir, 'resource-cleanup.json'), 'hold'], {
    env: launch.env, stdio: ['pipe', 'pipe', 'pipe'], ...(windows ? { windowsHide: true, detached: true } : {})
  })
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => fail(), 15_000)
    const fail = (code?: number | null): void => {
      clearTimeout(timer)
      child.stdin.end()
      reject(new Error(windows && code === PENDING_EXIT ? INSTALL_UNFINISHED
        : 'Package ownership is unavailable. Exit the owned app and finish external replacement.'))
    }
    const failed = (): void => fail()
    const exited = (code: number | null): void => fail(code)
    child.once('error', failed)
    child.once('exit', exited)
    let output = ''
    child.stdout.on('data', (data) => {
      output += String(data)
      if (hasLine(output, 'READY')) {
        clearTimeout(timer)
        child.removeListener('error', failed)
        child.removeListener('exit', exited)
        resolve(child)
      } else if (output.length > 1024) fail()
    })
    // Drain without logging secret-adjacent cleanup paths or process output.
    child.stderr.on('data', () => undefined)
  })
}

/** Commit lifetime admission only after read-only compatibility has passed. */
export function admitPackagedApp(child: ChildProcessWithoutNullStreams): Promise<void> {
  return new Promise((resolve, reject) => {
    let output = ''
    const cleanup = (): void => {
      clearTimeout(timer)
      child.removeListener('exit', fail)
      child.stdout.removeListener('data', ready)
    }
    const fail = (): void => {
      cleanup()
      child.stdin.end()
      reject(new Error('Package lifetime admission failed. Original profile was not opened.'))
    }
    const ready = (data: Buffer): void => {
      output += String(data)
      if (hasLine(output, 'ADMITTED')) { cleanup(); resolve() }
      else if (output.length > 1024) fail()
    }
    const timer = setTimeout(fail, 15_000)
    child.once('exit', fail)
    child.stdout.on('data', ready)
    child.stdin.write('ADMIT\n')
  })
}
