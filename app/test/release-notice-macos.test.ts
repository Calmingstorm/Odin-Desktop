// On macOS a release counts only if it carries the Mac disk image (phase 4): a newer release without one, a similarly
// named file, or a prerelease never reads as an update a Mac could install.
import { describe, expect, it, vi } from 'vitest'
import { macDiskImageName, ReleaseNoticeService, windowsInstallerName } from '../src/main/release-notice'

type Asset = { name: string; state: string; size: number }
const asset = (name: string, extra: Partial<Asset> = {}): Asset => ({ name, state: 'uploaded', size: 1000, ...extra })
const release = (tag: string, assets: Asset[], prerelease = false) => ({
  tag_name: tag, html_url: `https://github.com/Calmingstorm/Odin-Desktop/releases/tag/${tag}`, draft: false, prerelease,
  published_at: '2026-10-11T00:00:00Z', assets
})
const service = (rows: unknown[], system: NodeJS.Platform = 'darwin') => new ReleaseNoticeService('1.1.0', vi.fn(),
  async () => ({ status: 200, body: JSON.stringify(rows) }), system)

describe('the Mac update notice', () => {
  it('names the published disk image exactly', () => {
    expect(macDiskImageName('v1.2.0')).toBe('odin-desktop-1.2.0-arm64.dmg')
  })

  it('picks the newest release that carries the disk image, skipping a newer one without it', async () => {
    const notice = await service([
      release('v1.3.0', [asset('odin-desktop_1.3.0_amd64.deb'), asset(windowsInstallerName('v1.3.0'))]),
      release('v1.2.0', [asset('odin-desktop_1.2.0_amd64.deb'), asset(macDiskImageName('v1.2.0'))])
    ]).check()
    expect(notice).toMatchObject({ state: 'newer', latestVersion: 'v1.2.0' })
  })

  it('never counts a similar name, an unfinished upload, an empty file or a prerelease', async () => {
    for (const rows of [
      [release('v1.3.0', [asset('odin-desktop-1.3.0-arm64.dmg.sha256'), asset('odin-desktop-1.3.0-x64.dmg'),
        asset('odin-desktop-1.3.0-candidate-arm64.dmg')])],
      [release('v1.3.0', [asset(macDiskImageName('v1.3.0'), { state: 'starter' })])],
      [release('v1.3.0', [asset(macDiskImageName('v1.3.0'), { size: 0 })])],
      [release('v1.3.0', [asset(macDiskImageName('v1.3.0'))], true)],
      [{ ...release('v1.3.0', []), assets: 'not a list' }]
    ]) {
      expect((await service(rows).check()).state).toBe('no-release')
    }
  })

  it('leaves Windows needing its installer and Linux counting every stable release', async () => {
    const mac = [release('v1.3.0', [asset(macDiskImageName('v1.3.0'))])]
    expect((await service(mac, 'win32').check()).state).toBe('no-release')
    expect(await service(mac, 'linux').check()).toMatchObject({ state: 'newer', latestVersion: 'v1.3.0' })
  })
})
