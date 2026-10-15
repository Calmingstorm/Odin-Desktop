import { describe, expect, it } from 'vitest'
import { commandKey, onMac, shortcutLabel } from '../../src/renderer/src/shortcuts'

describe('in-window shortcuts follow the platform', () => {
  it('uses Ctrl off a Mac, exactly as before', () => {
    expect(commandKey({ ctrlKey: true, metaKey: false }, false)).toBe(true)
    expect(commandKey({ ctrlKey: false, metaKey: true }, false)).toBe(false)
    expect(shortcutLabel(',', {}, false)).toBe('Ctrl+,')
    expect(shortcutLabel('F', { shift: true }, false)).toBe('Ctrl+Shift+F')
    expect(shortcutLabel('.', {}, false)).toBe('Ctrl+.')
  })

  it('uses ⌘ on a Mac and still accepts Ctrl there', () => {
    expect(commandKey({ ctrlKey: false, metaKey: true }, true)).toBe(true)
    expect(commandKey({ ctrlKey: true, metaKey: false }, true)).toBe(true)
    expect(commandKey({ ctrlKey: false, metaKey: false }, true)).toBe(false)
    expect(shortcutLabel(',', {}, true)).toBe('⌘,')
    expect(shortcutLabel('F', { shift: true }, true)).toBe('⇧⌘F')
    expect(shortcutLabel('.', {}, true)).toBe('⌘.')
  })

  it('reads the platform Electron reports', () => {
    expect(onMac).toBe(/^Mac/i.test(globalThis.navigator?.platform ?? ''))
  })
})
