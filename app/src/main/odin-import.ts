// Import from Odin: read an Odin install through its own HTTP API with the user's admin token, then write each
// picked item through Odin Desktop's ordinary core methods, so their validation, owners and revisions all apply.
// The token is sent to the given address for these requests only; it is never stored or logged.
//
// "Already in Odin Desktop" is kept, not replaced: every create is either create-only in its owner (skills,
// presets, memory) or bound to the revision it was checked against (MCP servers, host commits), so something
// added while the import runs is never overwritten. A change the core doesn't confirm stops the import.
import { createHash } from 'node:crypto'
import type {
  OdinImportCategory,
  OdinImportItem,
  OdinImportOutcome,
  OdinImportPick,
  OdinImportPreview,
  OdinImportReport,
  OdinImportSource,
  Result
} from '../shared/api'
import type { Settled } from './broker'

/** What Odin's API shows in place of a value it never returns (Odin's apply_registry REDACTED). */
export const ODIN_REDACTED = '•'.repeat(8)
const REQUEST_TIMEOUT_MS = 15_000
const MCP_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/
const LOCAL_ADDRESS = /^(localhost|127\.\d+\.\d+\.\d+|::1|\[::1\])$/i
/** The current-personality action; saved presets use `preset:<name>`, so the two can never collide. */
const CURRENT_PERSONALITY = 'current'
const PRESET = 'preset:'
/** The settings the "Settings" group offers, each written through the handler the core names for it. */
const SETTING_PATHS = {
  agent_effort: 'openai_codex.agent_reasoning_effort',
  max_agents: 'agents.max_concurrent_agents',
  context: 'openai_codex.context_utilization',
  timezone: 'timezone'
} as const
const SETTINGS_WRITERS = new Set([
  'settings.set', 'providers.codex.set', 'providers.auxiliary.set', 'providers.ollama.set', 'providers.compat.set'
])

export interface ImportBroker {
  request(method: string, params?: Record<string, unknown>, id?: string): Promise<Settled>
}

export type FetchLike = (
  url: string,
  init: { headers: Record<string, string>; signal: AbortSignal; redirect: 'error' }
) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>

class ImportError extends Error {}
/** A change was sent but the core didn't confirm it; nothing after it may run. */
class Unconfirmed extends Error {}

type Json = Record<string, unknown>
const record = (value: unknown): Json =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {}
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])
const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const plural = (count: number, one: string, many: string): string => `${count} ${count === 1 ? one : many}`

/** Odin's API lives at the root, so a pasted WebUI link such as http://host:3002/ui/ still works. */
function origin(source: OdinImportSource): string {
  let url: URL
  try {
    url = new URL(source.url.trim())
  } catch {
    throw new ImportError('Enter an http:// or https:// address.')
  }
  if (url.protocol === 'http:' && !LOCAL_ADDRESS.test(url.hostname) && source.allow_insecure_http !== true) {
    throw new ImportError(
      "This address isn't encrypted, so the token would cross the network in plain text. Use https://, or confirm unencrypted HTTP for a network you trust."
    )
  }
  return url.origin
}

async function odinGet(source: OdinImportSource, path: string, fetchImpl: FetchLike): Promise<unknown> {
  const address = origin(source)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    let response: Awaited<ReturnType<FetchLike>>
    try {
      // A redirect could carry the token to another host, so it is an error, never followed.
      response = await fetchImpl(`${address}${path}`, {
        headers: { Authorization: `Bearer ${source.token}`, Accept: 'application/json' },
        signal: controller.signal,
        redirect: 'error'
      })
    } catch {
      throw new ImportError(`Couldn't reach Odin at ${address}. Check the address and that Odin is running.`)
    }
    if (response.status === 401 || response.status === 403) {
      throw new ImportError("Odin didn't accept this token. Use an admin API token from Odin's WebUI.")
    }
    if (!response.ok) throw new ImportError(`Odin answered ${response.status}. Check that this is Odin's address.`)
    try {
      return await response.json()
    } catch {
      throw new ImportError("That address didn't answer like Odin's API.")
    }
  } finally {
    clearTimeout(timer)
  }
}

