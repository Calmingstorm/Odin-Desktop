// The installed Windows app refuses to start elevated (phase 4, P9b). An elevated run of the same user creates
// Administrators-owned state, such as a config-lock folder in TEMP, that the user's normal runs then rightly refuse.
// The check reads this process's own token: the bundled guardian reports it (`ownership.py token`), and a child runs
// with its parent's token. TokenElevation refuses (an elevated administrator, an administrator with UAC off, SYSTEM),
// and so does a default owner other than the user, since that's who would own what Odin creates; a filtered
// administrator and a standard user start normally. It runs before identity, the single-instance lock or any profile
// write, and facts it can't read refuse too, rather than starting on a guess.
import { spawnSync } from 'node:child_process'
import { win32 } from 'node:path'
import { packagedCoreCommand, type PackagedLayout } from '../core-command'

type Run = (command: string, args: string[], options: { env: NodeJS.ProcessEnv; encoding: 'utf8';
  windowsHide: boolean; timeout: number; maxBuffer: number }) => { status: number | null; stdout?: string | null;
  error?: Error }

/** The token facts the check decides on; the guardian also reports the integrity label and session. */
export interface TokenFacts { user: string; owner: string; elevated: boolean; elevationType: number }

export const ELEVATED_REFUSAL = 'Odin was started as administrator, so it didn\'t open. Start it normally, from the '
  + 'Start menu or its shortcut, without "Run as administrator": files an elevated Odin creates belong to '
  + 'Administrators, and your normal Odin can\'t use them.'
export const UNCHECKED_REFUSAL = 'Odin couldn\'t check whether it was started as administrator, so it didn\'t open. '
  + 'Start it again normally. If this repeats, reinstall Odin for Windows.'
export function ownerRefusal(owner: string): string {
  return `Odin didn't open: Windows would make the files it creates belong to ${owner}, not to your account, and `
    + 'your normal Odin couldn\'t use them. Start it from your own account, without "Run as administrator".'
}

const SID = /^S-1-\d+(?:-\d+)+$/

/** The facts in the guardian's one-line JSON report, or null unless it's complete and well formed. */
export function tokenFacts(output: string): TokenFacts | null {
  let report: unknown
  try {
    report = JSON.parse(output)
  } catch {
    return null
  }
  if (!report || typeof report !== 'object' || Array.isArray(report)) return null
  const { user, owner, elevated, elevation_type: elevationType } = report as Record<string, unknown>
  if (typeof user !== 'string' || !SID.test(user) || typeof owner !== 'string' || !SID.test(owner)
    || typeof elevated !== 'boolean' || !(elevationType === 1 || elevationType === 2 || elevationType === 3)) {
    return null
  }
  return { user, owner, elevated, elevationType }
}

/** Why this process mustn't start, or null when its token is a normal one. */
export function elevatedStartRefusal(resources: string = process.resourcesPath, env: NodeJS.ProcessEnv = process.env,
  run: Run = spawnSync as unknown as Run, layout: PackagedLayout = {}): string | null {
  let launch
  try {
    launch = packagedCoreCommand(resources, [], env, { ...layout, system: 'win32' })
  } catch {
    return UNCHECKED_REFUSAL
  }
  const result = run(launch.command, ['-I', '-B', win32.join(resources, 'ownership.py'), 'token'],
    { env: launch.env, encoding: 'utf8', windowsHide: true, timeout: 15_000, maxBuffer: 65_536 })
  if (result.error || result.status !== 0 || typeof result.stdout !== 'string') return UNCHECKED_REFUSAL
  const facts = tokenFacts(result.stdout)
  if (!facts) return UNCHECKED_REFUSAL
  if (facts.elevated) return ELEVATED_REFUSAL
  return facts.owner === facts.user ? null : ownerRefusal(facts.owner)
}
