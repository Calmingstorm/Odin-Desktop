// The window's theme: System, Dark or Light, saved with the app's other preferences.
//
// Electron's native theme drives the page's `prefers-color-scheme`, so one choice themes the page, the title bar and
// native dialogs together. The window's own background is set to the page's, so no white frame shows before paint.
import type { Appearance } from '../shared/api'

/** The page background of each theme (`--bg` in the renderer's styles.css). */
export const WINDOW_BACKGROUND = { dark: '#0E1115', light: '#F5F7F9' } as const

/** Electron's nativeTheme, as far as the app uses it. */
export interface ThemeSource {
  themeSource: Appearance
  readonly shouldUseDarkColors: boolean
}

/** A saved choice that is missing or not one of the three follows the system. */
export function loadAppearance(value: unknown): Appearance {
  return value === 'dark' || value === 'light' || value === 'system' ? value : 'system'
}

export function windowBackground(dark: boolean): string {
  return dark ? WINDOW_BACKGROUND.dark : WINDOW_BACKGROUND.light
}

/** Owns the current choice: applies it to the native theme, then asks the caller to persist it. */
export class AppearanceController {
  private current: Appearance

  constructor(private readonly theme: ThemeSource, initial: Appearance, private readonly persist: () => void) {
    this.current = initial
    this.theme.themeSource = initial
  }

  get appearance(): Appearance {
    return this.current
  }

  /** The background for the theme in effect now, after any system change. */
  background(): string {
    return windowBackground(this.theme.shouldUseDarkColors)
  }

  set(appearance: Appearance): void {
    this.current = appearance
    this.theme.themeSource = appearance
    this.persist()
  }
}
