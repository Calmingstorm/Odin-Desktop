// Electron wiring for the window hardening policy in security-policy.ts.
// Reminder: this hardens the display page only. Odin's own capabilities are untouched.
import { readFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'
import { app, protocol, session, shell, type WebPreferences } from 'electron'
import {
  APP_SCHEME,
  CONTENT_SECURITY_POLICY,
  isAppUrl,
  isSafeExternalUrl,
  mimeTypeFor,
  resolveAppPath
} from './security-policy'

/** Must run before the app is ready. */
export function registerAppScheme(): void {
  protocol.registerSchemesAsPrivileged([
    { scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: false, corsEnabled: false } }
  ])
}

/** Serves the packaged renderer from app://odin/, with the CSP on every response. */
export function serveAppScheme(rendererDir: string): void {
  protocol.handle(APP_SCHEME, async (request) => {
    const file = resolveAppPath(request.url, rendererDir, resolve, sep)
    if (!file) return new Response('Not found', { status: 404 })
    try {
      const body = await readFile(file)
      return new Response(body, {
        status: 200,
        headers: {
          'Content-Type': mimeTypeFor(file),
          'Content-Security-Policy': CONTENT_SECURITY_POLICY,
          'X-Content-Type-Options': 'nosniff',
          'Cache-Control': 'no-store'
        }
      })
    } catch {
      return new Response('Not found', { status: 404 })
    }
  })
}

export function hardenedWebPreferences(preloadPath: string): WebPreferences {
  return {
    preload: preloadPath,
    sandbox: true,
    contextIsolation: true,
    nodeIntegration: false,
    nodeIntegrationInWorker: false,
    nodeIntegrationInSubFrames: false,
    webSecurity: true,
    allowRunningInsecureContent: false,
    experimentalFeatures: false,
    webviewTag: false,
    navigateOnDragDrop: false,
    spellcheck: false
  }
}

/** Applies to every web contents the app creates: no navigation away, no pop-ups, no webviews, no permissions. */
export function installGuards(): void {
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  session.defaultSession.setPermissionCheckHandler(() => false)

  app.on('web-contents-created', (_event, contents) => {
    contents.on('will-navigate', (event, url) => {
      if (!isAppUrl(url)) event.preventDefault()
    })
    contents.on('will-redirect', (event, url) => {
      if (!isAppUrl(url)) event.preventDefault()
    })
    contents.on('will-attach-webview', (event) => event.preventDefault())
    contents.setWindowOpenHandler(({ url }) => {
      // A link the user clicks opens in their browser; nothing ever opens inside the app.
      if (isSafeExternalUrl(url)) void shell.openExternal(url)
      return { action: 'deny' }
    })
  })
}
