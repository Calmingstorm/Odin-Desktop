import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

export default defineConfig({
  testDir: '.', testMatch: 'orca.spec.ts', workers: 1, fullyParallel: false,
  timeout: 240_000, expect: { timeout: 20_000 },
  reporter: [['list'], ['json', { outputFile: process.env.ODIN_APP_A11Y_REPORT ?? resolve(process.env.ODIN_ORCA_EVIDENCE ?? 'test-results/orca', 'tasks.json') }]],
  outputDir: resolve(process.env.ODIN_ORCA_EVIDENCE ?? 'test-results/orca', 'tasks'),
  use: { trace: 'retain-on-failure' }
})
