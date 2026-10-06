// The app's actual Broker against `python -m src`, never the fixture or an in-process service substitute.
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, readlinkSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { Broker, type Welcome } from '../src/main/broker'
import { ensureProfileDirs, ensureToken, profilePaths, type ProfilePaths } from '../src/main/paths'
import { startCannedProvider } from './real-core-provider-fixture.mjs'
import { configureCannedProvider } from '../src/main/real-core-smoke'

const repository = resolve(__dirname, '../..')

// The published named contract, not an arbitrary renderer RPC surface. Retained
// background work, reports and schedules are served; foreground input is absent.
export const SERVED_CAPABILITIES = ['status.get', 'events.subscribe', 'runtime.shutdown', 'submission.send', 'notifications.ack', ...[
  'attachments.begin', 'attachments.chunk', 'attachments.commit', 'attachments.cancel',
  'artifacts.read', 'tool.detail', 'tool.output',
  'control.stop', 'control.steer', 'control.resume',
  'work.list', 'work.control', 'reports.page',
  'schedules.list', 'schedules.save', 'schedules.delete', 'schedules.run',
  'schedules.reset_failures', 'schedules.history', 'schedules.validate_cron',
  'conversations.list', 'conversations.create', 'conversations.update', 'conversations.delete',
  'conversations.reset_context', 'conversations.mark_read', 'messages.list',
  'conversation.snapshot', 'search.query', 'messages.around',
  'settings.schema', 'settings.set', 'secrets.set', 'secrets.clear', 'secrets.unlock', 'models.image.intent',
  'providers.codex.set', 'providers.auxiliary.set', 'providers.ollama.set', 'providers.compat.set',
  'codex.accounts.list', 'codex.accounts.activate', 'codex.accounts.remove', 'codex.accounts.label', 'codex.accounts.refresh',
  'codex.login.begin', 'codex.login.poll',
  'hosts.list', 'hosts.settings', 'hosts.prepare', 'hosts.test', 'hosts.commit', 'hosts.set_enabled',
  'hosts.references', 'hosts.delete', 'hosts.public_key', 'hosts.force_revoke', 'hosts.import_legacy',
  'memory.list', 'memory.get', 'memory.set', 'memory.delete', 'memory.bulk_delete',
  'lists.list', 'lists.get', 'lists.delete',
  'knowledge.list', 'knowledge.search', 'knowledge.ingest', 'knowledge.reingest', 'knowledge.delete',
  'knowledge.versions', 'knowledge.restore', 'knowledge.import', 'knowledge.chunks', 'knowledge.duplicates',
  'knowledge.merge', 'knowledge.version', 'knowledge.diff',
  'audit.query', 'audit.verify', 'health.get', 'logs.search', 'turn_state.list', 'usage.get', 'runtime.reload',
  'audit.diffs', 'audit.failures', 'audit.tail', 'logs.stats', 'logs.tail',
  'models.main.set', 'models.agents.get', 'models.agents.set', 'models.discover',
  'personality.get', 'personality.set', 'personality.presets.save', 'personality.presets.delete',
  'tools.list', 'tools.set_enabled', 'tools.timeouts.get', 'tools.timeouts.set',
  'webhooks.outbound.list', 'webhooks.outbound.save', 'webhooks.outbound.delete',
  'webhooks.outbound.test', 'integrations.email.get',
  'learned.list', 'learned.update', 'learned.delete',
  'trajectories.list', 'trajectories.read', 'trajectories.search', 'trajectories.message',
  'observability.stats', 'observability.tools', 'observability.risk', 'observability.risk_recent',
  'observability.governor', 'observability.audit_risk', 'observability.freshness',
  'observability.freshness_recent', 'observability.bulkheads', 'observability.compression',
  'observability.validation', 'observability.affordances', 'observability.context',
  'observability.usage', 'observability.usage_totals', 'observability.subsystems',
  'recovery.stats', 'recovery.recent', 'capacity.snapshot', 'turn_state.snapshot',
  'pools.ssh', 'pools.http', 'pools.close',
  'openrouter.catalogue', 'openrouter.endpoints', 'openrouter.select',
  'providers.compat.diagnostic', 'models.status', 'models.provider.get', 'models.provider.set',
  'skills.list', 'skills.get', 'skills.save', 'skills.validate', 'skills.test', 'skills.set_enabled', 'skills.delete',
  'skills.config.get', 'skills.config.set',
  'mcp.list', 'mcp.status', 'mcp.tools', 'mcp.save', 'mcp.set_enabled', 'mcp.delete',
  'mcp.reconnect', 'mcp.refresh_tools', 'mcp.set_global_enabled', 'mcp.set_limits',
  'computer.status', 'computer.pause', 'computer.stop', 'computer.cancel', 'computer.close',
  'computer.reconcile', 'computer.reconcile_hyprland_owner', 'computer.acknowledge_legacy_recovery',
  'computer.operator_reconcile', 'computer.release_owned_input', 'computer.activation.set'
].sort()]

