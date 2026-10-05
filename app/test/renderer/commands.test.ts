// The composer's slash commands, driven through a fake bridge.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Result } from '../../src/shared/api'

type Commands = typeof import('../../src/renderer/src/commands')
type Store = typeof import('../../src/renderer/src/store')
type ComposerStore = typeof import('../../src/renderer/src/stores/composer')

let commands: Commands
let store: Store
let composer: ComposerStore
let calls: { usage: string[]; reload: string[]; steer: number }
let releaseReload: (() => void) | null

beforeEach(async () => {
  vi.resetModules()
  calls = { usage: [], reload: [], steer: 0 }
  releaseReload = null
  ;(globalThis as unknown as { window: unknown }).window = {
    odin: {
      usage: async (period: string) => {
        calls.usage.push(period)
        return { ok: true, result: { period, summary: `Usage for ${period}.` } }
      },
      reload: (scope: string) => {
        calls.reload.push(scope)
        return new Promise<Result<{ disposition: string; summary: string }>>((resolve) => {
          releaseReload = () => resolve({ ok: true, result: { disposition: 'reloaded', summary: 'Reloaded.' } })
        })
      },
      steer: async () => {
        calls.steer += 1
        return { ok: true, result: { disposition: 'queued', sequence: 1 } }
      }
    }
  }
  delete (globalThis as unknown as { document?: unknown }).document
  store = await import('../../src/renderer/src/store')
  composer = await import('../../src/renderer/src/stores/composer')
  commands = await import('../../src/renderer/src/commands')
})

const command = (name: string) => commands.COMMANDS.find((c) => c.name === name)!

describe('review round 1: slash commands', () => {
  it("/usage shows Odin's default 7d range, takes a range, and refuses others", async () => {
    await commands.dispatch(command('usage'), '')
    await commands.dispatch(command('usage'), '30d')
    expect(await commands.dispatch(command('usage'), 'week')).toBe(false)
    expect(calls.usage).toEqual(['7d', '30d'])
    expect(store.state.notice).toMatch(/24h, 7d, 30d, all/)
    expect(store.state.panel?.title).toBe('Usage, 30d')
  })

  it('runs one command at a time: a second press while /reload runs makes no second call', async () => {
    const first = commands.dispatch(command('reload'), '')
    expect(await commands.dispatch(command('reload'), '')).toBe(false)
    expect(calls.reload).toHaveLength(1)
    expect(store.state.notice).toMatch(/still running/)
    releaseReload?.()
    await first
    void commands.dispatch(command('reload'), '')
    expect(calls.reload).toHaveLength(2) // free again once the first finished
  })

  it('/steer with attachments in the box explains Queue instead of dropping them', async () => {
    store.state.activeId = 'c1'
    store.state.views.c1 = { running: { request_id: 'r1', generation: 1, started_at: '2026-10-05T00:00:00Z' } } as never
    composer.composer.attachments.c1 = [
      { id: 'a1', name: 'notes.txt', size: 3, mime: 'text/plain', status: 'ready', sent: 3, ref: 'ref-a1', addToKnowledge: false }
    ]
    expect(await commands.dispatch(command('steer'), 'look at this')).toBe(false)
    expect(calls.steer).toBe(0)
    expect(store.state.notice).toMatch(/Attachments go with a message, not a steer/)
  })
})
