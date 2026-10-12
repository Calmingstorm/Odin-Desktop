// The Windows real-app smoke (phase 3d, D11): the production entry, the checkout's real engine over the sealed pipe,
// and a loopback scripted model, inside a root the runner (scripts/windows-real-core-smoke.mjs) created and
// measured. Development only. Linux's real-core smoke and its isolation are separate and untouched.
import { strict as assert } from 'node:assert'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { win32 } from 'node:path'
import { app, type BrowserWindow } from 'electron'
import type { Broker } from './broker'
import { configureCannedProvider } from './real-core-smoke'

type Env = Record<string, string | undefined>

/** The runner's own root, bound by the nonce it wrote there: an environment flag alone enables nothing. The engine
 * profile and the Chromium profile both live under it (LOCALAPPDATA is its `local` folder). */
export function windowsSmokeRoot(env: Env, argv: readonly string[], packaged: boolean, system: NodeJS.Platform,
  read: (path: string) => string = (path) => readFileSync(path, 'utf8')): string | null {
  if (system !== 'win32' || packaged || env.ODIN_WINDOWS_SMOKE !== '1' || !argv.includes('--smoke-test')) return null
  const root = env.ODIN_WINDOWS_SMOKE_ROOT ?? ''
  const nonce = env.ODIN_WINDOWS_SMOKE_NONCE ?? ''
  if (!/^[A-Za-z]:\\/.test(root) || !/^[0-9a-f]{32}$/.test(nonce)) return null
  try {
    if ((JSON.parse(read(win32.join(root, 'smoke-root.json'))) as { nonce?: unknown }).nonce !== nonce) return null
  } catch {
    return null
  }
  return win32.relative(root, env.LOCALAPPDATA ?? '') === 'local' ? root : null
}

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

interface SmokeMessage { id: string; role: string; text?: string; request_id?: string }

