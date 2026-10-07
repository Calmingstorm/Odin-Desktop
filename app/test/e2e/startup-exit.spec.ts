import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { exitApp, launchApp, snapshot } from './harness'

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
