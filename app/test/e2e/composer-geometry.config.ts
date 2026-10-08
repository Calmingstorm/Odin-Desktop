import { defineConfig } from '@playwright/test'

// Selection only. scripts/composer-geometry.mjs owns the isolated launcher.
export default defineConfig({
  testDir: '.', testMatch: 'composer-geometry.spec.ts', workers: 1, fullyParallel: false,
  retries: 0, timeout: 90_000, expect: { timeout: 15_000 },
  outputDir: `${process.env.ODIN_APP_E2E_OUT}/test-results`,
  reporter: [['line'], ['json', { outputFile: `${process.env.ODIN_APP_E2E_OUT}/playwright.json` }]],
  use: { trace: 'retain-on-failure', screenshot: 'off', video: 'off' }
})
