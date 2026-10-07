import { expect, it, vi } from 'vitest'

it('mounts the renderer shell at the owned root', async () => {
  const mount = vi.fn()
  const createApp = vi.fn(() => ({ mount }))
  const shell = { name: 'inert-shell' }
  vi.doMock('vue', () => ({ createApp }))
  vi.doMock('../../src/renderer/src/App.vue', () => ({ default: shell }))
  await import('../../src/renderer/src/main')
  expect(createApp).toHaveBeenCalledWith(shell)
  expect(mount).toHaveBeenCalledWith('#app')
})
