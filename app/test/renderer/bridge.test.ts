import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { computed, isProxy, reactive, ref } from 'vue'
import { odin, toPlain } from '../../src/renderer/src/bridge'

// Electron's contextBridge copies each argument the way structuredClone does, and refuses a Vue proxy the same way:
// "An object could not be cloned." The renderer must hand the preload plain data.
afterEach(() => { vi.unstubAllGlobals() })

describe('toPlain', () => {
  it('turns reactive lists and objects, at any depth, into plain data that can be cloned', () => {
    const list = ref<unknown[]>([])
    list.value = ['gpt-6-astra', { model: 'gpt-6-luna', reasoning_effort: null }]
    const draft = reactive({ params: { auto_model_allowlist: list.value, hints: { 'gpt-6-luna': 'cheap' } } })
    const chosen = computed(() => list.value)
    // The failure being prevented: a live proxy can't be cloned.
    expect(() => structuredClone(chosen.value)).toThrow()
    for (const value of [list.value, chosen.value, draft, { wrapped: draft.params }]) {
      const plain = toPlain(value)
      expect(() => structuredClone(plain)).not.toThrow()
      expect(plain).toEqual(JSON.parse(JSON.stringify(value)))
      expect(isProxy(plain)).toBe(false)
    }
    const nested = toPlain(draft) as { params: { auto_model_allowlist: unknown[] } }
    expect(isProxy(nested.params)).toBe(false)
    expect(isProxy(nested.params.auto_model_allowlist[1])).toBe(false)
  })

  it('passes everything that is not a plain list or object unchanged', () => {
    const bytes = new Uint8Array([1, 2, 3])
    const listener = () => undefined
    const when = new Date(0)
    for (const value of [bytes, listener, when, 'text', 7, true, null, undefined]) expect(toPlain(value)).toBe(value)
    const bare = Object.assign(Object.create(null), { a: [1] })
    expect(toPlain(bare)).toEqual({ a: [1] })
    expect(toPlain({ bytes }).bytes).toBe(bytes)
  })
})

describe('odin', () => {
  it('calls the preload with plain arguments and returns its answer', async () => {
    const editLeaf = vi.fn(function (this: unknown, request: unknown) { structuredClone(request); return Promise.resolve({ ok: true, result: this }) })
    const api = { editLeaf, version: 'v' }
    vi.stubGlobal('window', { odin: api })
    const list = ref<string[]>([])
    list.value = ['gpt-6-astra']
    const answer = await odin.editLeaf({ method: 'models.agents.set', params: { auto_model_allowlist: list.value } })
    expect(answer).toEqual({ ok: true, result: api })
    const [sent] = editLeaf.mock.calls[0]! as [{ params: { auto_model_allowlist: unknown } }]
    expect(isProxy(sent.params.auto_model_allowlist)).toBe(false)
    expect(sent).toEqual({ method: 'models.agents.set', params: { auto_model_allowlist: ['gpt-6-astra'] } })
  })

  it("reads a member the preload doesn't offer as missing, and passes values through", () => {
    vi.stubGlobal('window', { odin: { version: 'v' } })
    expect((odin as unknown as Record<string, unknown>).version).toBe('v')
    expect(typeof (odin as unknown as Record<string, unknown>).codexRefresh).toBe('undefined')
    vi.stubGlobal('window', {})
    expect(typeof odin.editLeaf).toBe('undefined')
  })

  it('is the only way renderer code reaches the preload', () => {
    const root = join(__dirname, '../../src/renderer/src')
    const files = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
      const path = join(dir, name)
      return statSync(path).isDirectory() ? files(path) : /\.(ts|vue)$/.test(name) ? [path] : []
    })
    const direct = files(root).filter((path) => !['bridge.ts', 'env.d.ts'].includes(relative(root, path)) && readFileSync(path, 'utf8').includes('window.odin'))
    expect(direct.map((path) => relative(root, path))).toEqual([])
  })
})
