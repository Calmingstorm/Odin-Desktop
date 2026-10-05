import { resolve } from 'node:path'
import { defineConfig } from 'electron-vite'
import vue from '@vitejs/plugin-vue'

// Main and preload build as CommonJS: a sandboxed preload cannot load ES modules.
export default defineConfig({
  main: {
    build: {
      outDir: 'out/main',
      rollupOptions: { input: resolve(__dirname, 'src/main/index.ts') }
    }
  },
  preload: {
    build: {
      outDir: 'out/preload',
      rollupOptions: {
        input: resolve(__dirname, 'src/preload/index.ts'),
        output: { format: 'cjs', entryFileNames: '[name].js' }
      }
    }
  },
  renderer: {
    root: resolve(__dirname, 'src/renderer'),
    plugins: [vue()],
    build: {
      outDir: resolve(__dirname, 'out/renderer'),
      // No inline scripts or styles: everything is a packaged file the CSP allows.
      assetsInlineLimit: 0,
      cssCodeSplit: false,
      rollupOptions: { input: resolve(__dirname, 'src/renderer/index.html') }
    }
  }
})
