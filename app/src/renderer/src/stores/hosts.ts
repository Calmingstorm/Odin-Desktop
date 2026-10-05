// Hosts and trust, in the shapes of Odin's /api/hosts routes. Adding or changing a host follows Odin's enrollment:
// details, Odin's public key, the host's key checked against what you expect, a connection test, then activation.
// Nothing is targetable before it passes the test.
import { reactive } from 'vue'
import type { HostCandidate, HostList, HostPrepare, HostReference, HostRow, HostTest, PublicKeyInfo, Result } from '../../../shared/api'
import { act, failure, management } from './management'
import { isUnavailable, resultMessage, unavailableText } from '../capability'

export interface HostForm {
  alias: string
  address: string
  port: number
  ssh_user: string
  os: 'linux' | 'macos'
  description: string
  trust_mode: 'pinned' | 'ca' | 'tofu'
  confirm_local: boolean
  confirm_tofu: boolean
}

export interface Enrollment {
  editing: boolean
  step: 1 | 2 | 3 | 4 | 5
  form: HostForm
  /** Fingerprints you expect, one per line, checked out of band. */
  expected: string
  /** What the scan found. */
  observed: string[]
  token: string
  tested: boolean
  test: HostTest | null
  note: string
  busy: boolean
}

export const hosts = reactive({
  unavailable: false,
  error: '',
  list: null as HostList | null,
  key: null as PublicKeyInfo | null,
  /** What still names a host, from the last attempt to delete it. */
  references: {} as Record<string, HostReference[] | undefined>,
  enrollment: null as Enrollment | null
})

const FINGERPRINT = /^SHA256:[A-Za-z0-9+/]{20,64}$/

export const STEPS = ['Details', "Odin's key", 'Host key', 'Test', 'Activate']

/** Odin treats exactly these addresses as this computer: commands run inside Odin itself. */
const LOCAL = new Set(['127.0.0.1', 'localhost', '::1'])

export function isLocal(address: string): boolean {
  return LOCAL.has(address.trim())
}

/** Each read of the hosts, in order: an older answer never replaces a newer one. */
let hostsRead = 0

function refuseHosts(): void {
  hosts.unavailable = true
  hosts.error = ''
  management.error = ''
  hosts.list = null
  hosts.key = null
  hosts.references = {}
  // Keep local details, not a returned enrollment token or successful test from the refused core.
  if (hosts.enrollment) Object.assign(hosts.enrollment, { token: '', tested: false, test: null, observed: [], note: '', step: 1 })
  for (const key of Object.keys(management.notes)) {
    if ((key === 'hosts' || key.startsWith('host:')) && !management.busy[key]) delete management.notes[key]
  }
}

async function hostAct<T>(key: string, run: () => Promise<Result<T>>, done: (answer: T) => string): Promise<boolean> {
  if (hosts.unavailable) return false
  return act(key, async () => {
    const result = await run()
    if (!result.ok && isUnavailable(result.error)) {
      refuseHosts()
      return { ...result, error: { ...result.error, message: unavailableText('Host management') } }
    }
    return result
  }, done, async () => { if (!hosts.unavailable) await loadHosts() })
}

export async function loadHosts(): Promise<void> {
  const mine = ++hostsRead
  const [list, key] = await Promise.all([window.odin.hostsList({}), window.odin.hostsPublicKey({})])
  if (mine !== hostsRead) return
  if ((!list.ok && isUnavailable(list.error)) || (!key.ok && isUnavailable(key.error))) {
    refuseHosts()
    return
  }
  hosts.error = !list.ok ? resultMessage(list, 'Host management') : resultMessage(key, 'Host management')
  management.error = hosts.error
  if (list.ok && key.ok) hosts.unavailable = false
  if (list.ok) hosts.list = list.result
  if (key.ok) hosts.key = key.result
}

function blankForm(): HostForm {
  return {
    alias: '',
    address: '',
    port: 22,
    ssh_user: 'root',
    os: 'linux',
    description: '',
    trust_mode: 'pinned',
    confirm_local: false,
    confirm_tofu: false
  }
}

function start(editing: boolean, form: HostForm): void {
  hosts.enrollment = { editing, step: 1, form, expected: '', observed: [], token: '', tested: false, test: null, note: '', busy: false }
}

export function beginAdd(): void {
  if (hosts.unavailable) return
  start(false, blankForm())
}

/** A change goes through the same steps; the alias stays. */
export function beginEdit(row: HostRow): void {
  if (hosts.unavailable) return
  const mode = row.trust_mode === 'ca' || row.trust_mode === 'tofu' ? row.trust_mode : 'pinned'
  start(true, {
    ...blankForm(),
    alias: row.alias,
    address: row.address,
    port: row.port,
    ssh_user: row.ssh_user,
    os: row.os === 'macos' ? 'macos' : 'linux',
    description: row.description,
    trust_mode: mode
  })
}

export function closeEnrollment(): void {
  hosts.enrollment = null
}

/** Moves between the first steps; a scan or test moves on by itself when it passes. */
export function goTo(step: Enrollment['step']): void {
  const e = hosts.enrollment
  if (!e || e.busy) return
  // Anything earlier than the test invalidates what was scanned or tested after it.
  if (step < 4) Object.assign(e, { token: '', tested: false, test: null })
  if (step < 3) e.observed = []
  e.step = step
  e.note = ''
}

