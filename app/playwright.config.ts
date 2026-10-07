import { defineConfig } from '@playwright/test'

// This configuration is not a launcher. The isolated PID namespace, X server,
// session bus and disposable HOME are established by lifecycle-e2e.mjs.
export default defineConfig({
  testDir: './test/e2e',
  // Each independently isolated lane runs its own tests. A lifecycle runner
  // must not execute the differently rooted accessibility harness. Onboarding
  // uses Vitest's separately owned runner, not this Playwright configuration.
  testMatch: process.env.ODIN_APP_E2E === '1'
    ? ['**/lifecycle.spec.ts', '**/notifications.spec.ts', '**/admitted-work.spec.ts',
      '**/execution-containment.spec.ts', '**/native-reconciliation.spec.ts', '**/r4.spec.ts', '**/session-logout.spec.ts',
      '**/startup-exit.spec.ts']
    : ['**/accessibility.spec.ts', '**/release-notice.spec.ts'],
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: process.env.ODIN_APP_E2E_OUT
    ? `${process.env.ODIN_APP_E2E_OUT}/test-results`
    : process.env.ODIN_APP_E2E === '1' ? `${process.env.ODIN_REAL_CORE_ROOT}/e2e-results` : 'test-results/a11y',
  reporter: process.env.ODIN_APP_E2E_OUT
    ? [['line'], ['json', { outputFile: `${process.env.ODIN_APP_E2E_OUT}/playwright.json` }]]
    : [['list'], ['json', { outputFile: process.env.ODIN_APP_A11Y_REPORT ?? 'test-results/accessibility.json' }]],
  use: { trace: 'retain-on-failure' }
})
