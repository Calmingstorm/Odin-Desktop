// Structural regression checks only. The object renderer does not prove keyboard focus, Electron's tree or Orca.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flush, mount, type Host } from './component-host'

const ok = <T>(result: T) => ({ ok: true as const, result })
let bridge: Record<string, unknown>

beforeEach(() => {
  vi.resetModules()
  bridge = {
    computerStatus: async () => ok({ readiness: { management_available: true, foreground_available: false, dispatch: 'none', reason: 'not_enabled' }, session: null }),
    toolsList: async () => ok({ tools: [{ name: 'read_file', description: 'Read', enabled: true, state: 'available', input_schema: {} }], disabled_count: 0 }),
    toolsTimeoutsGet: async () => ok({ default_timeout: 30, overrides: { read_file: 10 } }),
    mcpStatus: async () => ok({ enabled: true, servers: [{ name: 'docs', transport: 'stdio', state: 'connected', enabled: true, header_keys: [], env_keys: [], discovered_count: 1, published_count: 1 }], connected_count: 1, server_count: 1, published_tool_count: 1, max_published_tools_per_server: 10, max_published_tools_global: 20 }),
    mcpTools: async () => ok([]),
    skillsList: async () => ok([{ name: 'hello', status: 'loaded', version: '1', description: '' }]),
    skillsValidate: async () => ok({ valid: false, errors: ['Syntax error on line 2.'], warnings: [], metadata: null, definition_keys: [] }),
    personalityGet: async () => ok({ preset: 'default', custom_name: '', custom_identity: '', custom_voice: '', presets: { default: { name: 'Odin', identity: 'i', voice: 'v' }, night: { name: 'Night', identity: 'i', voice: 'v' } }, builtin_presets: ['default'], user_presets: ['night'] })
  }
  ;(globalThis as unknown as { window: unknown }).window = { odin: bridge }
  ;(globalThis as unknown as { document: unknown }).document = { activeElement: null }
})

async function view(name: string) {
  const component = (await import(`../../src/renderer/src/views/settings/${name}.vue`)).default
  const v = mount(component)
  await flush()
  return v
}

function visibleLabels(root: Host): void {
  for (const field of root.findAll((n) => ['input', 'select', 'textarea'].includes(n.tag))) {
    let ancestor = field.parent
    while (ancestor && ancestor.tag !== 'label') ancestor = ancestor.parent
    const explicit = root.findAll((n) => n.tag === 'label' && n.props.for === field.props.id && !!field.props.id)[0]
    expect((ancestor ?? explicit)?.textContent().trim(), `visible label for ${field.tag} ${field.props.id ?? field.props.placeholder ?? ''}`).toBeTruthy()
  }
}

function invalidFields(root: Host): Host[] {
  return root.findAll((n) => n.props['aria-invalid'] === true)
}

function linkedError(root: Host, field: Host, text: string): void {
  const id = field.props['aria-describedby']
  expect(typeof id).toBe('string')
  const error = root.findAll((n) => n.props.id === id)[0]
  expect(error?.textContent()).toContain(text)
}

