import { resolve, sep } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  CONTENT_SECURITY_POLICY,
  isAppUrl,
  isSafeExternalUrl,
  isTrustedSender,
  mimeTypeFor,
  resolveAppPath
} from '../src/main/security-policy'

describe('window hardening policy (never limits Odin itself)', () => {
  it('serves only the app origin', () => {
    expect(isAppUrl('app://odin/index.html')).toBe(true)
    expect(isAppUrl('app://evil/index.html')).toBe(false)
    expect(isAppUrl('https://example.com/')).toBe(false)
    expect(isAppUrl('file:///etc/passwd')).toBe(false)
  })

  it('opens only web and mail links externally', () => {
    expect(isSafeExternalUrl('https://example.com/a')).toBe(true)
    expect(isSafeExternalUrl('mailto:someone@example.com')).toBe(true)
    for (const bad of ['javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,hi', 'https://user:pw@example.com', 'smb://host/share']) {
      expect(isSafeExternalUrl(bad)).toBe(false)
    }
  })

  it('trusts only the app window’s own page', () => {
    expect(isTrustedSender('app://odin/index.html', 7, 7)).toBe(true)
    expect(isTrustedSender('app://odin/index.html', 8, 7)).toBe(false)
    expect(isTrustedSender('https://example.com/', 7, 7)).toBe(false)
    expect(isTrustedSender(undefined, 7, 7)).toBe(false)
    expect(isTrustedSender('app://odin/index.html', 7, null)).toBe(false)
  })

  it('never resolves a path outside the packaged renderer', () => {
    const root = resolve('/srv/odin/renderer')
    expect(resolveAppPath('app://odin/', root, resolve, sep)).toBe(resolve(root, 'index.html'))
    expect(resolveAppPath('app://odin/assets/a.js', root, resolve, sep)).toBe(resolve(root, 'assets/a.js'))
    // The URL parser collapses dot segments (including %2e%2e), so these stay inside the root…
    expect(resolveAppPath('app://odin/../../etc/passwd', root, resolve, sep)?.startsWith(root + sep)).toBe(true)
    expect(resolveAppPath('app://odin/%2e%2e/%2e%2e/etc/passwd', root, resolve, sep)?.startsWith(root + sep)).toBe(true)
    // …and encoded slashes, which only become separators after decoding, are refused.
    expect(resolveAppPath('app://odin/a%2F..%2F..%2F..%2Fetc%2Fpasswd', root, resolve, sep)).toBeNull()
    expect(resolveAppPath('app://odin/a%00b', root, resolve, sep)).toBeNull()
    expect(resolveAppPath('app://other/index.html', root, resolve, sep)).toBeNull()
  })

  it('has a CSP with no inline or remote script and no network', () => {
    expect(CONTENT_SECURITY_POLICY).toContain("script-src 'self'")
    expect(CONTENT_SECURITY_POLICY).toContain("connect-src 'none'")
    expect(CONTENT_SECURITY_POLICY).not.toMatch(/unsafe-(inline|eval)/)
  })

  it('labels content types', () => {
    expect(mimeTypeFor('/x/index.html')).toMatch(/^text\/html/)
    expect(mimeTypeFor('/x/a.JS')).toMatch(/javascript/)
    expect(mimeTypeFor('/x/unknown.bin')).toBe('application/octet-stream')
  })
})