async function desktopCall(broker: ImportBroker, method: string, params: Record<string, unknown> = {}): Promise<Json> {
  const settled = await broker.request(method, params)
  if (!settled.ok) throw new ImportError(settled.error.message || 'Odin Desktop could not read its own settings.')
  return record(settled.result)
}

interface OdinSnapshot {
  memory: Json
  skills: Json[]
  config: Json
  personality: Json
}

async function readOdin(source: OdinImportSource, fetchImpl: FetchLike): Promise<OdinSnapshot> {
  origin(source)
  const [memory, skills, config, personality] = await Promise.all([
    odinGet(source, '/api/memory', fetchImpl),
    odinGet(source, '/api/skills', fetchImpl),
    odinGet(source, '/api/config', fetchImpl),
    odinGet(source, '/api/personality', fetchImpl)
  ])
  return { memory: record(memory), skills: list(skills).map(record), config: record(config), personality: record(personality) }
}

interface DesktopSnapshot {
  skills: Set<string>
  mcp: Set<string>
  presets: Set<string>
  hosts: Set<string>
}

const mcpNames = (status: Json): Set<string> => new Set(list(status.servers).map((row) => text(record(row).name)))
const hostNames = (hosts: Json): Set<string> => new Set(list(hosts.hosts).map((row) => text(record(row).alias)))

async function readDesktop(broker: ImportBroker): Promise<DesktopSnapshot> {
  const [skills, mcp, personality, hosts] = await Promise.all([
    broker.request('skills.list', {}),
    desktopCall(broker, 'mcp.status'),
    desktopCall(broker, 'personality.get'),
    desktopCall(broker, 'hosts.list')
  ])
  if (!skills.ok) throw new ImportError(skills.error.message || 'Odin Desktop could not list its skills.')
  return {
    skills: new Set(list(skills.result).map((row) => text(record(row).name))),
    mcp: mcpNames(mcp),
    presets: new Set([...list(personality.user_presets).map(text), ...list(personality.builtin_presets).map(text)]),
    hosts: hostNames(hosts)
  }
}

/** Values Odin never returns: the keys of a map whose values came back as the placeholder. */
function hiddenKeys(map: unknown): string[] {
  return Object.entries(record(map)).filter(([, value]) => value === ODIN_REDACTED).map(([key]) => key)
}

function shownValues(map: unknown): Record<string, string> {
  return Object.fromEntries(
    Object.entries(record(map)).filter(([, value]) => typeof value === 'string' && value !== ODIN_REDACTED)
  ) as Record<string, string>
}

/** OpenSSH's SHA256 fingerprint of a public key line, as Odin Desktop's host trust compares them. */
export function fingerprintOf(line: string): string | null {
  const parts = line.trim().split(/\s+/)
  const index = parts.findIndex((part) => /^(ssh-|ecdsa-|sk-)/.test(part))
  const encoded = index >= 0 ? parts[index + 1] : undefined
  if (!encoded || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) return null
  const digest = createHash('sha256').update(Buffer.from(encoded, 'base64')).digest('base64').replace(/=+$/, '')
  return `SHA256:${digest}`
}

function mcpServers(config: Json): Array<[string, Json]> {
  return Object.entries(record(record(config.mcp).servers)).map(([name, value]) => [name, record(value)])
}

function remoteHosts(config: Json): Array<[string, Json]> {
  return Object.entries(record(record(config.tools).hosts))
    .map(([alias, value]): [string, Json] => [alias, record(value)])
    .filter(([, host]) => !LOCAL_ADDRESS.test(text(host.address)))
}

function userPresets(personality: Json): Array<[string, Json]> {
  const presets = record(personality.presets)
  return list(personality.user_presets).map(text).filter(Boolean).map((name): [string, Json] => [name, record(presets[name])])
}

/** Only the providers that take a reasoning effort get one: Codex and OpenAI-compatible, never Ollama. */
function mainEffort(config: Json): string {
  const model = text(record(config.llm_provider).model)
  if (model.startsWith('ollama:')) return ''
  const section = model.startsWith('compat:') ? config.openai_compatible : config.openai_codex
  return text(record(section).reasoning_effort)
}

function effortLabel(value: unknown): string {
  return value === null || value === undefined || value === '' ? 'Same as main' : value === 'auto' ? 'Automatic' : String(value)
}

