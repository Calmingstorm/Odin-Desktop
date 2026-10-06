import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readlinkSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type ElectronApplication } from '@playwright/test'
import { assertIsolated, exitApp, isolatedEnv, launchApp, repository, request, snapshot, waitForCore } from './harness'

// Source qualification composition, not a claim of arbitrary graphical grants.
const entry = join(repository, 'tests/desktop_fixtures/native_reconciliation_entry.py')
const receiverEntry = join(repository, 'tests/desktop_fixtures/native_lifecycle_receiver.py')
type Row = { kind: string; type?: number; detail?: number; window?: number; pid?: number; keys?: number[] }
function rows(path: string): Row[] {
  if (!existsSync(path)) return []
  return readFileSync(path, 'utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line) as Row)
}
function identity(pid: number) {
  const text = readFileSync(`/proc/${pid}/stat`, 'utf8')
  return { pid, start_ticks: Number(text.slice(text.lastIndexOf(')') + 2).split(' ')[19]),
    namespace: readlinkSync(`/proc/${pid}/ns/pid`) }
}
function sameProcess(value: { pid: number; start_ticks: number }): boolean {
  try { return identity(value.pid).start_ticks === value.start_ticks } catch { return false }
}
async function runRecover(root: string, env: Record<string, string>) {
  const child = spawn(process.env.ODIN_DESKTOP_ENGINE_PYTHON!, [entry, 'recover', root],
    { cwd: repository, env, stdio: ['ignore', 'pipe', 'pipe'] })
  let stdout = '', stderr = ''
  child.stdout.on('data', (data: Buffer) => { stdout += data.toString() })
  child.stderr.on('data', (data: Buffer) => { stderr += data.toString() })
  const code = await new Promise<number | null>((done, reject) => {
    const deadline = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('Native recovery timed out')) }, 8_000)
    child.once('error', reject)
    child.once('exit', (code) => { clearTimeout(deadline); done(code) })
  })
  expect(code, stderr).toBe(0)
  return JSON.parse(stdout.trim()) as Record<string, any>
}

