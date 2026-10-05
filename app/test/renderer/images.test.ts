import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ArtifactRef, Result } from '../../src/shared/api'
import { ImageCache, showsInline } from '../../src/renderer/src/artifacts'

function image(ref: string, mime = 'image/png'): ArtifactRef {
  return { ref, name: `${ref}.png`, mime, size: 10, kind: 'image', available: true }
}

/** The main-process bridge, answering with `size` bytes, or failing for refs in `failing`. */
function bridge(size: number, failing = new Set<string>()) {
  const calls: string[] = []
  const fetch = async (ref: string): Promise<Result<{ data: Uint8Array }>> => {
    calls.push(ref)
    if (failing.has(ref)) return { ok: false, error: { code: 'not_found', message: 'gone', disposition: 'not_dispatched' } }
    return { ok: true, result: { data: new Uint8Array(size) } }
  }
  return { fetch, calls }
}

afterEach(() => vi.restoreAllMocks())

describe('inline images', () => {
  it('shows raster images inline, never SVG, and never one that is gone', () => {
    expect(showsInline(image('a'))).toBe(true)
    expect(showsInline(image('a', 'image/svg+xml'))).toBe(false)
    expect(showsInline({ ...image('a'), available: false })).toBe(false)
    expect(showsInline({ ...image('a'), kind: 'file' })).toBe(false)
  })

  it('fetches an image once for every message showing it', async () => {
    const { fetch, calls } = bridge(10)
    const cache = new ImageCache(fetch)
    const first = cache.acquire(image('a'))
    const second = cache.acquire(image('a'))
    expect(await first.url).toBe(await second.url)
    expect(await first.url).toMatch(/^blob:/)
    expect(calls).toEqual(['a'])
    expect(cache.cached()).toEqual([['a', 2]])
  })

  it('never revokes an image a message is showing, and drops released ones past the budget, oldest release first', async () => {
    const revoked = vi.spyOn(URL, 'revokeObjectURL')
    const { fetch } = bridge(40)
    const cache = new ImageCache(fetch, 100)
    const shown = cache.acquire(image('shown'))
    const handles = ['a', 'b', 'c'].map((ref) => cache.acquire(image(ref)))
    const urls = await Promise.all([shown.url, ...handles.map((h) => h.url)])
    for (const handle of handles) handle.release() // a, b, c released in that order: 120 bytes, over the budget
    expect(cache.cached()).toEqual([['shown', 1], ['b', 0], ['c', 0]])
    await Promise.resolve()
    expect(revoked.mock.calls.map(([url]) => url)).toEqual([urls[1]])
  })

  it('keeps a re-shown image as the most recently released', async () => {
    const { fetch, calls } = bridge(40)
    const cache = new ImageCache(fetch, 100)
    const a = cache.acquire(image('a'))
    const b = cache.acquire(image('b'))
    await Promise.all([a.url, b.url])
    a.release()
    b.release()
    const again = cache.acquire(image('a'))
    await again.url
    again.release()
    expect(cache.cached().map(([ref]) => ref)).toEqual(['b', 'a'])
    expect(calls).toEqual(['a', 'b'])
  })

  it('does not cache a failed fetch, so the next view tries again; releasing twice is harmless', async () => {
    const failing = new Set(['a'])
    const { fetch, calls } = bridge(10, failing)
    const cache = new ImageCache(fetch)
    const failed = cache.acquire(image('a'))
    expect(await failed.url).toBeNull()
    expect(cache.cached()).toEqual([])
    failing.delete('a')
    const retried = cache.acquire(image('a'))
    expect(await retried.url).toMatch(/^blob:/)
    failed.release()
    failed.release()
    expect(cache.cached()).toEqual([['a', 1]]) // the failed handle never counted against the new entry
    expect(calls).toEqual(['a', 'a'])
  })
})