function previewItems(odin: OdinSnapshot, desktop: DesktopSnapshot): OdinImportItem[] {
  const items: OdinImportItem[] = []
  // Shared memory first, then personal scopes largest first: the person's own is usually the biggest.
  const scopes = Object.entries(odin.memory).sort(([a, x], [b, y]) =>
    Number(b === 'global') - Number(a === 'global') || Number(record(y).count ?? 0) - Number(record(x).count ?? 0))
  for (const [scope, info] of scopes) {
    const keys = list(record(info).keys).map(text).filter(Boolean)
    const count = typeof record(info).count === 'number' ? (record(info).count as number) : keys.length
    if (!count) continue
    if (scope === 'global') {
      items.push({ category: 'memory', id: scope, label: "Odin's shared memory", detail: plural(count, 'entry', 'entries'),
        exists: false, notes: [], selected: true })
    } else {
      items.push({ category: 'memory', id: scope, label: `Personal memory ${scope.replace(/^user_/, '')}`,
        detail: `${plural(count, 'entry', 'entries')}: ${keys.slice(0, 3).join(', ')}${keys.length > 3 ? ', …' : ''}`,
        exists: false, notes: ['Saved as shared memory: Odin Desktop has one user.'], selected: false })
    }
  }
  for (const skill of odin.skills) {
    const name = text(skill.name)
    if (!name) continue
    const exists = desktop.skills.has(name)
    const status = text(skill.status)
    const notes = status === 'error' ? ["It doesn't load in Odin, so it may fail here too."]
      : status === 'disabled' ? ["It's off in Odin and stays off here."] : []
    items.push({ category: 'skills', id: name, label: name, detail: text(skill.description).slice(0, 160), exists, notes,
      selected: !exists && status !== 'disabled' })
  }
  for (const [name, server] of mcpServers(odin.config)) {
    const exists = desktop.mcp.has(name)
    const hidden = [...hiddenKeys(server.env), ...hiddenKeys(server.headers)]
    const notes = ['Imported switched off.']
    if (hidden.length) notes.push(`Re-enter in MCP servers → Edit: ${hidden.join(', ')}`)
    if (text(server.url) === ODIN_REDACTED) notes.push('Re-enter its URL in MCP servers → Edit.')
    const valid = MCP_NAME.test(name)
    if (!valid) notes.push('Odin Desktop server names use letters, digits and underscores only.')
    const target = text(server.transport) === 'http' ? 'http' : `stdio · ${text(server.command) || 'no command'}`
    items.push({ category: 'mcp', id: name, label: name, detail: target, exists, notes, selected: !exists && valid })
  }
  for (const [name, preset] of userPresets(odin.personality)) {
    const exists = desktop.presets.has(name)
    items.push({ category: 'personality', id: `${PRESET}${name}`, label: text(preset.name) || name,
      detail: 'Saved personality preset', exists, notes: [], selected: !exists })
  }
  const preset = text(odin.personality.preset)
  if (preset) {
    const current = preset === 'custom' ? `Custom: ${text(odin.personality.custom_name) || 'unnamed'}`
      : text(record(record(odin.personality.presets)[preset]).name) || preset
    const notes = ['Replaces the personality Odin Desktop uses now.']
    if (preset !== 'custom' && desktop.presets.has(preset)) notes.push("Uses Odin Desktop's own preset of the same name.")
    items.push({ category: 'personality', id: CURRENT_PERSONALITY, label: "Odin's current personality", detail: current,
      exists: false, notes, selected: false })
  }
  for (const [alias, host] of remoteHosts(odin.config)) {
    const exists = desktop.hosts.has(alias)
    const pinned = list(host.host_keys).map(text).some((line) => fingerprintOf(line) !== null)
    const target = `${text(host.ssh_user) || 'root'}@${text(host.address)}${host.port && host.port !== 22 ? `:${String(host.port)}` : ''}`
    items.push({ category: 'hosts', id: alias, label: alias, detail: target, exists,
      notes: pinned ? ["Needs Odin Desktop's SSH key on this host before it connects."]
        : ['Odin has no pinned key for this host. Add it in Hosts and access instead.'],
      selected: !exists && pinned })
  }
  const llm = record(odin.config.llm_provider)
  const agents = record(odin.config.agents)
  const codex = record(odin.config.openai_codex)
  if (text(llm.model)) {
    items.push({ category: 'models', id: 'main', label: 'Main model',
      detail: [text(llm.model), mainEffort(odin.config)].filter(Boolean).join(' · '), exists: false,
      notes: ['Its provider has to be set up in Odin Desktop.'], selected: false })
  }
  const agentModel = agents.model
  items.push({ category: 'models', id: 'agents', label: 'Agent model',
    detail: agentModel === 'auto' ? `Choose automatically from ${plural(list(agents.auto_model_allowlist).length, 'model', 'models')}`
      : text(agentModel) && agentModel !== 'inherit' ? text(agentModel) : 'Same as main',
    exists: false, notes: [], selected: false })
  items.push({ category: 'models', id: 'agent_effort', label: 'Agent reasoning effort',
    detail: effortLabel(codex.agent_reasoning_effort), exists: false, notes: [], selected: false })
  if (typeof agents.max_concurrent_agents === 'number') {
    items.push({ category: 'models', id: 'max_agents', label: 'Agents at once', detail: String(agents.max_concurrent_agents),
      exists: false, notes: [], selected: false })
  }
  if (typeof codex.context_utilization === 'number') {
    items.push({ category: 'models', id: 'context', label: 'Context use', detail: `${codex.context_utilization}%`,
      exists: false, notes: [], selected: false })
  }
  if (text(odin.config.timezone)) {
    items.push({ category: 'models', id: 'timezone', label: 'Time zone', detail: text(odin.config.timezone),
      exists: false, notes: [], selected: false })
  }
  return items
}

