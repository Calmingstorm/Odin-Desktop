import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['test/real-core-contract.test.ts', 'test/real-core-settings.test.ts', 'test/real-core-completion.test.ts'],
    environment: 'node',
    fileParallelism: false,
    // Each real case includes cold engine startup and bounded Broker requests.
    testTimeout: 60_000,
    hookTimeout: 30_000
  }
})
