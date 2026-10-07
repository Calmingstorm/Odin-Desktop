import { defineConfig } from 'vitest/config'
import { selectRealCoreFiles } from './scripts/real-core-shards.mjs'

export default defineConfig({
  test: {
    include: selectRealCoreFiles(process.env.ODIN_APP_REAL_CORE_SHARD),
    environment: 'node',
    fileParallelism: false,
    // Concurrent namespace shards must not write the same Vitest result cache.
    cache: false,
    // Each real case includes cold engine startup (up to the harness's 60 s
    // socket wait, twice for restart cases) and bounded Broker requests.
    testTimeout: 180_000,
    hookTimeout: 90_000
  }
})
