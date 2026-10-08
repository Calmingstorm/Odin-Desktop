import { expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import postcss from 'postcss'
import { buttonPattern, comparableButtonPattern } from './helpers/ui-button-pattern'

it('contains absolute accessible labels in the settings scroller without changing card width or padding', () => {
  const ast = postcss.parse(readFileSync(new URL('../src/renderer/src/styles.css', import.meta.url), 'utf8'))
  const declarations = (selector: string) => {
    const values: Record<string, string> = {}
    ast.walkRules(selector, (rule) => { rule.walkDecls((declaration) => { values[declaration.prop] = declaration.value }) })
    return values
  }
  expect(declarations('.settings-content')).toMatchObject({ position: 'relative', width: '100%',
    'max-width': '880px', 'min-width': '0', '--settings-padding': '18px' })
  expect(declarations('.settings-body')).toMatchObject({ 'overflow-y': 'auto', 'scrollbar-gutter': 'stable' })
  expect(declarations('.sr-only')).toMatchObject({ position: 'absolute', width: '1px', height: '1px' })
})

it('does not equate unclassed segmented choices to native Save controls', () => {
  expect(buttonPattern('', 'segmented')).toBe('settings-segmented')
  expect(buttonPattern('', 'editor-actions')).toBe('native-unclassed')
  expect(comparableButtonPattern('native-unclassed')).toBe(false)
  expect(comparableButtonPattern('settings-segmented')).toBe(true)
})

it('compares only explicit shared styles, preserving scoped and modifier overrides', () => {
  expect(buttonPattern('ghost danger-item', '')).toBe(buttonPattern('danger-item ghost', 'row-control'))
  expect(buttonPattern('ghost model-refresh', '')).not.toBe(buttonPattern('ghost', ''))
  expect(buttonPattern('primary', 'form-actions')).not.toBe(buttonPattern('primary', ''))
  expect(buttonPattern('ghost', 'menu')).toBe('menu-item')
  expect(comparableButtonPattern(buttonPattern('unknown-control', ''))).toBe(false)
  expect(comparableButtonPattern(buttonPattern('ghost', 'row-control'))).toBe(true)
})
