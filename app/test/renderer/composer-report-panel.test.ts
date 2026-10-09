// The command report panel renders the core's report as Odin's Discord replies show it: bold and code, lines kept.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host, type Mounted } from './component-host'
import { reportPlainText } from '../../src/shared/report-text'

type Store = typeof import('../../src/renderer/src/store')

const USAGE = [
  '**Usage — 7d** · settled turns 85 · generations 213 · error turns 0',
  '**Codex quota — account 1 (current)** · observed 6s ago',
  '  7d window: 47% used · resets in 5d 21h'
].join('\n')

let mounted: Mounted
let store: Store
beforeEach(async () => {
  vi.resetModules()
  vi.stubGlobal('window', { odin: {}, addEventListener() {} })
  vi.stubGlobal('document', { activeElement: null, addEventListener() {}, visibilityState: 'hidden', hasFocus: () => false })
  store = await import('../../src/renderer/src/store')
  const Component = (await import('../../src/renderer/src/components/Composer.vue')).default
  mounted = mount(Component)
  await flush()
})
afterEach(() => { mounted.unmount(); vi.unstubAllGlobals() })

const panelText = (): Host => mounted.root.findAll((host) => host.tag === 'pre' && host.props.class === 'panel-text')[0]!
const texts = (tag: string): string[] => panelText().findAll((host) => host.tag === tag).map((host) => host.textContent())

describe('command report panel', () => {
  it('shows a core report bold where Odin wrote bold, with no markers and every line kept', async () => {
    store.showPanel('Usage, 7d', USAGE, true)
    await flush()
    expect(texts('strong')).toEqual(['Usage — 7d', 'Codex quota — account 1 (current)'])
    expect(panelText().textContent()).toBe(reportPlainText(USAGE))
    expect(panelText().textContent()).not.toContain('**')
    expect(panelText().textContent().split('\n')[2]).toBe('  7d window: 47% used · resets in 5d 21h')
  })

  it('shows code spans as code, inside bold too', async () => {
    store.showPanel('Reload', '**Context reloaded `now`** — 1 file\nLoaded: `notes.md`', true)
    await flush()
    expect(texts('code')).toEqual(['now', 'notes.md'])
    // Bold that holds code renders as both: the code element sits inside the strong one.
    expect(texts('strong')).toEqual(['Context reloaded ', 'now'])
    expect(panelText().findAll((host) => host.tag === 'strong').map((host) => host.find('code')?.textContent())).toEqual([undefined, 'now'])
    expect(panelText().textContent()).toBe('Context reloaded now — 1 file\nLoaded: notes.md')
  })

  it('shows a panel that is not a core report exactly as written', async () => {
    store.showPanel('Main model', 'Main model: **gpt-6.1-sol**.')
    await flush()
    expect(texts('strong')).toEqual([])
    expect(panelText().textContent()).toBe('Main model: **gpt-6.1-sol**.')
  })
})