function failure(error: unknown): Result<never> {
  const message = error instanceof ImportError ? error.message : 'The import stopped unexpectedly.'
  return { ok: false, error: { code: 'import_failed', message, disposition: 'rejected' } }
}

export async function previewOdinImport(
  source: OdinImportSource,
  broker: ImportBroker,
  fetchImpl: FetchLike
): Promise<Result<OdinImportPreview>> {
  try {
    const [odin, desktop] = await Promise.all([readOdin(source, fetchImpl), readDesktop(broker)])
    return { ok: true, result: { items: previewItems(odin, desktop) } }
  } catch (error) {
    return failure(error)
  }
}

type Outcome = Omit<OdinImportOutcome, 'category' | 'id' | 'label'>
const done = (message: string): Outcome => ({ status: 'imported', message })
const skipped = (message: string): Outcome => ({ status: 'skipped', message })
const attention = (message: string): Outcome => ({ status: 'needs_attention', message })
const failed = (message: string): Outcome => ({ status: 'failed', message })
const ALREADY = 'Already in Odin Desktop.'
const CHANGED = "Odin Desktop's settings changed during the import. Import this again."
const refusal = (settled: Settled, fallback: string): string => (!settled.ok && settled.error.message) || fallback
const conflict = (settled: Settled): boolean => !settled.ok && settled.error.code === 'conflict'
/** The core refuses a write bound to a revision that has since moved on. */
const stale = (settled: Settled): boolean => !settled.ok && settled.error.code === 'stale_binding'

class Importer {
  needsKey = false

  constructor(
    private readonly source: OdinImportSource,
    private readonly broker: ImportBroker,
    private readonly fetchImpl: FetchLike,
    private readonly odin: OdinSnapshot
  ) {}

  /** A change the core may have made without confirming it: stop, so nothing builds on it or repeats it. */
  private async change(method: string, params: Record<string, unknown>): Promise<Settled> {
    const settled = await this.broker.request(method, params)
    if (!settled.ok && settled.error.disposition === 'outcome_unknown') throw new Unconfirmed(method)
    return settled
  }

