// The settings menu's state: Odin's settings as the core describes them (GET /api/config/meta shape), saved one field
// at a time through settings.set or the field's dedicated method, plus the Codex accounts with their device login.
import { reactive } from 'vue'
import {
  SETTINGS_SHAPED,
  type CodexAccount,
  type CodexStatus,
  type ConfigField,
  type ConfigMeta,
  type ImageLeaf,
  type Result,
  type SettingsSetParams,
  type SettingsSetResult
} from '../../../shared/api'
import { dedicatedMethod, imageLeafOf, isSecret, settingsShapedMethod } from '../settings-form'

export interface FieldState {
  status: 'saving' | 'saved' | 'error'
  message?: string
}

export interface LoginState {
  code: string
  url: string
  deviceAuthId: string
  interval: number
  status: 'waiting' | 'done' | 'expired' | 'failed' | 'stopped'
  message?: string
}

export const settings = reactive({
  meta: null as ConfigMeta | null,
  error: '',
  notice: '',
  fields: {} as Record<string, FieldState | undefined>,
  codex: {
    status: null as CodexStatus | null,
    error: '',
    busy: false,
    /** The list couldn't be refreshed after a change, so its indexes may be out of date: nothing acts on it. */
    stale: false,
    /** What the last action on an account said, by the account's identity (indexes shift when one is removed). */
    notes: {} as Record<string, string | undefined>,
    login: null as LoginState | null
  }
})

function message(result: Result<unknown>): string {
  return result.ok ? '' : result.error.message
}

/** Moves on with every read and every adopted answer, so an older read never replaces something newer. */
let settingsGeneration = 0

export async function loadSettings(): Promise<void> {
  const mine = ++settingsGeneration
  const result = await window.odin.settingsSchema()
  if (mine !== settingsGeneration) return
  if (!result.ok) {
    settings.error = result.error.message
    return
  }
  settings.error = ''
  settings.meta = result.result
}

/** Replaces the records a save returned, so each field shows what saving did and what runs now. */
function adopt(revision: string, records: readonly ConfigField[]): void {
  if (!settings.meta) return
  settingsGeneration += 1
  settings.meta.revision = revision
  for (const record of records) {
    const index = settings.meta.fields.findIndex((f) => f.path === record.path)
    if (index >= 0) settings.meta.fields[index] = record
  }
}

/** The core refused because settings changed elsewhere: show the current ones and say so. */
async function changedElsewhere(path: string): Promise<void> {
  await loadSettings()
  settings.fields[path] = { status: 'error', message: 'Settings changed elsewhere, so they were reloaded. Check, then save again.' }
}

/** The method that saves a field: its owner's settings-shaped method, which runs the owner's transaction, or settings.set. */
function saverFor(field: ConfigField): (params: SettingsSetParams) => Promise<Result<SettingsSetResult>> {
  const method = settingsShapedMethod(field)
  return method ? (params) => window.odin[SETTINGS_SHAPED[method].call](params) : (params) => window.odin.settingsSet(params)
}

/** Saves one field: through its dedicated method when Odin applies it that way, otherwise settings.set. */
export async function saveField(field: ConfigField, value: unknown): Promise<boolean> {
  if (!settings.meta || isSecret(field)) return false
  settings.fields[field.path] = { status: 'saving' }
  const method = dedicatedMethod(field)
  if (method) {
    const key = field.path.split('.').pop() as string
    const result = await window.odin.editLeaf({ method, params: { [key]: value } })
    if (!result.ok) {
      settings.fields[field.path] = { status: 'error', message: message(result) }
      return false
    }
    await loadSettings() // a dedicated method returns its own shape; the records come from the core
    settings.fields[field.path] = { status: 'saved' }
    return true
  }
  const result = await saverFor(field)({ expected_revision: settings.meta.revision, changes: [{ path: field.path, value }] })
  if (!result.ok) {
    if (result.error.code === 'stale_binding') await changedElsewhere(field.path)
    else settings.fields[field.path] = { status: 'error', message: message(result) }
    return false
  }
  adopt(result.result.revision, result.result.fields)
  if (imageLeafOf(field)) await loadSettings() // its follow/pin intent and revision changed too
  settings.fields[field.path] = { status: 'saved' }
  return true
}

/**
 * An image model follows Odin's shipped default, or is pinned to the value in effect now, even one equal to the
 * default. Bound to the intent's own revision.
 */
export async function setImageIntent(leaf: ImageLeaf, operation: 'follow' | 'pin'): Promise<boolean> {
  const revision = settings.meta?.image_models_revision
  if (!revision) return false
  const path = `image.openai.${leaf}`
  settings.fields[path] = { status: 'saving' }
  const result = await window.odin.imageModelIntent({ expected_revision: revision, operations: { [leaf]: operation } })
  if (!result.ok) {
    if (result.error.code === 'stale_binding') await changedElsewhere(path)
    else settings.fields[path] = { status: 'error', message: message(result) }
    return false
  }
  await loadSettings() // the saved values changed with the intent
  settings.fields[path] = { status: 'saved' }
  return true
}

