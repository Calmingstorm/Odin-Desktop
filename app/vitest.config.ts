import vue from '@vitejs/plugin-vue'
import { defineConfig, type Plugin } from 'vitest/config'

type Transform = (this: unknown, code: string, id: string, options?: { ssr?: boolean }) => unknown

/**
 * Compiles single-file components for the client, as the app's build does, so a test can mount a component's real
 * code on a renderer of its own. In Node, Vitest would otherwise ask for server-rendering code.
 */
function clientVue(): Plugin {
  const plugin = vue()
  const transform = plugin.transform as { handler: Transform }
  const handler = transform.handler
  transform.handler = function (code, id, options) {
    return handler.call(this, code, id, { ...options, ssr: false })
  }
  return plugin
}

export default defineConfig({
  plugins: [clientVue()],
  test: {
    include: ['test/**/*.test.ts'],
    exclude: ['test/real-core-contract.test.ts'],
    environment: 'node',
    testTimeout: 20000,
    hookTimeout: 20000
  }
})
