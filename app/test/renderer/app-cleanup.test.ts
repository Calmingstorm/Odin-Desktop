// Shell integration on Vue's plain-object renderer. No Electron or active desktop is opened.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flush, mount } from './component-host'

vi.mock('../../src/renderer/src/store', async (original) => ({
  ...await original<typeof import('../../src/renderer/src/store')>(), init: vi.fn()
}))
vi.mock('../../src/renderer/src/components/ConversationList.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/MessageList.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/Composer.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/SearchPanel.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/StatusBar.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/WorkPanel.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/ConfirmDialog.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/views/Settings.vue', () => ({ default: { render: () => null } }))

import App from '../../src/renderer/src/App.vue'
import { state } from '../../src/renderer/src/store'

describe('cleanup warning in the app shell', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('persists outside both view branches, never stealing focus when a warning arrives', async () => {
    const focus = vi.fn()
    const querySelector = vi.fn(() => ({ focus }))
    vi.stubGlobal('HTMLElement', class HTMLElement {})
    vi.stubGlobal('document', { activeElement: null, querySelector })
    vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn(), odin: {} })
    state.view = 'chat'
    state.app = { link: 'ready', coreInstanceId: 'core', noTray: false, unreceipted: 0, cleanupWarning: null }
    const { root, unmount } = mount(App)
    await flush()
    const notice = { id: 'notice-1', at: '2026-10-05T23:00:00Z', records: [{ at: '2026-10-05T22:00:00Z', reason: 'Unverified cleanup' }] }
    state.app.cleanupWarning = notice
    await flush()
    const banner = root.findAll((node) => node.props.class === 'cleanup-notice')[0]!
    expect(banner).toBeTruthy()
    expect(banner.parent?.props.class).toBe('shell')
    expect(root.textContent()).toContain('Unverified cleanup')
    expect(focus).not.toHaveBeenCalled()
    expect(querySelector).not.toHaveBeenCalled()
    state.view = 'settings'
    await flush()
    expect(root.findAll((node) => node.props.class === 'cleanup-notice')[0]).toBe(banner)
    // Existing view navigation may focus its Back button. A new warning must not request any focus.
    focus.mockClear()
    querySelector.mockClear()
    state.app.cleanupWarning = { ...notice, id: 'notice-2' }
    await flush()
    expect(root.textContent()).toContain('Unverified cleanup')
    expect(focus).not.toHaveBeenCalled()
    expect(querySelector).not.toHaveBeenCalled()
    state.view = 'chat'
    await flush()
    expect(root.findAll((node) => node.props.class === 'cleanup-notice')[0]).toBe(banner)
    unmount()
  })
})
