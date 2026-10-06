import { expect, it, vi } from 'vitest'
const handlers = vi.hoisted(() => new Map<string, Function>())
vi.mock('electron', () => ({ ipcMain: { handle: (name: string, handler: Function) => handlers.set(name, handler) } }))
import { registerIpc, type IpcDeps } from '../src/main/ipc'
import { ReleaseNoticeService } from '../src/main/release-notice'
import { IPC } from '../src/shared/api'

it('actual named IPC operations never call the core, write settings/drafts/artifacts or dispatch replay/lifecycle commands', async () => {
  const brokerRequest = vi.fn(() => { throw new Error('notice reached core') })
  const forbidden = vi.fn(() => { throw new Error('notice reached writable dependency') })
  const open = vi.fn(async () => undefined)
  const releases = new ReleaseNoticeService('0.1.0', open, async () => ({ status: 200, body: JSON.stringify([{
    draft: false, prerelease: false, tag_name: 'v1.0.0', published_at: '2026-10-05T00:00:00Z',
    html_url: 'https://github.com/Calmingstorm/Odin-Desktop/releases/tag/v1.0.0' }]) }))
  registerIpc({ releases, broker: { request: brokerRequest }, windowId: () => 7,
    mainFrame: () => ({ processId: 10, routingId: 20 }),
    drafts: { set: forbidden, flush: forbidden }, artifacts: { saveAs: forbidden, open: forbidden },
    setAutostart: forbidden, setNotifications: forbidden, setConversationMuted: forbidden } as unknown as IpcDeps)
  const event = { sender: { id: 7 }, senderFrame: { url: 'app://odin/index.html', processId: 10, routingId: 20 } }
  expect(await handlers.get(IPC.checkReleases)!(event, {})).toMatchObject({ ok: true, result: { state: 'newer' } })
  expect(await handlers.get(IPC.openRelease)!(event, {})).toEqual({ ok: true, result: { opened: true } })
  expect(open).toHaveBeenCalledExactlyOnceWith('https://github.com/Calmingstorm/Odin-Desktop/releases/tag/v1.0.0')
  expect(brokerRequest).not.toHaveBeenCalled()
  expect(forbidden).not.toHaveBeenCalled()
})
