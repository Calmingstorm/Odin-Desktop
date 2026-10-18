import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { exitApp, launchApp, request, snapshot, waitForCore } from './harness'

for (const becomesReady of [true, false]) {
  test(`Exit during real core startup: readiness ${becomesReady ? 'arrives' : 'never arrives'}`, async ({}, info) => {
    const gate = join(process.env.ODIN_REAL_CORE_ROOT!, `startup-${becomesReady}.release`)
    const application = await launchApp({ profile: `startup-exit-${becomesReady}`, env: {
      ODIN_DESKTOP_STARTUP_GATE: gate,
      ODIN_DESKTOP_CORE_CMD: JSON.stringify([process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
        '-m', 'tests.desktop_fixtures.startup_gate_core'])
    } })
    let release: NodeJS.Timeout | undefined
    try {
      await expect.poll(() => existsSync(gate.replace(/\.release$/, '.entered')), { timeout: 20_000 }).toBe(true)
      const before = await snapshot(application)
      expect(before.appState.link).not.toBe('ready')
      expect(before.corePid).toBeTruthy()
      if (becomesReady) release = setTimeout(() => writeFileSync(gate, 'release'), 150)
      await exitApp(application)
      const appReceipt = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
      await info.attach('startup-exit-log', { body: readFileSync(join(before.paths.dataDir, 'logs/core.log')),
        contentType: 'text/plain' })
      await info.attach('startup-exit-app-receipt', { body: Buffer.from(JSON.stringify({ before, appReceipt }, null, 2)),
        contentType: 'application/json' })
      expect(appReceipt.current.shutdownAccepted).toBe(becomesReady)
      expect(appReceipt.current.state).toBe(becomesReady ? 'process-exited' : 'unknown')
      expect(appReceipt.current.unreceipted).toBe(0)
      const coreReceipt = JSON.parse(readFileSync(join(before.paths.dataDir, 'resource-cleanup.json'), 'utf8'))
      expect(coreReceipt.state).toBe(becomesReady ? 'complete' : 'unknown')
      await info.attach('startup-exit-receipts', { body: Buffer.from(JSON.stringify({ before, appReceipt, coreReceipt }, null, 2)),
        contentType: 'application/json' })
    } finally {
      if (release) clearTimeout(release)
      writeFileSync(gate, 'release')
      try { await application.close() } catch (error) { if (!/closed|_object/.test(String(error))) throw error }
    }
  })
}

test('Exit while the core still answers earlier requests: accepted, with every receipt', async ({}, info) => {
  const gate = join(process.env.ODIN_REAL_CORE_ROOT!, 'slow-reads.gate')
  const application = await launchApp({ profile: 'exit-behind-requests', env: {
    ODIN_DESKTOP_SLOW_READ_GATE: gate,
    ODIN_DESKTOP_CORE_CMD: JSON.stringify([process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
      '-m', 'tests.desktop_fixtures.slow_read_core'])
  } })
  try {
    await waitForCore(application)
    // Requests are answered in order: once this one is, nothing sent before it still waits.
    expect((await request(application, 'status.get')).ok).toBe(true)
    writeFileSync(gate, 'reads 4')
    const earlier = [1, 2, 3, 4].map(() => request(application, 'status.get')
      .catch((error: unknown) => ({ ok: false, error: String(error) })))
    await expect.poll(() => existsSync(gate.replace(/\.gate$/, '.entered')), { timeout: 10_000 }).toBe(true)
    const before = await snapshot(application)
    // Four 2 s answers: each sooner than Exit's 5 s bound, together longer. Exit waits its turn behind them.
    await exitApp(application)
    expect((await Promise.all(earlier)).every((settled) => settled.ok)).toBe(true)
    const appReceipt = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
    const coreReceipt = JSON.parse(readFileSync(join(before.paths.dataDir, 'resource-cleanup.json'), 'utf8'))
    await info.attach('exit-behind-requests-receipts', { body: Buffer.from(JSON.stringify({ appReceipt, coreReceipt }, null, 2)),
      contentType: 'application/json' })
    expect(appReceipt.current).toMatchObject({ state: 'process-exited', shutdownAccepted: true, unreceipted: 0 })
    expect(coreReceipt.state).toBe('complete')
  } finally {
    try { await application.close() } catch (error) { if (!/closed|_object/.test(String(error))) throw error }
  }
})

test('a shutdown the core accepts after the request bound, while it is stopped, still counts', async ({}, info) => {
  const gate = join(process.env.ODIN_REAL_CORE_ROOT!, 'slow-shutdown.gate')
  const application = await launchApp({ profile: 'exit-late-acceptance', env: {
    ODIN_DESKTOP_SLOW_READ_GATE: gate,
    ODIN_DESKTOP_CORE_CMD: JSON.stringify([process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
      '-m', 'tests.desktop_fixtures.slow_read_core'])
  } })
  try {
    await waitForCore(application)
    expect((await request(application, 'status.get')).ok).toBe(true)
    const before = await snapshot(application)
    // The core's loop stalls 12 s before accepting: past the request's 10 s bound, within the stop's 15 s grace.
    writeFileSync(gate, 'shutdown 12')
    const began = Date.now()
    await exitApp(application, 45_000)
    expect(Date.now() - began).toBeGreaterThan(10_000)
    expect(existsSync(gate.replace(/\.gate$/, '.entered'))).toBe(true)
    const appReceipt = JSON.parse(readFileSync(before.cleanupPath, 'utf8'))
    const coreReceipt = JSON.parse(readFileSync(join(before.paths.dataDir, 'resource-cleanup.json'), 'utf8'))
    await info.attach('exit-late-acceptance-receipts', { body: Buffer.from(JSON.stringify({ appReceipt, coreReceipt }, null, 2)),
      contentType: 'application/json' })
    expect(appReceipt.current).toMatchObject({ state: 'process-exited', shutdownAccepted: true, unreceipted: 0 })
    expect(coreReceipt.state).toBe('complete')
  } finally {
    try { await application.close() } catch (error) { if (!/closed|_object/.test(String(error))) throw error }
  }
})
