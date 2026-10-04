// Per-user profile locations (XDG on Linux). Odin Desktop never reads or writes another Odin install's paths.
import { randomBytes } from 'node:crypto'
import { chmodSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'

export const DEFAULT_PROFILE = 'default'

export interface ProfilePaths {
  profileId: string
  configDir: string
  dataDir: string
  cacheDir: string
  runtimeDir: string
  socketPath: string
  tokenPath: string
  appStatePath: string
  logDir: string
}

type Env = Record<string, string | undefined>

export function profilePaths(profileId: string = DEFAULT_PROFILE, env: Env = process.env): ProfilePaths {
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(profileId)) throw new Error('invalid profile id')
  const home = env.HOME || homedir()
  const config = join(env.XDG_CONFIG_HOME || join(home, '.config'), 'odin-desktop', profileId)
  const data = join(env.XDG_DATA_HOME || join(home, '.local', 'share'), 'odin-desktop', profileId)
  const cache = join(env.XDG_CACHE_HOME || join(home, '.cache'), 'odin-desktop', profileId)
  const uid = typeof process.getuid === 'function' ? process.getuid() : 0
  const runtimeRoot = env.XDG_RUNTIME_DIR || join(tmpdir(), `odin-desktop-${uid}`)
  const runtime = join(runtimeRoot, 'odin-desktop', profileId)
  return {
    profileId,
    configDir: config,
    dataDir: data,
    cacheDir: cache,
    runtimeDir: runtime,
    socketPath: join(runtime, 'core.sock'),
    tokenPath: join(config, 'ipc.token'),
    appStatePath: join(config, 'app-state.json'),
    logDir: join(data, 'logs')
  }
}

export function ensureProfileDirs(paths: ProfilePaths): void {
  for (const dir of [paths.configDir, paths.dataDir, paths.cacheDir, paths.runtimeDir, paths.logDir]) {
    mkdirSync(dir, { recursive: true, mode: 0o700 })
    chmodSync(dir, 0o700)
  }
}

/**
 * Returns the profile's IPC token, creating it on first use. The token never leaves the main process: the core gets
 * the file's path, never the value, and nothing logs it.
 */
export function ensureToken(paths: ProfilePaths): string {
  try {
    const mode = statSync(paths.tokenPath).mode & 0o777
    if (mode !== 0o600) chmodSync(paths.tokenPath, 0o600)
    const token = readFileSync(paths.tokenPath, 'utf8').trim()
    if (/^[0-9a-f]{64}$/.test(token)) return token
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const token = randomBytes(32).toString('hex')
  writeFileSync(paths.tokenPath, token, { mode: 0o600 })
  chmodSync(paths.tokenPath, 0o600)
  return token
}
