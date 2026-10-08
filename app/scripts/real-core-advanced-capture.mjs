// C12: production entry, real schema, synthetic disposable profile only.
// Parent must declare source/build stable before invoking. Never touches a live display.
import { execFileSync, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchIsolated, repositoryRoot } from './real-core-isolation.mjs'

export const DEFAULT_OUTPUT = '/mnt/storage/odin-desktop-evidence/ui-v1-review-c-real-advanced'
export const VARIANT = { key: '1180x780-dark', width: 1180, height: 780, theme: 'dark' }
export const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex')
export function externalOutput(value, repository = repositoryRoot) {
  const requested = resolve(value || DEFAULT_OUTPUT)
  let ancestor = requested
  while (!existsSync(ancestor)) ancestor = dirname(ancestor)
  const output = resolve(realpathSync(ancestor), relative(ancestor, requested))
  const root = realpathSync(repository)
  if (output === root || output.startsWith(root + sep)) throw new Error('Real-core evidence must remain outside the repository')
  return output
}
export function captureLaunchPlan(appDir, config, output, python) {
  if (!python || !python.startsWith('/')) throw new Error('Explicit absolute engine Python required')
  return {
    command: 'dbus-run-session',
    args: ['--config-file', join(repositoryRoot, 'tests/desktop_fixtures/private-session.conf'), '--',
      'xvfb-run', '-a', '-s', '-screen 0 1280x800x24 -nolisten tcp', process.execPath,
      join(appDir, 'node_modules/@playwright/test/cli.js'), 'test', '--config', config],
    options: { cwd: repositoryRoot, timeoutMs: 600_000,
      env: { ODIN_APP_E2E: '1', ODIN_APP_E2E_OUT: output, ODIN_APP_REAL_ADVANCED_CAPTURE: '1',
        ODIN_DESKTOP_ENGINE_PYTHON: python } }
  }
}
export function verifyRealCaptureReceipt(receipt) {
  if (receipt?.outcome !== 'passed' || receipt.realCore !== true || receipt.fixture !== false) throw new Error('Passing REAL core receipt required')
  if (JSON.stringify(receipt.variant) !== JSON.stringify(VARIANT)) throw new Error('Expected 1180x780 dark capture')
  if (!receipt.schema?.revision || !Array.isArray(receipt.inventory) || receipt.inventory.length <= 30 || !receipt.core?.instanceId || !receipt.cleanup?.orderlyExit) {
    throw new Error('Missing real-schema inventory, core identity or orderly cleanup evidence')
  }
  if (!Array.isArray(receipt.frames) || receipt.frames.length < 2 || receipt.frames[0].top !== 0) throw new Error('Missing full Advanced scroll evidence')
  for (let index = 1; index < receipt.frames.length; index++) {
    const previous = receipt.frames[index - 1], frame = receipt.frames[index]
    if (frame.height !== previous.height || frame.top <= previous.top || frame.top > previous.top + previous.client) throw new Error('Scroll coverage is unstable or has gaps')
  }
  const last = receipt.frames.at(-1)
  if (last.top + last.client < last.height - 1) throw new Error('Scroll evidence does not reach the bottom')
}
function sourceProvenance() {
  const files = []
  function visit(path) {
    for (const entry of readdirSync(path, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const full = join(path, entry.name)
      if (entry.isDirectory()) visit(full)
      else if (entry.isFile()) files.push({ path: relative(repositoryRoot, full), sha256: sha256(readFileSync(full)) })
    }
  }
  // Both engine and built app are source-bound. No fixture-core hash presented as real-core evidence.
  for (const path of ['src', 'app/src', 'app/out', 'app/scripts']) visit(join(repositoryRoot, path))
  for (const path of ['app/test/e2e/ui-v1-real-advanced.spec.ts', 'app/test/e2e/harness.ts']) {
    files.push({ path, sha256: sha256(readFileSync(join(repositoryRoot, path))) })
  }
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
export async function runCapture() {
  if (process.platform !== 'linux' || process.getuid?.() === 0 || process.getuid?.() !== process.geteuid?.()) throw new Error('Run as nonprivileged odin; no root Electron or sandbox bypass')
  const appDir = join(repositoryRoot, 'app')
  const output = externalOutput(process.env.ODIN_APP_E2E_OUT)
  mkdirSync(output, { recursive: true, mode: 0o700 })
  const runDirectory = join(output, `real-advanced-${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`)
  mkdirSync(runDirectory, { mode: 0o700 })
  const config = join(runDirectory, 'capture.config.ts')
  const python = resolve(process.env.ODIN_DESKTOP_ENGINE_PYTHON || join(repositoryRoot, '.venv/bin/python'))
  const manifest = { schema: 'odin-real-core-advanced-capture-v1', outcome: 'running', startedAt: new Date().toISOString(),
    runDirectory, realCore: true, fixture: false, variant: VARIANT, screenshots: [], evidenceFiles: [],
    scope: 'C12 full Advanced allowlist against production core settings.schema, synthetic disposable fresh profile',
    limitations: ['No account credentials or production profile; real default values on a synthetic fresh profile.',
      'No provider generation, native desktop/platform, install, VM or live-service qualification.',
      'Read-only Advanced evidence; persistence/adoption is covered by separate real-core gates.'],
    isolation: { runner: 'launchIsolated', uid: process.getuid(), gid: process.getgid(), privateHomeXdg: true,
      privatePidProc: true, privateDbus: true, xvfb: '1280x800x24', chromiumSandbox: true, rendererSandbox: true },
    engineCommand: [python, '-B', '-P', '-m', 'src'] }
  let failure
  try {
    await bounded('npm', ['run', 'typecheck'], appDir)
    await bounded('npm', ['run', 'build'], appDir)
    manifest.git = { head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repositoryRoot, encoding: 'utf8' }).trim(),
      status: execFileSync('git', ['status', '--short'], { cwd: repositoryRoot, encoding: 'utf8' }),
      diffSha256: sha256(execFileSync('git', ['diff', 'HEAD'], { cwd: repositoryRoot, maxBuffer: 16 * 1024 * 1024 })) }
    manifest.source = sourceProvenance()
    writeFileSync(config, `import base from ${JSON.stringify(join(appDir, 'playwright.config.ts'))}\nexport default { ...base, testDir: ${JSON.stringify(join(appDir, 'test/e2e'))}, testMatch: ['ui-v1-real-advanced.spec.ts'], timeout: 180000, retries: 0, workers: 1, use: { trace: 'off', screenshot: 'off', video: 'off' } }\n`, { mode: 0o600 })
    const plan = captureLaunchPlan(appDir, config, runDirectory, python)
    await launchIsolated(plan.command, plan.args, plan.options)
    const receipt = JSON.parse(readFileSync(join(runDirectory, 'real-advanced-receipt.json'), 'utf8'))
    verifyRealCaptureReceipt(receipt)
    manifest.receipt = receipt
    if (sourceProvenance().digest !== manifest.source.digest) throw new Error('Source/build changed during capture; evidence is not a coherent source snapshot')
    manifest.outcome = 'passed'
  } catch (error) { failure = error; manifest.outcome = 'failed'; manifest.error = String(error?.stack || error) }
  finally {
    for (const name of readdirSync(runDirectory).sort()) {
      if (!name.endsWith('.png') && !['real-advanced-receipt.json', 'playwright.json', 'advanced-schema.json'].includes(name)) continue
      const path = join(runDirectory, name), bytes = readFileSync(path)
      const record = { path, bytes: bytes.length, sha256: sha256(bytes) }
      ;(name.endsWith('.png') ? manifest.screenshots : manifest.evidenceFiles).push(record)
    }
    rmSync(config, { force: true })
    manifest.finishedAt = new Date().toISOString()
    const path = join(runDirectory, 'manifest.json')
    writeFileSync(path, JSON.stringify(manifest, null, 2) + '\n', { mode: 0o600 })
    console.log(`REAL Advanced capture ${manifest.outcome}: ${path}\nManifest SHA256: ${sha256(readFileSync(path))}`)
  }
  if (failure) throw failure
  return manifest
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runCapture().catch((error) => { console.error(error); process.exitCode = 1 })
}
