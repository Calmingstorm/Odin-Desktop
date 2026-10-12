// Executes the Windows smoke driver against an inert, stateful page model. Orchestration coverage only: no display,
// process, network, real filesystem or live core. The native run is scripts/windows-real-core-smoke.mjs on Windows.
import { beforeEach, describe, expect, it, vi } from 'vitest'

const ports = vi.hoisted(() => ({ files: new Map<string, string>(), configure: vi.fn() }))
vi.mock('node:fs', () => ({
  readFileSync: (path: string) => {
    const value = ports.files.get(path)
    if (value === undefined) throw new Error(`Unmodeled read: ${path}`)
    return value
  },
  writeFileSync: (path: string, value: string) => { ports.files.set(path, value) },
  existsSync: (path: string) => ports.files.has(path)
}))
vi.mock('electron', () => ({ app: { getPath: () => 'C:\\smoke\\local\\odin-desktop\\electron' } }))
vi.mock('../src/main/real-core-smoke', () => ({ configureCannedProvider: ports.configure }))

import { windowsRealCoreSmoke, windowsSmokeRoot } from '../src/main/windows-smoke'

const ROOT = 'C:\\smoke'
const NONCE = 'a'.repeat(32)
const base = { ODIN_WINDOWS_SMOKE: '1', ODIN_WINDOWS_SMOKE_ROOT: ROOT, ODIN_WINDOWS_SMOKE_NONCE: NONCE, LOCALAPPDATA: `${ROOT}\\local` }

beforeEach(() => {
  ports.files.clear()
  ports.configure.mockReset()
  ports.files.set(`${ROOT}\\smoke-root.json`, JSON.stringify({ nonce: NONCE }))
})

describe('the Windows smoke gate', () => {
  const read = (path: string) => {
    const value = ports.files.get(path)
    if (value === undefined) throw new Error('missing')
    return value
  }

  it('binds to the runner\'s own root, never to a flag alone', () => {
    expect(windowsSmokeRoot(base, ['--smoke-test'], false, 'win32', read)).toBe(ROOT)
    expect(windowsSmokeRoot(base, ['--smoke-test'], false, 'linux', read)).toBeNull()
    expect(windowsSmokeRoot(base, ['--smoke-test'], true, 'win32', read)).toBeNull()
    expect(windowsSmokeRoot(base, [], false, 'win32', read)).toBeNull()
    expect(windowsSmokeRoot({ ...base, ODIN_WINDOWS_SMOKE: '' }, ['--smoke-test'], false, 'win32', read)).toBeNull()
    expect(windowsSmokeRoot({ ...base, ODIN_WINDOWS_SMOKE_ROOT: 'relative' }, ['--smoke-test'], false, 'win32', read)).toBeNull()
    expect(windowsSmokeRoot({ ...base, ODIN_WINDOWS_SMOKE_NONCE: 'short' }, ['--smoke-test'], false, 'win32', read)).toBeNull()
    expect(windowsSmokeRoot({ ...base, ODIN_WINDOWS_SMOKE_NONCE: 'b'.repeat(32) }, ['--smoke-test'], false, 'win32', read)).toBeNull()
    expect(windowsSmokeRoot({ ...base, LOCALAPPDATA: 'C:\\elsewhere' }, ['--smoke-test'], false, 'win32', read)).toBeNull()
    ports.files.clear()
    expect(windowsSmokeRoot(base, ['--smoke-test'], false, 'win32', read)).toBeNull() // no marker
    expect(windowsSmokeRoot(base, ['--smoke-test'], false, 'win32')).toBeNull() // the real reader, nothing there
  })
})

interface Message { id: string; role: string; text: string; request_id: string }