  async memory(scope: string): Promise<Outcome> {
    const body = record(await odinGet(this.source, `/api/memory/${encodeURIComponent(scope)}`, this.fetchImpl))
    let added = 0
    let kept = 0
    let refused = 0
    for (const [key, value] of Object.entries(record(body.entries))) {
      const settled = await this.change('memory.set', { scope: 'global', key, value, if_absent: true })
      if (!settled.ok) refused++
      else if (record(settled.result).status === 'exists') kept++
      else added++
    }
    const parts = [`${plural(added, 'entry', 'entries')} added`]
    if (kept) parts.push(`${kept} already there`)
    if (refused) parts.push(`${refused} couldn't be saved`)
    const message = `${parts.join(', ')}.`
    if (refused) return added ? attention(message) : failed(message)
    return added ? done(message) : skipped(message)
  }

  async skill(name: string, status: string): Promise<Outcome> {
    const detail = record(await odinGet(this.source, `/api/skills/${encodeURIComponent(name)}`, this.fetchImpl))
    const code = text(detail.code)
    if (!code.trim()) return failed("Odin didn't return this skill's code.")
    // create: true makes the core refuse a name that exists, even one added after the preview.
    const saved = await this.change('skills.save', { name, code, create: true })
    if (conflict(saved)) return skipped(ALREADY)
    if (!saved.ok) return failed(refusal(saved, "Odin Desktop didn't accept this skill."))
    const notes: string[] = []
    if (status === 'disabled') {
      const off = await this.change('skills.set_enabled', { name, enabled: false })
      if (!off.ok) return attention(`Imported, but it couldn't be switched off as it is in Odin: ${refusal(off, 'refused')}`)
      notes.push('Switched off, as in Odin.')
    }
    const hidden = hiddenKeys(detail.config)
    const config = Object.fromEntries(Object.entries(record(detail.config)).filter(([, value]) => value !== ODIN_REDACTED))
    if (Object.keys(config).length) {
      const set = await this.change('skills.config.set', { name, config })
      if (!set.ok) return attention(`Imported, but its settings weren't: ${refusal(set, 'refused')}`)
    }
    if (hidden.length) return attention(['Imported.', ...notes, `Re-enter in Skills → its settings: ${hidden.join(', ')}`].join(' '))
    return done(['Imported.', ...notes].join(' '))
  }

  async mcp(name: string, server: Json): Promise<Outcome> {
    if (!MCP_NAME.test(name)) return failed('Odin Desktop server names use letters, digits and underscores only.')
    const http = text(server.transport) === 'http'
    const url = text(server.url)
    if (http && (!url || url === ODIN_REDACTED)) {
      return attention("Odin doesn't share this server's address. Add it in MCP servers → Add server with its URL.")
    }
    // Checked and saved against one revision: if anything changes in between, the core refuses the save.
    const status = await desktopCall(this.broker, 'mcp.status')
    if (mcpNames(status).has(name)) return skipped(ALREADY)
    const timeout = typeof server.timeout_seconds === 'number' && server.timeout_seconds > 0 ? server.timeout_seconds : undefined
    const env = shownValues(server.env)
    const headers = shownValues(server.headers)
    const saved = await this.change('mcp.save', {
      name,
      transport: http ? 'http' : 'stdio',
      enabled: false,
      tool_allowlist: list(server.tool_allowlist).map(text).filter(Boolean),
      ...(text(status.revision) ? { expected_revision: text(status.revision) } : {}),
      ...(timeout ? { timeout_seconds: timeout } : {}),
      ...(http
        ? { url, ...(Object.keys(headers).length ? { headers_set: headers } : {}) }
        : {
            command: text(server.command),
            args: list(server.args).map(text),
            ...(text(server.cwd) ? { cwd: text(server.cwd) } : {}),
            ...(Object.keys(env).length ? { env_set: env } : {})
          })
    })
    if (stale(saved)) return failed("Odin Desktop's MCP settings changed during the import. Import this server again.")
    if (!saved.ok) return failed(refusal(saved, "Odin Desktop didn't accept this server."))
    const hidden = [...hiddenKeys(server.env), ...hiddenKeys(server.headers)]
    return hidden.length
      ? attention(`Imported switched off. Re-enter in MCP servers → Edit: ${hidden.join(', ')}, then switch it on.`)
      : done('Imported switched off. Switch it on in MCP servers when you want it.')
  }