describe('P3.4 management settings structural accessibility', () => {
  it('labels tool fields and identifies the disclosure and timeout removal by tool', async () => {
    const { root } = await view('Tools')
    visibleLabels(root)
    const button = root.button('Parameters')
    expect(button.props['aria-label']).toBe('Parameters for read_file')
    expect(button.props['aria-expanded']).toBe(false)
    expect(root.findAll((n) => n.props.id === button.props['aria-controls'])).toHaveLength(1)
    button.fire('click')
    await flush()
    expect(button.props['aria-expanded']).toBe(true)
    expect(button.props['aria-label']).toBe('Hide parameters for read_file')
    expect(root.button('Remove').props['aria-label']).toBe('Remove timeout for read_file')
  })

  it('marks only the invalid timeout and clears the association when edited', async () => {
    const { root } = await view('Tools')
    const numbers = root.findAll((n) => n.tag === 'input' && n.props.type === 'number')
    numbers[1]!.type('0')
    await flush()
    root.button('Save timeouts').fire('click')
    await flush()
    expect(invalidFields(root)).toEqual([numbers[1]])
    linkedError(root, numbers[1]!, 'read_file: a timeout')
    numbers[1]!.type('10')
    await flush()
    expect(invalidFields(root)).toHaveLength(0)
    numbers[0]!.type('0')
    await flush()
    root.button('Save timeouts').fire('click')
    await flush()
    expect(invalidFields(root)).toEqual([numbers[0]])
    linkedError(root, numbers[0]!, 'The default')
  })

  it('labels MCP secret rows, contextual actions and disclosure; scopes local error to timeout', async () => {
    const { root } = await view('Mcp')
    expect(root.button('Edit').props['aria-label']).toBe('Edit docs')
    expect(root.button('Remove…').props['aria-label']).toBe('Remove docs…')
    const availability = root.findAll((n) => n.props.role === 'switch' && n.props['aria-label'] === 'Turn off docs')
    expect(availability).toHaveLength(1)
    expect(availability[0]!.props.checked).toBe(true)
    expect(root.button('Reconnect').props['aria-label']).toBe('Reconnect docs')
    expect(root.button('Refresh tools').props['aria-label']).toBe('Refresh tools for docs')
    const disclosure = root.button('Tools')
    expect(disclosure.props['aria-label']).toBe('Tools for docs')
    expect(disclosure.props['aria-expanded']).toBe(false)
    disclosure.fire('click')
    await flush()
    expect(disclosure.props['aria-expanded']).toBe(true)
    expect(root.findAll((n) => n.props.id === disclosure.props['aria-controls'])).toHaveLength(1)
    root.button('Add server').fire('click')
    await flush()
    root.button('Add a header').fire('click')
    root.button('Add a variable').fire('click')
    await flush()
    visibleLabels(root)
    const passwords = root.findAll((n) => n.props.type === 'password')
    expect(passwords).toHaveLength(2)
    expect(passwords.every((n) => n.props.autocomplete === 'off')).toBe(true)
    const timeout = root.findAll((n) => n.tag === 'input' && n.props.min === '1')[0]!
    timeout.type('0')
    await flush()
    root.button('Add').fire('click')
    await flush()
    expect(invalidFields(root)).toEqual([timeout])
    linkedError(root, timeout, 'The timeout')
    timeout.type('10')
    await flush()
    expect(invalidFields(root)).toHaveLength(0)
  })

  it('links skill validation to visibly labelled code, not the skill name', async () => {
    const { root } = await view('Skills')
    expect(root.button('Open').props['aria-label']).toBe('Open hello')
    expect(root.button('Test').props['aria-label']).toBe('Test hello')
    expect(root.button('Delete…').props['aria-label']).toBe('Delete hello…')
    root.button('New skill').fire('click')
    await flush()
    visibleLabels(root)
    root.button('Validate').fire('click')
    await flush()
    const code = root.find('textarea')!
    expect(invalidFields(root)).toEqual([code])
    linkedError(root, code, 'Syntax error on line 2.')
    bridge.skillsValidate = async () => ok({ valid: true, errors: [], warnings: ['Check the description.'], metadata: null, definition_keys: [] })
    root.button('Validate').fire('click')
    await flush()
    expect(invalidFields(root)).toHaveLength(0)
    linkedError(root, code, 'Check the description.')
  })

  it('scopes preset errors to name or the identity/voice alternative and resets them on edit', async () => {
    const { root } = await view('Personality')
    visibleLabels(root)
    expect(root.button('Save').props['aria-label']).toBe('Save personality')
    expect(root.button('Delete…').props['aria-label']).toBe('Delete preset night…')
    root.button('Save preset').fire('click')
    await flush()
    const name = root.findAll((n) => n.props.placeholder === 'night_shift')[0]!
    expect(invalidFields(root)).toEqual([name])
    linkedError(root, name, 'Name the preset.')
    name.type('new_preset')
    await flush()
    expect(invalidFields(root)).toHaveLength(0)
    root.button('Save preset').fire('click')
    await flush()
    const content = root.findAll((n) => n.tag === 'textarea')
    expect(invalidFields(root)).toEqual(content)
    for (const field of content) linkedError(root, field, 'identity, a voice, or both')
    content[0]!.type('Identity')
    await flush()
    expect(invalidFields(root)).toHaveLength(0)
  })
})
