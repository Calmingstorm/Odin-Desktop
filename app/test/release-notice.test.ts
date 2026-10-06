import { describe, expect, it, vi } from 'vitest'
import { ReleaseNoticeService, stableVersion, validReleaseUrl } from '../src/main/release-notice'
import { releaseNoticeSchema } from '../src/main/schemas'

const release = (tag = 'v1.2.3', extra = {}) => ({ tag_name: tag,
  html_url: `https://github.com/Calmingstorm/Odin-Desktop/releases/tag/${tag}`,
  draft: false, prerelease: false, published_at: '2026-10-05T00:00:00Z', ...extra })
const check = (body: unknown, status = 200, remaining?: string) => new ReleaseNoticeService('1.2.3', vi.fn(),
  async () => ({ status, body: JSON.stringify(body), remaining }))

describe('anonymous stable release metadata', () => {
  it.each([[404, 'cannot-check-private'], [401, 'cannot-check-private'], [403, 'unavailable'], [500, 'unavailable'],
    [302, 'unavailable'], [429, 'rate-limited']])('keeps HTTP %s honest', async (status, state) => {
    expect(await check([], status as number).check()).toEqual({ state, currentVersion: '1.2.3' })
  })
  it('distinguishes offline and rate-limited from no release', async () => {
    expect((await check([], 403, '0').check()).state).toBe('rate-limited')
    expect((await new ReleaseNoticeService('1.2.3', vi.fn(), async () => { throw new Error('offline') }).check()).state).toBe('offline')
    expect((await check([]).check()).state).toBe('no-release')
  })
  it.each([['v1.2.3', 'equal'], ['1.2.2', 'older'], ['v1.2.10', 'newer'], ['v2.0.0', 'newer']])(
    'compares numeric stable %s', async (tag, state) => expect(await check([release(tag)]).check()).toMatchObject({ state, latestVersion: tag }))
  it('selects highest stable version, ignoring draft/prerelease metadata', async () => {
    expect(await check([release('v1.2.9'), release('v1.2.3'), release('v1.2.10'),
      { draft: true, prerelease: false }, { draft: false, prerelease: true }]).check()).toMatchObject({ state: 'newer', latestVersion: 'v1.2.10' })
    expect((await check([{ draft: true, prerelease: false }, { draft: false, prerelease: true }]).check()).state).toBe('no-release')
  })
  it.each([{}, [null], [release('v1.2.3-beta')], [release('v01.2.3')], [release('v1.2.3', { draft: undefined })],
    [release('v1.2.3', { published_at: null })], [release('v1.2.3', { html_url: 'https://example.com/' })]])(
    'rejects malformed responses without a release link', async (body) => expect(await check(body).check()).toEqual({ state: 'malformed', currentVersion: '1.2.3' }))
  it('bounds metadata and refuses incomplete pagination and invalid current versions', async () => {
    const service = (body: string, link?: string) => new ReleaseNoticeService('1.2.3', vi.fn(), async () => ({ status: 200, body, link }))
    expect((await service('{').check()).state).toBe('malformed')
    expect((await service(JSON.stringify(Array(101).fill(release()))).check()).state).toBe('malformed')
    expect((await service(' '.repeat(1024 * 1024 + 1)).check()).state).toBe('malformed')
    expect((await service('[]', '<https://api.github.com/next>; rel="next"').check()).state).toBe('unavailable')
    const transport = vi.fn()
    expect((await new ReleaseNoticeService('1.2.3-dev', vi.fn(), transport).check()).state).toBe('invalid-current-version')
    expect(transport).not.toHaveBeenCalled()
  })
  it.each(['v1.2', 'v1.2.3+build', 'v1.2.3-rc.1', 'v01.2.3', 'v9007199254740992.0.0', 'v1.2.3/evil'])('rejects tag %s', (tag) => {
    expect(stableVersion(tag)).toBeNull()
  })
  it.each(['http://github.com/Calmingstorm/Odin-Desktop/releases/tag/v1.2.3',
    'https://github.com.evil/Calmingstorm/Odin-Desktop/releases/tag/v1.2.3',
    'https://user@github.com/Calmingstorm/Odin-Desktop/releases/tag/v1.2.3',
    'https://github.com:443/Calmingstorm/Odin-Desktop/releases/tag/v1.2.3',
    'https://github.com/Calmingstorm/Odin-Desktop/releases/tag/v1.2.3?download=1',
    'https://github.com/Calmingstorm/Odin-Desktop/releases/tag/v1.2.3#asset',
    'https://github.com/Calmingstorm/Odin-Desktop/releases/tag/%761.2.3',
    'https://github.com/Other/Repo/releases/tag/v1.2.3',
    'https://github.com/Calmingstorm/Odin-Desktop/releases/download/v1.2.3/app.deb'])('rejects noncanonical target %s', (url) => {
    expect(validReleaseUrl(url, 'v1.2.3')).toBe(false)
  })
  it('opens only a last validated link; failed checks revoke it, with no broker or lifecycle capability', async () => {
    const open = vi.fn(async () => undefined)
    const transport = vi.fn().mockResolvedValueOnce({ status: 200, body: JSON.stringify([release('v2.0.0')]) })
      .mockResolvedValueOnce({ status: 404, body: '{}' })
    const service = new ReleaseNoticeService('1.2.3', open, transport)
    expect((await service.open()).ok).toBe(false)
    await service.check()
    expect(await service.open()).toEqual({ ok: true, result: { opened: true } })
    expect(open).toHaveBeenCalledExactlyOnceWith(release('v2.0.0').html_url)
    await service.check()
    expect((await service.open()).ok).toBe(false)
    expect(open).toHaveBeenCalledTimes(1)
  })
  it('coalesces concurrent reads and rejects caller URL/repo/credentials/update payloads', async () => {
    const transport = vi.fn(async () => ({ status: 200, body: '[]' }))
    const service = new ReleaseNoticeService('1.2.3', vi.fn(), transport)
    await Promise.all([service.check(), service.check()])
    expect(transport).toHaveBeenCalledTimes(1)
    for (const payload of [{ url: 'https://example.com' }, { repo: 'other' }, { token: 'not-a-secret' }, { install: true }]) {
      expect(releaseNoticeSchema.safeParse(payload).success).toBe(false)
    }
    expect(releaseNoticeSchema.safeParse({}).success).toBe(true)
  })
  it('revokes the previous target before an in-flight recheck and keeps opener failure honest', async () => {
    let finish!: (response: unknown) => void
    const transport = vi.fn().mockResolvedValueOnce({ status: 200, body: JSON.stringify([release()]) })
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const open = vi.fn(async () => { throw new Error('browser failure') })
    const service = new ReleaseNoticeService('1.2.3', open, transport)
    await service.check()
    expect(await service.open()).toMatchObject({ ok: false, error: { message: 'Could not open the release page in your browser.' } })
    const checking = service.check()
    expect((await service.open()).ok).toBe(false)
    finish({ status: 200, body: '[]' })
    await checking
    expect(open).toHaveBeenCalledTimes(1)
  })
})