/** A page that answers the driver's scripts the way the app's renderer would. */
function page(options: { phase: 'first' | 'relaunch'; toolRuns?: boolean; draft?: string } = { phase: 'first' }) {
  const state = { rows: options.phase === 'relaunch' ? 1 : 0, composer: options.phase === 'relaunch' ? (options.draft ?? '') : '',
    messages: [] as Message[], requests: 0 }
  if (options.phase === 'relaunch') {
    state.messages.push({ id: 'm1', role: 'user', text: '[reply] windows smoke', request_id: 'r1' },
      { id: 'm2', role: 'assistant', text: 'Scripted reply: windows smoke.', request_id: 'r1' })
  }
  const run = vi.fn(async (script: string) => {
    if (script === 'Boolean(window.odin)') return true
    if (script.includes('.rail-link')) return 'Connected'
    if (script === 'document.querySelectorAll(".conv-row").length') return state.rows
    if (script.includes('querySelector("button[title=\\"New conversation\\"]").click()')) { state.rows = 1; return undefined }
    if (script.includes('querySelector("button[title=\\"New conversation\\"]")')) return true
    if (script.includes('.conv-row").length === 1 && !document.querySelector(".composer textarea")?.disabled')) return state.rows === 1
    if (script === 'document.querySelectorAll(".conv-row").length === 1') return state.rows === 1
    if (script.includes('Boolean(document.querySelector(".conv-row"))')) return true
    if (script.includes('document.querySelector(".conv-row").click()')) return undefined
    if (script.includes('window.odin["listConversations"]')) return { ok: true, result: { items: [{ id: 'c1' }] } }
    if (script.includes('window.odin["snapshotConversation"]')) return { ok: true, result: { messages: { items: state.messages } } }
    if (script.includes('input.value = ')) {
      state.composer = JSON.parse(script.slice(script.indexOf('input.value = ') + 14, script.indexOf('; input.dispatchEvent')))
      return undefined
    }
    if (script.includes('button[type=submit]")?.disabled === false')) return true
    if (script.includes('.composer form').valueOf() && script.includes('dispatchEvent(new Event("submit"')) {
      const request = `r${++state.requests + 1}`
      const prompt = state.composer
      state.messages.push({ id: `u${request}`, role: 'user', text: prompt, request_id: request })
      if (prompt.includes('[tool]')) {
        if (options.toolRuns !== false) ports.files.set(`${ROOT}\\tool-marker.txt`, 'windows smoke tool ran\r\n')
        state.messages.push({ id: `a${request}`, role: 'assistant', text: 'Scripted reply: the local tool ran.', request_id: request })
      } else {
        state.messages.push({ id: `a${request}`, role: 'assistant', text: 'Scripted reply: windows smoke.', request_id: request })
      }
      state.composer = ''
      return undefined
    }
    if (script === 'document.querySelector(".composer textarea").value === ""') return state.composer === ''
    if (script.includes('.composer textarea")?.value === ')) return state.composer === options.draft
    if (script.startsWith('document.getElementById(')) return true
    if (script.includes("querySelector(\"body\")?.innerText")) return 'page'
    throw new Error(`Unmodeled script: ${script}`)
  })
  return { win: { webContents: { isLoading: () => false, executeJavaScript: run } }, state, run }
}

const broker = { linkState: 'ready', coreInstanceId: 'core-1' }

describe('the Windows smoke driver', () => {
  it('drives a first run: provider, reply, a local tool turn and a draft', async () => {
    const { win, state } = page({ phase: 'first' })
    await windowsRealCoreSmoke(win as never, broker as never, ROOT, () => 42,
      { ...base, ODIN_WINDOWS_SMOKE_PHASE: 'first', ODIN_SMOKE_PROVIDER_BASE_URL: 'http://127.0.0.1:1/v1' })
    expect(ports.configure).toHaveBeenCalledWith(broker, 'http://127.0.0.1:1/v1')
    const evidence = JSON.parse(ports.files.get(`${ROOT}\\evidence-first.json`)!)
    expect(evidence).toMatchObject({ ok: true, phase: 'first', reply: 'Scripted reply: windows smoke.',
      toolReply: 'Scripted reply: the local tool ran.', toolMarker: 'windows smoke tool ran', session: { corePid: 42 } })
    expect(state.composer).toBe('windows smoke draft')
  })

  it('checks the conversation and the draft after a relaunch', async () => {
    const { win } = page({ phase: 'relaunch', draft: 'windows smoke draft' })
    await windowsRealCoreSmoke(win as never, broker as never, ROOT, () => undefined, { ...base, ODIN_WINDOWS_SMOKE_PHASE: 'relaunch' })
    const evidence = JSON.parse(ports.files.get(`${ROOT}\\evidence-relaunch.json`)!)
    expect(evidence).toMatchObject({ ok: true, relaunch: { conversation: true, draft: true, messages: 2 } })
  })

  it('records a failure as evidence and rethrows it', async () => {
    const { win } = page({ phase: 'first', toolRuns: false })
    await expect(windowsRealCoreSmoke(win as never, broker as never, ROOT, () => 7, { ...base }))
      .rejects.toThrow('the integrated executor ran the harmless local command')
    const evidence = JSON.parse(ports.files.get(`${ROOT}\\evidence-first.json`)!)
    expect(evidence.ok).toBe(false)
    expect(evidence.error).toContain('harmless local command')
  })

  it('turns a page that throws into a named UI failure', async () => {
    const win = { webContents: { isLoading: () => false, executeJavaScript: vi.fn(async () => { throw new Error('renderer gone') }) } }
    await expect(windowsRealCoreSmoke(win as never, broker as never, ROOT, () => 1, { ...base }))
      .rejects.toThrow('UI assertion failed')
  })
})
