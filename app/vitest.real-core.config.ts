import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['test/real-core-contract.test.ts', 'test/renderer/real-core-renderer-contract.test.ts'],
    environment: 'node',
    fileParallelism: false,
    testTimeout: 20_000,
    hookTimeout: 20_000
  }
})
