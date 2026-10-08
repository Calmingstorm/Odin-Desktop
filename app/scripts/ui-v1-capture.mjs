// UI D visual-review evidence only. Not native desktop/platform qualification.
// Run only after parent declares the tree stable, as nonprivileged odin.
import { spawn, execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

export const CAPTURE_EPOCH = '2026-10-08T03:43:00.000Z'
export const DEFAULT_OUTPUT = '/mnt/storage/odin-desktop-evidence/ui-v1-slices5-7-20261008'
export const PRIMARY_NAV = ['General', 'Models and providers', 'Personality', 'Tools', 'Skills',
  'MCP servers', 'Hosts and access', 'Work', 'Data and privacy']
export const CAPTURE_VARIANTS = [
  { key: '1180x780-dark', width: 1180, height: 780, theme: 'dark' },
  { key: '1920x1080-light', width: 1920, height: 1080, theme: 'light' },
  { key: '1180x780-light', width: 1180, height: 780, theme: 'light' },
  { key: '1920x1080-dark', width: 1920, height: 1080, theme: 'dark' }
]
export const BOUNDS_VARIANTS = [
  { key: 'minimum-720x480', width: 720, height: 480, zoom: 1 },
  { key: 'zoom-200-percent', width: 1180, height: 780, zoom: 2 },
  { key: 'narrow-720x780', width: 720, height: 780, zoom: 1 }
]
export const REQUIRED_STATES = ['models-more-options', 'provider-codex-configure', 'provider-ollama-configure',
  'provider-compat-configure', 'mcp-add', 'mcp-edit', 'outbound-add', 'outbound-edit', 'advanced-search', 'advanced-no-results', 'pending-restart',
  'data-memory', 'data-conversations', 'data-records', 'chat-empty', 'chat-populated',
  'models-dirty-save', 'models-long-names', 'mcp-validation-error']
// These remain their own gates. A screenshot must never silently inherit their qualification.
export const EXISTING_GATES = [
  { id: 'dirty-stale-and-unavailable', command: 'npm test -- test/renderer/settings-store.test.ts test/renderer/ui-v1-models.test.ts test/real-core-settings.test.ts',
    source: ['app/test/renderer/settings-store.test.ts', 'app/test/renderer/ui-v1-models.test.ts', 'app/test/real-core-settings.test.ts'], scope: 'settings ownership and revision failures' },
  { id: 'onboarding-loading-and-provider-retry', command: 'npm run test:onboarding',
    source: ['app/test/e2e/onboarding.spec.ts', 'app/scripts/onboarding-test.mjs'], scope: 'isolated real-core onboarding, no real credentials' },
  { id: 'keyboard-reduced-motion-and-light-contrast', command: 'npm run test:a11y',
    source: ['app/test/e2e/accessibility.spec.ts'], scope: 'AX/axe and theme/keyboard/reflow gate, not Orca or installed qualification' },
  { id: 'retained-output-nonreplay', command: 'npm test -- test/renderer/tool-output.test.ts test/renderer/tool-activity.test.ts',
    source: ['app/test/renderer/tool-output.test.ts', 'app/test/renderer/tool-activity.test.ts'], scope: 'retained output cursor owner, never re-run' }
]
export const CAPTURE_LONG_ACCOUNT_LABEL = 'Capture secondary account with an intentionally lengthy label for wrap review'
export const ADVANCED_CATEGORIES = ['Models and context', 'Tool execution', 'Hosts and access', 'Work and recovery', 'Data and retention']
// Declared illustration only. This is not a copied production capability table.
export const CAPTURE_MODEL_CATALOGUE = {
  codex: [{ ref: 'gpt-6.1-sol', provider: 'codex', name: 'Capture main model', capability: 'reasoning',
    available: true, unavailable_reason: null, hint_metadata: {}, efforts: ['medium', 'high'], effort_capabilities: {
    values: ['medium', 'high'], restrictions_known: true, source: 'synthetic_capture_fixture' } }],
  ollama: [{ ref: 'ollama:fixture-local', provider: 'ollama', name: 'Capture local model', capability: 'thinking',
    available: false, unavailable_reason: 'Synthetic local provider disabled', hint_metadata: {}, efforts: [], effort_capabilities: {
    values: [], restrictions_known: true, source: 'synthetic_capture_fixture' } }],
  compat: [{ ref: 'compat:fixture-chat', provider: 'compat', name: 'Capture compatible model', capability: 'chat',
    available: false, unavailable_reason: 'Synthetic compatible provider disabled', hint_metadata: {}, efforts: [], effort_capabilities: {
    values: [], restrictions_known: true, source: 'synthetic_capture_fixture' } }]
}
// Metadata-shaped synthetic status, not a successful connection probe.
export const CAPTURE_MODEL_STATUS = {
  model_catalogue: CAPTURE_MODEL_CATALOGUE, serving_provider: 'codex', active_provider: 'codex',
  codex: { configured: true },
  ollama: { configured: false, base_url: 'http://127.0.0.1:11434', model: 'fixture-local' },
  openai_compatible: { configured: false, base_url: 'https://openrouter.ai/api/v1',
    model: 'openai/fixture-chat', openrouter_recognized: true }
}
export const CAPTURE_OUTBOUND_WEBHOOKS = {
  webhook_count: 1, enabled_count: 0, scrub_secrets: true, rate_limit_seconds: 1,
  webhooks: [{ id: 'capture-target', name: 'Capture event target', url: 'https://capture.invalid/events',
    has_secret: false, events: ['task.completed'], enabled: false, scrub_secrets: true, verify_ssl: true,
    created_at: CAPTURE_EPOCH }], stats: {}
}
export const CAPTURE_FIELD_METADATA = {
  'openai_compatible.api_key': { sensitivity: 'sensitive', secret_route: 'secrets.set' }
}
// Capture-only synthetic schema samples supplement the small fixture, never
// production metadata. Types/defaults are illustrative, not engine qualification.
export const CAPTURE_FIXTURE_FIELDS = [
  ['openai_codex.enabled', 'boolean', 'Enable Codex', true],
  ['llm_provider.model', 'string', 'Main model', 'gpt-6.1-sol'],
  ['agents.model', 'string', 'Agent model', ''],
  ['openai_compatible.model', 'string', 'Provider model', 'openai/gpt-6.1-sol'],
  ['openai_compatible.reasoning_effort', 'string', 'Provider effort', 'medium'],
  ['openai_compatible.thinking_mode', 'string', 'Provider thinking mode', 'auto'],
  ['agents.thinking_mode', 'string', 'Agent thinking mode', 'auto'],
  ['agents.model_selection_hints', 'object', 'Automatic selection guidance', {}],
  ['openai_codex.agent_reasoning_effort', 'string', 'Agent reasoning effort', 'auto'],
  ['ollama.num_ctx', 'integer', 'Local context size', 32768],
  ['openai_compatible.context_utilization', 'integer', 'Provider context', 60],
  ['openai_compatible.reasoning_content_feedback_policy', 'string', 'Reasoning history', 'auto'],
  ['openai_compatible.openrouter.order', 'array', 'Preferred providers', []],
  ['openai_compatible.openrouter.allow_fallbacks', 'boolean', 'Provider fallbacks', true],
  ['openai_compatible.openrouter.quantizations', 'array', 'Allowed quantizations', []],
  ['openai_compatible.openrouter.sort', 'string', 'Routing priority', 'price'],
  ['openai_compatible.openrouter.data_collection', 'string', 'Provider data collection', 'deny'],
  ['openai_compatible.openrouter.reasoning_effort', 'string', 'Routing reasoning default', 'medium'],
  ['openai_compatible.openrouter.model_pins', 'object', 'Model provider pins', {}],
  ['sessions.adaptive_compaction', 'boolean', 'Adaptive conversation summaries', true],
  ['image.openai.enabled', 'boolean', 'Image generation', true],
  ['sessions.max_history', 'integer', 'Conversation history limit', 80],
  ['tools.governor.host_overrides', 'object', 'Per-host command safety', {}],
  ['agents.max_iterations', 'integer', 'Agent iteration limit', 100],
  ['logging.level', 'string', 'Log detail', 'INFO'],
  ['attachments.retention_hours', 'integer', 'Attachment retention', 24, 'restart']
]
export function validateCaptureEvidence(receipts) {
  if (receipts.length !== CAPTURE_VARIANTS.length) throw new Error('Expected four passing variant receipts')
  for (const variant of CAPTURE_VARIANTS) {
    const receipt = receipts.find((item) => item.variant?.key === variant.key)
    if (!receipt || receipt.outcome !== 'passed') throw new Error(`Missing passing variant: ${variant.key}`)
    for (const page of [...PRIMARY_NAV, 'Advanced settings']) {
      const record = receipt.pages?.find((item) => item.name === page)
      if (!record || !record.frames?.length || record.frames[0].top !== 0 ||
        record.frames.at(-1).top + record.frames.at(-1).client < record.frames.at(-1).height - 1) {
        throw new Error(`Incomplete full-page scroll evidence: ${variant.key} ${page}`)
      }
      for (let index = 1; index < record.frames.length; index++) {
        if (record.frames[index].top > record.frames[index - 1].top + record.frames[index - 1].client) {
          throw new Error(`Scroll coverage gap: ${variant.key} ${page}`)
        }
      }
    }
    for (const state of REQUIRED_STATES) {
      if (!receipt.screenshots?.some((image) => image.label === state || image.label.startsWith(`${state}-scroll-`))) {
        throw new Error(`Missing required state: ${variant.key} ${state}`)
      }
    }
    if (JSON.stringify(receipt.advancedCategories) !== JSON.stringify(ADVANCED_CATEGORIES)) throw new Error('Advanced categories missing or reordered')
    for (const page of [...PRIMARY_NAV, 'Advanced settings']) {
      if (!receipt.geometry?.some((record) => record.name === page && record.outcome === 'passed')) {
        throw new Error(`Missing numerical page geometry: ${variant.key} ${page}`)
      }
    }
  }
  for (const bounds of BOUNDS_VARIANTS) {
    const images = receipts.flatMap((receipt) => receipt.screenshots ?? []).filter((image) => image.label === bounds.key)
    if (images.length !== 1) throw new Error(`Expected exactly one bounded screenshot: ${bounds.key}`)
  }
}
export function assertStableTree(value) {
  if (value !== '1') throw new Error('Parent must confirm the tree stable: ODIN_APP_UI_TREE_STABLE=1')
}
export function contactSheetArgs(paths, output) {
  if (!paths.length) throw new Error('Cannot build an empty contact sheet')
  return ['-font', 'DejaVu-Sans', '-pointsize', '12', '-background', '#e5e7eb', '-fill', '#111827',
    '-label', '%f', ...paths, '-thumbnail', '460x', '-tile', '3x', '-geometry', '+8+24', output]
}
export function sha256(bytes) { return createHash('sha256').update(bytes).digest('hex') }

// Resolve existing ancestors too, so a symlink cannot quietly put screenshots in Git.
export function externalOutput(value, repository = repositoryRoot) {
  const requested = resolve(value || DEFAULT_OUTPUT)
  let ancestor = requested
  while (!existsSync(ancestor)) ancestor = dirname(ancestor)
  const output = resolve(realpathSync(ancestor), relative(ancestor, requested))
  const root = realpathSync(repository)
  if (output === root || output.startsWith(root + sep)) throw new Error('UI evidence must remain outside the repository')
  return output
}

export function captureLaunchPlan(appDir, config, output) {
  return {
    command: 'dbus-run-session',
    args: ['--config-file', join(repositoryRoot, 'tests/desktop_fixtures/private-session.conf'), '--',
      'xvfb-run', '-a', '-s', '-screen 0 2048x1200x24 -nolisten tcp', process.execPath,
      join(appDir, 'node_modules/@playwright/test/cli.js'), 'test', '--config', config],
    options: { cwd: repositoryRoot, timeoutMs: 20 * 60_000,
      env: { ODIN_APP_E2E: '1', ODIN_APP_E2E_OUT: output, ODIN_APP_UI_CAPTURE: '1',
        ODIN_APP_UI_PLAN: join(output, 'capture-plan.json') } }
  }
}

// Freeze only the fixture's presentation clock. Timeouts/event loops remain real.
// The exact fixture file is passed explicitly, never discovered or substituted.
export function fixtureCommand(python, fixture, fields = []) {
  if (!python || !isAbsolute(python) || !isAbsolute(fixture)) throw new Error('Explicit absolute engine Python and fixture path required')
  const bootstrap = `import datetime, runpy, sys, uuid, random\nclass FrozenDateTime(datetime.datetime):\n    @classmethod\n    def now(cls, tz=None):\n        value = cls(2026, 10, 8, 3, 43, tzinfo=datetime.timezone.utc)\n        return value.astimezone(tz) if tz else value.replace(tzinfo=None)\ndatetime.datetime = FrozenDateTime\nfixture_random = random.Random(20261008)\nuuid.uuid4 = lambda: uuid.UUID(int=fixture_random.getrandbits(128), version=4)\nfixture = sys.argv.pop(1)\nsys.argv[0] = fixture\nrunpy.run_path(fixture, run_name='__main__')`
  // developmentArgv correctly rejects literal control characters. Keep argv a
  // single printable line; Python exec receives escaped newlines as data.
  const augmented = fields.length ? bootstrap.replace("runpy.run_path(fixture, run_name='__main__')",
    `import asyncio, json\nmodule = runpy.run_path(fixture, run_name='capture_fixture')\nfor row in json.loads(${JSON.stringify(JSON.stringify(fields))}):\n    existing = module['SETTINGS_FIELDS'].get(row[0])\n    record = dict(existing) if existing else module['field'](*row[:4], apply_mode=row[4] if len(row) > 4 else 'live_read')\n    record['default'] = row[3]\n    module['SETTINGS_FIELDS'][row[0]] = record\nfor path, metadata in json.loads(${JSON.stringify(JSON.stringify(CAPTURE_FIELD_METADATA))}).items():\n    if path in module['SETTINGS_FIELDS']:\n        module['SETTINGS_FIELDS'][path] = {**module['SETTINGS_FIELDS'][path], **metadata}\ncapture_catalogue = json.loads(${JSON.stringify(JSON.stringify(CAPTURE_MODEL_CATALOGUE))})\nmodule['METHODS']['models.status'] = lambda core, params, writer: {'model_catalogue': capture_catalogue}\ncapture_outbound = json.loads(${JSON.stringify(JSON.stringify(CAPTURE_OUTBOUND_WEBHOOKS))})\nmodule['METHODS']['webhooks.outbound.list'] = lambda core, params, writer: capture_outbound\nsys.exit(asyncio.run(module['main']()))`) : bootstrap
  const statusBootstrap = fields.length ? augmented.replace(
    "sys.exit(asyncio.run(module['main']()))",
    `capture_status = json.loads(${JSON.stringify(JSON.stringify(CAPTURE_MODEL_STATUS))})\nmodule['METHODS']['models.status'] = lambda core, params, writer: capture_status\nsys.exit(asyncio.run(module['main']()))`
  ) : augmented
  return [python, '-B', '-P', '-c', `exec(${JSON.stringify(statusBootstrap)})`, fixture]
}

async function bounded(command, args, cwd, timeoutMs = 180_000) {
  console.log(`UI capture prerequisite: ${command} ${args.join(' ')}`)
  await new Promise((accept, reject) => {
    const child = spawn(command, args, { cwd, stdio: 'inherit', detached: true })
    let timedOut = false
    const timer = setTimeout(() => { timedOut = true; try { process.kill(-child.pid, 'SIGKILL') } catch {} }, timeoutMs)
    child.once('error', (error) => { clearTimeout(timer); reject(error) })
    child.once('exit', (code, signal) => {
      clearTimeout(timer)
      if (code === 0 && !timedOut) accept()
      else reject(new Error(`${command} failed: code=${code}, signal=${signal}, timedOut=${timedOut}`))
    })
  })
}

function sourceProvenance(appDir) {
  const files = []
  const visit = (path) => {
    for (const entry of readdirSync(path, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const full = join(path, entry.name)
      if (entry.isDirectory()) visit(full)
      else if (entry.isFile()) files.push({ path: relative(repositoryRoot, full), sha256: sha256(readFileSync(full)) })
    }
  }
  for (const directory of ['src', 'fixture-core', 'scripts', 'out', 'test']) visit(join(appDir, directory))
  for (const path of ['playwright.config.ts', 'package.json', 'package-lock.json']) {
    files.push({ path: `app/${path}`, sha256: sha256(readFileSync(join(appDir, path))) })
  }
  return { files, digest: sha256(JSON.stringify(files)) }
}

export async function runCapture() {
  assertStableTree(process.env.ODIN_APP_UI_TREE_STABLE)
  if (process.platform !== 'linux' || process.getuid?.() === 0 || process.getuid?.() !== process.geteuid?.()) {
    throw new Error('Run UI capture as the nonprivileged odin user. No root Electron or sandbox bypass.')
  }
  const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const output = externalOutput(process.env.ODIN_APP_E2E_OUT)
  mkdirSync(output, { recursive: true, mode: 0o700 })
  // Keep prior evidence intact. Every rerun gets a fresh private profile and evidence directory.
  const runDirectory = join(output, `ui-d-${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`)
  mkdirSync(runDirectory, { mode: 0o700 })
  const config = join(runDirectory, 'capture.config.ts')
  const manifest = {
    schema: 'odin-ui-d-capture-v1', startedAt: new Date().toISOString(), outcome: 'running',
    scope: 'UI D source-build evidence matrix; all Settings, chat empty/populated, measured geometry and expanded workflows',
    limitations: ['Fixture core, not model or production-core evidence', 'No installed package, VM, live display, Orca or platform qualification',
      'Fixture schema samples and accounts are synthetic; appearance does not prove engine adoption or workflow qualification',
      'Existing ownership, onboarding, accessibility and nonreplay gates are independent; this manifest does not claim their qualification',
      'Real Advanced owner inventory remains a separately captured REAL-core receipt; synthetic Advanced does not prove engine ownership'],
    runDirectory, epoch: CAPTURE_EPOCH, primaryNavigation: PRIMARY_NAV,
    screenshotVariants: CAPTURE_VARIANTS, singleScreenshotBoundsVariants: BOUNDS_VARIANTS,
    isolation: { runner: 'launchIsolated', uid: process.getuid(), gid: process.getgid(),
      privateHomeXdg: true, privatePidProc: true, privateDbus: true, xvfb: '2048x1200x24',
      chromiumSandbox: true, rendererSandbox: true, contextIsolation: true, nodeIntegration: false },
    fixtureFields: CAPTURE_FIXTURE_FIELDS, fixtureModelCatalogue: CAPTURE_MODEL_CATALOGUE,
    fixtureOutboundWebhooks: CAPTURE_OUTBOUND_WEBHOOKS,
    fixtureFieldMetadata: CAPTURE_FIELD_METADATA,
    fixtureModelStatus: CAPTURE_MODEL_STATUS,
    existingGates: [],
    requiredStates: REQUIRED_STATES, advancedCategories: ADVANCED_CATEGORIES,
    screenshots: [], contactSheets: [], outcomes: []
  }
  let failure
  try {
    // Concurrent UI editing is coordinated by the parent before this runner is invoked.
    await bounded('npm', ['run', 'typecheck'], appDir)
    await bounded('npm', ['run', 'build'], appDir)
    manifest.git = {
      head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repositoryRoot, encoding: 'utf8' }).trim(),
      status: execFileSync('git', ['status', '--short'], { cwd: repositoryRoot, encoding: 'utf8' }),
      diffSha256: sha256(execFileSync('git', ['diff', 'HEAD', '--', 'app'], { cwd: repositoryRoot, maxBuffer: 16 * 1024 * 1024 }))
    }
    manifest.source = sourceProvenance(appDir)
    manifest.existingGates = EXISTING_GATES.map((gate) => ({ ...gate, outcome: 'separate-gate-required',
      sourceHashes: gate.source.map((path) => ({ path, sha256: sha256(readFileSync(join(repositoryRoot, path))) })) }))
    // Playwright compiles .ts tests to CJS in this project. Supply data, not a
    // CJS import of this executable ESM runner (which contains import.meta).
    writeFileSync(join(runDirectory, 'capture-plan.json'), JSON.stringify({
      epoch: CAPTURE_EPOCH, navigation: PRIMARY_NAV, variants: CAPTURE_VARIANTS, bounds: BOUNDS_VARIANTS,
      requiredStates: REQUIRED_STATES, advancedCategories: ADVANCED_CATEGORIES,
      fixtureModelCatalogue: CAPTURE_MODEL_CATALOGUE,
      fixtureOutboundWebhooks: CAPTURE_OUTBOUND_WEBHOOKS,
      longAccountLabel: CAPTURE_LONG_ACCOUNT_LABEL,
      command: fixtureCommand(resolve(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python')),
        join(appDir, 'fixture-core/fixture_core.py'), CAPTURE_FIXTURE_FIELDS)
    }, null, 2) + '\n', { mode: 0o600 })
    // Own no shared configuration file: a disposable absolute-path config overrides only selection/report location.
    writeFileSync(config, `import base from ${JSON.stringify(join(appDir, 'playwright.config.ts'))}\nexport default { ...base, testDir: ${JSON.stringify(join(appDir, 'test/e2e'))}, testMatch: ['ui-v1-capture.spec.ts'], timeout: 300000, retries: 0, workers: 1, use: { trace: 'off', screenshot: 'off', video: 'off' } }\n`, { mode: 0o600 })
    const plan = captureLaunchPlan(appDir, config, runDirectory)
    await launchIsolated(plan.command, plan.args, plan.options)
    const after = sourceProvenance(appDir)
    if (manifest.source.digest !== after.digest) throw new Error('Source/build changed during capture; evidence is not a coherent source snapshot')
    manifest.outcome = 'passed'
  } catch (error) {
    failure = error
    manifest.outcome = 'failed'
    manifest.error = String(error?.stack || error)
  } finally {
    for (const variant of CAPTURE_VARIANTS) {
      const receipt = join(runDirectory, `${variant.key}.json`)
      if (existsSync(receipt)) manifest.outcomes.push(JSON.parse(readFileSync(receipt, 'utf8')))
    }
    for (const name of readdirSync(runDirectory).filter((name) => name.endsWith('.png')).sort()) {
      const path = join(runDirectory, name)
      const bytes = readFileSync(path)
      manifest.screenshots.push({ path, relativePath: name, bytes: bytes.length, sha256: sha256(bytes) })
    }
    for (const name of ['capture-plan.json', 'playwright.json', ...CAPTURE_VARIANTS.map((variant) => `${variant.key}.json`)]) {
      const path = join(runDirectory, name)
      if (existsSync(path)) {
        manifest.evidenceFiles ??= []
        const bytes = readFileSync(path)
        manifest.evidenceFiles.push({ path, bytes: bytes.length, sha256: sha256(bytes) })
      }
    }
    if (manifest.outcome === 'passed') {
      try {
        validateCaptureEvidence(manifest.outcomes)
        for (const receipt of manifest.outcomes) {
          for (const group of [...receipt.pages, { name: 'Expanded workflows', frames: receipt.screenshots.filter((image) => !receipt.pages.some((page) => page.frames.some((frame) => frame.path === image.path))) },
            { name: 'All settings', frames: receipt.screenshots },
            { name: 'Models complete', frames: receipt.screenshots.filter((image) => image.label.startsWith('models-') || image.label.startsWith('provider-')) }]) {
            const path = join(runDirectory, `${receipt.variant.key}-${group.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-contact-sheet.png`)
            execFileSync('montage', contactSheetArgs(group.frames.map((image) => image.path), path), { timeout: 120_000 })
            const bytes = readFileSync(path)
            manifest.contactSheets.push({ path, bytes: bytes.length, sha256: sha256(bytes), group: group.name, variant: receipt.variant.key })
          }
        }
      } catch (error) {
        manifest.outcome = 'failed'
        failure = error
        manifest.error = String(error?.stack || error)
      }
    }
    manifest.finishedAt = new Date().toISOString()
    rmSync(config, { force: true })
    const path = join(runDirectory, 'manifest.json')
    writeFileSync(path, JSON.stringify(manifest, null, 2) + '\n', { mode: 0o600 })
    console.log(`UI C capture ${manifest.outcome}: ${path}`)
    console.log(`Manifest SHA256: ${sha256(readFileSync(path))}`)
  }
  if (failure) throw failure
  return manifest
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCapture().catch((error) => { console.error(error); process.exitCode = 1 })
}
