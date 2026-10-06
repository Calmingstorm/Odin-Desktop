import { EventEmitter } from 'node:events'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const fake = vi.hoisted(() => ({ supported: true, throws: false, objects: [] as unknown[] }))
vi.mock('electron', () => ({ Notification: class extends EventEmitter {
  static isSupported(): boolean { return fake.supported }
  close = vi.fn()
  constructor(public options: unknown) { super(); if (fake.throws) throw new Error('native constructor failure'); fake.objects.push(this) }
  show(): void { /* tests deliver adapter events rather than a fake policy result */ }
} }))
import { Notification } from 'electron'
import { showNativeNotification } from '../src/main/native-notifications'

describe('native notification adapter', () => {
  beforeEach(() => { fake.supported = true; fake.throws = false; fake.objects = []; vi.useFakeTimers() })
  afterEach(() => vi.useRealTimers())
  function show() {
    const click = vi.fn()
    const live = new Set<Notification>()
    const pending = showNativeNotification({ title: 'Odin', body: 'committed', onClick: click }, live, 'icon')
    const os = fake.objects.at(-1) as Notification & EventEmitter
    return { click, live, pending, os }
  }
  it('waits for native acceptance and routes one action only', async () => {
    const { pending, os, live, click } = show()
    expect(live.size).toBe(1)
    os.emit('click')
    expect(click).not.toHaveBeenCalled()
    os.emit('show')
    expect(await pending).toBe('shown')
    os.emit('click'); os.emit('click')
    expect(click).toHaveBeenCalledTimes(1)
    expect(live.size).toBe(0)
  })
  it('times out failed, retires handlers, and late acceptance/action cannot navigate', async () => {
    const { pending, os, live, click } = show()
    await vi.advanceTimersByTimeAsync(5000)
    expect(await pending).toBe('failed')
    expect(live.size).toBe(0)
    expect(os.close).toHaveBeenCalledOnce()
    os.emit('show'); os.emit('click')
    expect(click).not.toHaveBeenCalled()
  })
  it('native rejection settles failed and constructor failure is not an unhandled rejection', async () => {
    const { pending, os } = show()
    os.emit('failed')
    expect(await pending).toBe('failed')
    fake.throws = true
    expect(await show().pending).toBe('failed')
    fake.supported = false
    expect(await show().pending).toBe('failed')
  })
})
