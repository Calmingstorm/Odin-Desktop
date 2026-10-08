import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fitComposer, observeComposer } from '../../src/renderer/src/composer-geometry'

const css = { fontSize: '16px', lineHeight: '20px', paddingTop: '9px', paddingBottom: '9px', borderTopWidth: '0px', borderBottomWidth: '0px' }
let field: HTMLTextAreaElement
let mirror: HTMLDivElement
let resize: () => void
let mutation: () => void
let disconnectResize: ReturnType<typeof vi.fn>
let disconnectMutation: ReturnType<typeof vi.fn>
let fonts: EventTarget & { ready: Promise<void> }
let win: EventTarget
const settle = async () => { await Promise.resolve(); await Promise.resolve() }

beforeEach(() => {
  field = { value: '', clientWidth: 400, style: {}, scrollTop: 72 } as unknown as HTMLTextAreaElement
  mirror = { style: {}, scrollHeight: 38, textContent: '' } as unknown as HTMLDivElement
  vi.stubGlobal('getComputedStyle', () => css)
  fonts = Object.assign(new EventTarget(), { ready: Promise.resolve() })
  win = new EventTarget()
  vi.stubGlobal('window', win)
  vi.stubGlobal('document', { fonts })
  disconnectResize = vi.fn(); disconnectMutation = vi.fn()
  vi.stubGlobal('ResizeObserver', class { constructor(cb: () => void) { resize = cb } observe = vi.fn(); disconnect = disconnectResize })
  vi.stubGlobal('MutationObserver', class { constructor(cb: () => void) { mutation = cb } observe = vi.fn(); disconnect = disconnectMutation })
})
afterEach(() => vi.unstubAllGlobals())

describe('off-layout composer geometry', () => {
  it('starts at 38px, fits multiline text and caps at eight rendered lines with internal overflow', () => {
    fitComposer(field, mirror)
    expect(field.style).toMatchObject({ height: '38px', overflowY: 'hidden' })
    expect(mirror.style.width).toBe('400px')
    field.value = 'one\ntwo\n'
    Object.assign(mirror, { scrollHeight: 78 })
    fitComposer(field, mirror)
    expect(field.style.height).toBe('78px')
    expect(mirror.textContent).toBe('one\ntwo\n\u200b')
    Object.assign(mirror, { scrollHeight: 618 })
    fitComposer(field, mirror)
    expect(field.style).toMatchObject({ height: '178px', overflowY: 'auto' })
    expect(field.scrollTop).toBe(72)
    Object.assign(mirror, { scrollHeight: 0 })
    fitComposer(field, mirror)
    expect(field.style).toMatchObject({ height: '38px', overflowY: 'hidden' })
  })
  it('derives padding, border and line metric fallback from computed typography', () => {
    vi.stubGlobal('getComputedStyle', () => ({ fontSize: '20px', lineHeight: 'normal', paddingTop: '4px', paddingBottom: '6px', borderTopWidth: '1px', borderBottomWidth: '2px' }))
    Object.assign(mirror, { scrollHeight: 500 })
    fitComposer(field, mirror)
    expect(field.style.height).toBe('205px')
    vi.stubGlobal('getComputedStyle', () => ({}))
    fitComposer(field, mirror)
    expect(field.style.height).toBe('160px')
  })
  it('honors a short viewport cap while keeping one line and scrolling internally', () => {
    vi.stubGlobal('getComputedStyle', () => ({ ...css, maxHeight: '120px' }))
    Object.assign(mirror, { scrollHeight: 178 })
    fitComposer(field, mirror)
    expect(field.style).toMatchObject({ height: '120px', overflowY: 'auto' })
    vi.stubGlobal('getComputedStyle', () => ({ ...css, maxHeight: '20px' }))
    fitComposer(field, mirror)
    expect(field.style.height).toBe('38px')
  })
  it('uses scrollbar-free width so an eight-line draft stops scrolling after a longer one', () => {
    Object.assign(field, { offsetWidth: 400, clientWidth: 385 })
    Object.assign(mirror, { scrollHeight: 178 })
    fitComposer(field, mirror)
    expect(mirror.style.width).toBe('400px')
    expect(field.style).toMatchObject({ height: '178px', overflowY: 'hidden' })
  })
  it('coalesces invalidation, ignores height-only resize and remeasures width and fonts without text edits', async () => {
    const measure = vi.fn(() => css)
    vi.stubGlobal('getComputedStyle', measure)
    const controller = observeComposer(field, mirror)
    await settle()
    const initial = measure.mock.calls.length
    resize(); await settle()
    expect(measure).toHaveBeenCalledTimes(initial)
    Object.assign(field, { clientWidth: 150 })
    resize(); resize(); mutation(); controller.update()
    await settle()
    expect(measure).toHaveBeenCalledTimes(initial + 1)
    expect(mirror.style.width).toBe('150px')
    for (const type of ['loadingdone', 'loadingerror']) { fonts.dispatchEvent(new Event(type)); await settle() }
    win.dispatchEvent(new Event('resize')); await settle()
    expect(measure).toHaveBeenCalledTimes(initial + 4)
    controller.dispose()
    expect(disconnectResize).toHaveBeenCalledOnce()
    expect(disconnectMutation).toHaveBeenCalledOnce()
    const before = measure.mock.calls.length
    resize(); mutation(); controller.update(); fonts.dispatchEvent(new Event('loadingdone')); win.dispatchEvent(new Event('resize'))
    await settle()
    expect(measure).toHaveBeenCalledTimes(before)
  })
  it('cleans pending font/measurement promises on unmount and tolerates absent observer APIs', async () => {
    let ready!: () => void
    fonts.ready = new Promise((resolve) => { ready = resolve })
    const measure = vi.fn(() => css)
    vi.stubGlobal('getComputedStyle', measure)
    const controller = observeComposer(field, mirror)
    controller.dispose(); ready(); await settle()
    expect(measure).not.toHaveBeenCalled()
    vi.stubGlobal('ResizeObserver', undefined); vi.stubGlobal('MutationObserver', undefined)
    vi.stubGlobal('document', {})
    Object.assign(field, { clientWidth: 0 })
    const absent = observeComposer(field, mirror)
    await settle()
    expect(measure).not.toHaveBeenCalled()
    Object.assign(field, { clientWidth: 400 })
    absent.update(); await settle()
    expect(measure).toHaveBeenCalledOnce()
    absent.dispose()
  })
  it('observes only typography attributes up the local ancestry', async () => {
    const observe = vi.fn()
    vi.stubGlobal('MutationObserver', class { observe = observe; disconnect = vi.fn() })
    const ancestor = { parentElement: null }
    Object.assign(field, { parentElement: ancestor })
    const controller = observeComposer(field, mirror)
    await settle()
    expect(observe.mock.calls.map(([node]) => node)).toEqual([field, ancestor])
    expect(observe.mock.calls[0]![1]).toEqual({ attributes: true, attributeFilter: ['class', 'style'] })
    controller.dispose()
  })
})
