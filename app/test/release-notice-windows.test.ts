// On Windows a release counts only if it carries the Windows installer (phase 4, P10): a newer Linux-only release,
// a similarly named file, or a prerelease never reads as an update Windows could install.
import { describe, expect, it, vi } from 'vitest'
import { ReleaseNoticeService, windowsInstallerName } from '../src/main/release-notice'

type Asset = { name: string; state: string; size: number }
const asset = (name: string, extra: Partial<Asset> = {}): Asset => ({ name, state: 'uploaded', size: 1000, ...extra })
const release = (tag: string, assets: Asset[], prerelease = false) => ({
  tag_name: tag, html_url: `https://github.com/Calmingstorm/Odin-Desktop/releases/tag/${tag}`, draft: false, prerelease,
  published_at: '2026-10-11T00:00:00Z', assets
})
const service = (rows: unknown[], system: NodeJS.Platform = 'win32') => new ReleaseNoticeService('1.1.0', vi.fn(),
  async () => ({ status: 200, body: JSON.stringify(rows) }), system)

describe('the Windows update notice', () => {
  it('names the published installer exactly', () => {
    expect(windowsInstallerName('v1.2.0')).toBe('odin-desktop-1.2.0-x64-setup.exe')
  })

  it('picks the newest release that carries the installer, skipping a newer Linux-only one', async () => {
    const notice = await service([
      release('v1.3.0', [asset('odin-desktop_1.3.0_amd64.deb'), asset('odin-desktop-1.3.0-x86_64.AppImage')]),
      release('v1.2.0', [asset('odin-desktop_1.2.0_amd64.deb'), asset(windowsInstallerName('v1.2.0'))])
    ]).check()
    expect(notice).toMatchObject({ state: 'newer', latestVersion: 'v1.2.0' })
  })

  it('never counts a similar name, an unfinished upload, an empty file or a prerelease', async () => {
    for (const rows of [
      [release('v1.3.0', [asset('odin-desktop-1.3.0-x64-setup.exe.sha256'), asset('odin-desktop-1.3.0-arm64-setup.exe')])],
      [release('v1.3.0', [asset(windowsInstallerName('v1.3.0'), { state: 'starter' })])],
      [release('v1.3.0', [asset(windowsInstallerName('v1.3.0'), { size: 0 })])],
      [release('v1.3.0', [asset(windowsInstallerName('v1.3.0'))], true)],
      [{ ...release('v1.3.0', []), assets: 'not a list' }]
    ]) {
      expect((await service(rows).check()).state).toBe('no-release')
    }
  })

  it('leaves Linux counting every stable release', async () => {
    const notice = await service([release('v1.3.0', [asset('odin-desktop_1.3.0_amd64.deb')])], 'linux').check()
    expect(notice).toMatchObject({ state: 'newer', latestVersion: 'v1.3.0' })
  })
})
