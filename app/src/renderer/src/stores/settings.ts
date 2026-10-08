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
import { dedicatedMethod, editableHere, imageLeafOf, isSecret, settingsShapedMethod } from '../settings-form'
import { isUnavailable } from '../capability'
import { refreshStatus } from './status'
import { state as appState } from '../store'

export interface FieldState {
  status: 'saving' | 'saved' | 'error'
  message?: string
}

export interface LoginState {
  code: string
  url: string
  loginId: string
  interval: number
  status: 'waiting' | 'done' | 'expired' | 'failed' | 'stopped'
  message?: string
}

export const settings = reactive({
  meta: null as ConfigMeta | null,
  error: '',
  unavailable: false,
  notice: '',
  unknownSave: false,
  fields: {} as Record<string, FieldState | undefined>,
  codex: {
    status: null as CodexStatus | null,
    error: '',
    unavailable: false,
    busy: false,
    beginning: false,
    /** No list read since the last account action is in, so its indexes may be out of date: nothing acts on it. */
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

export async function loadSettings(explicit = false): Promise<void> {
  const mine = ++settingsGeneration
  const epoch = appState.recoveryEpoch
  const instance = appState.app.coreInstanceId
  const result = await window.odin.settingsSchema()
  if (mine !== settingsGeneration || epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId) return
  if (!result.ok) {
    if (isUnavailable(result.error)) {
      settings.meta = null
      settings.unavailable = true
      settings.error = ''
      return
    }
    settings.unavailable = false
    settings.error = result.error.message
    return
  }
  settings.unavailable = false
  settings.error = ''
  settings.meta = result.result
  if (explicit) { settings.unknownSave = false; settings.notice = '' }
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

/** Capture editing shape as well as the write owner before queuing deliberate intent. */
function fieldAuthority(field: ConfigField | undefined): string {
  return JSON.stringify(field && [field.apply_handler, field.sensitivity, field.type, field.enum, field.constraints, field.nullable, field.record_members])
}

// All generic settings owners share the configuration revision. Serialize deliberate mutations,
// but a failed/unknown settlement invalidates already queued intent. No automatic resubmission.
let mutationTail: Promise<unknown> = Promise.resolve()
let mutationFence = 0
/** Dedicated grouped workflows share the same revision fence as ordinary fields. */
function queueMutation(run: () => Promise<boolean>): Promise<boolean> {
  const fence = mutationFence
  const epoch = appState.recoveryEpoch
  const instance = appState.app.coreInstanceId
  const result = mutationTail.then(async () => {
    if (fence !== mutationFence || epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId || settings.unknownSave) {
      settings.notice = 'An earlier change did not complete, or settings changed. Refresh, check, then save again.'
      return false
    }
    try {
      const saved = await run()
      if (!saved) mutationFence += 1
      return saved
    } catch {
      mutationFence += 1
      settings.unknownSave = true
      settings.notice = 'The save outcome could not be confirmed. Refresh saved settings and check before submitting again.'
      return false
    }
  })
  mutationTail = result.then(() => undefined, () => undefined)
  return result
}
function unknownResult(result: Result<unknown>): void {
  if (!result.ok && (['no_receipt', 'outcome_unknown', 'unknown'].includes(result.error.code) || result.error.disposition === 'outcome_unknown')) {
    settings.unknownSave = true
    settings.notice = 'The save outcome could not be confirmed. Refresh saved settings and check before submitting again.'
  }
}
async function guardedSettlement(run: () => Promise<boolean>): Promise<boolean> {
  const epoch = appState.recoveryEpoch
  const instance = appState.app.coreInstanceId
  const result = await run()
  if (epoch === appState.recoveryEpoch && instance === appState.app.coreInstanceId) return result
  settings.unknownSave = true
  settings.notice = 'Odin changed while saving. Refresh saved settings and check before submitting again.'
  for (const path of Object.keys(settings.fields)) if (settings.fields[path]?.status === 'saving' || settings.fields[path]?.status === 'saved') settings.fields[path] = { status: 'error', message: settings.notice }
  return false
}
/** A settings-affecting management command must not race ordinary settings saves. */
export function settingsCommand<T>(run: (revision: string) => Promise<Result<T>>): Promise<Result<T>> {
  const fence = mutationFence
  const epoch = appState.recoveryEpoch
  const instance = appState.app.coreInstanceId
  const queued = mutationTail.then(async (): Promise<Result<T>> => {
    if (fence !== mutationFence || epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId || settings.unknownSave || !settings.meta) return { ok: false, error: { code: 'stale_binding', message: 'Refresh saved settings and check before submitting again.' } }
    try {
      settingsGeneration += 1
      const result = await run(settings.meta.revision)
      if (epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId) {
        settings.unknownSave = true; mutationFence += 1
        settings.notice = 'Odin changed while saving. Refresh saved settings and check before submitting again.'
        return { ok: false, error: { code: 'outcome_unknown', disposition: 'outcome_unknown', message: settings.notice } }
      }
      unknownResult(result)
      if (!result.ok) mutationFence += 1
      return result
    } catch {
      mutationFence += 1; settings.unknownSave = true
      settings.notice = 'The save outcome could not be confirmed. Refresh saved settings and check before submitting again.'
      return { ok: false, error: { code: 'outcome_unknown', disposition: 'outcome_unknown', message: settings.notice } }
    }
  })
  mutationTail = queued.then(() => undefined, () => undefined)
  return queued
}
/** One provider-owner transaction. Never split dependent values into sequential writes. */
export function saveFields(changes: readonly { field: ConfigField; value: unknown }[]): Promise<boolean> {
  const epoch = appState.recoveryEpoch
  const instance = appState.app.coreInstanceId
  const authority = fieldAuthority
  const bindings = new Map(changes.map(({ field }) => [field.path, authority(field)]))
  return queueMutation(async () => {
    if (!settings.meta || !changes.length) return false
    const latest = changes.map((change) => ({ ...change, latest: settings.meta!.fields.find((item) => item.path === change.field.path) }))
    if (latest.some(({ field, latest }) => !latest || bindings.get(field.path) !== authority(latest) || isSecret(latest) || !editableHere(latest) || dedicatedMethod(latest))) { settings.notice = 'These settings changed. Refresh, check, then save again.'; return false }
    const owners = new Set(latest.map(({ latest }) => settingsShapedMethod(latest!)))
    if (owners.size !== 1) { settings.notice = 'These settings cannot be saved together.'; return false }
    for (const { field } of latest) settings.fields[field.path] = { status: 'saving' }
    settingsGeneration += 1
    const result = await saverFor(latest[0]!.latest!)({ expected_revision: settings.meta.revision, changes: latest.map(({ field, value }) => ({ path: field.path, value })) })
    if (epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId) { settings.unknownSave = true; settings.notice = 'Odin changed while saving. Refresh saved settings and check before submitting again.'; for (const { field } of latest) settings.fields[field.path] = { status: 'error', message: settings.notice }; return false }
    unknownResult(result)
    if (!result.ok) {
      if (result.error.code === 'stale_binding') await loadSettings()
      for (const { field } of latest) settings.fields[field.path] = { status: 'error', message: result.error.code === 'stale_binding' ? 'Settings changed elsewhere. Check, then save again.' : result.error.message }
      return false
    }
    adopt(result.result.revision, result.result.fields)
    await refreshStatus()
    if (epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId) { settings.unknownSave = true; settings.notice = 'Odin changed while saving. Refresh saved settings and check before submitting again.'; for (const { field } of latest) settings.fields[field.path] = { status: 'error', message: settings.notice }; return false }
    for (const { field } of latest) settings.fields[field.path] = { status: 'saved' }
    return true
  })
}
/** Main/agent policy methods return their own shape; refresh rather than manufacture field receipts. */
export function saveModelSettings(method: 'models.main.set' | 'models.agents.set', params: Record<string, unknown>): Promise<boolean> {
  const path = method === 'models.main.set' ? 'llm_provider.model' : 'agents.model'
  const binding = settings.meta?.fields.find((field) => field.path === path)
  const authority = fieldAuthority
  const bindingAuthority = authority(binding)
  const dependent = method === 'models.main.set'
    ? ['openai_codex.reasoning_effort', 'openai_compatible.reasoning_effort']
    : Object.keys(params).map((key) => `agents.${key}`)
  const dependentBindings = new Map(dependent.map((path) => [path, authority(settings.meta?.fields.find((field) => field.path === path))]))
  const epoch = appState.recoveryEpoch
  const instance = appState.app.coreInstanceId
  return queueMutation(async () => {
    const current = settings.meta?.fields.find((field) => field.path === path)
    if (!settings.meta || !binding || !current || current.apply_handler !== method || bindingAuthority !== authority(current)) { settings.fields[path] = { status: 'error', message: 'This setting changed. Refresh, check, then save again.' }; return false }
    if (dependent.some((path) => dependentBindings.get(path) !== authority(settings.meta?.fields.find((field) => field.path === path)))) { settings.fields[path] = { status: 'error', message: 'Related model settings changed. Refresh, check, then save again.' }; return false }
    settings.fields[path] = { status: 'saving' }
    settingsGeneration += 1
    const result = await window.odin.editLeaf({ method, params: { ...params, expected_revision: settings.meta.revision } })
    if (epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId) { settings.unknownSave = true; settings.notice = 'Odin changed while saving. Refresh saved settings and check before submitting again.'; settings.fields[path] = { status: 'error', message: settings.notice }; return false }
    unknownResult(result)
    if (!result.ok) {
      if (result.error.code === 'stale_binding') await changedElsewhere(path)
      else settings.fields[path] = { status: 'error', message: result.error.message }
      return false
    }
    await loadSettings()
    await refreshStatus()
    if (epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId) { settings.unknownSave = true; settings.notice = 'Odin changed while saving. Refresh saved settings and check before submitting again.'; settings.fields[path] = { status: 'error', message: settings.notice }; return false }
    if (settings.error || settings.unavailable) { settings.fields[path] = { status: 'error', message: 'Saved settings could not be refreshed. Check them before relying on this change.' }; return false }
    settings.fields[path] = { status: 'saved' }
    return true
  })
}
export function saveField(field: ConfigField, value: unknown): Promise<boolean> {
  const fence = mutationFence
  const epoch = appState.recoveryEpoch
  const instance = appState.app.coreInstanceId
  const authority = fieldAuthority(field)
  const run = mutationTail.then(async () => {
    if (fence !== mutationFence) {
      settings.fields[field.path] = { status: 'error', message: 'An earlier save did not complete. Check the current settings, then save this change again.' }
      return false
    }
    if (settings.unknownSave) { settings.fields[field.path] = { status: 'error', message: 'A save outcome is unknown. Refresh saved settings and check before submitting again.' }; return false }
    try {
      const latest = settings.meta?.fields.find((record) => record.path === field.path)
      if (!latest || epoch !== appState.recoveryEpoch || instance !== appState.app.coreInstanceId || authority !== fieldAuthority(latest)) {
        mutationFence += 1
        settings.fields[field.path] = { status: 'error', message: 'The setting or its write authority changed. Refresh, check, then submit again.' }
        return false
      }
      settingsGeneration += 1
      const saved = await saveFieldNow(latest, value)
      if (!saved) mutationFence += 1
      return saved
    } catch {
      mutationFence += 1
      settings.unknownSave = true
      settings.notice = 'A save outcome is unknown. Refresh saved settings and check before submitting again.'
      settings.fields[field.path] = { status: 'error', message: 'The save outcome could not be confirmed. Refresh and check the value before submitting again.' }
      return false
    }
  })
  mutationTail = run.then(() => undefined, () => undefined)
  return run
}

/** Saves through the metadata's owner, never a presentation routing table. */
async function saveFieldNow(field: ConfigField, value: unknown): Promise<boolean> {
  const epoch = appState.recoveryEpoch
  const instance = appState.app.coreInstanceId
  const current = (): boolean => {
    if (epoch === appState.recoveryEpoch && instance === appState.app.coreInstanceId) return true
    settings.unknownSave = true
    settings.notice = 'A save settled after the core changed. Refresh saved settings and check before submitting again.'
    settings.fields[field.path] = { status: 'error', message: settings.notice }
    return false
  }
  const uncertain = (result: Result<unknown>): void => {
    if (!result.ok && (['no_receipt', 'outcome_unknown', 'unknown'].includes(result.error.code) || result.error.disposition === 'outcome_unknown')) {
      settings.unknownSave = true
      settings.notice = 'A save outcome is unknown. Refresh saved settings and check before submitting again.'
    }
  }
  if (!settings.meta || isSecret(field) || !editableHere(field)) return false
  settings.fields[field.path] = { status: 'saving' }
  const method = dedicatedMethod(field)
  if (method) {
    const key = field.path.split('.').pop() as string
    const result = await window.odin.editLeaf({ method, params: { [key]: value, expected_revision: settings.meta.revision } })
    if (!current()) return false
    uncertain(result)
    if (!result.ok) {
      if (result.error.code === 'stale_binding') await changedElsewhere(field.path)
      else settings.fields[field.path] = { status: 'error', message: message(result) }
      return false
    }
    await loadSettings() // a dedicated method returns its own shape; the records come from the core
    await refreshStatus()
    if (!current()) return false
    settings.fields[field.path] = { status: 'saved' }
    return true
  }
  const result = await saverFor(field)({ expected_revision: settings.meta.revision, changes: [{ path: field.path, value }] })
  if (!current()) return false
  uncertain(result)
  if (!result.ok) {
    if (['no_receipt', 'outcome_unknown', 'unknown'].includes(result.error.code) || result.error.disposition === 'outcome_unknown') {
      settings.unknownSave = true
      settings.notice = 'A save outcome is unknown. Refresh saved settings and check before submitting again.'
    }
    if (result.error.code === 'stale_binding') await changedElsewhere(field.path)
    else settings.fields[field.path] = { status: 'error', message: message(result) }
    return false
  }
  adopt(result.result.revision, result.result.fields)
  if (imageLeafOf(field)) await loadSettings() // its follow/pin intent and revision changed too
  settings.fields[field.path] = { status: 'saved' }
  await refreshStatus()
  return true
}

/**
 * An image model follows Odin's shipped default, or is pinned to the value in effect now, even one equal to the
 * default. Bound to the intent's own revision.
 */
export function setImageIntent(leaf: ImageLeaf, operation: 'follow' | 'pin'): Promise<boolean> {
  return queueMutation(() => guardedSettlement(() => setImageIntentNow(leaf, operation)))
}
async function setImageIntentNow(leaf: ImageLeaf, operation: 'follow' | 'pin'): Promise<boolean> {
  const revision = settings.meta?.image_models_revision
  if (!revision) return false
  const path = `image.openai.${leaf}`
  settings.fields[path] = { status: 'saving' }
  const result = await window.odin.imageModelIntent({ expected_revision: revision, operations: { [leaf]: operation } })
  unknownResult(result)
  if (!result.ok) {
    if (result.error.code === 'stale_binding') await changedElsewhere(path)
    else settings.fields[path] = { status: 'error', message: message(result) }
    return false
  }
  await loadSettings() // the saved values changed with the intent
  settings.fields[path] = { status: 'saved' }
  await refreshStatus()
  return true
}

/** Back to Odin's default for that field. */
export function resetField(field: ConfigField): Promise<boolean> {
  return queueMutation(() => guardedSettlement(() => resetFieldNow(field)))
}
async function resetFieldNow(field: ConfigField): Promise<boolean> {
  if (!settings.meta || isSecret(field) || dedicatedMethod(field)) return false
  settings.fields[field.path] = { status: 'saving' }
  const result = await saverFor(field)({ expected_revision: settings.meta.revision, changes: [{ path: field.path, delete: true }] })
  unknownResult(result)
  if (!result.ok) {
    if (result.error.code === 'stale_binding') await changedElsewhere(field.path)
    else settings.fields[field.path] = { status: 'error', message: message(result) }
    return false
  }
  adopt(result.result.revision, result.result.fields)
  if (imageLeafOf(field)) await loadSettings() // back to following, with a new revision
  settings.fields[field.path] = { status: 'saved' }
  await refreshStatus()
  return true
}

/** Secrets are write-only: the window sends a new value or clears it, and never reads one back. */
export function setSecret(field: ConfigField, value: string): Promise<boolean> {
  const shown = { ...field }
  return queueMutation(() => guardedSettlement(() => setSecretNow(shown, value)))
}
async function setSecretNow(field: ConfigField, value: string): Promise<boolean> {
  const latest = settings.meta?.fields.find((item) => item.path === field.path)
  if (!latest || latest.sensitivity !== 'sensitive' || field.sensitivity !== 'sensitive' || latest.secret_route !== 'secrets.set' || field.secret_route !== 'secrets.set' || latest.apply_handler !== field.apply_handler) return false
  settings.fields[field.path] = { status: 'saving' }
  const result = await window.odin.secretsSet({ path: field.path, value })
  unknownResult(result)
  settings.fields[field.path] = result.ok ? { status: 'saved' } : { status: 'error', message: message(result) }
  if (result.ok) await loadSettings()
  await refreshStatus()
  return result.ok
}

export function clearSecret(field: ConfigField): Promise<boolean> {
  const shown = { ...field }
  return queueMutation(() => guardedSettlement(() => clearSecretNow(shown)))
}
async function clearSecretNow(field: ConfigField): Promise<boolean> {
  const latest = settings.meta?.fields.find((item) => item.path === field.path)
  if (!latest || latest.sensitivity !== 'sensitive' || field.sensitivity !== 'sensitive' || latest.secret_route !== 'secrets.set' || field.secret_route !== 'secrets.set' || latest.apply_handler !== field.apply_handler) return false
  settings.fields[field.path] = { status: 'saving' }
  const result = await window.odin.secretsClear({ path: field.path })
  unknownResult(result)
  settings.fields[field.path] = result.ok ? { status: 'saved' } : { status: 'error', message: message(result) }
  if (result.ok) await loadSettings()
  await refreshStatus()
  return result.ok
}

// ---- Codex accounts ------------------------------------------------------------------------------------------------

/** Each account list read, in order: an older answer never replaces a newer one. */
let codexRead = 0
/** The last read sent before the latest account action. Only a read sent after it can show where accounts are now. */
let codexActedAfter = 0

export async function loadCodex(): Promise<boolean> {
  const mine = ++codexRead
  const result = await window.odin.codexAccounts()
  if (mine !== codexRead) return false // a newer read owns the list
  if (!result.ok) {
    if (isUnavailable(result.error)) {
      settings.codex.status = null
      settings.codex.unavailable = true
      settings.codex.error = ''
      settings.codex.stale = false
      settings.codex.notes = {}
      settings.codex.login = null
      return false
    }
    settings.codex.unavailable = false
    settings.codex.error = result.error.message
    return false
  }
  settings.codex.unavailable = false
  settings.codex.error = ''
  settings.codex.status = result.result
  if (mine > codexActedAfter) settings.codex.stale = false
  return true
}

/**
 * Who an account is, apart from its place in the list: its ID, or else its email. An account with neither has only
 * its place, so for it the list being current is the only check.
 */
export function accountIdentity(account: CodexAccount): string {
  return account.account_id || account.email || `#${account.index}`
}

/**
 * Acts on the account the user saw, by its index, only if that index still holds it. A removal shifts every index
 * after it, so the controls stay locked until a list read after the action is in; if that read fails, they stay
 * locked.
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
  settings.codex.stale = true
  codexActedAfter = codexRead
  try {
    const result = await run(account.index)
    settings.codex.notes[identity] = result.ok ? done : message(result)
    await loadCodex()
    await refreshStatus()
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
  if (settings.codex.beginning || settings.codex.login?.status === 'waiting') return
  const run = ++loginRun
  settings.codex.beginning = true
  const begun = await window.odin.codexLoginBegin().finally(() => { settings.codex.beginning = false })
  if (run !== loginRun) return
  if (!begun.ok) {
    settings.codex.error = begun.error.message
    return
  }
  settings.codex.error = ''
  const { login_id: loginId, user_code: code, interval, verify_url: url } = begun.result
  settings.codex.login = { code, url, loginId, interval, status: 'waiting' }
  await pollLogin(run)
}

/** Retry the same device login after a keyring/transport failure; the core retains authorization until expiry. */
export async function retryLogin(): Promise<void> {
  if (settings.codex.login?.status !== 'failed') return
  settings.codex.login = { ...settings.codex.login, status: 'waiting', message: undefined }
  await pollLogin(++loginRun)
}

async function pollLogin(run: number): Promise<void> {
  const login = settings.codex.login
  if (!login) return
  const { loginId, interval } = login
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, Math.max(1, interval) * 1000))
    if (run !== loginRun || settings.codex.login?.status !== 'waiting') return
    const polled = await window.odin.codexLoginPoll({ login_id: loginId })
    if (run !== loginRun) return
    if (!polled.ok) {
      const expired = polled.error.code === 'expired'
      settings.codex.login = { ...settings.codex.login, status: expired ? 'expired' : 'failed', message: polled.error.message }
      await refreshStatus()
      return
    }
    if (polled.result.status === 'authenticated') {
      settings.codex.login = { ...settings.codex.login, status: 'done', message: `Signed in as ${polled.result.email}.` }
      await loadCodex()
      await refreshStatus()
      return
    }
  }
}

/** Stops polling here; the core does not finish device login without a subsequent poll. */
export function stopLogin(): void {
  loginRun += 1
  if (settings.codex.login?.status === 'waiting') settings.codex.login = { ...settings.codex.login, status: 'stopped' }
}