function body(e: Enrollment): HostPrepare {
  const f = e.form
  const prepare: HostPrepare = {
    alias: f.alias.trim(),
    address: f.address.trim(),
    ssh_user: f.ssh_user.trim(),
    port: Number(f.port),
    os: f.os,
    description: f.description.trim(),
    trust_mode: f.trust_mode
  }
  if (isLocal(f.address)) prepare.confirm_local = f.confirm_local
  const expected = e.expected.split(/\s+/).filter(Boolean)
  if (f.trust_mode !== 'tofu') prepare.expected_fingerprints = expected
  else if (e.observed.length) {
    // The second request binds the confirmation to exactly what the first scan showed.
    prepare.candidate_fingerprints = e.observed
    prepare.confirm_tofu = f.confirm_tofu
  }
  return prepare
}

/** Scans the host's key and compares it. Trust on first use takes two scans: one to see the key, one to accept it. */
export async function scan(): Promise<void> {
  if (hosts.unavailable) return
  const e = hosts.enrollment
  if (!e || e.busy) return
  const odd = e.form.trust_mode === 'tofu' ? undefined : e.expected.split(/\s+/).filter(Boolean).find((f) => !FINGERPRINT.test(f))
  if (odd !== undefined) {
    e.note = `${odd} is not a fingerprint. One looks like SHA256:… as ssh-keygen -lf prints it.`
    return
  }
  e.busy = true
  const firstLook = e.form.trust_mode === 'tofu' && e.observed.length === 0
  const result = await window.odin.hostsPrepare(body(e))
  e.busy = false
  if (!result.ok && isUnavailable(result.error)) {
    refuseHosts()
    return
  }
  if (!result.ok) {
    e.note = result.error.message
    return
  }
  const candidate: HostCandidate = result.result
  e.observed = candidate.fingerprints
  // Odin trusts this computer without a key to check, whatever was asked for: nothing to look at first.
  if (firstLook && candidate.trust_mode === 'tofu') {
    e.form.confirm_tofu = false
    e.note = 'Scanned. Check this fingerprint, tick to trust it, then scan again.'
    return
  }
  e.token = candidate.candidate_token
  e.note = ''
  e.step = 4
}

export async function testConnection(): Promise<void> {
  if (hosts.unavailable) return
  const e = hosts.enrollment
  if (!e || e.busy || !e.token) return
  e.busy = true
  const result = await window.odin.hostsTest({ token: e.token })
  e.busy = false
  if (!result.ok && isUnavailable(result.error)) {
    refuseHosts()
    return
  }
  if (!result.ok) {
    e.note = result.error.message
    return
  }
  e.tested = result.result.tested
  e.test = result.result.last_test
  e.note = e.tested ? '' : (result.result.error ?? 'The connection test failed.')
  if (e.tested) e.step = 5
}

/** The lock and note an enrollment's activation goes under: its host's. */
export const hostKey = (e: Enrollment): string => `host:${e.form.alias.trim()}`

/**
 * Activates the tested host. It is live at once. With no answer, the host stays held under that command, which is
 * never sent again under a new one; its answer, now or by a late receipt, closes the wizard that asked for it.
 */
export async function activate(): Promise<boolean> {
  if (hosts.unavailable) return false
  const e = hosts.enrollment
  if (!e || e.busy || !e.tested) return false
  const key = hostKey(e)
  if (management.busy[key]) return false
  management.notes[key] = undefined
  e.busy = true
  const ok = await hostAct(key, () => window.odin.hostsCommit({ token: e.token }), () => {
    if (hosts.enrollment === e) hosts.enrollment = null // another wizard opened since stays
    return e.editing ? 'Saved and live.' : 'Added and live.'
  })
  e.busy = false
  return ok
}

export async function setHostEnabled(alias: string, enabled: boolean): Promise<void> {
  await hostAct(`host:${alias}`, () => window.odin.hostsSetEnabled({ alias, enabled }), () => (enabled ? 'On.' : 'Off: Odin no longer runs anything there.'))
}

export async function saveHostSettings(change: { default_host?: string; allow_host_tofu?: boolean }): Promise<boolean> {
  return hostAct('hosts', () => window.odin.hostsSettings(change), () => 'Saved and live.')
}

/** Deleting a host that something still names is refused; this shows what names it, and deletes nothing. */
export async function deleteHost(alias: string): Promise<'deleted' | 'blocked' | 'failed'> {
  if (hosts.unavailable) return 'failed'
  const refs = await window.odin.hostsReferences({ alias })
  if (!refs.ok && isUnavailable(refs.error)) {
    refuseHosts()
    return 'failed'
  }
  if (!refs.ok) {
    management.notes[`host:${alias}`] = failure(refs)
    return 'failed'
  }
  hosts.references[alias] = refs.result.references
  if (refs.result.references.length) return 'blocked'
  const ok = await hostAct(`host:${alias}`, () => window.odin.hostsDelete({ alias }), () => 'Deleted.')
  return ok ? 'deleted' : 'failed'
}

export async function forceRevoke(alias: string): Promise<void> {
  await hostAct(
    `host:${alias}`,
    () => window.odin.hostsForceRevoke({ alias }),
    (r) =>
      `Revoked. ${r.leases_interrupted} running uses interrupted; processes: ${r.processes.killed} stopped, ${r.processes.unknown} unknown.`
  )
}
