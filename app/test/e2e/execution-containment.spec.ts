import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readlinkSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type TestInfo } from '@playwright/test'
import { exitApp, isolatedEnv, launchApp, repository, snapshot, waitForCore } from './harness'
import { admissionReceipt } from './admission-receipt'

type Identity = { pid: number; ppid: number; sid: number; pgid: number; startTicks: string; namespace: string }
function identity(pid: number): Identity {
  const stat = readFileSync(`/proc/${pid}/stat`, 'utf8')
  const fields = stat.slice(stat.lastIndexOf(')') + 2).split(' ')
  return { pid, ppid: Number(fields[1]), pgid: Number(fields[2]), sid: Number(fields[3]),
    startTicks: fields[19]!, namespace: readlinkSync(`/proc/${pid}/ns/pid`) }
}
function alive(original: Identity): boolean {
  try {
    const stat = readFileSync(`/proc/${original.pid}/stat`, 'utf8')
    const fields = stat.slice(stat.lastIndexOf(')') + 2).split(' ')
    return fields[0] !== 'Z' && fields[19] === original.startTicks
      && readlinkSync(`/proc/${original.pid}/ns/pid`) === original.namespace
  } catch { return false }
}
function counter(root: string, role: string) { return readFileSync(join(root, `${role}.effects`), 'utf8').split('\n').length - 1 }
async function evidence(info: TestInfo, name: string, data: unknown) {
  await info.attach(name, { body: Buffer.from(JSON.stringify(data, null, 2)), contentType: 'application/json' })
}
function options(profile: string) {
  const root = join(process.env.HOME!, `execution-${profile}`)
  mkdirSync(root, { mode: 0o700 })
  const env = { ODIN_APP_EXECUTION_ROOT: root,
    ODIN_DESKTOP_CORE_CMD: JSON.stringify([process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
      join(repository, 'tests/desktop_fixtures/lifecycle_engine_entry.py')]) }
  return { root, profile, env }
}
async function admitted(root: string) {
  await expect.poll(() => existsSync(join(root, 'escaped.json')) && existsSync(join(root, 'leader.json'))).toBe(true)
  const leader: Identity = JSON.parse(readFileSync(join(root, 'leader.json'), 'utf8'))
  const escaped: Identity = JSON.parse(readFileSync(join(root, 'escaped.json'), 'utf8'))
  expect(alive(leader)).toBe(true)
  expect(alive(escaped)).toBe(true)
  expect(escaped.sid).not.toBe(leader.sid)
  expect(escaped.pgid).not.toBe(leader.pgid)
  await expect.poll(() => counter(root, 'escaped')).toBeGreaterThan(2)
  await expect.poll(() => admissionReceipt(join(root, 'admitted.json'))).not.toBeNull()
  const admission = admissionReceipt(join(root, 'admitted.json')) as { records: Array<{ supervisorPid: number }> }
  const supervisor = identity(admission.records[0]!.supervisorPid)
  expect(alive(supervisor)).toBe(true)
  return { leader, escaped, supervisor, admission }
}
async function settled(root: string, owned: Awaited<ReturnType<typeof admitted>>) {
  await expect.poll(() => alive(owned.leader) || alive(owned.escaped) || alive(owned.supervisor), { timeout: 12_000 }).toBe(false)
  const stopped = { leader: counter(root, 'leader'), escaped: counter(root, 'escaped') }
  await new Promise(done => setTimeout(done, 250))
  expect({ leader: counter(root, 'leader'), escaped: counter(root, 'escaped') }).toEqual(stopped)
  const lifecycle = readFileSync(join(root, 'lifecycle.jsonl'), 'utf8').trim().split('\n').map(line => JSON.parse(line))
  return { stopped, lifecycle, survivorsAbsent: true,
    scope: 'Original ProcessRegistry/local supervisor through test-only real-core composition, not supported chat dispatch or native input release' }
}

