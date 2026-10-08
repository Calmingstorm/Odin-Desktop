// No build here. The parent must stabilize the shared app/out before invoking.
// Source-build real Composer + synthetic core geometry evidence, not platform qualification.
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

const digest = (bytes) => createHash('sha256').update(bytes).digest('hex')
export const COMPOSER_PROOFS = ['growth-paste', 'send-draft', 'width-font', 'scroll-stability', 'bounds-commands']
export function validateComposerReceipts(receipts) {
  if (!Array.isArray(receipts) || receipts.length !== COMPOSER_PROOFS.length ||
    new Set(receipts.map((item) => item?.name)).size !== COMPOSER_PROOFS.length) {
    throw new Error('Expected exactly five unique composer proof receipts')
  }
  for (const name of COMPOSER_PROOFS) {
    const receipt = receipts.find((item) => item.name === name)
    if (!receipt || receipt.outcome !== 'passed' || receipt.cleanupError || !Array.isArray(receipt.measurements) || !receipt.measurements.length) {
      throw new Error(`Missing complete passing composer proof: ${name}`)
    }
  }
}
export function composerOutput(value) {
  const requested = resolve(value || '/mnt/storage/odin-desktop-evidence/ui-v1-composer-geometry')
  let ancestor = requested
  while (!existsSync(ancestor)) ancestor = dirname(ancestor)
  const output = resolve(realpathSync(ancestor), relative(ancestor, requested))
  const repo = realpathSync(repositoryRoot)
  if (output === repo || output.startsWith(repo + sep)) throw new Error('Composer evidence must stay outside repository')
  return output
}
export function composerFixtureCommand(python, fixture) {
  if (!python || !fixture || !python.startsWith('/') || !fixture.startsWith('/')) throw new Error('Explicit absolute Python and fixture paths required')
  // Seed through the fixture's own methods, never DOM-inject messages or replace Composer.
  const bootstrap = `import asyncio, runpy, sys\nfixture = sys.argv.pop(1)\nmodule = runpy.run_path(fixture, run_name='composer_geometry_fixture')\nCore = module['Core']\noriginal = Core.__init__\ndef init(self, *args, **kwargs):\n    original(self, *args, **kwargs)\n    conv = self.m_conv_create({'title': 'Composer geometry history'}, None)['conversation']\n    for index in range(60):\n        self.commit_message(conv['id'], {'id': 'geometry-message-' + str(index), 'role': 'user', 'created_at': module['now'](), 'text': 'Geometry history row ' + str(index) + '\\n' + 'A stable reading anchor for composer resizing. ' * 8}, unread=False)\nCore.__init__ = init\nsys.exit(asyncio.run(module['main']()))`
  return [python, '-B', '-P', '-c', `exec(${JSON.stringify(bootstrap)})`, fixture]
}
function provenance(appDir) {
  const files = []
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) visit(path)
      else if (entry.isFile()) files.push({ path: relative(repositoryRoot, path), sha256: digest(readFileSync(path)) })
    }
  }
  for (const directory of ['src', 'out']) visit(join(appDir, directory))
  for (const path of ['fixture-core/fixture_core.py', 'test/e2e/harness.ts', 'test/e2e/composer-geometry.spec.ts',
    'test/e2e/composer-geometry.config.ts', 'scripts/composer-geometry.mjs', 'scripts/real-core-isolation.mjs']) {
    files.push({ path: `app/${path}`, sha256: digest(readFileSync(join(appDir, path))) })
  }
  return { files, digest: digest(JSON.stringify(files)) }
}
export async function runComposerGeometry() {
  if (process.platform !== 'linux' || process.getuid?.() === 0 || process.getuid?.() !== process.geteuid?.()) {
    throw new Error('Run as unchanged nonprivileged odin user; no root Electron or sandbox bypass')
  }
  const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  if (!existsSync(join(appDir, 'out/main/index.js'))) throw new Error('Parent must build app first; runner never builds shared out')
  const output = composerOutput(process.env.ODIN_APP_E2E_OUT)
  mkdirSync(output, { recursive: true, mode: 0o700 })
  const runDirectory = join(output, `composer-${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`)
  mkdirSync(runDirectory, { mode: 0o700 })
  const plan = { command: composerFixtureCommand(resolve(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python')),
    join(appDir, 'fixture-core/fixture_core.py')) }
  writeFileSync(join(runDirectory, 'plan.json'), JSON.stringify(plan, null, 2) + '\n', { mode: 0o600 })
  const manifest = { schema: 'odin-composer-geometry-v1', startedAt: new Date().toISOString(), outcome: 'running',
    runDirectory, noBuild: true, source: provenance(appDir),
    git: { head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repositoryRoot, encoding: 'utf8' }).trim(),
      status: execFileSync('git', ['status', '--short'], { cwd: repositoryRoot, encoding: 'utf8' }) },
    isolation: { uid: process.getuid(), gid: process.getgid(), privateHomeXdg: true, privatePidProc: true,
      privateDbus: true, xvfb: '2048x1200x24', chromiumSandbox: true },
    limitation: 'Real source-built Composer with synthetic fixture core. Not installed-package, model, engine or native-platform qualification.' }
  let failure
  try {
    await launchIsolated('dbus-run-session', ['--config-file', join(repositoryRoot, 'tests/desktop_fixtures/private-session.conf'), '--',
      'xvfb-run', '-a', '-s', '-screen 0 2048x1200x24 -nolisten tcp', process.execPath,
      join(appDir, 'node_modules/@playwright/test/cli.js'), 'test', '--config', join(appDir, 'test/e2e/composer-geometry.config.ts'),
      ...process.argv.slice(2)], { cwd: repositoryRoot, timeoutMs: 10 * 60_000,
      env: { ODIN_APP_E2E: '1', ODIN_APP_COMPOSER_GEOMETRY: '1', ODIN_APP_E2E_OUT: runDirectory,
        ODIN_APP_COMPOSER_PLAN: join(runDirectory, 'plan.json') } })
    validateComposerReceipts(COMPOSER_PROOFS.map((name) => {
      const path = join(runDirectory, `${name}.json`)
      return existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : { name, outcome: 'missing' }
    }))
    if (manifest.source.digest !== provenance(appDir).digest) throw new Error('Source/build changed during proof; incoherent snapshot')
    manifest.outcome = 'passed'
  } catch (error) { failure = error; manifest.outcome = 'failed'; manifest.error = String(error?.stack || error) }
  finally {
    manifest.completedAt = new Date().toISOString()
    manifest.evidence = readdirSync(runDirectory).filter((name) => /\.(json|png)$/.test(name)).sort().map((name) => {
      const bytes = readFileSync(join(runDirectory, name))
      return { path: join(runDirectory, name), bytes: bytes.length, sha256: digest(bytes) }
    })
    writeFileSync(join(runDirectory, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n', { mode: 0o600 })
    console.log(`Composer geometry ${manifest.outcome}: ${runDirectory}`)
  }
  if (failure) throw failure
  return manifest
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runComposerGeometry().catch((error) => { console.error(error.stack || error); process.exitCode = 1 })
}
