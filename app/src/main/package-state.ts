// Compatibility before app profile scaffolding or log writers. No fallback.
import { execFileSync } from 'node:child_process'
import type { ProfilePaths } from './paths'
import { packagedCoreCommand } from './core-command'

export function inspectPackagedState(paths: ProfilePaths, resourcesPath: string, env: NodeJS.ProcessEnv): void {
  const launch = packagedCoreCommand(resourcesPath, [], env)
  try {
    execFileSync(launch.command, ['-I', '-B', '-m', 'src.desktop.package_state',
      '--profile', paths.profileId, '--token-file', paths.tokenPath, '--data-dir', paths.dataDir], {
      env: launch.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: 30_000,
      maxBuffer: 65_536
    })
  } catch {
    throw new Error('Odin Desktop state is incompatible or unavailable. Original state was preserved.')
  }
}