test('exact committed pre-barrier management source exposes missing registry shutdown', async ({}, info) => {
  const setup = options('baseline-gap')
  const env = { ...isolatedEnv(setup.profile), ...setup.env, ODIN_APP_EXECUTION_SOURCE_BASELINE: '1' }
  const config = join(setup.root, 'config'), data = join(setup.root, 'data')
  mkdirSync(config, { mode: 0o700 }); mkdirSync(data, { mode: 0o700 })
  const token = join(config, 'ipc.token'), socket = join(setup.root, 'core.sock')
  writeFileSync(token, 'ab'.repeat(32), { mode: 0o600 })
  const child = spawn(process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
    [join(repository, 'tests/desktop_fixtures/lifecycle_engine_entry.py'), '--socket', socket,
      '--token-file', token, '--profile', setup.profile, '--data-dir', data],
    { cwd: repository, env, stdio: ['pipe', 'pipe', 'pipe'] })
  let stderr = ''; child.stderr.on('data', chunk => { stderr += chunk.toString() })
  const ended = new Promise<{code: number | null; signal: string | null}>(done => child.once('exit', (code, signal) => done({ code, signal })))
  try {
    const owned = await admitted(setup.root)
    child.stdin.end()
    const result = await Promise.race([ended, new Promise<never>((_, reject) => setTimeout(() => reject(new Error('Baseline core EOF timeout')), 15_000))])
    const cleanup = await settled(setup.root, owned)
    await evidence(info, 'exact-source-baseline-owner-gap', { owned, result, cleanup, stderr })
    expect(cleanup.lifecycle.some(row => row.kind === 'exact_committed_baseline')).toBe(true)
    expect(cleanup.lifecycle.some(row => row.kind === 'registry_shutdown_enter')).toBe(false)
    const closed = cleanup.lifecycle.find(row => row.kind === 'management_close_return')
    expect(closed.records[0]).toMatchObject({ status: 'running', session_confirmed_empty: false })
    // The retained local supervisor independently contains descendants even
    // though the domain owner omitted settlement. Do not invent a leak claim.
    expect(stderr).toContain('Relaunch vetoed: local command supervisor ownership lost')
  } finally { child.stdin.end(); if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM') }
})

test('original execution owner shuts down escaped descendants on real-core parent EOF', async ({}, info) => {
  const setup = options('direct-eof')
  const env = { ...isolatedEnv(setup.profile), ...setup.env }
  const config = join(setup.root, 'config'), data = join(setup.root, 'data')
  mkdirSync(config, { mode: 0o700 }); mkdirSync(data, { mode: 0o700 })
  const token = join(config, 'ipc.token'), socket = join(setup.root, 'core.sock')
  writeFileSync(token, 'ab'.repeat(32), { mode: 0o600 })
  const child = spawn(process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
    [join(repository, 'tests/desktop_fixtures/lifecycle_engine_entry.py'), '--socket', socket,
      '--token-file', token, '--profile', 'direct-eof', '--data-dir', data],
    { cwd: repository, env, stdio: ['pipe', 'pipe', 'pipe'] })
  let stderr = ''; child.stderr.on('data', chunk => { stderr += chunk.toString() })
  const ended = new Promise<{code: number | null; signal: string | null}>(done => child.once('exit', (code, signal) => done({ code, signal })))
  try {
    const owned = await admitted(setup.root)
    child.stdin.end()
    const result = await Promise.race([ended, new Promise<never>((_, reject) => setTimeout(() => reject(new Error('Core EOF timeout')), 15_000))])
    const cleanup = await settled(setup.root, owned)
    await evidence(info, 'original-execution-parent-eof', { owned, result, cleanup, stderr, socketRemoved: !existsSync(socket) })
    expect(result.code).toBe(0)
    expect(existsSync(socket)).toBe(false)
    expect(cleanup.lifecycle.some(row => row.kind === 'registry_shutdown_return')).toBe(true)
  } finally { child.stdin.end(); if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM') }
})

for (const loss of ['orderly', 'abrupt'] as const) {
  test(`original execution descendants settle after ${loss} Electron parent loss without replay`, async ({}, info) => {
    const setup = options(loss)
    const application = await launchApp(setup)
    let closed = false
    try {
      const core = await waitForCore(application)
      const before = await snapshot(application)
      const owned = await admitted(setup.root)
      if (loss === 'orderly') await exitApp(application)
      else {
        const event = application.waitForEvent('close')
        application.process().kill('SIGKILL'); await event
      }
      closed = true
      const cleanup = await settled(setup.root, owned)
      const pending = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
      const resourceReceipt = JSON.parse(readFileSync(join(before.paths.dataDir, 'resource-cleanup.json'), 'utf8'))
      expect(resourceReceipt).toMatchObject({ state: 'complete', resources: { processes: { state: 'released', method: 'shutdown' } } })
      await evidence(info, `original-execution-${loss}`, { core, owned, cleanup, pending, resourceReceipt })
      expect(cleanup.lifecycle.some(row => row.kind === 'registry_shutdown_return')).toBe(true)
      const successor = await launchApp(setup)
      try {
        await waitForCore(successor)
        await expect.poll(() => readFileSync(join(setup.root, 'lifecycle.jsonl'), 'utf8').includes('restart_no_readmission')).toBe(true)
        expect(alive(owned.escaped)).toBe(false)
        expect(counter(setup.root, 'escaped')).toBe(cleanup.stopped.escaped)
        const recovered = await snapshot(successor)
        if (loss === 'abrupt') expect(recovered.cleanupUnknown?.state).toBe('unknown')
        await evidence(info, `original-execution-${loss}-successor`, { recovered,
          admissionUnchanged: JSON.parse(readFileSync(join(setup.root, 'admitted.json'), 'utf8')), effectsUnchanged: true })
        await exitApp(successor)
      } finally { try { await successor.close() } catch {} }
    } finally { if (!closed) { try { await application.close() } catch {} } }
  })
}
