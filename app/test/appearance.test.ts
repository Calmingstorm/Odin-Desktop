import { describe, expect, it, vi } from 'vitest'
import { AppearanceController, WINDOW_BACKGROUND, loadAppearance, windowBackground, type ThemeSource } from '../src/main/appearance'

/** Electron's nativeTheme as the OS reports it: dark follows the choice, or the system while the choice is System. */
function theme(systemDark: boolean): ThemeSource {
  let source: ThemeSource['themeSource'] = 'system'
  return {
    get themeSource() { return source },
    set themeSource(value) { source = value },
    get shouldUseDarkColors() { return source === 'system' ? systemDark : source === 'dark' }
  }
}

describe('appearance', () => {
  it('loads a saved choice and follows the system for anything else', () => {
    expect(loadAppearance('dark')).toBe('dark')
    expect(loadAppearance('light')).toBe('light')
    expect(loadAppearance('system')).toBe('system')
    for (const value of [undefined, null, '', 'Dark', 'auto', 1, {}]) expect(loadAppearance(value)).toBe('system')
  })

  it('gives the window the page background of the theme in effect', () => {
    expect(windowBackground(true)).toBe(WINDOW_BACKGROUND.dark)
    expect(windowBackground(false)).toBe(WINDOW_BACKGROUND.light)
  })

  it('applies the saved choice to the native theme at startup, without saving it again', () => {
    const native = theme(false)
    const persist = vi.fn()
    const controller = new AppearanceController(native, 'dark', persist)
    expect(native.themeSource).toBe('dark')
    expect(controller.appearance).toBe('dark')
    expect(controller.background()).toBe(WINDOW_BACKGROUND.dark)
    expect(persist).not.toHaveBeenCalled()
  })

  it('applies a new choice before saving it, and System follows the OS again', () => {
    const native = theme(true)
    const order: string[] = []
    const controller = new AppearanceController(native, 'system', () => order.push(`saved ${native.themeSource}`))
    expect(controller.background()).toBe(WINDOW_BACKGROUND.dark)
    controller.set('light')
    expect(native.themeSource).toBe('light')
    expect(controller.appearance).toBe('light')
    expect(controller.background()).toBe(WINDOW_BACKGROUND.light)
    controller.set('system')
    expect(controller.background()).toBe(WINDOW_BACKGROUND.dark)
    expect(order).toEqual(['saved light', 'saved system'])
  })
})