  async preset(name: string, preset: Json): Promise<Outcome> {
    const saved = await this.change('personality.presets.save', {
      name, display_name: text(preset.name) || name, identity: text(preset.identity), voice: text(preset.voice), create: true
    })
    if (conflict(saved)) return skipped(ALREADY)
    return saved.ok ? done('Imported.') : failed(refusal(saved, "Odin Desktop didn't accept this preset."))
  }

  async currentPersonality(): Promise<Outcome> {
    const personality = this.odin.personality
    const preset = text(personality.preset)
    const user = userPresets(personality).find(([name]) => name === preset)
    if (user) {
      const saved = await this.preset(user[0], user[1])
      if (saved.status === 'failed') return saved
    }
    const set = await this.change('personality.set', {
      preset,
      ...(preset === 'custom' ? {
        custom_name: text(personality.custom_name),
        custom_identity: text(personality.custom_identity),
        custom_voice: text(personality.custom_voice)
      } : {})
    })
    return set.ok ? done('Odin Desktop now uses it.') : failed(refusal(set, "Odin Desktop didn't accept it."))
  }

  async host(alias: string, host: Json): Promise<Outcome> {
    if (hostNames(await desktopCall(this.broker, 'hosts.list')).has(alias)) return skipped(ALREADY)
    const fingerprints = list(host.host_keys).map(text).map(fingerprintOf).filter((value): value is string => value !== null)
    if (!fingerprints.length) return attention('Odin has no pinned key for this host. Add it in Hosts and access instead.')
    const user = text(host.ssh_user) || 'root'
    const address = text(host.address)
    const prepared = await this.broker.request('hosts.prepare', {
      alias,
      address,
      ssh_user: user,
      port: typeof host.port === 'number' ? host.port : 22,
      os: text(host.os) === 'macos' ? 'macos' : 'linux',
      description: text(host.description),
      enabled: host.enabled !== false,
      trust_mode: 'pinned',
      expected_fingerprints: fingerprints
    })
    if (!prepared.ok) return failed(refusal(prepared, "Odin Desktop couldn't check this host's key."))
    const token = text(record(prepared.result).candidate_token)
    const tested = await this.broker.request('hosts.test', { token })
    if (!tested.ok && tested.error.disposition === 'outcome_unknown') {
      return attention("The connection test didn't answer in time. Nothing was saved; import this host again.")
    }
    if (!tested.ok || record(tested.result).tested !== true) {
      this.needsKey = true
      return attention(`Couldn't sign in to ${user}@${address}. Add Odin Desktop's key there, then retry.`)
    }
    // An alias added between the first check and prepare would make this candidate an update: keep it instead.
    // From prepare on, commit itself refuses if the alias changes.
    if (hostNames(await desktopCall(this.broker, 'hosts.list')).has(alias)) return skipped(ALREADY)
    const committed = await this.change('hosts.commit', { token })
    if (!committed.ok) return failed(refusal(committed, "Odin Desktop couldn't save this host."))
    return done('Added and tested.')
  }

  private async revision(): Promise<{ revision: string; fields: Json[] }> {
    const schema = await desktopCall(this.broker, 'settings.schema')
    return { revision: text(schema.revision), fields: list(schema.fields).map(record) }
  }

  private async setting(path: string, value: unknown): Promise<Outcome> {
    const { revision, fields } = await this.revision()
    const field = fields.find((row) => row.path === path)
    if (!field) return failed("Odin Desktop doesn't have this setting.")
    const method = text(field.apply_handler) || 'settings.set'
    if (!SETTINGS_WRITERS.has(method)) return failed("Odin Desktop changes this setting elsewhere.")
    const settled = await this.change(method, { expected_revision: revision, changes: [{ path, value }] })
    if (stale(settled)) return failed(CHANGED)
    return settled.ok ? done('Set.') : failed(refusal(settled, "Odin Desktop didn't accept this value."))
  }

