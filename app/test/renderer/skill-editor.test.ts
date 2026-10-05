// Review round 3: the skill editor keeps what the user changed when a skill is read again, and settings keep their types.
import { describe, expect, it } from 'vitest'
import { configValue } from '../../src/renderer/src/skill-config'
import { adoptSkill } from '../../src/renderer/src/skill-editor'
import { blank, mcpBody } from '../../src/renderer/src/mcp-form'
import type { McpServer } from '../../src/shared/api'

const skill = (code: string, config: Record<string, unknown> = { units: 'metric' }) => ({ name: 'weather', code, config })

describe('the skill editor across reloads', () => {
  it('keeps code typed since the last load when the skill is read again, as after saving its settings', () => {
    const loaded = { name: 'weather', code: 'v1', config: JSON.stringify({ units: 'metric' }) }
    const adopted = adoptSkill({ name: 'weather', code: 'v1 plus unsaved', create: false }, loaded, loaded.config, skill('v1', { units: 'imperial' }))
    expect(adopted.editor?.code).toBe('v1 plus unsaved')
    expect(adopted.replaceConfig).toBe(true) // the settings shown were untouched, so the saved ones show
  })

  it('takes the new code when the editor was untouched, and keeps settings changed meanwhile', () => {
    const loaded = { name: 'weather', code: 'v1', config: JSON.stringify({ units: 'metric' }) }
    const adopted = adoptSkill({ name: 'weather', code: 'v1', create: false }, loaded, JSON.stringify({ units: 'imperial' }), skill('v2'))
    expect(adopted.editor?.code).toBe('v2')
    expect(adopted.replaceConfig).toBe(false)
  })

  it('shows another skill whole when another one is opened', () => {
    const loaded = { name: 'weather', code: 'v1', config: '{}' }
    const adopted = adoptSkill({ name: 'weather', code: 'edited', create: false }, loaded, '{}', { name: 'news', code: 'n1', config: {} })
    expect(adopted).toMatchObject({ editor: { name: 'news', code: 'n1' }, replaceConfig: true })
  })
})

describe("a skill's settings keep their types", () => {
  it('takes the enum option picked, booleans included, never its text', () => {
    expect(configValue({ type: 'boolean', enum: [true, false] }, 'true', 0)).toBe(true)
    expect(configValue({ type: 'boolean', enum: [true, false] }, 'false', 1)).toBe(false)
    expect(configValue({ type: 'integer', enum: [1, 7, 30] }, '7', 1)).toBe(7)
    expect(configValue({ enum: ['metric', 'imperial'] }, 'imperial', 1)).toBe('imperial')
    expect(configValue({ enum: [1, 2, 3] }, '2', 1)).toBe(2) // no declared type: the option itself, not its text
    expect(configValue({ enum: [null, 'auto'] }, 'null', 0)).toBeNull()
    expect(configValue({ type: 'boolean' }, true)).toBe(true)
    expect(configValue({ type: 'integer' }, '14')).toBe(14)
  })
})

describe('the MCP form sends what was chosen', () => {
  const server = { name: 'LMMS', transport: 'stdio', header_keys: ['Authorization'], env_keys: [] } as unknown as McpServer

  it('keeps what is stored when a field is left blank, and clears the arguments or the tool list only when asked', () => {
    const untouched = blank(server)
    expect(mcpBody(untouched)).toEqual({ name: 'LMMS', create: false, transport: 'stdio' })
    expect(mcpBody({ ...blank(server), clearArgs: true, allTools: true })).toEqual({
      name: 'LMMS', create: false, transport: 'stdio', args: [], tool_allowlist: null
    })
    expect(mcpBody({ ...blank(server), allowlist: 'create_track\n mix ' })).toMatchObject({ tool_allowlist: ['create_track', 'mix'] })
    expect(mcpBody({ ...blank(server), removeHeaders: ['Authorization'] })).toMatchObject({ headers_remove: ['Authorization'] })
  })
})

