import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['test/real-core-contract.test.ts', 'test/real-core-settings.test.ts', 'test/real-core-work.test.ts'],
    environment: 'node',
    fileParallelism: false,
    testTimeout: 35_000,
    hookTimeout: 40_000
  }
})
