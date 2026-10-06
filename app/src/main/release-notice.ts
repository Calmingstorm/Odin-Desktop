// Metadata only. This module has no filesystem, core, credential, installer or lifecycle dependency.
import * as https from 'node:https'
import type { ReleaseNotice, Result } from '../shared/api'

export const RELEASES_API = 'https://api.github.com/repos/Calmingstorm/Odin-Desktop/releases?per_page=100'
const RELEASE_BASE = 'https://github.com/Calmingstorm/Odin-Desktop/releases/tag/'
const MAX_BYTES = 1024 * 1024
class OversizedMetadata extends Error {}
export interface ReleaseResponse { status: number; body: string; remaining?: string; link?: string }
export type ReleaseTransport = () => Promise<ReleaseResponse>

/** Intentionally excludes prerelease/build labels, leading zeroes and unsafe numeric components. */
export function stableVersion(value: unknown): number[] | null {
  if (typeof value !== 'string' || !/^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(value)) return null
  const parts = value.replace(/^v/, '').split('.').map(Number)
  return parts.every(Number.isSafeInteger) ? parts : null
}

export function validReleaseUrl(url: unknown, tag: unknown): url is string {
  return stableVersion(tag) !== null && typeof tag === 'string' && url === RELEASE_BASE + tag
}

/** Node HTTPS uses neither Electron's browser cookies nor local credential stores. Never follow redirects. */
export const anonymousReleaseTransport: ReleaseTransport = () => new Promise((resolve, reject) => {
  const request = https.request(RELEASES_API, {
    method: 'GET', agent: false, headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Odin-Desktop-release-notice',
      'X-GitHub-Api-Version': '2022-11-28' }
  }, (response) => {
    const chunks: Buffer[] = []
    let bytes = 0
    response.on('data', (chunk: Buffer) => {
      bytes += chunk.length
      if (bytes > MAX_BYTES) request.destroy(new OversizedMetadata('metadata too large'))
      else chunks.push(chunk)
    })
    response.on('error', (error) => reject(bytes > MAX_BYTES ? new OversizedMetadata('metadata too large') : error))
    response.on('aborted', () => reject(bytes > MAX_BYTES ? new OversizedMetadata('metadata too large') : new Error('metadata response aborted')))
    response.on('end', () => resolve({ status: response.statusCode ?? 0, body: Buffer.concat(chunks).toString('utf8'),
      remaining: response.headers['x-ratelimit-remaining'] as string | undefined,
      link: typeof response.headers.link === 'string' ? response.headers.link : undefined }))
  })
  const deadline = setTimeout(() => request.destroy(new Error('metadata deadline')), 10_000)
  request.on('error', reject)
  request.on('close', () => clearTimeout(deadline))
  request.end()
})

export class ReleaseNoticeService {
  private latest: { tag: string; url: string } | null = null
  private pending: Promise<ReleaseNotice> | null = null
  constructor(private readonly currentVersion: string, private readonly openExternal: (url: string) => Promise<void>,
    private readonly transport: ReleaseTransport = anonymousReleaseTransport) {}

  check(): Promise<ReleaseNotice> {
    if (this.pending) return this.pending
    this.latest = null
    this.pending = this.read().finally(() => { this.pending = null })
    return this.pending
  }

  private async read(): Promise<ReleaseNotice> {
    const result = (state: ReleaseNotice['state']): ReleaseNotice => ({ state, currentVersion: this.currentVersion })
    if (!stableVersion(this.currentVersion)) return result('invalid-current-version')
    let response: ReleaseResponse
    try { response = await this.transport() } catch (error) { return result(error instanceof OversizedMetadata ? 'malformed' : 'offline') }
    if (response.status === 404 || response.status === 401) return result('cannot-check-private')
    if (response.status === 429 || (response.status === 403 && response.remaining === '0')) return result('rate-limited')
    if (response.status !== 200) return result('unavailable')
    if (Buffer.byteLength(response.body) > MAX_BYTES) return result('malformed')
    // A truncated list is not proof there are no releases or that a version is current.
    if (response.link?.includes('rel="next"')) return result('unavailable')
    let rows: unknown
    try { rows = JSON.parse(response.body) } catch { return result('malformed') }
    if (!Array.isArray(rows) || rows.length > 100) return result('malformed')
    const stable: Array<{ tag: string; url: string; version: number[] }> = []
    for (const row of rows) {
      if (!row || typeof row !== 'object' || typeof row.draft !== 'boolean' || typeof row.prerelease !== 'boolean') return result('malformed')
      if (row.draft || row.prerelease) continue
      const version = stableVersion(row.tag_name)
      if (!version || !validReleaseUrl(row.html_url, row.tag_name) || typeof row.published_at !== 'string' ||
        !Number.isFinite(Date.parse(row.published_at))) return result('malformed')
      stable.push({ tag: row.tag_name, url: row.html_url, version })
    }
    if (!stable.length) return result('no-release')
    const compare = (a: number[], b: number[]): number => a[0]! - b[0]! || a[1]! - b[1]! || a[2]! - b[2]!
    stable.sort((a, b) => compare(b.version, a.version))
    const release = stable[0]!
    const relation = compare(release.version, stableVersion(this.currentVersion)!)
    this.latest = { tag: release.tag, url: release.url }
    return { ...result(relation > 0 ? 'newer' : relation < 0 ? 'older' : 'equal'), latestVersion: release.tag, releaseUrl: release.url }
  }

  /** No URL argument from the renderer. Only the last successful, validated check can supply the target. */
  async open(): Promise<Result<{ opened: true }>> {
    const release = this.latest
    if (!release || !validReleaseUrl(release.url, release.tag)) return {
      ok: false, error: { code: 'unavailable', message: 'Check for a published release before opening its page.' }
    }
    try {
      await this.openExternal(release.url)
      return { ok: true, result: { opened: true } }
    } catch {
      return { ok: false, error: { code: 'unavailable', message: 'Could not open the release page in your browser.' } }
    }
  }
}
