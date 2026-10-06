import { beforeEach, expect, it, vi } from 'vitest'
import { flush, mount } from './component-host'

beforeEach(() => vi.resetModules())

it('announces check progress/errors and exposes a keyboard-native release link without forwarding a URL', async () => {
  let resolve!: (value: unknown) => void
  const checkReleases = vi.fn(() => new Promise((r) => { resolve = r }))
  const openRelease = vi.fn(async () => ({ ok: false, error: { message: 'Browser unavailable.' } }))
  ;(globalThis as any).window = { odin: { checkReleases, openRelease } }
  const Component = (await import('../../src/renderer/src/components/ReleaseNotice.vue')).default
  const { root, unmount } = mount(Component)
  expect(checkReleases).not.toHaveBeenCalled()
  const status = () => root.findAll((node) => node.props.role === 'status')[0]!
  expect(status().props['aria-live']).toBe('polite')
  expect(status().props['aria-atomic']).toBe('true')
  expect(root.button('Check for updates').props['aria-describedby']).toBe(status().props.id)
  root.button('Check for updates').fire('click')
  await flush()
  expect(status().textContent()).toContain('Checking')
  expect(root.button('Check for updates').props.disabled).toBe(true)
  resolve({ ok: true, result: { state: 'newer', currentVersion: '0.1.0', latestVersion: 'v1.0.0',
    releaseUrl: 'https://github.com/Calmingstorm/Odin-Desktop/releases/tag/v1.0.0' } })
  await flush()
  expect(status().textContent()).toContain('A new version is available')
  root.find('a')!.fire('click', { preventDefault: () => undefined })
  await flush()
  expect(openRelease).toHaveBeenCalledWith()
  expect(status().textContent()).toBe('Browser unavailable.')
  unmount()
})
