// UI B visual-review evidence only. Not native desktop/platform qualification.
// Run as odin: ODIN_APP_E2E_OUT=/mnt/storage/odin-desktop-evidence/ui-v1-slice2-20261008 node scripts/ui-v1-capture.mjs
import { spawn, execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

export const CAPTURE_EPOCH = '2026-10-08T03:43:00.000Z'
export const DEFAULT_OUTPUT = '/mnt/storage/odin-desktop-evidence/ui-v1-slice2-20261008'
export const PRIMARY_NAV = ['General', 'Models and providers', 'Personality', 'Tools', 'Skills',
  'MCP servers', 'Hosts and access', 'Work', 'Data and privacy']
export const CAPTURE_VARIANTS = [
  { key: '1180x780-dark', width: 1180, height: 780, theme: 'dark' },
  { key: '1920x1080-light', width: 1920, height: 1080, theme: 'light' }
]
export const BOUNDS_VARIANTS = [
  { key: 'minimum-720x480', width: 720, height: 480, zoom: 1 },
  { key: 'zoom-200-percent', width: 1180, height: 780, zoom: 2 },
  { key: 'narrow-720x780', width: 720, height: 780, zoom: 1 }
]
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
    options: { cwd: repositoryRoot, timeoutMs: 10 * 60_000,
      env: { ODIN_APP_E2E: '1', ODIN_APP_E2E_OUT: output, ODIN_APP_UI_CAPTURE: '1',
        ODIN_APP_UI_PLAN: join(output, 'capture-plan.json') } }
  }
}

// Freeze only the fixture's presentation clock. Timeouts/event loops remain real.
// The exact fixture file is passed explicitly, never discovered or substituted.
export function fixtureCommand(python, fixture) {
  if (!python || !isAbsolute(python) || !isAbsolute(fixture)) throw new Error('Explicit absolute engine Python and fixture path required')
  const bootstrap = `import datetime, runpy, sys, uuid, random\nclass FrozenDateTime(datetime.datetime):\n    @classmethod\n    def now(cls, tz=None):\n        value = cls(2026, 10, 8, 3, 43, tzinfo=datetime.timezone.utc)\n        return value.astimezone(tz) if tz else value.replace(tzinfo=None)\ndatetime.datetime = FrozenDateTime\nfixture_random = random.Random(20261008)\nuuid.uuid4 = lambda: uuid.UUID(int=fixture_random.getrandbits(128), version=4)\nfixture = sys.argv.pop(1)\nsys.argv[0] = fixture\nrunpy.run_path(fixture, run_name='__main__')`
  // developmentArgv correctly rejects literal control characters. Keep argv a
  // single printable line; Python exec receives escaped newlines as data.
  return [python, '-B', '-P', '-c', `exec(${JSON.stringify(bootstrap)})`, fixture]
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
  for (const directory of ['src', 'fixture-core', 'scripts', 'out']) visit(join(appDir, directory))
  for (const path of ['playwright.config.ts', 'test/e2e/harness.ts', 'test/e2e/ui-v1-capture.spec.ts']) {
    files.push({ path: `app/${path}`, sha256: sha256(readFileSync(join(appDir, path))) })
  }
  return { files, digest: sha256(JSON.stringify(files)) }
}

export async function runCapture() {
  if (process.platform !== 'linux' || process.getuid?.() === 0 || process.getuid?.() !== process.geteuid?.()) {
    throw new Error('Run UI capture as the nonprivileged odin user. No root Electron or sandbox bypass.')
  }
  const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const output = externalOutput(process.env.ODIN_APP_E2E_OUT)
  mkdirSync(output, { recursive: true, mode: 0o700 })
  // Keep prior evidence intact. Every rerun gets a fresh private profile and evidence directory.
  const runDirectory = join(output, `ui-b-${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`)
  mkdirSync(runDirectory, { mode: 0o700 })
  const config = join(runDirectory, 'capture.config.ts')
  const manifest = {
    schema: 'odin-ui-b-capture-v1', startedAt: new Date().toISOString(), outcome: 'running',
    scope: 'UI B source-build visual review; General and settings shell only',
    limitations: ['Fixture core, not model or production-core evidence', 'No installed package, VM, live display, Orca or platform qualification',
      'Other settings pages remain staged; Models and providers is representative shell evidence, not conversion acceptance',
      'Small/narrow/200% zoom checks have no screenshots until UI D'],
    runDirectory, epoch: CAPTURE_EPOCH, primaryNavigation: PRIMARY_NAV,
    screenshotVariants: CAPTURE_VARIANTS, boundsOnlyVariants: BOUNDS_VARIANTS,
    isolation: { runner: 'launchIsolated', uid: process.getuid(), gid: process.getgid(),
      privateHomeXdg: true, privatePidProc: true, privateDbus: true, xvfb: '2048x1200x24',
      chromiumSandbox: true, rendererSandbox: true, contextIsolation: true, nodeIntegration: false },
    screenshots: [], outcomes: []
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
    // Playwright compiles .ts tests to CJS in this project. Supply data, not a
    // CJS import of this executable ESM runner (which contains import.meta).
    writeFileSync(join(runDirectory, 'capture-plan.json'), JSON.stringify({
      epoch: CAPTURE_EPOCH, navigation: PRIMARY_NAV, variants: CAPTURE_VARIANTS, bounds: BOUNDS_VARIANTS,
      command: fixtureCommand(resolve(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python')),
        join(appDir, 'fixture-core/fixture_core.py'))
    }, null, 2) + '\n', { mode: 0o600 })
    // Own no shared configuration file: a disposable absolute-path config overrides only selection/report location.
    writeFileSync(config, `import base from ${JSON.stringify(join(appDir, 'playwright.config.ts'))}\nexport default { ...base, testDir: ${JSON.stringify(join(appDir, 'test/e2e'))}, testMatch: ['ui-v1-capture.spec.ts'], timeout: 180000, retries: 0, workers: 1, use: { trace: 'off', screenshot: 'off', video: 'off' } }\n`, { mode: 0o600 })
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
    if (manifest.outcome === 'passed' && (manifest.outcomes.length !== CAPTURE_VARIANTS.length ||
      manifest.outcomes.some((receipt) => receipt.outcome !== 'passed') || manifest.screenshots.length !== 10)) {
      manifest.outcome = 'failed'
      failure = new Error('Capture evidence incomplete: expected two passing receipts and ten review PNGs')
      manifest.error = failure.message
    }
    manifest.finishedAt = new Date().toISOString()
    rmSync(config, { force: true })
    const path = join(runDirectory, 'manifest.json')
    writeFileSync(path, JSON.stringify(manifest, null, 2) + '\n', { mode: 0o600 })
    console.log(`UI B capture ${manifest.outcome}: ${path}`)
    console.log(`Manifest SHA256: ${sha256(readFileSync(path))}`)
  }
  if (failure) throw failure
  return manifest
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCapture().catch((error) => { console.error(error); process.exitCode = 1 })
}
