// macOS profile locations, the engine's own layout (src/desktop/platform/macos.py): ~/Library/odin-desktop/<profile>
// with config and data, and ~/Library/Caches/odin-desktop/<profile>. The paths must hold no whitespace: OpenSSH
// splits its options' values on it. The engine's socket lives in the per-user temporary folder macOS creates for each
// user, whose privacy is verified here as the engine verifies it (darwin.user_temp_root), never assumed.
import { execFileSync } from 'node:child_process'
import { lstatSync, realpathSync } from 'node:fs'
import { homedir } from 'node:os'
import { isAbsolute, join } from 'node:path'
import { DEFAULT_PROFILE, type ProfilePaths } from '../paths'

/** sun_path is 104 bytes on macOS, including the terminating NUL. */
export const SOCKET_PATH_LIMIT = 103
export const HOME_WITH_WHITESPACE = 'Odin Desktop on macOS needs a home folder path without spaces: OpenSSH splits its '
  + 'options on them.'

type Env = Record<string, string | undefined>

export interface TempRootSystem {
  /** confstr(_CS_DARWIN_USER_TEMP_DIR), the engine's source, read through getconf. */
  named: () => string
  real: (path: string) => string
  stat: (path: string) => { isDirectory(): boolean; uid: number; mode: number }
  uid: number
}

const system = (): TempRootSystem => ({
  named: () => execFileSync('/usr/bin/getconf', ['DARWIN_USER_TEMP_DIR'], { encoding: 'utf8', timeout: 5_000 }).trim(),
  real: (path) => realpathSync(path),
  stat: (path) => lstatSync(path),
  uid: process.geteuid?.() ?? -1
})

const outside = (path: string): boolean => !isAbsolute(path) || path.split('/').includes('..')
  || /[\u0000-\u001f]/.test(path)

/** The per-user temporary folder: absolute as named, then its real path, a folder owned by this user with mode 0700. */
export function userTempRoot(os: TempRootSystem = system()): string {
  const named = os.named()
  if (outside(named)) throw new Error('The per-user temporary folder is not an absolute local path.')
  const root = os.real(named)
  const info = os.stat(root)
  if (!info.isDirectory() || info.uid !== os.uid || (info.mode & 0o777) !== 0o700) {
    throw new Error('The per-user temporary folder is not private to this user.')
  }
  return root
}

let verifiedRoot: string | undefined
/** Verified once per process: the folder is the user's for the session. */
const defaultTempRoot = (): string => (verifiedRoot ??= userTempRoot())

export function macosProfilePaths(profileId: string = DEFAULT_PROFILE, env: Env = process.env,
  tempRoot: () => string = defaultTempRoot): ProfilePaths {
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(profileId)) throw new Error('invalid profile id')
  const home = env.HOME || homedir()
  if (outside(home)) throw new Error('The home folder must be an absolute local path.')
  if (/\s/u.test(home)) throw new Error(HOME_WITH_WHITESPACE)
  const profile = join(home, 'Library', 'odin-desktop', profileId)
  const config = join(profile, 'config')
  const data = join(profile, 'data')
  const runtime = join(tempRoot(), 'odin-desktop', profileId)
  const socketPath = join(runtime, 'core.sock')
  if (Buffer.byteLength(socketPath) > SOCKET_PATH_LIMIT) {
    throw new Error(`The engine's socket path is longer than macOS allows (${SOCKET_PATH_LIMIT} bytes).`)
  }
  return {
    profileId,
    configDir: config,
    dataDir: data,
    cacheDir: join(home, 'Library', 'Caches', 'odin-desktop', profileId),
    runtimeDir: runtime,
    socketPath,
    tokenPath: join(config, 'ipc.token'),
    appStatePath: join(config, 'app-state.json'),
    logDir: join(data, 'logs')
  }
}