type IsolatedServices = { memoryKeyring?: boolean; authBaseUrl?: string; profileRoot?: string; workProof?: boolean }

// Only the external secret/auth boundary is substituted. The entry point, management services,
// transport, command journal, settings persistence and Broker remain the actual repository code.
const isolatedServicesBootstrap = `
import sys, runpy, os
from src.desktop.management import ManagementService
class MemoryKeyring:
    def __init__(self): self.values = {}
    def check(self):
        if os.path.exists(os.path.join(os.environ['HOME'], 'keyring.locked')):
            raise RuntimeError('ephemeral test keyring locked')
    def get_password(self, namespace, name):
        self.check()
        return self.values.get((namespace, name))
    def set_password(self, namespace, name, value):
        self.check()
        self.values[(namespace, name)] = value
    def delete_password(self, namespace, name):
        self.check()
        self.values.pop((namespace, name), None)
if sys.argv[1] == 'memory':
    original = ManagementService.compose.__func__
    backend = MemoryKeyring()
    ManagementService.compose = classmethod(lambda cls, core, **kw: original(cls, core, secret_backend=backend))
base = sys.argv[2]
if base:
    import src.desktop.codex_accounts as device
    import src.llm.codex_auth as auth
    device.DEVICE_USERCODE_URL = base + '/device/code'
    device.DEVICE_TOKEN_URL = base + '/device/token'
    device.DEVICE_VERIFY_URL = base + '/verify'
    auth.TOKEN_URL = base + '/oauth/token'
sys.argv = ['src', *sys.argv[3:]]
runpy.run_module('src', run_name='__main__')
`

export function assertIsolated(): void {
  if (process.platform !== 'linux' || !process.getuid || process.getuid() === 0) {
    throw new Error('Real-core tests require Linux and an unprivileged user; never run them as root.')
  }
  const outer = process.env.ODIN_REAL_CORE_OUTER_PID_NS
  if (!outer || readlinkSync('/proc/self/ns/pid') === outer) {
    throw new Error('Real-core tests refused outside an isolated PID namespace. Run npm run test:real-core, not vitest directly.')
  }
  const init = readFileSync('/proc/1/cmdline', 'utf8').split('\0')
  if (!init.includes(join(repository, 'app/scripts/real-core-isolation.mjs')) || !init.includes('--inside-run')) {
    throw new Error('Real-core tests refused: namespace PID 1 is not the isolation runner.')
  }
  const root = process.env.ODIN_REAL_CORE_ROOT
  if (!root || !root.startsWith(join(tmpdir(), 'odrc-')) || process.env.HOME !== root) {
    throw new Error('Real-core tests refused without the isolation runner throwaway HOME.')
  }
  for (const [key, leaf] of Object.entries({
    XDG_CONFIG_HOME: 'config', XDG_DATA_HOME: 'data', XDG_CACHE_HOME: 'cache', XDG_RUNTIME_DIR: 'run'
  })) {
    if (process.env[key] !== join(root, leaf)) throw new Error(`Real-core tests refused: unsafe ${key}.`)
  }
}

function enginePython(): string {
  assertIsolated()
  const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repository, '.venv/bin/python')
  if (!existsSync(python)) {
    throw new Error('Real engine Python is absent. Set ODIN_DESKTOP_ENGINE_PYTHON or provision repository .venv with engine dependencies. Tests never skip.')
  }
  if (!existsSync(join(repository, 'src/desktop/core.py'))) throw new Error('Real repository core is absent; no fixture fallback.')
  return python
}

export async function waitFor(check: () => boolean, description: string, timeoutMs = 8_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (!check()) {
    if (Date.now() >= deadline) throw new Error(`Timed out: ${description}`)
    await new Promise((accept) => setTimeout(accept, 20))
  }
}

export function onceEvent<T>(broker: Broker, event: string, timeoutMs = 8_000): Promise<T> {
  return new Promise((accept, reject) => {
    const listener = (value: T): void => { clearTimeout(timer); accept(value) }
    const timer = setTimeout(() => {
      broker.off(event, listener)
      reject(new Error(`Timed out waiting for Broker ${event}`))
    }, timeoutMs)
    broker.once(event, listener)
  })
}

