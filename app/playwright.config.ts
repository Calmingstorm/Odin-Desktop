import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './test/e2e',
  // Onboarding uses Vitest's separate owned runner; Playwright must not import that suite.
  testMatch: 'accessibility.spec.ts',
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['json', { outputFile: process.env.ODIN_APP_A11Y_REPORT ?? 'test-results/accessibility.json' }]],
  outputDir: 'test-results/a11y',
  use: { trace: 'retain-on-failure' }
})
