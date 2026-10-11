// Windows profile layout, from a source checkout (phase 3d): local AppData, the engine's named pipe, and the token.
// The app creates the profile plainly and never repairs an ACL: the engine judges its privacy (it repairs its own
// namespace folders and refuses bootstrap files that aren't private), so a fresh, owner-private local profile is the
// supported start. A link anywhere in the profile is refused before anything sensitive is written.
import { execFileSync } from 'node:child_process'
import { createHash, randomBytes } from 'node:crypto'
import { lstatSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, sep, win32 } from 'node:path'
import { DEFAULT_PROFILE, type ProfilePaths } from '../paths'

type Env = Record<string, string | undefined>

const PROFILE_ID = /^[a-z0-9][a-z0-9_-]{0,63}$/
const PIPE_PREFIX = '\\\\.\\pipe\\odin-desktop-'
const SID = /^S-1-\d+(?:-\d+)+$/
const TOKEN = /^[0-9a-f]{64}$/

/** The app's admission subset of the engine's rule: set, drive-absolute, no "..", no control characters. */
export function localAppData(env: Env): string {
  const base = env.LOCALAPPDATA ?? ''
  // eslint-disable-next-line no-control-regex
  if (!/^[A-Za-z]:[\\/]/.test(base) || /[\u0000-\u001f]/.test(base) || base.split(/[\\/]/).includes('..')) {
    throw new Error('LOCALAPPDATA must be set to an absolute folder on a local drive.')
  }
  return base
}

/** One CSV record's fields: quoted fields may hold commas and doubled quotes. */
export function csvFields(line: string): string[] | null {
  const fields: string[] = []
  const pattern = /("(?:[^"]|"")*"|[^,"]*)(,|$)/y
  let match: RegExpExecArray | null
  while (pattern.lastIndex < line.length && (match = pattern.exec(line))) {
    const raw = match[1]!
    fields.push(raw.startsWith('"') ? raw.slice(1, -1).replace(/""/g, '"') : raw)
    if (match[2] === '') return pattern.lastIndex === line.length ? fields : null
  }
  return pattern.lastIndex === line.length ? fields : null
}

/** The user's SID from `whoami /user /fo csv /nh`: its second field (the first is the localized account name). */
export function parseWhoamiUser(output: string): string {
  const lines = output.split(/\r?\n/).filter((line) => line.trim() !== '')
  const fields = lines.length === 1 ? csvFields(lines[0]!.trim()) : null
  if (!fields || fields.length !== 2 || !SID.test(fields[1]!)) throw new Error('whoami gave an unexpected answer.')
  return fields[1]!
}

function whoami(env: Env = process.env): string {
  const system = env.SystemRoot ?? ''
  if (!/^[A-Za-z]:[\\/]/.test(system)) throw new Error('SystemRoot must be an absolute folder.')
  return execFileSync(win32.join(system, 'System32', 'whoami.exe'), ['/user', '/fo', 'csv', '/nh'],
    { encoding: 'utf8', windowsHide: true, timeout: 5_000, maxBuffer: 4_096 })
}

let cachedSid: string | null = null

/** This process's user SID, read once. */
export function userSid(run: () => string = whoami): string {
  if (cachedSid === null) cachedSid = parseWhoamiUser(run())
  return cachedSid
}

/** `\\.\pipe\odin-desktop-<16 hex of SHA-256(SID)>-<profile>`: the only name the engine accepts. */
export function pipeName(profileId: string, sid: string): string {
  return `${PIPE_PREFIX}${createHash('sha256').update(sid, 'utf8').digest('hex').slice(0, 16)}-${profileId}`
}

export function windowsProfilePaths(profileId: string = DEFAULT_PROFILE, env: Env = process.env,
  sid: () => string = userSid): ProfilePaths {
  if (!PROFILE_ID.test(profileId)) throw new Error('invalid profile id')
  const root = win32.join(localAppData(env), 'odin-desktop', profileId)
  const config = win32.join(root, 'config')
  const data = win32.join(root, 'data')
  const cache = win32.join(root, 'cache')
  return {
    profileId,
    configDir: config,
    dataDir: data,
    cacheDir: cache,
    runtimeDir: cache, // Windows needs no runtime folder: the endpoint is a pipe
    socketPath: pipeName(profileId, sid()),
    tokenPath: win32.join(config, 'ipc.token'),
    appStatePath: win32.join(config, 'app-state.json'),
    logDir: win32.join(data, 'logs')
  }
}

/** Refuses a link (a symlink or junction) at `path`; absence is fine. */
function refuseLink(path: string): void {
  try {
    if (lstatSync(path).isSymbolicLink()) throw new Error(`A link in Odin's profile is refused: ${path}`)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
}

/** Every folder from `odin-desktop` down to `path` (in this system's own path syntax). */
function chain(paths: ProfilePaths, path: string): string[] {
  const top = dirname(dirname(paths.configDir))
  const parts = relative(top, path).split(sep).filter(Boolean)
  return [top, ...parts.map((_, index) => join(top, ...parts.slice(0, index + 1)))]
}

export function ensureWindowsProfileDirs(paths: ProfilePaths): void {
  for (const dir of [paths.configDir, paths.dataDir, paths.cacheDir, paths.logDir]) {
    for (const folder of chain(paths, dir)) refuseLink(folder)
    mkdirSync(dir, { recursive: true })
    for (const folder of chain(paths, dir)) refuseLink(folder)
  }
}

/** The engine reads exactly 64 hex bytes: a file that is exactly that is reused, anything else is replaced. */
export function ensureWindowsToken(paths: ProfilePaths): string {
  for (const folder of chain(paths, paths.configDir)) refuseLink(folder)
  refuseLink(paths.tokenPath)
  try {
    const token = readFileSync(paths.tokenPath, 'latin1')
    if (TOKEN.test(token)) return token
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const token = randomBytes(32).toString('hex')
  writeFileSync(paths.tokenPath, token)
  return token
}