/** Back to Odin's default for that field. */
export async function resetField(field: ConfigField): Promise<boolean> {
  if (!settings.meta || isSecret(field) || dedicatedMethod(field)) return false
  settings.fields[field.path] = { status: 'saving' }
  const result = await saverFor(field)({ expected_revision: settings.meta.revision, changes: [{ path: field.path, delete: true }] })
  if (!result.ok) {
    if (result.error.code === 'stale_binding') await changedElsewhere(field.path)
    else settings.fields[field.path] = { status: 'error', message: message(result) }
    return false
  }
  adopt(result.result.revision, result.result.fields)
  if (imageLeafOf(field)) await loadSettings() // back to following, with a new revision
  settings.fields[field.path] = { status: 'saved' }
  return true
}

/** Secrets are write-only: the window sends a new value or clears it, and never reads one back. */
export async function setSecret(field: ConfigField, value: string): Promise<boolean> {
  settings.fields[field.path] = { status: 'saving' }
  const result = await window.odin.secretsSet({ path: field.path, value })
  settings.fields[field.path] = result.ok ? { status: 'saved' } : { status: 'error', message: message(result) }
  if (result.ok) await loadSettings()
  return result.ok
}

export async function clearSecret(field: ConfigField): Promise<boolean> {
  settings.fields[field.path] = { status: 'saving' }
  const result = await window.odin.secretsClear({ path: field.path })
  settings.fields[field.path] = result.ok ? { status: 'saved' } : { status: 'error', message: message(result) }
  if (result.ok) await loadSettings()
  return result.ok
}

// ---- Codex accounts ------------------------------------------------------------------------------------------------

export async function loadCodex(): Promise<boolean> {
  const result = await window.odin.codexAccounts()
  if (!result.ok) {
    settings.codex.error = result.error.message
    return false
  }
  settings.codex.error = ''
  settings.codex.status = result.result
  settings.codex.stale = false
  return true
}

/** Who an account is, apart from its place in the list. */
export function accountIdentity(account: CodexAccount): string {
  return account.account_id ?? account.email ?? `#${account.index}`
}

/**
 * Acts on the account the user saw, by its index, only if that index still holds it. The controls stay locked until
 * the list is refreshed, since a removal shifts every index after it; if refreshing fails, they stay locked.
 */
async function accountAction(account: CodexAccount, run: (index: number) => Promise<Result<unknown>>, done: string): Promise<void> {
  if (settings.codex.busy || settings.codex.stale) return
  const identity = accountIdentity(account)
  const now = settings.codex.status?.accounts.find((a) => a.index === account.index)
  if (!now || accountIdentity(now) !== identity) {
    settings.codex.notes[identity] = 'The accounts changed. Check the list, then try again.'
    return
  }
  settings.codex.busy = true
  try {
    const result = await run(account.index)
    settings.codex.notes[identity] = result.ok ? done : message(result)
    if (!(await loadCodex())) settings.codex.stale = true
  } finally {
    settings.codex.busy = false
  }
}

export const activateAccount = (account: CodexAccount): Promise<void> =>
  accountAction(account, (index) => window.odin.codexActivate({ index }), 'Now the active account.')
export const labelAccount = (account: CodexAccount, label: string): Promise<void> =>
  accountAction(account, (index) => window.odin.codexLabel({ index, label }), 'Label saved.')
export const removeAccount = (account: CodexAccount): Promise<void> =>
  accountAction(account, (index) => window.odin.codexRemove({ index }), 'Removed.')

let loginRun = 0

/** Starts a device-code login: the user approves in the browser, and the window checks at the code's interval. */
export async function beginLogin(): Promise<void> {
  const begun = await window.odin.codexLoginBegin()
  if (!begun.ok) {
    settings.codex.error = begun.error.message
    return
  }
  const run = ++loginRun
  const { device_auth_id: deviceAuthId, user_code: code, interval, verify_url: url } = begun.result
  settings.codex.login = { code, url, deviceAuthId, interval, status: 'waiting' }
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, Math.max(1, interval) * 1000))
    if (run !== loginRun || settings.codex.login?.status !== 'waiting') return
    const polled = await window.odin.codexLoginPoll({ device_auth_id: deviceAuthId, user_code: code })
    if (run !== loginRun) return
    if (!polled.ok) {
      const expired = polled.error.code === 'expired'
      settings.codex.login = { ...settings.codex.login, status: expired ? 'expired' : 'failed', message: polled.error.message }
      return
    }
    if (polled.result.status === 'authenticated') {
      settings.codex.login = { ...settings.codex.login, status: 'done', message: `Signed in as ${polled.result.email}.` }
      await loadCodex()
      return
    }
  }
}

/** Stops waiting here. A login the user still completes in the browser is added by the core all the same, as in Odin. */
export function stopLogin(): void {
  loginRun += 1
  if (settings.codex.login?.status === 'waiting') settings.codex.login = { ...settings.codex.login, status: 'stopped' }
}
