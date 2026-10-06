import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

// Execute the actual suite function, not a separately copied retry algorithm.
// No VM, Electron, device, child process or accessibility bus is used here.
const source = readFileSync(resolve('test/e2e/orca.spec.ts'), 'utf8')
const nativeSource = source.slice(source.indexOf('async function native('), source.indexOf('async function section('))
const javascript = ts.transpileModule(nativeSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }
}).outputText

function model(invoke: (action: string) => void) {
  const calls: string[] = []
  const native = runInNewContext(`${javascript}\nnative`, {
    guest: '/unit/orca-guest.py',
    execFileSync: (_exe: string, argv: string[]) => { calls.push(argv[4]!); invoke(argv[4]!) },
    expect: {
      poll: (predicate: () => boolean) => ({
        toBe: async (wanted: boolean) => {
          for (let n = 0; n < 3; n++) if (predicate() === wanted) return
          throw new Error('Observation deadline')
        }
      })
    }
  }) as (title: string, action: string, path?: string) => Promise<void>
  return { native, calls }
}

describe('Orca suite native input is never retried', () => {
  it('retries only pre-input observation, then invokes input once', async () => {
    let observations = 0
    const task = model(action => {
      if (action === 'describe' && ++observations === 1) throw new Error('No owned active AT-SPI dialog')
    })
    await task.native('Attach files', 'file', '/unit/file.txt')
    expect(task.calls).toEqual(['describe', 'describe', 'file'])
  })

  it('does not replay if readback after partial typing returns the lookup sentinel', async () => {
    const task = model(action => {
      if (action === 'file') throw new Error('No owned active AT-SPI dialog during post-typing readback')
    })
    await expect(task.native('Attach files', 'file', '/unit/file.txt')).rejects.toThrow('post-typing readback')
    expect(task.calls).toEqual(['describe', 'file'])
  })

  it('does not replay cancellation after an uncertain outcome', async () => {
    const task = model(action => {
      if (action === 'cancel') throw new Error('No owned active AT-SPI dialog after Escape')
    })
    await expect(task.native('Attach files', 'cancel')).rejects.toThrow('after Escape')
    expect(task.calls).toEqual(['describe', 'cancel'])
  })

  it('unknown observation errors fail before any input', async () => {
    const task = model(() => { throw new Error('Collector binding lost') })
    await expect(task.native('Save file', 'file', '/unit/saved.txt')).rejects.toThrow('Collector binding lost')
    expect(task.calls).toEqual(['describe'])
  })

  it('describe remains observation-only', async () => {
    const task = model(() => {})
    await task.native('Save file', 'describe')
    expect(task.calls).toEqual(['describe'])
  })
})
