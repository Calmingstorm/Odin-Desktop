// The installed Windows app refuses to start elevated (phase 4, P9b). An elevated run of the same user creates
// Administrators-owned state, such as a config-lock folder in TEMP, that the user's normal runs then rightly refuse.
// The check reads this process's own token through whoami's mandatory label: High or System integrity means
// elevated (an elevated administrator, an administrator with UAC off, SYSTEM), while a filtered administrator and a
// standard user run at Medium. It runs before identity, the single-instance lock or any profile write, and an
// answer it can't read refuses too, rather than starting on a guess.
import { spawnSync } from 'node:child_process'
import { win32 } from 'node:path'
import { csvFields } from './windows-paths'

type Env = Record<string, string | undefined>
type Run = (command: string, args: string[], options: { encoding: 'utf8'; windowsHide: boolean; timeout: number;
  maxBuffer: number }) => { status: number | null; stdout?: string | null; error?: Error }

const HIGH_INTEGRITY = 12288

export const ELEVATED_REFUSAL = 'Odin was started as administrator, so it didn\'t open. Start it normally, from the '
  + 'Start menu or its shortcut, without "Run as administrator": files an elevated Odin creates belong to '
  + 'Administrators, and your normal Odin can\'t use them.'
export const UNCHECKED_REFUSAL = 'Odin couldn\'t check whether it was started as administrator, so it didn\'t open. '
  + 'Start it again normally. If this repeats, check that Windows\' whoami.exe runs.'

/** The highest mandatory-label RID in `whoami /groups /fo csv /nh`, or null when there's none. */
export function integrityLevel(output: string): number | null {
  let level: number | null = null
  for (const line of output.split(/\r?\n/)) {
    const sid = csvFields(line.trim())?.[2]
    const match = sid?.match(/^S-1-16-(\d+)$/)
    if (match) level = Math.max(level ?? 0, Number(match[1]))
  }
  return level
}

/** Why this process mustn't start, or null when it runs with a normal token. */
export function elevatedStartRefusal(env: Env = process.env, run: Run = spawnSync as unknown as Run): string | null {
  const system = env.SystemRoot ?? ''
  if (!/^[A-Za-z]:[\\/]/.test(system)) return UNCHECKED_REFUSAL
  const result = run(win32.join(system, 'System32', 'whoami.exe'), ['/groups', '/fo', 'csv', '/nh'],
    { encoding: 'utf8', windowsHide: true, timeout: 5_000, maxBuffer: 65_536 })
  if (result.error || result.status !== 0 || typeof result.stdout !== 'string') return UNCHECKED_REFUSAL
  const level = integrityLevel(result.stdout)
  if (level === null) return UNCHECKED_REFUSAL
  return level >= HIGH_INTEGRITY ? ELEVATED_REFUSAL : null
}