  async model(id: string): Promise<Outcome> {
    const config = this.odin.config
    if (id === 'main') {
      const { revision } = await this.revision()
      const effort = mainEffort(config)
      const settled = await this.change('models.main.set', {
        model: text(record(config.llm_provider).model), ...(effort ? { reasoning_effort: effort } : {}), expected_revision: revision
      })
      if (stale(settled)) return failed(CHANGED)
      return settled.ok ? done('Set.') : failed(refusal(settled, 'Odin Desktop could not use this model. Set up its provider first.'))
    }
    if (id === 'agents') {
      const agents = record(config.agents)
      const { revision } = await this.revision()
      const settled = await this.change('models.agents.set', {
        model: agents.model ?? null,
        ...(agents.model === 'auto' ? { auto_model_allowlist: list(agents.auto_model_allowlist) } : {}),
        ...(Object.keys(record(agents.model_selection_hints)).length ? { model_selection_hints: agents.model_selection_hints } : {}),
        expected_revision: revision
      })
      if (stale(settled)) return failed(CHANGED)
      return settled.ok ? done('Set.') : failed(refusal(settled, "Odin Desktop didn't accept these agent settings."))
    }
    // Ids come from previewItems, so every other id names one of these settings.
    const path = SETTING_PATHS[id as keyof typeof SETTING_PATHS]
    const [section, key] = path.includes('.') ? path.split('.') : [path, '']
    const value = key ? record(config[section as string])[key] : config[path]
    return this.setting(path, value ?? null)
  }
}

const ORDER: OdinImportCategory[] = ['memory', 'skills', 'mcp', 'personality', 'hosts', 'models']

export async function applyOdinImport(
  source: OdinImportSource,
  picks: OdinImportPick[],
  broker: ImportBroker,
  fetchImpl: FetchLike
): Promise<Result<OdinImportReport>> {
  try {
    const [odin, desktop] = await Promise.all([readOdin(source, fetchImpl), readDesktop(broker)])
    const available = previewItems(odin, desktop)
    const importer = new Importer(source, broker, fetchImpl, odin)
    const wanted = new Set(picks.map((pick) => `${pick.category}\u0000${pick.id}`))
    const outcomes: OdinImportOutcome[] = []
    const servers = new Map(mcpServers(odin.config))
    const hosts = new Map(remoteHosts(odin.config))
    const presets = new Map(userPresets(odin.personality))
    const skillStatus = new Map(odin.skills.map((row) => [text(row.name), text(row.status)]))
    const queue = ORDER.flatMap((category) =>
      available.filter((row) => row.category === category && wanted.has(`${category}\u0000${row.id}`)))
    let stopped = false
    for (const item of queue) {
      const { category, id, label } = item
      if (stopped) {
        outcomes.push({ category, id, label, status: 'not_attempted', message: 'Not attempted: an earlier change was not confirmed.' })
        continue
      }
      let outcome: Outcome
      try {
        if (item.exists) outcome = skipped(ALREADY)
        else if (category === 'memory') outcome = await importer.memory(id)
        else if (category === 'skills') outcome = await importer.skill(id, skillStatus.get(id) ?? '')
        else if (category === 'mcp') outcome = await importer.mcp(id, servers.get(id) ?? {})
        else if (category === 'personality') {
          outcome = id === CURRENT_PERSONALITY ? await importer.currentPersonality()
            : await importer.preset(id.slice(PRESET.length), presets.get(id.slice(PRESET.length)) ?? {})
        } else if (category === 'hosts') outcome = await importer.host(id, hosts.get(id) ?? {})
        else outcome = await importer.model(id)
      } catch (error) {
        if (error instanceof Unconfirmed) {
          stopped = true
          outcome = { status: 'unknown', message: "Odin Desktop didn't confirm this change in time, so the import stopped. Check it before importing it again." }
        } else {
          outcome = failed(error instanceof ImportError ? error.message : 'Something went wrong with this item.')
        }
      }
      outcomes.push({ category, id, label, ...outcome })
    }
    // Picks Odin no longer has are reported, never silently dropped.
    for (const pick of picks) {
      if (!available.some((row) => row.category === pick.category && row.id === pick.id)) {
        outcomes.push({ category: pick.category, id: pick.id, label: pick.id, status: 'failed', message: "Odin doesn't have this any more." })
      }
    }
    let publicKey: string | undefined
    if (importer.needsKey) {
      const key = await broker.request('hosts.public_key', {})
      publicKey = key.ok ? text(record(key.result).public_key) || undefined : undefined
    }
    return { ok: true, result: { outcomes, ...(publicKey ? { public_key: publicKey } : {}) } }
  } catch (error) {
    return failure(error)
  }
}
