// Round E source-build renderer evidence, not installed/platform qualification.
import { spawn, execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

export const DEFAULT_OUTPUT = '/mnt/storage/odin-desktop-evidence/ui-v1-round-E-20261008'
export const EPOCH = '2026-10-08T12:14:00.000Z'
export const REQUIRED_SCREENSHOTS = ['main-model-picker-open', 'knowledge-add-document', 'knowledge-details',
  'models-after-restart', 'header-switcher-open', 'header-switcher-inline-error',
  'image-late-bottom-pinned', 'image-late-user-scrolled-up', 'avatar-and-rail-dark', 'avatar-and-rail-light']
const model = (ref, provider, values) => ({ ref, name: ref, provider, available: true,
  effort_capabilities: { values, restrictions_known: values !== null, source: 'round_e_synthetic' } })
export const MODEL_CATALOGUE = {
  codex: [model('gpt-6.1-sol', 'codex', ['medium', 'high']), model('gpt-6-luna', 'codex', ['low', 'medium'])],
  compat: [model('compat:deepseek-v4-flash', 'compat', null)], ollama: [model('ollama:llama3.1:8b', 'ollama', null)]
}
export const FIELDS = [
  ['openai_codex.enabled', 'boolean', 'Enable Codex', true],
  ['llm_provider.model', 'string', 'Main model', 'gpt-6.1-sol'],
  ['openai_codex.reasoning_effort', 'string', 'Reasoning effort', 'high'],
  ['agents.model', 'string', 'Agent model', ''],
  ['agents.auto_model_allowlist', 'array', 'Automatic model allowlist', []],
  ['openai_compatible.enabled', 'boolean', 'Enable compatible provider', false],
  ['ollama.enabled', 'boolean', 'Enable Ollama', false]
]
export const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex')
export function externalOutput(value = DEFAULT_OUTPUT) {
  const requested = resolve(value)
  let ancestor = requested
  while (!existsSync(ancestor)) ancestor = dirname(ancestor)
  const output = resolve(realpathSync(ancestor), relative(ancestor, requested))
  const root = realpathSync(repositoryRoot)
  if (output === root || output.startsWith(root + sep)) throw new Error('Evidence must remain outside repository')
  return output
}

// Augment only the disposable fixture. Backend holds artifacts.read bytes until
// explicitly released after measured scroll intent. No renderer/preload mocks.
export function fixtureCommand(python, fixture) {
  if (!isAbsolute(python) || !isAbsolute(fixture)) throw new Error('Absolute Python and fixture paths required')
  const bootstrap = `import asyncio, datetime, json, runpy, sys, uuid, random, pathlib, struct, zlib
class FrozenDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 8, 12, 14, tzinfo=datetime.timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)
datetime.datetime = FrozenDateTime
rng = random.Random(20261008)
uuid.uuid4 = lambda: uuid.UUID(int=rng.getrandbits(128), version=4)
fixture = sys.argv.pop(1)
sys.argv[0] = fixture
module = runpy.run_path(fixture, run_name='round_e_fixture')
Core, Error = module['Core'], module['CoreError']
catalogue = json.loads(${JSON.stringify(JSON.stringify(MODEL_CATALOGUE))})
for row in json.loads(${JSON.stringify(JSON.stringify(FIELDS))}):
    record = dict(module['SETTINGS_FIELDS'].get(row[0]) or module['field'](*row))
    record['default'] = row[3]
    module['SETTINGS_FIELDS'][row[0]] = record
original_init = Core.__init__
def initialize(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    self.e_path = pathlib.Path.home() / ('round-e-' + str(self.profile) + '.json')
    self.e_calls, self.e_pending, self.e_hold, self.e_fail = [], [], set(), False
    if self.e_path.exists():
        self.settings_values.update(json.loads(self.e_path.read_text()))
        self.boot_values = dict(self.settings_values)
Core.__init__ = initialize
def status(core, params, writer):
    return {'model_catalogue': catalogue, 'serving_provider': 'codex', 'active_provider': 'codex',
            'main_model': core.settings_values['llm_provider.model'],
            'codex': {'configured': True}, 'ollama': {'configured': False}, 'openai_compatible': {'configured': False}}
def main_set(core, params, writer):
    core.e_calls.append(dict(params))
    if core.e_fail:
        core.e_fail = False
        raise Error('bad_request', 'Round E fixture save rejected. No values changed.')
    if params.get('expected_revision') != core.settings_revision():
        raise Error('stale_binding', 'settings changed since you loaded them', 'stale_binding')
    row = next((r for r in catalogue['codex'] if r['ref'] == params.get('model')), None)
    if row is None or params.get('reasoning_effort') not in row['effort_capabilities']['values']:
        raise Error('bad_request', 'Invalid model and effort pair; nothing changed.')
    core.settings_values.update({'llm_provider.model': row['ref'], 'openai_codex.reasoning_effort': params['reasoning_effort']})
    core.e_path.write_text(json.dumps(core.settings_values))
    return {'status': 'switched', 'main_model': row['ref'], 'configured_provider': 'codex'}
module['METHODS']['models.status'] = status
module['METHODS']['models.main.set'] = main_set
def png():
    width, height = 900, 520
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    rows = b''.join(b'\\0' + b''.join(bytes((20 + x * 55 // width, 30 + y * 100 // height, 70 + x * 80 // width)) for x in range(width)) for y in range(height))
    return b'\\x89PNG\\r\\n\\x1a\\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')
image_data = png()
original_dispatch = Core.dispatch
def dispatch(core, writer, frame):
    if frame.get('method') == 'artifacts.read' and (frame.get('params') or {}).get('ref') in core.e_hold:
        core.e_pending.append((writer, frame))
        return
    original_dispatch(core, writer, frame)
Core.dispatch = dispatch
def control(core, params, writer):
    action = params.get('action')
    if action == 'status':
        return {'calls': core.e_calls, 'pending_reads': len(core.e_pending), 'values': core.settings_values}
    if action == 'fail_next_save':
        core.e_fail = True
        return {'armed': True}
    if action == 'release_image':
        core.e_hold.clear()
        pending, core.e_pending = core.e_pending, []
        for held_writer, frame in pending:
            original_dispatch(core, held_writer, frame)
        return {'released': len(pending)}
    if action == 'seed_history':
        cid = params['conversation_id']
        core.require_conversation(cid)
        for i in range(14):
            core.commit_message(cid, {'id': 'e-history-' + str(i), 'role': 'user' if i % 2 == 0 else 'assistant',
                'text': ('Round E synthetic conversation. Earlier context ' + str(i) + '.\\n\\n' + 'Readable fixture history, not a provider response. ' * 7), 'created_at': module['now']()})
        return {'count': 14}
    if action == 'late_image':
        cid, key = params['conversation_id'], params['key']
        ref, mid = 'e-image-' + key, 'e-delivery-' + key
        core.artifacts[ref] = {'name': 'round-e-gradient-' + key + '.png', 'mime': 'image/png', 'data': image_data, 'conversation_id': cid}
        core.e_hold.add(ref)
        artifact = {'ref': ref, 'name': core.artifacts[ref]['name'], 'mime': 'image/png', 'size': len(image_data), 'kind': 'image', 'available': True}
        core.commit_message(cid, {'id': mid, 'role': 'notice', 'author': 'odin', 'request_id': 'tool-request-' + key,
            'text': 'Synthetic tool-delivered image. Fetch held until user intent is measured.', 'created_at': module['now'](), 'artifacts': [artifact]})
        core.commit_message(cid, {'id': 'e-reply-' + key, 'role': 'assistant', 'request_id': 'tool-request-' + key,
            'text': 'The image is ready. This reply must remain reachable below it.', 'created_at': module['now']()})
        return {'message_id': mid, 'reply_id': 'e-reply-' + key, 'ref': ref}
    if action == 'genuine_notice':
        cid = params['conversation_id']
        core.artifacts['e-system-file'] = {'name': 'system-status.txt', 'mime': 'text/plain', 'data': b'Synthetic system status', 'conversation_id': cid}
        artifact = {'ref': 'e-system-file', 'name': 'system-status.txt', 'mime': 'text/plain', 'size': 23, 'kind': 'file', 'available': True}
        core.commit_message(cid, {'id': 'e-system-notice', 'role': 'notice', 'request_id': 'system-request',
            'text': 'Synthetic system notice with a non-tool file. Must remain Notice.', 'created_at': module['now'](), 'artifacts': [artifact]})
        return {'added': True}
    raise Error('bad_request', 'Unknown synthetic evidence action')
module['METHODS']['round_e.fixture'] = control
sys.exit(asyncio.run(module['main']()))`
  return [python, '-B', '-P', '-c', `exec(${JSON.stringify(bootstrap)})`, fixture]
}

function sourceProvenance(appDir) {
  const files = []
  const visit = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) visit(path)
      else if (entry.isFile()) files.push({ path: relative(repositoryRoot, path), sha256: sha256(readFileSync(path)) })
    }
  }
  for (const directory of ['src', 'resources', 'fixture-core', 'scripts', 'out', 'test']) visit(join(appDir, directory))
  return { files, digest: sha256(JSON.stringify(files)) }
}
async function bounded(command, args, cwd) {
  await new Promise((accept, reject) => {
    const child = spawn(command, args, { cwd, stdio: 'inherit', detached: true })
    const timer = setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL') } catch {} }, 180_000)
    child.once('error', (error) => { clearTimeout(timer); reject(error) })
    child.once('exit', (code, signal) => { clearTimeout(timer); code === 0 ? accept() : reject(new Error(`${command} failed: ${code}/${signal}`)) })
  })
}
export async function runRoundE() {
  if (process.env.ODIN_APP_UI_TREE_STABLE !== '1') throw new Error('Parent must authorize stable tree: ODIN_APP_UI_TREE_STABLE=1')
  if (process.platform !== 'linux' || process.getuid?.() === 0 || process.getuid?.() !== process.geteuid?.()) throw new Error('Run as nonprivileged odin, never root Electron')
  const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const root = externalOutput(process.env.ODIN_APP_E2E_OUT)
  mkdirSync(root, { recursive: true, mode: 0o700 })
  const output = join(root, `round-e-${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`)
  mkdirSync(output, { mode: 0o700 })
  const manifest = { schema: 'odin-ui-round-e-v1', outcome: 'running', startedAt: new Date().toISOString(), output,
    limitations: ['Source-build synthetic renderer evidence, not a production provider call or quota proof.',
      'Restart persists synthetic pair in disposable HOME, not proof of live-provider boot adoption.',
      'No installed package, VM, live config/display, platform qualification or Orca evidence.',
      'Backend holds artifact bytes; real fetch/decode/layout and renderer user intent run without renderer mocks.'],
    isolation: { launcher: 'unchanged launchIsolated/harness', uid: process.getuid(), privatePidHomeXdgDbus: true,
      display: 'private xvfb-run -a, never :0', chromiumSandbox: true },
    requiredScreenshots: REQUIRED_SCREENSHOTS, modelCatalogue: MODEL_CATALOGUE, artifacts: [] }
  let failure
  try {
    await bounded('npm', ['run', 'typecheck'], appDir)
    if (process.env.ODIN_APP_ROUND_E_REUSE_BUILD === '1') {
      if (!existsSync(join(appDir, 'out/main/index.js')) || !existsSync(join(appDir, 'out/renderer/index.html'))) throw new Error('Missing existing source build')
      manifest.build = { reused: true, limitation: 'Caller supplies the already completed build; source/out hashes retained and checked for changes.' }
    } else { await bounded('npm', ['run', 'build'], appDir); manifest.build = { reused: false } }
    manifest.git = { head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repositoryRoot, encoding: 'utf8' }).trim(),
      status: execFileSync('git', ['status', '--short'], { cwd: repositoryRoot, encoding: 'utf8' }),
      diffSha256: sha256(execFileSync('git', ['diff', 'HEAD', '--', 'app'], { cwd: repositoryRoot, maxBuffer: 16 * 1024 * 1024 })) }
    manifest.source = sourceProvenance(appDir)
    const plan = { epoch: EPOCH, requiredScreenshots: REQUIRED_SCREENSHOTS,
      command: fixtureCommand(resolve(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python')),
        join(appDir, 'fixture-core/fixture_core.py')) }
    writeFileSync(join(output, 'plan.json'), JSON.stringify(plan, null, 2) + '\n', { mode: 0o600 })
    const config = join(output, 'round-e.config.ts')
    writeFileSync(config, `import base from ${JSON.stringify(join(appDir, 'playwright.config.ts'))}\nexport default { ...base, testDir: ${JSON.stringify(join(appDir, 'test/e2e'))}, testMatch: ['ui-v1-round-e.spec.ts'], timeout: 240000, retries: 0, workers: 1, use: { trace: 'off', screenshot: 'off', video: 'off' } }\n`, { mode: 0o600 })
    await launchIsolated('dbus-run-session', ['--config-file', join(repositoryRoot, 'tests/desktop_fixtures/private-session.conf'), '--',
      'xvfb-run', '-a', '-s', '-screen 0 1600x1000x24 -nolisten tcp', process.execPath,
      join(appDir, 'node_modules/@playwright/test/cli.js'), 'test', '--config', config], {
      cwd: repositoryRoot, timeoutMs: 360_000, env: { ODIN_APP_E2E: '1', ODIN_APP_E2E_OUT: output,
        ODIN_APP_ROUND_E: '1', ODIN_APP_ROUND_E_PLAN: join(output, 'plan.json') }
    })
    if (manifest.source.digest !== sourceProvenance(appDir).digest) throw new Error('Source/build changed during capture')
    const receipt = JSON.parse(readFileSync(join(output, 'receipt.json'), 'utf8'))
    if (receipt.outcome !== 'passed') throw new Error('Behavioral receipt did not pass')
    for (const label of REQUIRED_SCREENSHOTS) if (!receipt.screenshots.some((image) => image.label === label)) throw new Error(`Missing screenshot: ${label}`)
    manifest.outcome = 'passed'
  } catch (error) { failure = error; manifest.outcome = 'failed'; manifest.error = String(error?.stack || error) }
  finally {
    for (const name of readdirSync(output).sort()) {
      if (!/\.(png|json)$/.test(name)) continue
      const path = join(output, name), bytes = readFileSync(path)
      manifest.artifacts.push({ path, bytes: bytes.length, sha256: sha256(bytes) })
    }
    manifest.finishedAt = new Date().toISOString()
    const path = join(output, 'manifest.json')
    writeFileSync(path, JSON.stringify(manifest, null, 2) + '\n', { mode: 0o600 })
    console.log(`Round E ${manifest.outcome}: ${path}\nManifest SHA256: ${sha256(readFileSync(path))}`)
  }
  if (failure) throw failure
  return manifest
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runRoundE().catch((error) => { console.error(error); process.exitCode = 1 })
}
