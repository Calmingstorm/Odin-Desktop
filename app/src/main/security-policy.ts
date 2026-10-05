// Window hardening policy. Pure functions, so they can be tested without Electron.
//
// None of this limits Odin. Odin's engine (the core process) keeps exactly the access it has today. These rules only
// stop the window's web page, which displays content from sites and files Odin reads, from acting on its own.

export const APP_SCHEME = 'app'
export const APP_HOST = 'odin'
export const APP_ORIGIN = `${APP_SCHEME}://${APP_HOST}`

/** Content Security Policy for every page the app serves. No inline or remote scripts, no network from the page. */
export const CONTENT_SECURITY_POLICY = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "media-src 'self' blob:",
  "connect-src 'none'",
  "object-src 'none'",
  "frame-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'none'",
  "form-action 'none'"
].join('; ')

export function isAppUrl(raw: string): boolean {
  try {
    const url = new URL(raw)
    return url.protocol === `${APP_SCHEME}:` && url.host === APP_HOST
  } catch {
    return false
  }
}

const EXTERNAL_PROTOCOLS = new Set(['https:', 'http:', 'mailto:'])

/** Links a user clicks may open in their browser or mail client; anything else (file:, javascript:, data:…) is refused. */
export function isSafeExternalUrl(raw: string): boolean {
  try {
    const url = new URL(raw)
    if (!EXTERNAL_PROTOCOLS.has(url.protocol)) return false
    if (url.username || url.password) return false
    return url.protocol === 'mailto:' || url.hostname.length > 0
  } catch {
    return false
  }
}

/** Only the app's own page, in the app's own window, may call the bridge. */
export function isTrustedSender(senderFrameUrl: string | undefined, senderId: number, expectedId: number | null): boolean {
  if (expectedId === null || senderId !== expectedId) return false
  return typeof senderFrameUrl === 'string' && isAppUrl(senderFrameUrl)
}

export interface FrameIdentity {
  processId: number
  routingId: number
}

/** True only for the window's own top frame: a subframe of the same page never counts as the window. */
export function isSameFrame(sender: FrameIdentity | null | undefined, main: FrameIdentity | null | undefined): boolean {
  if (!sender || !main) return false
  return sender.processId === main.processId && sender.routingId === main.routingId
}

const MIME_TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.json': 'application/json'
}

export function mimeTypeFor(path: string): string {
  const dot = path.lastIndexOf('.')
  return (dot >= 0 && MIME_TYPES[path.slice(dot).toLowerCase()]) || 'application/octet-stream'
}

/**
 * Maps an app:// URL to a file under the packaged renderer directory, or null if it would escape that directory.
 * `join` and `sep` are passed in so the function stays pure and platform-testable.
 */
export function resolveAppPath(
  raw: string,
  rootDir: string,
  resolvePath: (...parts: string[]) => string,
  sep: string
): string | null {
  if (!isAppUrl(raw)) return null
  let pathname: string
  try {
    pathname = decodeURIComponent(new URL(raw).pathname)
  } catch {
    return null
  }
  if (pathname.includes('\0')) return null
  const relative = pathname === '/' || pathname === '' ? 'index.html' : pathname.replace(/^\/+/, '')
  const resolved = resolvePath(rootDir, relative)
  const root = rootDir.endsWith(sep) ? rootDir : rootDir + sep
  return resolved.startsWith(root) ? resolved : null
}