for (const loss of ['controller', 'guardian', 'app-parent'] as const) {
  test(`real native ${loss} loss: restart quarantine, original reconcile, no replay`, async ({}, info) => {
    assertIsolated()
    const profile = `native-${loss}`
    const env = isolatedEnv(profile)
    const root = join(process.env.ODIN_REAL_CORE_ROOT!, profile)
    mkdirSync(root, { mode: 0o700 })
    const edgesPath = join(root, 'receiver.jsonl')
    const receiver = spawn(process.env.ODIN_DESKTOP_ENGINE_PYTHON!, [receiverEntry, edgesPath],
      { cwd: repository, env, stdio: ['pipe', 'pipe', 'pipe'] })
    let receiverError = ''
    receiver.stderr.on('data', (data: Buffer) => { receiverError += data.toString() })
    let app: ElectronApplication | null = null
    let original: { controller: {pid: number; start_ticks: number}; guardian: {pid: number; start_ticks: number}; helper: {pid: number; start_ticks: number} } | null = null
    let replacement: ElectronApplication | null = null
    try {
      await expect.poll(() => rows(edgesPath)[0]?.kind, { message: receiverError }).toBe('ready')
      const ready = rows(edgesPath)[0]!
      const receiverIdentity = identity(receiver.pid!)
      app = await launchApp({ profile })
      await waitForCore(app)
      receiver.stdin.write('focus\n')
      await expect.poll(() => rows(edgesPath).some((row) => row.kind === 'focused')).toBe(true)
      // ACTUAL sandboxed Electron main is the parent. SIGKILL closes its pipe.
      await app.evaluate((_electron, input) => {
        const { spawn } = process.getBuiltinModule('child_process') as typeof import('node:child_process')
        const child = spawn(input.python, [input.entry, 'controller', input.root,
          String(input.window), String(input.receiverPid)],
        { cwd: input.repository, env: input.env, stdio: ['pipe', 'pipe', 'pipe'] })
        const state = { child, stdout: '', stderr: '', ended: false }
        child.stdout.on('data', (chunk: Buffer) => { state.stdout += chunk.toString() })
        child.stderr.on('data', (chunk: Buffer) => { state.stderr += chunk.toString() })
        child.on('exit', () => { state.ended = true })
        ;(globalThis as any).__nativeQualification = state
      }, { python: process.env.ODIN_DESKTOP_ENGINE_PYTHON!, entry, root, window: ready.window!,
        receiverPid: receiver.pid!, repository, env })
      await expect.poll(() => existsSync(join(root, 'identity.json'))).toBe(true)
      original = JSON.parse(readFileSync(join(root, 'identity.json'), 'utf8'))
      expect(identity(original!.controller.pid).namespace).toBe(receiverIdentity.namespace)
      await expect.poll(() => rows(edgesPath).filter((row) => row.type === 2).length).toBe(1)
      if (loss === 'app-parent') {
        const mainPid = app.process().pid!
        expect(identity(mainPid).namespace).toBe(receiverIdentity.namespace)
        const closed = app.waitForEvent('close')
        process.kill(mainPid, 'SIGKILL')
        await closed
        app = null
      } else {
        const victim = original![loss]
        expect(sameProcess(victim)).toBe(true)
        process.kill(victim.pid, 'SIGKILL')
      }
      // No global key-up. Guardian hard lease bounds surviving work.
      await new Promise((done) => setTimeout(done, 2_500))
      const afterLoss = rows(edgesPath).filter((row) => row.kind === 'edge')
      expect(afterLoss.filter((row) => row.type === 2)).toHaveLength(1)
      receiver.stdin.write('state\n')
      await expect.poll(() => rows(edgesPath).filter((row) => row.kind === 'server-keymap').length).toBe(1)
      const serverKeymap = rows(edgesPath).find((row) => row.kind === 'server-keymap')!
      if (loss !== 'guardian') {
        expect(afterLoss.filter((row) => row.type === 3)).toHaveLength(1)
        expect(serverKeymap.keys).not.toContain(afterLoss[0]!.detail)
        expect(existsSync(join(root, 'guardian-receipt.json'))).toBe(true)
        const nativeReceipt = JSON.parse(readFileSync(join(root, 'guardian-receipt.json'), 'utf8'))
        expect(nativeReceipt.released).toBe(true)
        expect(nativeReceipt.status).toBe('unknown')
      } else {
        expect(existsSync(join(root, 'guardian-receipt.json'))).toBe(false)
      }
      if (app) { await exitApp(app); app = null }
      const nativeCore = { ODIN_DESKTOP_CORE_CMD: JSON.stringify([
        process.env.ODIN_DESKTOP_ENGINE_PYTHON!, entry, 'core', root]) }
      replacement = await launchApp({ profile, env: nativeCore })
      try { await waitForCore(replacement) } catch (error) {
        const failed = await snapshot(replacement)
        await info.attach('native-core-startup-log', { contentType: 'text/plain',
          body: Buffer.from(readFileSync(join(failed.paths.dataDir, 'logs/core.log'), 'utf8')) })
        throw error
      }
      await expect.poll(() => existsSync(join(root, 'core-native-owner.json'))).toBe(true)
      const restarted = await runRecover(root, env)
      expect(restarted.qualification).toBe('test-only-original-native-composition')
      expect(restarted.production_controller_reconcile_denial).toBe('operator_surface_required')
      expect(restarted.recovery_composition).toBe('original-verify_absence-and-store-CAS-test-only')
      expect(restarted.controller_source).toBe(join(repository, 'src/computer/controller.py'))
      expect(restarted.store_source).toBe(join(repository, 'src/computer/store.py'))
      expect(restarted.state).toBe('quarantined')
      expect(restarted.recovery.complete).toBe(false)
      expect(restarted.recovery.status).toBe('unknown')
      expect(['owned_input_release_unproven', 'owned_process_remaining', 'process_inspection_unavailable'])
        .toContain(restarted.recovery.reason)
      expect(restarted.receipt.status).toBe('unknown')
      expect(restarted.receipt.reason).toBe('controller_lost')
      expect(restarted.retry_receipt).toEqual(restarted.receipt)
      expect(restarted.new_session_error).toBe('session_busy')
      expect(restarted.live_backends).toBe(0)
      const repeated = await runRecover(root, env)
      expect(repeated.state).toBe('quarantined')
      expect(repeated.generation).toBe(restarted.generation)
      await new Promise((done) => setTimeout(done, 150))
      expect(rows(edgesPath).filter((row) => row.kind === 'edge')).toEqual(afterLoss)
      expect(sameProcess(receiverIdentity)).toBe(true)
      const nativeAppState = await snapshot(replacement)
      await exitApp(replacement)
      replacement = null
      const cleanupPath = join(nativeAppState.paths.dataDir, 'resource-cleanup.json')
      const coreNativeCleanup = JSON.parse(readFileSync(cleanupPath, 'utf8'))
      expect(coreNativeCleanup.state).toBe('unknown')
      expect(coreNativeCleanup.resources.computer.state).toBe('unknown')
      replacement = await launchApp({ profile, env: nativeCore })
      await waitForCore(replacement)
      const publicStatus = await request(replacement, 'status.get')
      expect(publicStatus.ok).toBe(true)
      const publicCleanup = (publicStatus.result as any).resource_cleanup
      expect(publicCleanup.reconciliation_required).toBe(true)
      expect(publicCleanup.previous_unknown.state).toBe('unknown')
      expect(publicCleanup.replay).toBe(false)
      await info.attach(`native-${loss}-evidence`, { contentType: 'application/json',
        body: Buffer.from(JSON.stringify({ qualification: 'test-only-original-native-composition',
          fullGraphicalControllerGrant: 'not-qualified', namespace: receiverIdentity.namespace,
          receiverIdentity, original, receiverEdges: afterLoss, serverKeymap,
          guardianReceipt: existsSync(join(root, 'guardian-receipt.json'))
            ? JSON.parse(readFileSync(join(root, 'guardian-receipt.json'), 'utf8')) : null,
          restarted, repeated, coreNativeCleanup, publicCleanup, noReplayMeasured: true,
          limitation: 'Shared X11 reconcile is read-only. PID absence or incidental receiver release is not universal release proof.' }, null, 2)) })
    } finally {
      if (app) { try { await app.close() } catch { /* already lost */ } }
      if (replacement) { try { await replacement.close() } catch { /* already lost */ } }
      if (original && sameProcess(original.controller)) process.kill(original.controller.pid, 'SIGKILL')
      if (original && sameProcess(original.guardian)) process.kill(original.guardian.pid, 'SIGKILL')
      receiver.stdin.end()
      if (receiver.exitCode === null && receiver.signalCode === null) {
        await new Promise<void>((done) => {
          const timeout = setTimeout(() => { receiver.kill('SIGKILL') }, 2_000)
          receiver.once('exit', () => { clearTimeout(timeout); done() })
        })
      }
    }
  })
}