export class RealCoreHarness {
  readonly root: string
  readonly paths: ProfilePaths
  readonly python: string
  readonly env: NodeJS.ProcessEnv
  private process: ChildProcessWithoutNullStreams | null = null
  private output = ''
  private exited: Promise<{ code: number | null; signal: NodeJS.Signals | null }> | null = null
  private readonly brokers = new Set<Broker>()
  private providerConfigured = false
  provider: Awaited<ReturnType<typeof startCannedProvider>> | null = null

  constructor(private readonly services: IsolatedServices = {}) {
    this.python = enginePython()
    if (services.authBaseUrl) {
      const url = new URL(services.authBaseUrl)
      if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port ||
          url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
        throw new Error('Isolated auth must be a disposable HTTP server on 127.0.0.1 with an explicit port.')
      }
    }
    if (services.profileRoot && services.profileRoot !== process.env.ODIN_REAL_CORE_ROOT) throw new Error('Shared smoke profile must belong to the isolation runner.')
    this.root = services.profileRoot ?? mkdtempSync(join(process.env.ODIN_REAL_CORE_ROOT!, 'profile-'))
    this.env = {
      PATH: '/usr/local/bin:/usr/bin:/bin', LANG: 'C.UTF-8', HOME: this.root,
      XDG_CONFIG_HOME: join(this.root, 'config'), XDG_DATA_HOME: join(this.root, 'data'),
      XDG_CACHE_HOME: join(this.root, 'cache'), XDG_RUNTIME_DIR: join(this.root, 'run'),
      PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1',
      ODIN_DESKTOP_BUNDLE_ROOT: join(this.root, 'absent-browser-bundle')
    }
    this.paths = profilePaths('default', this.env)
    ensureProfileDirs(this.paths)
    ensureToken(this.paths)
  }

  get child(): ChildProcessWithoutNullStreams {
    if (!this.process) throw new Error('No real core process has been started.')
    return this.process
  }

  get running(): boolean {
    return this.process !== null && this.process.exitCode === null && this.process.signalCode === null
  }

  async start(): Promise<void> {
    assertIsolated()
    if (this.running) throw new Error('Real core is already running.')
    this.output = ''
    this.providerConfigured = false
    const entry = this.services.workProof ? [join(repository, 'app/test/services-b-core.py')]
      : this.services.memoryKeyring || this.provider || this.services.authBaseUrl
        ? ['-c', isolatedServicesBootstrap, this.services.memoryKeyring || this.provider ? 'memory' : 'missing', this.services.authBaseUrl ?? '']
      : ['-m', 'src']
    const child = spawn(this.python, ['-B', '-P', ...entry, '--socket', this.paths.socketPath,
      '--token-file', this.paths.tokenPath, '--profile', this.paths.profileId, '--data-dir', this.paths.dataDir],
    // app/src is TypeScript, not the engine. Exercise the installed engine from the shadowing directory.
    { cwd: join(repository, 'app'), env: this.env, stdio: ['pipe', 'pipe', 'pipe'] })
    this.process = child
    child.stdout.on('data', (chunk: Buffer) => { this.output = (this.output + chunk.toString()).slice(-8_000) })
    child.stderr.on('data', (chunk: Buffer) => { this.output = (this.output + chunk.toString()).slice(-8_000) })
    let launchError: Error | null = null
    this.exited = new Promise((accept) => {
      child.once('error', (error) => { launchError = error; accept({ code: null, signal: null }) })
      child.once('exit', (code, signal) => accept({ code, signal }))
    })
    await waitFor(() => {
      if (launchError || !this.running) {
        throw new Error(`Real core startup failed. Check engine Python/dependencies. ${launchError?.message ?? ''}\n${this.output}`)
      }
      return existsSync(this.paths.socketPath)
    // A cold installed engine imports its complete retained dependency closure.
    // Allow bounded startup on busy self-hosted runners (CI runs the shards and
    // these contracts in parallel on one host), without retrying or substituting
    // a fixture after launch. Event wait defaults stay unchanged.
    }, 'real core socket creation', 60_000)
    if (this.services.workProof) await waitFor(() => {
      if (!this.running) throw new Error(`Work bootstrap failed: ${this.output}`)
      return existsSync(join(this.root, 'work-proof.json'))
    }, 'actual manager proof admission', 12_000)
  }

  async configureProvider(): Promise<void> {
    if (this.running) throw new Error('Configure the canned provider before core startup.')
    this.provider = await startCannedProvider({ root: join(this.root, 'provider') })
  }

  broker(wrongToken = false): Broker {
    const broker = new Broker({
      socketPath: this.paths.socketPath,
      readToken: () => wrongToken ? '0'.repeat(64) : readFileSync(this.paths.tokenPath, 'utf8').trim(),
      profileId: this.paths.profileId, clientVersion: 'real-core-contract',
      // Real first-use owners can import their retained dependencies lazily.
      // Keep a bounded receipt wait below the production 30s default, without
      // retrying an unknown outcome or fabricating a successful receipt.
      requestTimeoutMs: 15_000, helloTimeoutMs: 3_000, reconnectDelaysMs: [40, 80, 150]
    })
    this.brokers.add(broker)
    return broker
  }

  async connect(): Promise<{ broker: Broker; welcome: Welcome }> {
    const broker = this.broker()
    const ready = onceEvent<Welcome>(broker, 'welcome')
    broker.connect()
    const welcome = await ready
    if (this.provider && !this.providerConfigured) {
      await configureCannedProvider(broker, this.provider.baseUrl)
      this.providerConfigured = true
    }
    return { broker, welcome }
  }

  async waitExit(timeoutMs = 15_000): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
    if (!this.exited) throw new Error('No real core process to wait for.')
    let timer: NodeJS.Timeout | undefined
    try {
      return await Promise.race([this.exited, new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Real core did not exit in ${timeoutMs}ms.\n${this.output}`)), timeoutMs)
      })])
    } finally {
      if (timer) clearTimeout(timer)
    }
  }

  async parentEOF(): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
    this.child.stdin.end()
    return this.waitExit()
  }

  /** Capture only this disposable profile's files; prove write-only values never reach disk. */
  persistedFilesContain(value: string): boolean {
    assertIsolated()
    const visit = (directory: string): boolean => readdirSync(directory, { withFileTypes: true }).some((entry) => {
      const path = join(directory, entry.name)
      return entry.isDirectory() ? visit(path) : entry.isFile() && readFileSync(path).includes(Buffer.from(value))
    })
    return visit(this.root)
  }

  get diagnostics(): string { return this.output }

  /** Damage only an existing checkpoint's integrity proof offline. No invented authority. */
  corruptCheckpoint(requestId: string): void {
    assertIsolated()
    if (this.running) throw new Error('Checkpoint corruption requires the owned core to have exited.')
    const result = spawnSync(this.python, ['-c',
      'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); row=db.execute("UPDATE turns SET payload_digest=? WHERE message_id=? AND payload IS NOT NULL",("invalid-contract-digest",sys.argv[2])); assert row.rowcount==1; db.commit(); db.close()',
      join(this.paths.dataDir, 'turn_state/turns.db'), requestId], { cwd: repository, env: this.env, encoding: 'utf8', timeout: 5000 })
    if (result.error || result.status !== 0) throw new Error(`Checkpoint corruption failed: ${result.error?.message ?? result.stderr}`)
  }

  /** Lock only the ephemeral adapter; never touch a host keyring or Secret Service. */
  lockKeyring(): void {
    assertIsolated()
    if (!this.services.memoryKeyring) throw new Error('No ephemeral keyring adapter.')
    writeFileSync(join(this.root, 'keyring.locked'), 'locked', { mode: 0o600 })
  }

  /** Offline time travel, not a fabricated tombstone: startup runs the real receipt pruner. */
  ageReceipt(commandId: string): void {
    assertIsolated()
    if (this.running) throw new Error('Receipt aging requires the real core to have exited.')
    const result = spawnSync(this.python, ['-c',
      'import sqlite3, sys; db=sqlite3.connect(sys.argv[1]); row=db.execute("UPDATE command_receipts SET finished_at=0 WHERE command_id=? AND state=\'final\' AND unknown_outcome=0", (sys.argv[2],)); assert row.rowcount == 1, "Expected one real final receipt"; db.commit(); db.close()',
      join(this.paths.dataDir, 'transport.sqlite3'), commandId], { cwd: repository, env: this.env, encoding: 'utf8', timeout: 5_000 })
    if (result.error || result.status !== 0) throw new Error(`Offline receipt aging failed: ${result.error?.message ?? result.stderr}`)
  }

  async dispose(): Promise<void> {
    for (const broker of this.brokers) broker.close()
    try {
      if (this.running) {
        this.child.stdin.end()
        try { await this.waitExit(5_000) } catch {
          this.child.kill('SIGKILL')
          await this.waitExit(3_000)
        }
      }
    } finally {
      await this.provider?.close()
      if (!this.running && !this.services.profileRoot) rmSync(this.root, { recursive: true, force: true })
    }
  }
}
