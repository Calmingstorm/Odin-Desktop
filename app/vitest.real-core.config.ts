import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['test/real-core-contract.test.ts', 'test/real-core-settings.test.ts', 'test/real-core-completion.test.ts', 'test/real-core-services.test.ts', 'test/real-core-work.test.ts', 'test/real-core-webhooks.test.ts', 'test/real-core-skills.test.ts', 'test/renderer/real-core-renderer-contract.test.ts'],
    environment: 'node',
    fileParallelism: false,
    // Each real case includes cold engine startup (up to the harness's 60 s
    // socket wait, twice for restart cases) and bounded Broker requests.
    testTimeout: 180_000,
    hookTimeout: 90_000
  }
})