export async function windowsRealCoreSmoke(win: BrowserWindow, broker: Broker, root: string, corePid: () => number | undefined,
  env: Env = process.env): Promise<void> {
  const phase = env.ODIN_WINDOWS_SMOKE_PHASE === 'relaunch' ? 'relaunch' : 'first'
  const out = win32.join(root, `evidence-${phase}.json`)
  const evidence: Record<string, unknown> = { phase, versions: { ...process.versions } }
  const run = async <T = unknown>(script: string): Promise<T> => {
    try { return await win.webContents.executeJavaScript(script, true) as T }
    catch (error) { throw new Error(`UI assertion failed: ${script}: ${String(error)}`) }
  }
  const text = (selector: string): Promise<string> => run(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? ''`)
  const until = async (predicate: () => Promise<boolean> | boolean, label: string, timeout = 30_000): Promise<void> => {
    const end = Date.now() + timeout
    while (!await predicate()) {
      if (Date.now() >= end) throw new Error(`Did not settle: ${label}. Rendered page: ${await text('body')}`)
      await pause(100)
    }
  }
  const click = async (selector: string): Promise<void> => {
    assert(await run(`Boolean(document.querySelector(${JSON.stringify(selector)}))`), `missing UI control ${selector}`)
    await run(`document.querySelector(${JSON.stringify(selector)}).click()`)
  }
  const setInput = async (selector: string, value: string): Promise<void> => {
    await run(`(() => { const input = document.querySelector(${JSON.stringify(selector)}); input.value = ${JSON.stringify(value)}; input.dispatchEvent(new Event('input', { bubbles: true })); })()`)
    await pause(50)
  }
  const bridge = <T = unknown>(method: string, params?: unknown): Promise<T> =>
    run(`window.odin[${JSON.stringify(method)}](${params === undefined ? '' : JSON.stringify(params)})`)
  const send = async (value: string): Promise<void> => {
    await setInput('.composer textarea', value)
    await until(() => run('document.querySelector(".composer button[type=submit]")?.disabled === false'), 'sendable composer')
    await run('document.querySelector(".composer form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))')
    await until(() => run('document.querySelector(".composer textarea").value === ""'), 'submission admitted')
  }
  const messages = async (cid: string): Promise<SmokeMessage[]> => {
    const result = await bridge<{ ok: boolean; result: { messages: { items: SmokeMessage[] } } }>('snapshotConversation', { conversation_id: cid })
    assert(result.ok, 'snapshot bridge succeeds')
    return result.result.messages.items
  }
  const reply = async (cid: string, prompt: string): Promise<SmokeMessage> => {
    let answer: SmokeMessage | undefined
    await until(async () => {
      const items = await messages(cid)
      const request = items.find((m) => m.role === 'user' && m.text === prompt)?.request_id
      answer = items.find((m) => m.role === 'assistant' && m.request_id === request && Boolean(m.text))
      return Boolean(answer)
    }, `the committed reply to ${prompt}`, 90_000)
    await until(() => run(`document.getElementById(${JSON.stringify(`m-${answer!.id}`)})?.textContent.includes(${JSON.stringify(answer!.text)}) ?? false`),
      `the rendered reply to ${prompt}`)
    return answer!
  }
  try {
    assert(win32.relative(root, app.getPath('userData')).startsWith('local\\'), 'the Chromium profile lives under the runner root')
    await until(async () => broker.linkState === 'ready' && !win.webContents.isLoading() && await run<boolean>('Boolean(window.odin)'),
      'the sealed session and the renderer', 90_000)
    evidence.session = { link: broker.linkState, coreInstance: broker.coreInstanceId, corePid: corePid() }
    if (phase === 'first') {
      await configureCannedProvider(broker, env.ODIN_SMOKE_PROVIDER_BASE_URL ?? '')
      await until(async () => (await text('.rail-link')).includes('Connected'), 'the connection indicator')
      if (await run<number>('document.querySelectorAll(".conv-row").length') === 0) await click('button[title="New conversation"]')
      await until(() => run('document.querySelectorAll(".conv-row").length === 1 && !document.querySelector(".composer textarea")?.disabled'),
        'a conversation')
      const listed = await bridge<{ ok: boolean; result: { items: Array<{ id: string }> } }>('listConversations')
      assert(listed.ok)
      const cid = listed.result.items[0]!.id
      evidence.conversation = cid
      await send('[reply] windows smoke')
      evidence.reply = (await reply(cid, '[reply] windows smoke')).text
      await send('[tool] windows smoke')
      evidence.toolReply = (await reply(cid, '[tool] windows smoke')).text
      const marker = win32.join(root, 'tool-marker.txt')
      assert(existsSync(marker), 'the integrated executor ran the harmless local command')
      evidence.toolMarker = readFileSync(marker, 'utf8').trim()
      await setInput('.composer textarea', 'windows smoke draft')
      await pause(1_500) // the draft reaches the app's store, which Exit flushes
      evidence.draft = 'typed, not sent'
    } else {
      await until(() => run('document.querySelectorAll(".conv-row").length === 1'), 'the conversation after the relaunch')
      await click('.conv-row')
      await until(() => run('document.querySelector(".composer textarea")?.value === "windows smoke draft"'), 'the draft after the relaunch')
      const listed = await bridge<{ ok: boolean; result: { items: Array<{ id: string }> } }>('listConversations')
      assert(listed.ok)
      const kept = await messages(listed.result.items[0]!.id)
      assert(kept.some((m) => m.role === 'assistant' && m.text?.includes('Scripted reply')), 'the earlier replies persisted')
      evidence.relaunch = { conversation: true, draft: true, messages: kept.length }
    }
    evidence.ok = true
  } catch (error) {
    evidence.ok = false
    evidence.error = String(error)
    throw error
  } finally {
    writeFileSync(out, JSON.stringify(evidence, null, 2))
  }
}
