import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'
import { packagedCoreCommand } from './core-command'
import type { ProfilePaths } from './paths'

/** Independent guardian even when a user invokes the raw Electron executable. */
export function acquirePackagedApp(paths: ProfilePaths, resources: string, env: NodeJS.ProcessEnv): Promise<ChildProcessWithoutNullStreams> {
  const launch = packagedCoreCommand(resources, [], env)
  const kind = dirname(resolve(resources)) === '/opt/odin-desktop' ? 'deb' : 'appimage'
  const child = spawn(launch.command, ['-I', '-B', join(resources, 'ownership.py'),
    '--kind', kind, '--role', 'app',
    '--app-cleanup', join(paths.configDir, '..', `${paths.profileId}-cleanup-state.json`),
    '--core-cleanup', join(paths.dataDir, 'resource-cleanup.json'), 'hold'], {
    env: launch.env, stdio: ['pipe', 'pipe', 'pipe']
  })
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => fail(), 15_000)
    const fail = (): void => {
      clearTimeout(timer)
      child.stdin.end()
      reject(new Error('Package ownership is unavailable. Exit the owned app and finish external replacement.'))
    }
    child.once('error', fail)
    child.once('exit', fail)
    let output = ''
    child.stdout.on('data', (data) => {
      output += String(data)
      if (output.includes('READY\n')) {
        clearTimeout(timer)
        child.removeListener('error', fail)
        child.removeListener('exit', fail)
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
      if (output.includes('ADMITTED\n')) { cleanup(); resolve() }
      else if (output.length > 1024) fail()
    }
    const timer = setTimeout(fail, 15_000)
    child.once('exit', fail)
    child.stdout.on('data', ready)
    child.stdin.write('ADMIT\n')
  })
}
