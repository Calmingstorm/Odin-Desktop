// Starts the development fixture core in a throwaway profile for integration tests.
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { ensureProfileDirs, ensureToken, profilePaths, type ProfilePaths } from '../src/main/paths'

export const FIXTURE = resolve(__dirname, '../fixture-core/fixture_core.py')

export interface FixtureCore {
  paths: ProfilePaths
  child: ChildProcess
  root: string
  stop: () => Promise<void>
}

export async function startFixture(): Promise<FixtureCore> {
  const root = mkdtempSync(join(tmpdir(), 'odin-fixture-'))
  const paths = profilePaths('default', {
    HOME: root,
    XDG_CONFIG_HOME: join(root, 'config'),
    XDG_DATA_HOME: join(root, 'data'),
    XDG_CACHE_HOME: join(root, 'cache'),
    XDG_RUNTIME_DIR: join(root, 'run')
  })
  ensureProfileDirs(paths)
  ensureToken(paths)
  const child = spawn(
    'python3',
    [FIXTURE, '--socket', paths.socketPath, '--token-file', paths.tokenPath, '--profile', 'default'],
    { stdio: ['pipe', 'ignore', 'pipe'] }
  )
  await waitFor(() => existsSync(paths.socketPath), 10_000)
  const stop = async (): Promise<void> => {
    if (child.exitCode === null && child.signalCode === null) {
      const exited = new Promise((r) => child.once('exit', r))
      child.stdin?.end()
      await Promise.race([exited, new Promise((r) => setTimeout(r, 5_000))])
      if (child.exitCode === null) child.kill('SIGKILL')
    }
    rmSync(root, { recursive: true, force: true })
  }
  return { paths, child, root, stop }
}

export async function waitFor(check: () => boolean, timeoutMs = 10_000, stepMs = 25): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (!check()) {
    if (Date.now() > deadline) throw new Error('timed out waiting for condition')
    await new Promise((r) => setTimeout(r, stepMs))
  }
}
